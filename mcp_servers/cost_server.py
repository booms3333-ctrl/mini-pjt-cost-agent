"""AWS/GCP/Azure Cost API를 흉내 낸 MCP 서버 (패턴 5).

Day 4(day04/mcp_server.py)와 같은 fastmcp 패턴(TOOL_SPECS/TOOLS_IMPL 순회 등록)을
쓴다. 세 서버(aws-cost-mcp / gcp-billing-mcp / azure-cost-mcp)는 로직이 동일하고
계정 경계만 다르므로, 파일을 3벌 복제하는 대신 이 스크립트 하나를 MCP_PROVIDER
환경변수로 파라미터화했다. 비용·사용률·유휴 리소스 도구는 src/tools.py의 SQLite
조회를 그대로 감싸되 provider를 이 서버의 값으로 고정해 "이 계정 데이터만
보인다"는 경계를 흉내 낸다. check_incidents만 예외 — 이건 합성 데이터가 아니라
src/incident_feeds.py를 통해 실제 클라우드 공개 상태 피드를 실시간으로 조회한다.

실행 (직접 실행할 때는 stdio 클라이언트가 없으면 그냥 대기한다):
    MCP_PROVIDER=aws python mcp_servers/cost_server.py
    MCP_PROVIDER=gcp python mcp_servers/cost_server.py
    MCP_PROVIDER=azure python mcp_servers/cost_server.py

실제 연결은 src/mcp_client.py 가 세 프로세스를 자식으로 띄워서 한다.

주의: stdio 전송에서는 stdout에 아무것도 print하면 안 된다 (프로토콜이 깨진다).
로그가 필요하면 반드시 stderr로 보낸다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import incident_feeds  # noqa: E402
import tools  # noqa: E402

PROVIDER = os.environ.get("MCP_PROVIDER", "").lower()
if PROVIDER not in tools.VALID_PROVIDERS:
    print(
        f"MCP_PROVIDER 환경변수가 aws/gcp/azure 중 하나여야 합니다 (받은 값: '{PROVIDER}')",
        file=sys.stderr,
    )
    sys.exit(1)


def get_cost(start_date: str | None = None, end_date: str | None = None) -> str:
    """이 계정의 기간·서비스별 비용을 조회합니다 (전체 팀 합산).

    team 인자를 일부러 안 받는다: authz.py의 팀별 접근 제한(src/tools.py의
    get_cost_by_service가 쓰는 것)은 contextvars 기반이라 이 MCP 서버가 별도
    자식 프로세스로 뜨는 순간 부모 프로세스의 요청자 정보를 못 받는다. team
    인자를 열어두면 제한된 요청자도 이 경로로 다른 팀 비용을 콕 집어 볼 수
    있었다 — 그래서 팀별 조회는 권한 검사가 실제로 걸리는 로컬 도구
    get_cost_by_service로만 하게 막고, 여기서는 계정 전체 합산만 내준다.
    """
    return tools.get_cost_by_service.func(provider=PROVIDER, start_date=start_date, end_date=end_date, team=None)


def get_utilization(resource_id: str) -> str:
    """이 계정 소속 리소스의 사용률과 상태를 조회합니다. 다른 계정 리소스는 조회할 수 없습니다.

    [과거 한계, 부모 프로세스 쪽에서 막음] 이 함수 자체는 여전히 요청자 신원을
    모른다(자식 프로세스라 authz의 contextvars가 안 건너감) — 그건 근본적으로
    안 바뀐다. 다만 agent.py의 tools_node가 이 도구(aws/gcp/azure_get_utilization)를
    실제로 호출하기 *전에*, 같은 costs.db를 직접 읽어 resource_id의 소유 팀을
    확인하고 authz.check_resource_team()으로 막을지 판단한다 — 여기 이 함수까지
    오기 전에 이미 걸러진다는 뜻이다. 이 함수를 MCP 없이 직접(테스트 코드 등에서)
    호출하면 이 검사를 우회하게 되므로, 실제 서비스로 확장할 때는 여전히 MCP 툴
    호출 자체에 요청자 신원을 실어 보내는 방식(세션별 서버 기동, 서명된 토큰 등)이
    더 근본적인 해법이다.
    """
    result = tools.get_resource_utilization.func(resource_id=resource_id)
    if f"({PROVIDER}/" not in result:
        return f"'{resource_id}'는 이 계정({PROVIDER})에 속한 리소스가 아니거나 존재하지 않습니다."
    return result


def list_idle() -> str:
    """이 계정의 유휴 리소스를 목록화합니다."""
    return tools.list_idle_resources.func(provider=PROVIDER)


def check_incidents(start_date: str, end_date: str) -> str:
    """이 계정(클라우드 제공자)의 실제 공개 상태 피드에서 [start_date, end_date]와
    겹치는 장애 이력을 조회합니다. 인증이 필요 없는 공개 API를 실시간으로 호출합니다
    (src/incident_feeds.py 참고) — 합성 비용 데이터와 달리 이건 실제 데이터입니다.

    비용 이상 급증이 클라우드 자체 장애 때문인지 확인할 때 쓰세요. GCP는 과거
    이력을 제공하지만, AWS/Azure 피드는 "현재 진행 중인 이슈"만 제공한다는 한계가
    있습니다(결과가 비어 있어도 그 날짜에 장애가 없었다고 단정하면 안 됩니다).
    """
    return incident_feeds.check_incidents(PROVIDER, start_date, end_date)


# 프로바이더별로 도구 이름을 구분한다 (aws_get_cost / gcp_get_cost / ...). 세 서버의
# 도구를 한 클라이언트에서 합쳐 쓰므로, 이름이 겹치면 어느 계정 도구인지 알 수 없다.
TOOL_SPECS: list[dict] = [
    {
        "name": f"{PROVIDER}_get_cost",
        "description": (
            f"{PROVIDER.upper()} 계정의 기간·서비스별 비용을 조회합니다(전체 팀 합산). "
            "팀별로 나눠 봐야 하면 이 도구 대신 get_cost_by_service를 쓰세요."
        ),
        "args": {
            "start_date": "YYYY-MM-DD. 비우면 이번 달 1일",
            "end_date": "YYYY-MM-DD. 비우면 데이터 마지막 날",
        },
    },
    {
        "name": f"{PROVIDER}_get_utilization",
        "description": f"{PROVIDER.upper()} 계정 리소스의 사용률·상태를 조회합니다.",
        "args": {"resource_id": "조회할 리소스 ID"},
    },
    {
        "name": f"{PROVIDER}_list_idle",
        "description": f"{PROVIDER.upper()} 계정의 유휴 리소스를 목록화합니다.",
        "args": {},
    },
    {
        "name": f"{PROVIDER}_check_incidents",
        "description": (
            f"{PROVIDER.upper()}의 실제 공개 상태 피드에서 지정 기간과 겹치는 장애 이력을 "
            "조회합니다(인증 불필요, 실시간). 비용 이상 급증이 클라우드 자체 장애 때문인지 "
            "확인할 때 쓰세요."
        ),
        "args": {
            "start_date": "조회 시작일 YYYY-MM-DD",
            "end_date": "조회 종료일 YYYY-MM-DD",
        },
    },
]

TOOLS_IMPL = {
    f"{PROVIDER}_get_cost": get_cost,
    f"{PROVIDER}_get_utilization": get_utilization,
    f"{PROVIDER}_list_idle": list_idle,
    f"{PROVIDER}_check_incidents": check_incidents,
}


def build_server():
    """TOOL_SPECS를 순회하며 fastmcp에 도구를 등록한다."""
    from fastmcp import FastMCP

    mcp = FastMCP(f"{PROVIDER}-cost-mcp")
    for spec in TOOL_SPECS:
        fn = TOOLS_IMPL[spec["name"]]
        mcp.tool(name=spec["name"], description=spec["description"])(fn)
    return mcp


if __name__ == "__main__":
    build_server().run(show_banner=False)
