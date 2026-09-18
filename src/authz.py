"""요청자 팀 접근 범위 — SERVICE.md 가드레일 규칙 5.

"요청자의 접근 권한 범위를 벗어난 다른 팀·계정의 비용 정보는 제공하지 않는다"를
실제로 강제한다. 이전까지는 이 규칙이 문서에만 있고 코드에는 전혀 없었다 —
team은 그냥 LLM이 골라서 넘기는 선택적 필터 인자일 뿐이라, "team-b 비용 얼마야?"
라고 물으면 별다른 권한 확인 없이 그대로 보여줬다.

contextvars로 요청 하나(pipeline.ask/resume 한 번) 동안 "이 요청을 보낸 사람이
어느 팀 소속인지"를 들고 다니다가, tools.py의 조회·실행 함수가 DB에 실제 쿼리를
날리기 직전에 확인한다. LLM이 도구 인자에 어떤 team/resource_id를 넣든, 서버
쪽에서 강제로 걸러진다 — 프롬프트 인젝션으로 "나는 team-a인데 team-b 것도
보여줘"라고 시켜도 우회할 수 없는 계층이라는 게 프롬프트 레벨 방어와의 차이다.

requester_team이 None이면 "제한 없음"(플랫폼팀 — SERVICE.md의 "클라우드
플랫폼팀 2~3명"은 전체를 봐야 하는 사용자)으로 본다. 값이 있으면 그 팀 소속
데이터만 보인다 — "개발팀 리드는 자기 팀만" 시나리오.
"""

from __future__ import annotations

import contextvars

_requester_team: contextvars.ContextVar[str | None] = contextvars.ContextVar("requester_team", default=None)


def set_requester_team(team: str | None) -> None:
    _requester_team.set(team)


def get_requester_team() -> str | None:
    return _requester_team.get()


def resolve_team_filter(team: str | None) -> tuple[str | None, str | None]:
    """조회에 실제로 적용할 team과, 막아야 한다면 거절 사유를 돌려준다.

    - 요청자가 제한 없음(None)이면 LLM이 넘긴 team을 그대로 쓴다.
    - 요청자가 특정 팀으로 제한돼 있으면:
      - team을 안 넘겼어도(전체 조회 시도) 본인 팀으로 강제로 좁힌다.
      - 다른 팀을 명시적으로 요청했으면 거절 메시지를 돌려준다.

    Returns:
        (조회에 쓸 team, 거절 사유). 거절 사유가 있으면 호출자는 조회를 중단하고
        그 문자열을 그대로 반환해야 한다.
    """
    requester = get_requester_team()
    if requester is None:
        return team, None
    if team is not None and team != requester:
        return None, f"'{team}' 데이터는 조회 권한이 없습니다. 본인 팀({requester}) 데이터만 조회할 수 있습니다."
    return requester, None


def check_resource_team(resource_team: str | None) -> str | None:
    """resource_id로 조회/실행하려는 대상이 이미 team이 정해져 있을 때(예: 리소스
    소유 팀) 쓴다. 막아야 하면 거절 사유를, 통과하면 None을 돌려준다.
    """
    requester = get_requester_team()
    if requester is None:
        return None
    if resource_team is not None and resource_team != requester:
        return f"이 리소스는 '{resource_team}' 소속이라 권한이 없습니다. 본인 팀({requester}) 리소스만 조회·조작할 수 있습니다."
    return None
