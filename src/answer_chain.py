"""LCEL 구조화 출력 체인 — 패턴 1.

Day 1(day01/practice/starter/submission.py)의 build_triage_chain과 같은 형태를
그대로 따른다: Pydantic 스키마 정의 -> JsonOutputParser에 물려 format_instructions를
프롬프트에 주입 -> `prompt | llm | parser` LCEL 체인으로 답변을 구조화한다.

서브 에이전트(Supervisor)가 만든 원시 텍스트 답변을 사용자에게 그대로 보내는 대신,
이 체인을 한 번 더 거쳐 {summary, key_numbers, confidence, needs_followup} 형태로
정규화한다. pipeline.finalize()가 이 dict를 최종 응답에 담는다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

def _default_llm():
    """MODEL_FAILOVER.md의 9개 모델 우선순위로 페일오버 체인을 만든다 — 도구 바인딩이
    필요 없는 구조화 호출이라 llm_utils.build_llm_with_failover()를 그대로 쓴다."""
    from llm_utils import build_llm_with_failover

    return build_llm_with_failover()


class StructuredAnswer(BaseModel):
    """최종 사용자 응답 스키마."""

    summary: str = Field(description="사용자 질문에 대한 핵심 답변. 2~4문장, 정중한 존댓말")
    key_numbers: list[str] = Field(
        default_factory=list,
        description=(
            "답변에 등장하는 핵심 수치·금액·비율 목록 (예: ['$332.35', 'z-score 72.55']). "
            "수치가 없는 답변이면 빈 리스트"
        ),
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="원시 답변이 실제 도구 조회 결과에 근거하는 정도. 도구 호출 없이 나온 답변이면 low"
    )
    needs_followup: bool = Field(description="사용자에게 추가 확인·승인·후속 조치를 권해야 하는지")


ANSWER_SCHEMA = StructuredAnswer

_SYSTEM_PROMPT = (
    "너는 클라우드 비용 에이전트의 응답을 사용자에게 보여줄 형태로 정리하는 후처리기다. "
    "원시 답변에 있는 사실과 수치만 쓰고, 없는 내용은 절대 지어내지 마라."
)


def build_answer_chain(llm=None):
    """원시 답변 텍스트를 StructuredAnswer 형태의 dict로 정규화하는 LCEL 체인을 만든다.

    반드시 지킬 것 (Day 1과 동일):
      - 프롬프트에 파서의 format_instructions를 실제로 주입해야 한다.
        스키마만 정의하고 프롬프트에 넣지 않으면 모델은 형식을 모른다.
    """
    from langchain_core.output_parsers import JsonOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    llm = llm or _default_llm()

    parser = JsonOutputParser(pydantic_object=ANSWER_SCHEMA)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _SYSTEM_PROMPT),
            (
                "human",
                "질문: {question}\n\n원시 답변:\n{raw_answer}\n\n{format_instructions}",
            ),
        ]
    ).partial(format_instructions=parser.get_format_instructions())

    return prompt | llm | parser
