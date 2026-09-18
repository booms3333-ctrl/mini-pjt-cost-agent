"""트레이스 기록 — 패턴 11.

기본 경로는 로컬 JSONL 트레이스다: Day 7(day07/practice/starter/submission.py)의
TraceCollector를 그대로 가져와 llm_start/llm_end/tool_start/tool_end를 기록하고
data/traces/<thread_id>.jsonl 로 남긴다. 외부 서비스 계정이 없어도 항상 동작하고
검증 가능하다는 게 핵심 — 이 프로젝트를 만든 샌드박스에는 LangSmith 계정이 없어서
로컬 경로만 실행 검증했다.

.env에 LANGCHAIN_TRACING_V2=true + LANGCHAIN_API_KEY(+ LANGCHAIN_PROJECT)를 설정하면
LangSmith가 코드 변경 없이 모든 LangChain/LangGraph 호출을 추가로 수집한다 — 이건
LangChain의 전역 표준 트레이싱이라 여기서 따로 배선할 게 없다(app.py가 앱 시작 시
load_dotenv()로 그 값을 읽어들이기만 하면 된다). LangFuse를 쓰려면 langfuse의
CallbackHandler를 그래프 invoke의 config["callbacks"]에 추가하면 같은 방식으로 붙는다.
"""

from __future__ import annotations

import contextvars
import json
import os
import time
from pathlib import Path
from typing import Any

TRACE_DIR = Path(__file__).resolve().parent.parent / "data" / "traces"


class TraceCollector:
    """실행 중 일어난 일을 기록한다. (Day 7과 동일한 최소 인터페이스)"""

    def __init__(self) -> None:
        self._events: list[dict] = []

    def record(self, event: str, name: str, **fields: Any) -> None:
        """event: "llm_start" | "llm_end" | "tool_start" | "tool_end" 중 하나."""
        self._events.append({"seq": len(self._events), "event": event, "name": name, **fields})

    @property
    def events(self) -> list[dict]:
        return list(self._events)

    def dump(self, path: str | Path) -> None:
        """이벤트를 JSON Lines 파일로 쓴다. 한 줄에 한 이벤트."""
        with Path(path).open("w", encoding="utf-8") as f:
            for event in self._events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")


# 요청 하나(=graph.ainvoke 한 번) 동안 생긴 이벤트를 어디서든 기록할 수 있도록
# contextvar에 둔다. asyncio 태스크 안에서 await를 타고 내려가도 값이 유지되므로,
# agent.py의 노드 함수들이 별도 인자 없이 get_collector()로 같은 콜렉터를 찾는다.
_current_collector: contextvars.ContextVar["TraceCollector | None"] = contextvars.ContextVar(
    "current_trace_collector", default=None
)


def start_collector() -> TraceCollector:
    """요청 하나를 시작할 때 호출한다 (pipeline.ask/resume)."""
    collector = TraceCollector()
    _current_collector.set(collector)
    return collector


def get_collector() -> TraceCollector:
    """현재 요청의 TraceCollector를 찾는다.

    start_collector()를 거치지 않은 컨텍스트(단위 테스트 등)에서는 매번 새
    콜렉터를 만들어 반환한다 — 기록은 되지만 아무도 dump하지 않으니 버려진다.
    """
    return _current_collector.get() or TraceCollector()


def dump_current(thread_id: str) -> Path | None:
    collector = _current_collector.get()
    if collector is None:
        return None
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    path = TRACE_DIR / f"{thread_id}.jsonl"
    collector.dump(path)
    return path


def langsmith_enabled() -> bool:
    return os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true" and bool(
        os.environ.get("LANGCHAIN_API_KEY")
    )


class Timer:
    """with 블록으로 감싸 호출 하나를 {event_prefix}_start/{event_prefix}_end로 기록한다."""

    def __init__(self, event_prefix: str, name: str, **fields: Any) -> None:
        self.collector = get_collector()
        self.event_prefix = event_prefix
        self.name = name
        self.fields = fields
        self._start = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.monotonic()
        self.collector.record(f"{self.event_prefix}_start", self.name, **self.fields)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        elapsed = time.monotonic() - self._start
        status = "error" if exc_type else "ok"
        self.collector.record(f"{self.event_prefix}_end", self.name, latency_s=round(elapsed, 3), status=status)
        return False
