"""RAG 파이프라인 — FinOps 정책 · 가격 문서 검색.

Day 2 (day02/practice/starter/submission.py) 의 구조(청크 metadata, k 값 근거를
주석으로 남기기, assess_retrieval로 근거 없으면 모델을 부르지 않기)를 그대로 따르되,
Day 2는 vectorstore가 이미 주어진다고 가정했던 것과 달리 이 파일은 파이프라인을
처음부터 끝까지(문서 → 청크 → 벡터스토어 → 하이브리드 리트리버 → 쿼리 확장 →
리랭킹) 직접 구성한다.

- 하이브리드 검색 = BM25(키워드) + 벡터(의미) 앙상블. 정책 문서가 "예산 한도",
  "team-a" 처럼 고유명사·태그를 그대로 포함하는 경우가 많아 키워드 검색이 잘 먹히고,
  "돈을 어떻게 나누나요" 같은 의역 질문은 벡터 검색이 더 잘 잡는다.
- 쿼리 확장 = MultiQueryRetriever로 LLM이 원 질문을 3가지 버전으로 바꿔 각각
  하이브리드 검색을 돌린다. 사용자가 정책 문서의 정확한 용어를 안 쓰는 경우(예:
  "얼마까지 써도 돼?" vs 문서의 "월간 한도") 재현율을 넓히기 위함.
- 리랭킹 = 확장 검색으로 늘어난 후보(최대 10개)를 LLM에게 관련도 순으로 다시
  매기게 해서 상위 4개만 남긴다. 쿼리 확장이 재현율을 넓히는 대신 무관한 후보도
  끌고 오므로, 최종 답변 생성 전에 정밀도를 다시 좁히는 단계가 필요하다.

[중요] 이 저장소의 langchain은 1.x대(requirements.txt의 >=0.3는 하한선일 뿐 실제
설치본은 더 최신일 수 있음)라, EnsembleRetriever/MultiQueryRetriever가
`langchain.retrievers`가 아니라 `langchain_classic.retrievers`로 옮겨갔다.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from llm_utils import get_text

EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"
REGION = "us-east-1"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PERSIST_DIR = str(DATA_DIR / "chroma_db")
COLLECTION = "finops_docs"


def _default_llm():
    """MODEL_FAILOVER.md의 9개 모델 우선순위로 페일오버 체인을 만든다 — 쿼리 확장·
    리랭킹·retrieve_docs 자체 답변 합성 모두 도구 바인딩이 없는 호출이라
    llm_utils.build_llm_with_failover()를 그대로 쓴다."""
    from llm_utils import build_llm_with_failover

    return build_llm_with_failover(region=REGION)


def _default_embeddings():
    from langchain_aws import BedrockEmbeddings

    return BedrockEmbeddings(model_id=EMBED_MODEL_ID, region_name=REGION)


def format_docs(docs) -> str:
    """검색된 문서를 프롬프트에 넣을 문자열로 만든다."""
    return "\n\n".join(
        f"[출처: {d.metadata.get('source', '알 수 없음')}]\n{d.page_content}" for d in docs
    )


# ══════════════════════════════════════════════════════════════════
# 문서 수집 대상 — data/policy_docs, data/pricing_docs
# ══════════════════════════════════════════════════════════════════

_DOC_TYPE_BY_SOURCE = {
    "budget_policy.md": "policy",
    "cost_allocation_policy.md": "policy",
    "tagging_policy.md": "policy",
    "anomaly_response_principles.md": "policy",
    "reserved_instance_policy.md": "pricing",
}


def default_doc_paths() -> list[str]:
    """data/policy_docs, data/pricing_docs 아래 모든 .md 파일 경로를 모은다."""
    paths = []
    for sub in ("policy_docs", "pricing_docs"):
        paths.extend(str(p) for p in sorted((DATA_DIR / sub).glob("*.md")))
    return paths


def build_chunks(doc_paths: list[str] | None = None) -> list[Document]:
    """문서를 읽어 청크 Document 리스트를 만든다.

    - 모든 청크 metadata에 source / doc_type 두 키를 넣는다 (분할 전에 붙여야 상속됨).
    - 정책 문서는 표·목록이 많아 MarkdownHeaderTextSplitter로 섹션 단위를 먼저 살리고,
      그 안에서 너무 긴 섹션만 RecursiveCharacterTextSplitter로 추가 분할한다.
    """
    from langchain_text_splitters import (
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )

    doc_paths = doc_paths if doc_paths is not None else default_doc_paths()

    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2")]
    )
    char_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=60)

    chunks: list[Document] = []
    for doc_path in doc_paths:
        path = Path(doc_path)
        source = path.name
        doc_type = _DOC_TYPE_BY_SOURCE.get(source, "unknown")

        sections = header_splitter.split_text(path.read_text(encoding="utf-8"))
        for section in sections:
            section.metadata = {**section.metadata, "source": source, "doc_type": doc_type}

        for section in sections:
            if len(section.page_content) <= 500:
                chunks.append(section)
            else:
                chunks.extend(char_splitter.split_documents([section]))

    return chunks


_CORPUS_HASH_FILE = "corpus_hash.txt"


def _corpus_hash(chunks: list[Document]) -> str:
    """청크 전체 내용(출처+본문)을 해시한다 — "지난번과 문서가 완전히 같은가"의 근거.

    청크 순서·분할 결과가 바뀌면(문서 추가/수정/삭제, 스플리터 설정 변경 등) 해시도
    같이 바뀌므로, 내용이 조금이라도 달라지면 안전하게 재색인 쪽으로 넘어간다.
    """
    h = hashlib.sha256()
    for chunk in chunks:
        h.update(chunk.metadata.get("source", "").encode("utf-8"))
        h.update(b"\0")
        h.update(chunk.page_content.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def build_vectorstore(chunks: list[Document], embeddings=None):
    """청크를 임베딩해 Chroma 벡터스토어를 만든다.

    문서 내용 해시가 지난 실행과 완전히 같으면 재임베딩을 건너뛰고 이미 저장된
    컬렉션을 그대로 재사용한다 — `data/policy_docs`·`data/pricing_docs`는 자주 안
    바뀌는데, 예전엔 그래프를 새로 만들 때마다(서버 재시작마다, `run_eval.py`
    실행마다) 전체를 처음부터 다시 임베딩해서 콜드 스타트가 매번 그만큼 길어졌다
    (AWS/GCP/Azure 공식 비용 절감 가이드 3개, 9만자 이상을 추가한 뒤 특히 체감됨).
    해시가 하나라도 다르면(문서 추가·수정·삭제, 청크 설정 변경) 안전하게 기존
    동작(전체 삭제 후 재색인)으로 폴백한다.

    파일을 직접 지우지 않고(`shutil.rmtree`) Chroma의 `delete_collection()`으로 지우는
    이유: 같은 프로세스 안에서 이전 Chroma 클라이언트가 파일을 열어둔 채로 있으면
    Windows에서 rmtree가 "다른 프로세스가 사용 중"이라며 PermissionError를 던진다
    (직접 겪음). 클라이언트 API로 지우면 그 문제가 없다.
    """
    from langchain_chroma import Chroma

    embeddings = embeddings or _default_embeddings()
    persist_path = Path(PERSIST_DIR)
    hash_path = persist_path / _CORPUS_HASH_FILE
    current_hash = _corpus_hash(chunks)

    if persist_path.exists() and hash_path.exists() and hash_path.read_text(encoding="utf-8").strip() == current_hash:
        store = Chroma(collection_name=COLLECTION, persist_directory=PERSIST_DIR, embedding_function=embeddings)
        # count()는 Chroma의 langchain 래퍼가 따로 안 감싸줘서 내부 chromadb
        # Collection(_collection)에서 직접 읽는다 — 해시 파일만 남고 컬렉션은
        # 비어있는 등 이상 상태를 방어하기 위한 확인이다.
        if store._collection.count() > 0:
            return store

    if persist_path.exists():
        Chroma(
            collection_name=COLLECTION, persist_directory=PERSIST_DIR, embedding_function=embeddings
        ).delete_collection()

    store = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=COLLECTION,
        persist_directory=PERSIST_DIR,
    )
    persist_path.mkdir(parents=True, exist_ok=True)
    hash_path.write_text(current_hash, encoding="utf-8")
    return store


def _kiwi_tokenize(text: str) -> list[str]:
    """BM25용 한국어 형태소 토크나이저. kiwipiepy 로딩 실패 시 공백 분리로 폴백."""
    try:
        from kiwipiepy import Kiwi

        kiwi = _kiwi_tokenize._kiwi  # type: ignore[attr-defined]
    except AttributeError:
        from kiwipiepy import Kiwi

        kiwi = Kiwi()
        _kiwi_tokenize._kiwi = kiwi  # type: ignore[attr-defined]
    except ImportError:
        return text.split()
    return [t.form for t in kiwi.tokenize(text)]


def build_bm25_retriever(chunks: list[Document], k: int = 4):
    """키워드 기반 BM25 리트리버. 태그명·정책 고유명사 검색에 강하다."""
    from langchain_community.retrievers import BM25Retriever

    retriever = BM25Retriever.from_documents(chunks, preprocess_func=_kiwi_tokenize)
    retriever.k = k
    return retriever


def build_retriever(chunks: list[Document], vectorstore=None, embeddings=None):
    """BM25 + 벡터 검색을 앙상블한 하이브리드 리트리버를 만든다.

    k=4: 정책 문서가 짧고(문서당 1~4개 섹션) 개수가 적어, 상위 4개면 관련 섹션을
    놓치지 않으면서 무관한 문서가 컨텍스트에 섞이는 것도 피할 수 있는 절충값.
    weights=[0.5, 0.5]: 키워드(BM25)와 의미(벡터) 중 한쪽에 치우치지 않도록 동등 가중.
    """
    from langchain_classic.retrievers import EnsembleRetriever

    vectorstore = vectorstore or build_vectorstore(chunks, embeddings=embeddings)
    vector_retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
    bm25_retriever = build_bm25_retriever(chunks, k=4)

    return EnsembleRetriever(retrievers=[bm25_retriever, vector_retriever], weights=[0.5, 0.5])


def build_expanded_retriever(base_retriever, llm=None):
    """LLM이 원 질문을 3가지 버전으로 바꿔 각각 base_retriever로 검색한 뒤 합친다.

    MultiQueryRetriever가 내부적으로 "질문 -> 대안 질문 목록" LCEL 체인을 만들고,
    각 버전으로 base_retriever.invoke()를 호출해 결과를 중복 제거해 합친다.
    """
    from langchain_classic.retrievers.multi_query import MultiQueryRetriever

    llm = llm or _default_llm()
    return MultiQueryRetriever.from_llm(retriever=base_retriever, llm=llm)


# ══════════════════════════════════════════════════════════════════
# 검색 결과 품질 판정 — 근거 없으면 모델을 부르지 않는다 (Day 2 assess_retrieval 재사용)
# ══════════════════════════════════════════════════════════════════

def assess_retrieval(docs, question: str) -> dict:
    """검색 결과가 이 질문에 답하기에 쓸만한지 판정한다. LLM을 호출하지 않는다."""

    def _clean(text: str) -> str:
        return re.sub(r"[^0-9A-Za-z가-힣]", "", text or "")

    cleaned_question = _clean(question)
    keywords = {cleaned_question[i : i + 2] for i in range(len(cleaned_question) - 1)}

    if not docs or not keywords:
        return {
            "usable": False,
            "reason": "검색 결과가 없거나 질문에서 핵심어를 뽑지 못했습니다.",
            "matched": 0,
            "ratio": 0.0,
        }

    body = _clean(" ".join(d.page_content for d in docs))
    matched = sum(1 for kw in keywords if kw in body)
    ratio = matched / len(keywords)
    # matched >= 2 를 고정으로 두면, 정리된 질문이 2~3자라 고유 2-그램이 1개뿐인
    # 경우(예: "한도?" -> "한도" 하나) 아무리 관련 있어도 절대 통과할 수 없었다.
    # 핵심어가 1개뿐이면 그 1개만 맞아도 충분하다고 본다.
    required = min(2, len(keywords))
    usable = matched >= required and ratio >= 0.2

    return {
        "usable": usable,
        "reason": f"질의어 조각 {len(keywords)}개 중 {matched}개가 본문에 등장 (비율 {ratio:.2f})",
        "matched": matched,
        "ratio": ratio,
    }


# ══════════════════════════════════════════════════════════════════
# 리랭킹 — 쿼리 확장으로 늘어난 후보를 관련도 순으로 다시 좁힌다
# ══════════════════════════════════════════════════════════════════

class RankedDocs(BaseModel):
    """질문과의 관련도가 높은 순서대로 나열한 문서 번호."""

    ranked_indices: list[int] = Field(
        description=(
            "관련도가 높은 순서대로 나열한 문서 번호(0부터 시작) 목록. "
            "질문과 관련 없는 문서는 목록에서 아예 빼도 된다."
        )
    )


_RERANK_SYSTEM_PROMPT = (
    "너는 검색 결과 리랭커다. 질문과 각 문서의 관련도를 판단해, 이 질문에 답하는 데 "
    "실제로 도움이 되는 순서대로 문서 번호를 나열하라. 관련 없는 문서는 제외하라."
)


def build_reranker(llm=None):
    """문서 후보 목록을 관련도 순으로 재정렬하는 LCEL 체인을 만든다 (패턴 1과 동일한
    JsonOutputParser + Pydantic 스키마 구조).
    """
    from langchain_core.output_parsers import JsonOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    llm = llm or _default_llm()
    parser = JsonOutputParser(pydantic_object=RankedDocs)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _RERANK_SYSTEM_PROMPT),
            ("human", "질문: {question}\n\n문서 후보:\n{numbered_docs}\n\n{format_instructions}"),
        ]
    ).partial(format_instructions=parser.get_format_instructions())

    return prompt | llm | parser


def rerank_docs(question: str, docs: list[Document], reranker, top_k: int = 4) -> list[Document]:
    """reranker로 docs를 관련도 순 재정렬하고 top_k개만 남긴다.

    reranker 호출이 실패하거나(파싱 오류 등) 응답이 비어 있으면, 원래 순서 그대로
    top_k개를 잘라 반환한다 — 리랭킹은 정밀도 보강이지 필수 경로가 아니다.
    """
    if not docs:
        return docs
    if reranker is None:
        return docs[:top_k]

    numbered = "\n\n".join(
        f"[{i}] (출처: {d.metadata.get('source', '알 수 없음')})\n{d.page_content}" for i, d in enumerate(docs)
    )
    try:
        result = reranker.invoke({"question": question, "numbered_docs": numbered})
        order = result.get("ranked_indices") or []
    except Exception:  # noqa: BLE001
        return docs[:top_k]

    ranked = [docs[i] for i in order if isinstance(i, int) and 0 <= i < len(docs)]
    # 모델이 순위에서 빠뜨린 문서는 완전히 버리지 않고 원래 순서대로 뒤에 붙인다.
    seen = {i for i in order if isinstance(i, int)}
    ranked += [d for i, d in enumerate(docs) if i not in seen]
    return ranked[:top_k]


NO_ANSWER = {
    "answer": "제공된 정책·가격 문서에서 답을 찾을 수 없습니다.",
    "sources": [],
}

_SYSTEM_PROMPT = (
    "당신은 사내 클라우드 비용(FinOps) 정책 문서에 근거해 답하는 도우미입니다. "
    "아래 제공된 문서 내용만 근거로 답하고, 문서에 없는 내용은 답하지 마세요. "
    "숫자(한도·절감률 등)를 답할 때는 반드시 출처 문서명을 함께 밝히세요."
)


_FAST_PATH_RATIO = 0.5  # 이 이상이면 쿼리 확장·리랭킹 없이 기본 검색 결과만으로 충분하다고 본다


def build_rag_chain(
    retriever,
    base_retriever=None,
    llm=None,
    reranker=None,
    rerank_top_k: int = 4,
    candidate_cap: int = 10,
):
    """질문 문자열을 받아 {"answer": str, "sources": list[str]} 를 반환하는 체인을 만든다.

    retriever가 build_expanded_retriever로 감싼 쿼리 확장 리트리버면 후보가
    늘어나므로(질문 변형 3개 x 하이브리드 상위 8개까지), candidate_cap으로 먼저
    자르고 reranker로 rerank_top_k개까지 좁힌다. reranker가 None이면 그냥
    candidate_cap 안에서 상위 rerank_top_k개를 쓴다(기존 동작과 동일).

    base_retriever(쿼리 확장 전, LLM 미호출 하이브리드 리트리버)를 같이 주면 "빠른
    경로"를 먼저 시도한다: 확장 없이 base_retriever로만 검색해서 assess_retrieval의
    일치 비율이 이미 충분히 높으면(_FAST_PATH_RATIO 이상) 쿼리 확장(LLM 1회) +
    리랭킹(LLM 1회)을 통째로 건너뛴다. 질문이 정책 문서의 용어를 그대로 쓴
    경우(예: "예산 한도") 흔한 경로라, 이 두 LLM 호출을 아끼면 retrieve_docs 전체
    지연이 눈에 띄게 줄어든다 — 용어가 안 겹치는 애매한 질문은 비율이 낮게 나와
    기존처럼 확장+리랭킹 경로로 그대로 넘어간다(정확도 저하 없음).
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.runnables import RunnableLambda

    llm = llm or _default_llm()

    def _answer(question: str) -> dict:
        docs = None
        judgement = None
        if base_retriever is not None:
            base_candidates = base_retriever.invoke(question)[:candidate_cap]
            base_judgement = assess_retrieval(base_candidates, question)
            if base_judgement.get("usable") and base_judgement.get("ratio", 0.0) >= _FAST_PATH_RATIO:
                docs = base_candidates[:rerank_top_k]
                judgement = base_judgement

        if docs is None:
            candidates = retriever.invoke(question)[:candidate_cap]
            docs = rerank_docs(question, candidates, reranker, top_k=rerank_top_k)
            judgement = assess_retrieval(docs, question)

        if not judgement.get("usable"):
            return {**NO_ANSWER, "sources": []}

        context = format_docs(docs)
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=f"문서:\n{context}\n\n질문: {question}"),
        ]
        response = llm.invoke(messages)

        sources: list[str] = []
        for d in docs:
            source = d.metadata.get("source")
            if source and source not in sources:
                sources.append(source)

        return {"answer": get_text(response), "sources": sources}

    return RunnableLambda(_answer)


