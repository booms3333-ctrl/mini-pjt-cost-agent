"""RAGAS 대체 구현 — 패턴 12 (RAGAS 지표).

`ragas` PyPI 패키지는 이 프로젝트의 langchain 스택과 호환되지 않는다. 직접 겪은
문제: ragas는 버전(0.2.15, 0.4.3 둘 다 확인)과 무관하게 모듈 로드 시
`langchain_community.chat_models.vertexai`를 무조건 import 하는데, 이 모듈은
langchain-community 0.4 이상에서 제거되었다. 되돌리려고 langchain-community를
0.3.x로 내리면 langchain-core가 1.0 미만으로 강제 다운그레이드되고, 그 순간
langgraph 1.x / langchain-aws / langchain-chroma / langchain-classic /
langchain-mcp-adapters가 전부 깨진다 — 이 프로젝트의 Multi-Agent Supervisor,
MCP 연동, 하이브리드 리트리버(EnsembleRetriever)가 모두 이 최신 스택에 의존하므로
ragas 하나를 위해 나머지를 전부 되돌릴 수는 없다 (실제로 시도했다가 원복했다).

그래서 ragas 패키지를 쓰지 않고, 같은 지표를 우리 Bedrock LLM으로 직접 계산한다.
faithfulness / answer_relevancy / context_precision은 RAGAS 논문과 같은 정의를
LLM-as-Judge로 재구현했다 (answer_chain.py, retriever.py의 리랭커와 같은
LCEL + Pydantic 구조화 출력 패턴). context_recall은 구현하지 않았다 — RAGAS의
context_recall은 정답 문서(ground_truth) 목록이 있어야 계산되는데
test_queries.csv에는 없다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

def _default_llm():
    """MODEL_FAILOVER.md의 9개 모델 우선순위로 페일오버 체인을 만든다."""
    from llm_utils import build_llm_with_failover

    return build_llm_with_failover()


class FaithfulnessResult(BaseModel):
    """RAGAS faithfulness와 같은 정의: 답변의 주장이 컨텍스트로 뒷받침되는 비율."""

    score: float = Field(description="0.0~1.0. 답변의 주장 중 컨텍스트로 뒷받침되는 비율")
    unsupported_claims: list[str] = Field(
        default_factory=list, description="컨텍스트에 없는데 답변에 등장하는 주장 목록. 없으면 빈 리스트"
    )


class RelevancyResult(BaseModel):
    """RAGAS answer_relevancy와 같은 정의: 답변이 질문에 얼마나 직접적으로 답하는가."""

    score: float = Field(description="0.0~1.0. 답변이 질문의 의도에 직접적으로 답할수록 1.0에 가깝다")


class ContextPrecisionResult(BaseModel):
    """RAGAS context_precision과 같은 정의: 검색된 컨텍스트 중 실제로 관련 있는 비율."""

    score: float = Field(description="0.0~1.0. 컨텍스트 중 질문에 답하는 데 실제로 쓸모 있었던 비율")


def _build_chain(llm, schema, system_prompt: str, human_template: str):
    from langchain_core.output_parsers import JsonOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    parser = JsonOutputParser(pydantic_object=schema)
    prompt = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", human_template + "\n\n{format_instructions}")]
    ).partial(format_instructions=parser.get_format_instructions())
    return prompt | llm | parser


def build_faithfulness_chain(llm=None):
    llm = llm or _default_llm()
    return _build_chain(
        llm,
        FaithfulnessResult,
        "너는 RAG 답변의 사실성(faithfulness)을 평가하는 채점자다. 답변에 등장하는 "
        "주장 각각이 주어진 컨텍스트로 실제 뒷받침되는지만 본다. 컨텍스트에 없는 "
        "일반 상식이나 예의상 문구는 주장으로 치지 않는다.",
        "질문: {question}\n\n컨텍스트:\n{contexts}\n\n답변:\n{answer}",
    )


def build_relevancy_chain(llm=None):
    llm = llm or _default_llm()
    return _build_chain(
        llm,
        RelevancyResult,
        "너는 RAG 답변의 관련성(answer relevancy)을 평가하는 채점자다. 답변이 "
        "질문에 실제로 답하고 있는지만 본다. 답변이 사실인지는 평가하지 마라.",
        "질문: {question}\n\n답변:\n{answer}",
    )


def build_context_precision_chain(llm=None):
    llm = llm or _default_llm()
    return _build_chain(
        llm,
        ContextPrecisionResult,
        "너는 RAG 검색 결과의 정밀도(context precision)를 평가하는 채점자다. "
        "검색된 컨텍스트 중 이 질문에 답하는 데 실제로 쓸모 있었던 비율만 본다.",
        "질문: {question}\n\n검색된 컨텍스트:\n{contexts}",
    )


def evaluate_ragas_lite(records: list[dict[str, Any]], llm=None) -> dict:
    """records: [{"question": str, "answer": str, "contexts": list[str]}]

    contexts가 없는 레코드(RAG 도구를 안 쓴 문항)는 호출자가 미리 걸러서 넘겨야 한다.
    개별 레코드 채점이 실패해도(예: JSON 파싱 오류) 그 레코드만 건너뛰고 계속한다.
    """
    llm = llm or _default_llm()
    faithfulness_chain = build_faithfulness_chain(llm)
    relevancy_chain = build_relevancy_chain(llm)
    precision_chain = build_context_precision_chain(llm)

    scores: dict[str, list[float]] = {"faithfulness": [], "answer_relevancy": [], "context_precision": []}
    details = []

    for i, rec in enumerate(records, start=1):
        print(f"  [{i}/{len(records)}] 채점 중: {rec.get('question', '')[:30]}...", flush=True)
        question = rec.get("question", "")
        answer = rec.get("answer", "")
        contexts_text = "\n\n".join(rec.get("contexts") or []) or "(검색된 컨텍스트 없음)"

        entry: dict[str, Any] = {"question": question}
        try:
            f = faithfulness_chain.invoke({"question": question, "answer": answer, "contexts": contexts_text})
            scores["faithfulness"].append(float(f["score"]))
            entry["faithfulness"] = f
        except Exception as exc:  # noqa: BLE001
            entry["faithfulness_error"] = f"{type(exc).__name__}: {exc}"

        try:
            rel = relevancy_chain.invoke({"question": question, "answer": answer})
            scores["answer_relevancy"].append(float(rel["score"]))
            entry["answer_relevancy"] = rel
        except Exception as exc:  # noqa: BLE001
            entry["answer_relevancy_error"] = f"{type(exc).__name__}: {exc}"

        try:
            prec = precision_chain.invoke({"question": question, "contexts": contexts_text})
            scores["context_precision"].append(float(prec["score"]))
            entry["context_precision"] = prec
        except Exception as exc:  # noqa: BLE001
            entry["context_precision_error"] = f"{type(exc).__name__}: {exc}"

        details.append(entry)

    summary = {k: (round(sum(v) / len(v), 3) if v else None) for k, v in scores.items()}
    summary["context_recall"] = None  # ground_truth 없어 계산 불가 (RAGAS 정의상 필수 입력)
    summary["n"] = len(records)

    return {"summary": summary, "details": details}