# ══════════════════════════════════════════════════════════════════
# 도구화 — Supervisor의 서브 에이전트가 호출할 retrieve_docs
# ══════════════════════════════════════════════════════════════════

class RetrieveDocsArgs(BaseModel):
    query: str = Field(..., description="검색할 질문. 예: '팀별 예산 한도가 얼마야'")


def make_retrieve_docs_tool(rag_chain):
    """rag_chain을 클로저로 감싼 retrieve_docs 도구를 만든다.

    retriever 자체가 아니라 rag_chain(질문 -> {answer, sources})을 감싸는 이유:
    도구 호출 한 번으로 "근거 문서 + 이미 답변까지 합성된 결과"를 서브 에이전트에
    돌려줘야 ReAct 루프가 한 바퀴 덜 돈다.
    """

    @tool(args_schema=RetrieveDocsArgs)
    def retrieve_docs(query: str) -> str:
        """FinOps 정책·가격 문서에서 근거를 검색해 답한다.

        예산 한도, 태깅 규칙, 비용 배분 기준, RI/Savings Plan 절감 조건처럼
        정책 문서 근거가 필요한 질문에만 사용하라. 비용 수치 조회에는 쓰지 마라.
        """
        result = rag_chain.invoke(query)
        sources = ", ".join(result.get("sources", [])) or "없음"
        return f"{result['answer']}\n(출처: {sources})"

    return retrieve_docs
