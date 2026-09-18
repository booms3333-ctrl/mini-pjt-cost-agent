"""도메인 도구 — 비용조회 · 이상탐지 · 절감계산 · 실행.

Day 3 (day03/practice/starter/submission.py) 의 도구 스타일(Pydantic args_schema,
결정적 동작 — 같은 인자엔 항상 같은 결과, 언제 써야 하는지 docstring에 명시)을
그대로 따른다. 데이터 소스는 LLM이 아니라 ``data/costs.db`` (scripts/generate_data.py
로 생성한 합성 SQLite)이다.

쓰기·실행 도구(stop_resource / resize_resource / send_cost_alert)는 여기서는
"이미 승인됐다"는 전제로 동작한다. 승인 여부 판정(needs_approval)과 실제 승인
게이트는 agent.py에서 guardrails.needs_approval + interrupt()로 처리한다.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, Field

import authz

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "costs.db"
VALID_PROVIDERS = {"aws", "gcp", "azure"}


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise RuntimeError(
            f"{DB_PATH} 가 없습니다. 먼저 `python scripts/generate_data.py` 를 실행하세요."
        )
    return sqlite3.connect(DB_PATH)


def _data_range() -> tuple[date, date]:
    conn = _connect()
    row = conn.execute("SELECT MIN(usage_date), MAX(usage_date) FROM costs").fetchone()
    conn.close()
    if not row or not row[0]:
        raise RuntimeError("costs 테이블이 비어 있습니다.")
    return date.fromisoformat(row[0]), date.fromisoformat(row[1])


def today() -> date:
    """시스템이 '오늘'로 취급하는 날짜. 데이터 마지막 날짜 + 1일 (구현 전 의사결정 A)."""
    _, d_end = _data_range()
    return d_end + timedelta(days=1)


def today_str() -> str:
    return today().isoformat()


def resource_team(resource_id: str) -> str | None:
    """resource_id의 소유 팀을 조회한다. 없으면 None.

    agent.py가 MCP 리소스 단위 도구(aws_get_utilization 등)를 실제로 호출하기
    *전에* authz 경계를 강제하려고 쓴다 — MCP 서버는 별도 자식 프로세스라
    contextvars(요청자 팀 정보)가 안 건너가므로, 그 경계 검사를 여기 부모
    프로세스 쪽에서 먼저 해야 한다(mcp_servers/cost_server.py의 "알려진 한계"
    주석 참고). costs.db는 부모·자식이 같은 파일을 읽으므로 이 조회 자체는
    MCP 프로세스를 거치지 않고도 가능하다.
    """
    conn = _connect()
    row = conn.execute("SELECT team FROM resources WHERE resource_id = ?", (resource_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def _provider_error(provider: str | None) -> str | None:
    if provider is not None and provider.lower() not in VALID_PROVIDERS:
        return f"'{provider}'는 관리 대상 클라우드가 아닙니다 (지원: aws, gcp, azure)."
    return None


# ══════════════════════════════════════════════════════════════════
# 조회
# ══════════════════════════════════════════════════════════════════

class GetCostArgs(BaseModel):
    provider: str | None = Field(None, description="aws/gcp/azure 중 하나. 비우면 전체 합산")
    start_date: str | None = Field(None, description="조회 시작일 YYYY-MM-DD. 비우면 이번 달 1일")
    end_date: str | None = Field(
        None, description="조회 종료일 YYYY-MM-DD. 비우면 데이터의 마지막 날(=오늘의 전날)"
    )
    team: str | None = Field(None, description="team-a/team-b/team-c 중 하나로 필터. 비우면 전체")


@tool(args_schema=GetCostArgs)
def get_cost_by_service(
    provider: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    team: str | None = None,
) -> str:
    """기간·프로바이더·서비스·팀 태그별 비용을 집계 조회한다.

    비용 총액, 기간 비교, 멀티클라우드 합산 질문에 사용하라. 이상 여부 판정에는
    detect_cost_anomaly를, 정책 근거가 필요하면 retrieve_docs를 대신 사용하라.
    """
    err = _provider_error(provider)
    if err:
        return err

    team, denial = authz.resolve_team_filter(team)
    if denial:
        return denial

    d_start, d_end = _data_range()
    end = date.fromisoformat(end_date) if end_date else d_end
    start = date.fromisoformat(start_date) if start_date else end.replace(day=1)

    if end < d_start or start > d_end:
        return (
            f"{start.isoformat()}~{end.isoformat()} 기간은 보유한 데이터 범위를 벗어납니다. "
            f"조회 가능한 기간은 {d_start.isoformat()}~{d_end.isoformat()} 입니다."
        )
    start, end = max(start, d_start), min(end, d_end)

    conn = _connect()
    query = "SELECT provider, service, SUM(cost_amount) FROM costs WHERE usage_date BETWEEN ? AND ?"
    params: list = [start.isoformat(), end.isoformat()]
    if provider:
        query += " AND provider = ?"
        params.append(provider.lower())
    if team:
        query += " AND tag_team = ?"
        params.append(team)
    query += " GROUP BY provider, service ORDER BY provider, service"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        return f"{start.isoformat()}~{end.isoformat()} 기간에 조건에 맞는 비용 데이터가 없습니다."

    lines = [f"- {p}/{s}: ${amt:,.2f}" for p, s, amt in rows]
    total = sum(r[2] for r in rows)
    return (
        f"조회 기간: {start.isoformat()} ~ {end.isoformat()}\n"
        + "\n".join(lines)
        + f"\n총합: ${total:,.2f} USD"
    )


class ResourceArgs(BaseModel):
    resource_id: str = Field(..., description="조회할 리소스 ID. 예: 'i-1001-ec2-team-a'")


@tool(args_schema=ResourceArgs)
def get_resource_utilization(resource_id: str) -> str:
    """리소스의 최근 사용률과 상태(running/idle)를 조회한다. 존재하지 않는 ID면 그렇다고 답하라."""
    conn = _connect()
    row = conn.execute(
        "SELECT provider, service, team, is_idle FROM resources WHERE resource_id = ?",
        (resource_id,),
    ).fetchone()
    if not row:
        conn.close()
        return f"'{resource_id}' 리소스를 찾을 수 없습니다."

    provider, service, team, is_idle = row
    denial = authz.check_resource_team(team)
    if denial:
        conn.close()
        return denial

    recent = conn.execute(
        "SELECT usage_date, utilization_pct, status FROM resource_utilization "
        "WHERE resource_id = ? ORDER BY usage_date DESC LIMIT 7",
        (resource_id,),
    ).fetchall()
    conn.close()

    avg_pct = sum(r[1] for r in recent) / len(recent) if recent else 0.0
    latest_status = recent[0][2] if recent else "알수없음"
    idle_note = ", 유휴 리소스로 등록됨" if is_idle else ""
    return (
        f"{resource_id} ({provider}/{service}, team={team})\n"
        f"최근 7일 평균 사용률: {avg_pct:.1f}%, 최근 상태: {latest_status}{idle_note}"
    )


class ProviderFilterArgs(BaseModel):
    provider: str | None = Field(None, description="aws/gcp/azure 중 하나. 비우면 전체")


@tool(args_schema=ProviderFilterArgs)
def list_idle_resources(provider: str | None = None) -> str:
    """장기간 사용률이 낮게 등록된 유휴 리소스를 목록화한다."""
    err = _provider_error(provider)
    if err:
        return err

    # 이 도구엔 team 인자가 없다 — LLM이 넘길 수 있는 값이 아니므로 우회 걱정 없이
    # 요청자가 제한된 경우 무조건 본인 팀으로 좁힌다.
    requester_team, _ = authz.resolve_team_filter(None)

    conn = _connect()
    query = "SELECT resource_id, provider, service, team FROM resources WHERE is_idle = 1"
    params: list = []
    if provider:
        query += " AND provider = ?"
        params.append(provider.lower())
    if requester_team:
        query += " AND team = ?"
        params.append(requester_team)
    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        return "유휴로 등록된 리소스가 없습니다."
    lines = [f"- {rid} ({p}/{s}, team={t})" for rid, p, s, t in rows]
    # LLM-as-Judge로 발견한 문제(#3): 목록만 돌려주고 "왜 유휴로 판단했는지" 기준이
    # 없으면, 에이전트도 답변에서 설명할 근거가 없어 그냥 나열만 하고 끝난다.
    # estimate_savings의 권장 기준(_MIN_UTIL_FOR_RECOMMENDATION)과 같은 기준을 여기서도
    # 명시해 판단 근거를 답변에 실을 수 있게 한다.
    return (
        "유휴 리소스 목록"
        f"(판단 기준: 최근 사용률이 {_MIN_UTIL_FOR_RECOMMENDATION:.0f}% 미만으로 지속됨):\n"
        + "\n".join(lines)
    )


# 팀별 월간 예산 한도(USD). data/policy_docs/budget_policy.md 와 동일한 수치를
# 유지해야 한다 — _RI_TERMS가 reserved_instance_policy.md와 동일한 수치를
# 유지하는 것과 같은 이유(정책 문서와 코드가 서로 다른 숫자를 말하면 안 된다).
_BUDGET_LIMITS: dict[str, float] = {
    "team-a": 1200.0,
    "team-b": 900.0,
    "team-c": 700.0,
}


class BudgetStatusArgs(BaseModel):
    team: str | None = Field(
        None, description="team-a/team-b/team-c 중 하나. 비우면 요청자 본인 팀(제한 없는 요청자는 전체 팀)"
    )


@tool(args_schema=BudgetStatusArgs)
def get_budget_status(team: str | None = None) -> str:
    """이번 달 팀별 비용이 budget_policy.md의 월간 한도 대비 몇 %인지 계산한다.

    "우리 팀 예산 얼마나 썼어?" 같은 질문에 사용하라. 한도 초과 자체는 리소스
    정지·축소의 근거가 되지 않는다(budget_policy.md "초과 대응 원칙") — 이 도구는
    현재 상태만 보고하고 어떤 조치도 실행하지 않는다.
    """
    team, denial = authz.resolve_team_filter(team)
    if denial:
        return denial

    d_start, d_end = _data_range()
    month_start = max(d_start, d_end.replace(day=1))
    teams = [team] if team else sorted(_BUDGET_LIMITS)

    conn = _connect()
    lines = []
    for t in teams:
        limit = _BUDGET_LIMITS.get(t)
        if limit is None:
            lines.append(f"- {t}: 등록된 예산 한도가 없습니다.")
            continue
        row = conn.execute(
            "SELECT SUM(cost_amount) FROM costs WHERE tag_team = ? AND usage_date BETWEEN ? AND ?",
            (t, month_start.isoformat(), d_end.isoformat()),
        ).fetchone()
        spent = row[0] or 0.0
        pct = spent / limit * 100
        note = " — 한도 초과, 플랫폼팀 알림 대상(자동 조치 없음)" if spent > limit else ""
        lines.append(f"- {t}: ${spent:,.2f} / ${limit:,.2f} 한도 ({pct:.0f}%){note}")
    conn.close()

    header = f"{month_start.isoformat()}~{d_end.isoformat()} 기준 팀별 예산 사용 현황:"
    return header + "\n" + "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 이상탐지
# ══════════════════════════════════════════════════════════════════

class AnomalyArgs(BaseModel):
    provider: str | None = Field(None, description="aws/gcp/azure 중 하나. 비우면 전체")
    lookback_days: int = Field(14, description="이상 여부를 검사할 최근 기간(일)")
    window_days: int = Field(7, description="비교 기준이 되는 직전 이동평균 기간(일)")
    z_threshold: float = Field(2.0, description="이상으로 판정할 z-score 임계값")


@tool(args_schema=AnomalyArgs)
def detect_cost_anomaly(
    provider: str | None = None,
    lookback_days: int = 14,
    window_days: int = 7,
    z_threshold: float = 2.0,
) -> str:
    """최근 lookback_days 안에서 직전 window_days 이동평균 대비 z-score 급증을 탐지한다.

    "어제/최근 비용 이상했어?" 같은 질문에 사용하라. 결과가 있어도 공휴일 등
    예정된 증가일 수 있으니 단정하지 말고 retrieve_docs로 대응 원칙을 함께 확인하라.
    """
    err = _provider_error(provider)
    if err:
        return err

    # 이 도구도 team 인자가 없다 — 요청자가 제한된 경우 본인 팀 리소스만 검사 대상으로 삼는다.
    requester_team, _ = authz.resolve_team_filter(None)

    d_start, d_end = _data_range()
    lookback_start = max(d_start, d_end - timedelta(days=lookback_days - 1))

    conn = _connect()
    conditions: list[str] = []
    params: list = []
    if provider:
        conditions.append("provider = ?")
        params.append(provider.lower())
    if requester_team:
        conditions.append("tag_team = ?")
        params.append(requester_team)
    query = "SELECT DISTINCT resource_id, account_id FROM costs"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    # account_id는 리소스마다 계정 하나로 고정이라(같은 provider 안에서도 계정이
    # 여러 개일 수 있음) resource_id와 함께 미리 짝지어 둔다 — 이게 없으면
    # "어느 provider인지"까지만 알 수 있고 "같은 provider 안 어느 계정인지"는
    # 결과에서 사라진다(배치 로그·리포트에서 계정 정보 누락 문제로 발견됨).
    account_by_rid = {r[0]: r[1] for r in conn.execute(query, params).fetchall()}

    findings = []
    for rid, account_id in account_by_rid.items():
        rows = conn.execute(
            "SELECT usage_date, cost_amount FROM costs WHERE resource_id = ? "
            "AND usage_date <= ? ORDER BY usage_date",
            (rid, d_end.isoformat()),
        ).fetchall()
        by_date = {date.fromisoformat(d): amt for d, amt in rows}
        dates_sorted = sorted(by_date)

        for d in dates_sorted:
            if d < lookback_start:
                continue
            history_dates = [dd for dd in dates_sorted if dd < d][-window_days:]
            if len(history_dates) < window_days:
                continue
            history = [by_date[dd] for dd in history_dates]
            mean = statistics.mean(history)
            stdev = statistics.pstdev(history) or 0.01
            z = (by_date[d] - mean) / stdev
            if z >= z_threshold:
                findings.append((rid, account_id, d, by_date[d], mean, z))
    conn.close()

    if not findings:
        return (
            f"{lookback_start.isoformat()}~{d_end.isoformat()} 구간에서 "
            f"z-score {z_threshold} 이상인 이상 급증이 없습니다."
        )

    findings.sort(key=lambda f: f[2], reverse=True)
    lines = [
        f"- {rid} (계정: {account_id}, {d.isoformat()}): ${cost:,.2f} "
        f"(직전 {window_days}일 평균 ${mean:,.2f} 대비 z-score {z:.2f})"
        for rid, account_id, d, cost, mean, z in findings
    ]
    return f"이상 급증 탐지 {len(findings)}건:\n" + "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 절감 계산
# ══════════════════════════════════════════════════════════════════

# 제공자별 RI/Savings Plan 절감률. pricing_docs/reserved_instance_policy.md 와
# 동일한 수치를 유지해야 한다.
# - aws: 이 프로젝트의 가정치(실제 AWS 공식 수치 아님). AWS Price List API는
#   pricing:GetProducts 권한이 있어야 하는데 이 프로젝트 자격증명엔 없어서(직접
#   확인) 실측치로 못 바꿨다 — 권한이 생기면 azure처럼 스냅샷 방식으로 바꿀 수 있다.
# - gcp: GCP 공식 문서(Committed Use Discounts, 범용 인스턴스 스펜드 기반 CUD)에
#   실제로 명시된 수치. https://cloud.google.com/compute/docs/instances/committed-use-discounts-overview
#   (확인일 2026-09-16). 계약상 고정된 값이라 API 조회 없이 문서값을 그대로 쓴다.
# - azure: scripts/fetch_azure_pricing.py가 Azure Retail Prices API(인증 불필요)로
#   실제 조회해 만든 스냅샷(data/pricing_docs/azure_ri_rates.json)에서 읽는다.
#   스냅샷이 없거나 손상됐으면 스냅샷 생성 당시 실측치(아래 폴백값)를 그대로 쓴다.
_RI_TERMS: dict[str, dict[str, dict]] = {
    "aws": {
        "1yr": {"months": 12, "discount": 0.30},
        "3yr": {"months": 36, "discount": 0.50},
    },
    "gcp": {
        "1yr": {"months": 12, "discount": 0.28},
        "3yr": {"months": 36, "discount": 0.46},
    },
    "azure": {
        "1yr": {"months": 12, "discount": 0.4102},  # 폴백값 = 2026-09-16 스냅샷 실측치
        "3yr": {"months": 36, "discount": 0.6199},
    },
}
_AZURE_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "pricing_docs" / "azure_ri_rates.json"
_azure_snapshot_as_of = "2026-09-16"  # 폴백값 생성일. 스냅샷을 읽으면 실제 날짜로 갱신됨


def _load_azure_snapshot() -> None:
    global _azure_snapshot_as_of
    try:
        snapshot = json.loads(_AZURE_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        _RI_TERMS["azure"]["1yr"]["discount"] = snapshot["discount_1yr"]
        _RI_TERMS["azure"]["3yr"]["discount"] = snapshot["discount_3yr"]
        _azure_snapshot_as_of = snapshot["as_of"]
    except Exception:  # noqa: BLE001 — 스냅샷이 없거나 손상됐으면 위 폴백값을 그대로 쓴다
        pass


_load_azure_snapshot()

# 답변에 절감률 출처를 밝히기 위한 문구 — 세 제공자의 데이터 품질이 서로 다르다는
# 걸 사용자가 답변만 보고도 알 수 있어야 한다(가정치를 실측치처럼 보이게 하지 않는다).
_RATE_SOURCE_NOTE = {
    "aws": "이 프로젝트의 가정치, 실제 AWS 공식 수치 아님",
    "gcp": "GCP 공식 문서 기준(Committed Use Discounts)",
    "azure": f"Azure 실제 가격 API 스냅샷 기준({_azure_snapshot_as_of})",
}

_MIN_UTIL_FOR_RECOMMENDATION = 30.0

# 다운사이징 절감 추정에 쓰는 목표 사용률(%). resources/costs 테이블엔 인스턴스
# 타입(m5.large 등)이 없어서 "한 단계 작은 타입"의 실제 가격을 알 방법이 없다 —
# 그래서 실제 가격표 대신 "사용률이 이 정도가 되도록 용량을 줄인다면"이라는
# 사용률 비율 기반 근사치로 계산한다(용량과 비용이 선형이라는 단순화 가정).
# _MIN_UTIL_FOR_RECOMMENDATION(30%)보다 높게 잡은 이유: 다운사이징 "후"에는 여유
# 없이 빡빡하게 쓰는 게 아니라 적정 수준(권장 하한보다 위)에서 안정적으로 도는
# 크기를 목표로 하기 때문이다.
_DOWNSIZING_TARGET_UTIL = 65.0


_VALID_PLAN_TYPES = ("1yr", "3yr", "downsizing")


class SavingsArgs(BaseModel):
    resource_id: str = Field(..., description="절감액을 계산할 리소스 ID")
    plan_type: str = Field(
        "1yr",
        description="'1yr'/'3yr'(RI·Savings Plan 전환) 또는 'downsizing'(사용률 기반 다운사이징 절감 추정)",
    )


@tool(args_schema=SavingsArgs)
def estimate_savings(resource_id: str, plan_type: str = "1yr") -> str:
    """RI/Savings Plan 전환 또는 다운사이징 시 절감액을 계산한다.

    plan_type이 '1yr'/'3yr'이면 RI/Savings Plan 절감률(제공자마다 다름 — _RI_TERMS
    정의부의 출처 주석 참고)을 적용하고, 전제 조건(최근 90일 평균 사용률 30% 이상)을
    만족하지 않으면 절감액과 함께 "권장 조건 미충족"을 안내한다(reserved_instance_policy.md
    참고). plan_type이 'downsizing'이면 실제 인스턴스 타입 가격표 대신 사용률
    비율로 근사한 다운사이징 절감액을 계산한다 — 사용률이 이미 낮은 리소스에 더
    적합하다.
    """
    if plan_type not in _VALID_PLAN_TYPES:
        return f"'{plan_type}'은 지원하지 않는 약정 유형입니다 (1yr/3yr/downsizing)."

    conn = _connect()
    owner_row = conn.execute(
        "SELECT team, provider FROM resources WHERE resource_id = ?", (resource_id,)
    ).fetchone()
    provider: str | None = None
    if owner_row:
        team, provider = owner_row
        denial = authz.check_resource_team(team)
    elif authz.get_requester_team() is not None:
        # resources 테이블에 없는 resource_id다(costs에는 있을 수 있음 — 예:
        # 폐기된 리소스). 소유 팀을 확인할 길이 없으니, 권한이 제한된 요청자에게는
        # stop_resource/resize_resource처럼 "못 찾음"으로 거절한다 — 이전엔 이
        # 경우 검사 자체를 건너뛰어서 다른 팀 리소스일 수도 있는 걸 그냥 계산해
        # 돌려줬다 (코드 리뷰에서 발견).
        denial = f"'{resource_id}' 리소스를 찾을 수 없어 절감액을 계산할 수 없습니다."
    else:
        denial = None
    if denial:
        conn.close()
        return denial

    if provider is None:
        # resources에 없는(제한 없는 요청자에게만 허용된) 폐기 리소스도 costs
        # 테이블엔 provider가 남아있을 수 있다 — 있으면 그걸로 제공자별 절감률을 고른다.
        provider_row = conn.execute(
            "SELECT provider FROM costs WHERE resource_id = ? LIMIT 1", (resource_id,)
        ).fetchone()
        provider = provider_row[0] if provider_row else None

    cost_row = conn.execute(
        """
        SELECT AVG(daily) * 30 FROM (
            SELECT usage_date, SUM(cost_amount) AS daily FROM costs
            WHERE resource_id = ? GROUP BY usage_date
        )
        """,
        (resource_id,),
    ).fetchone()
    util_row = conn.execute(
        "SELECT AVG(utilization_pct) FROM resource_utilization WHERE resource_id = ?",
        (resource_id,),
    ).fetchone()
    conn.close()

    if not cost_row or cost_row[0] is None:
        return f"'{resource_id}' 리소스의 비용 데이터를 찾을 수 없습니다."

    monthly_cost = cost_row[0]
    avg_util = util_row[0] if util_row and util_row[0] is not None else 0.0

    if plan_type == "downsizing":
        if avg_util <= 0:
            return f"'{resource_id}'의 최근 사용률 데이터가 없어 다운사이징 절감액을 계산할 수 없습니다."
        if avg_util >= _DOWNSIZING_TARGET_UTIL:
            return (
                f"{resource_id} 현재 추정 월 비용: ${monthly_cost:,.2f}\n"
                f"최근 평균 사용률이 {avg_util:.1f}%로 이미 목표 사용률({_DOWNSIZING_TARGET_UTIL:.0f}%) "
                "이상이라 다운사이징으로 얻을 절감 여지가 크지 않습니다."
            )
        # 용량과 비용이 선형이라는 단순화 가정 — 사용률을 목표치까지 끌어올리려면
        # 용량을 (avg_util / 목표) 배로 줄이면 된다고 근사한다.
        size_ratio = avg_util / _DOWNSIZING_TARGET_UTIL
        savings = round(monthly_cost * (1 - size_ratio), 2)
        return (
            f"{resource_id} 현재 추정 월 비용: ${monthly_cost:,.2f}\n"
            f"다운사이징 시(최근 평균 사용률 {avg_util:.1f}% → 목표 {_DOWNSIZING_TARGET_UTIL:.0f}% 수준으로 "
            f"용량 조정 가정) 절감액: 월 ${savings:,.2f}\n"
            "주의: 실제 인스턴스 타입별 가격표가 아니라 사용률 비율로 추정한 근사치입니다 — "
            "정확한 절감액은 목표 인스턴스 타입의 실제 가격을 확인해야 합니다."
        )

    term = _RI_TERMS.get(provider or "", _RI_TERMS["aws"])[plan_type]
    savings = round(monthly_cost * term["discount"], 2)

    lines = [
        f"{resource_id} 현재 추정 월 비용: ${monthly_cost:,.2f}",
        f"{plan_type} 약정({term['months']}개월, 절감률 {term['discount']:.0%}, "
        f"{_RATE_SOURCE_NOTE.get(provider, _RATE_SOURCE_NOTE['aws'])}) 전환 시 "
        f"절감액: 월 ${savings:,.2f}",
    ]
    if avg_util < _MIN_UTIL_FOR_RECOMMENDATION:
        lines.append(
            f"주의: 최근 평균 사용률 {avg_util:.1f}%로 권장 기준(90일 평균 {_MIN_UTIL_FOR_RECOMMENDATION:.0f}% "
            "이상)에 못 미쳐 RI 전환보다 다운사이징·정지 검토를 우선 권장합니다."
        )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 실행 — HITL 승인 이후에만 호출되어야 한다 (agent.py에서 게이트)
# ══════════════════════════════════════════════════════════════════

class StopResourceArgs(BaseModel):
    resource_id: str = Field(..., description="정지할 리소스 ID")


@tool(args_schema=StopResourceArgs)
def stop_resource(resource_id: str) -> str:
    """리소스를 정지한다. 반드시 사용자 승인(HITL) 이후에만 호출되어야 하는 도구다."""
    conn = _connect()
    row = conn.execute("SELECT resource_id, team FROM resources WHERE resource_id = ?", (resource_id,)).fetchone()
    if not row:
        conn.close()
        return f"'{resource_id}' 리소스를 찾을 수 없어 정지할 수 없습니다."
    denial = authz.check_resource_team(row[1])
    if denial:
        conn.close()
        return denial
    conn.execute(
        "INSERT INTO actions_log (resource_id, action, detail, executed_at) VALUES (?, 'stop', ?, ?)",
        (resource_id, "리소스 정지", datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return f"'{resource_id}' 리소스를 정지했습니다."


class ResizeResourceArgs(BaseModel):
    resource_id: str = Field(..., description="축소·변경할 리소스 ID")
    target_type: str = Field(..., description="변경할 목표 사양. 예: 't3.small'")


@tool(args_schema=ResizeResourceArgs)
def resize_resource(resource_id: str, target_type: str) -> str:
    """리소스를 지정한 사양으로 축소·변경한다. 반드시 사용자 승인(HITL) 이후에만 호출되어야 한다."""
    conn = _connect()
    row = conn.execute("SELECT resource_id, team FROM resources WHERE resource_id = ?", (resource_id,)).fetchone()
    if not row:
        conn.close()
        return f"'{resource_id}' 리소스를 찾을 수 없어 변경할 수 없습니다."
    denial = authz.check_resource_team(row[1])
    if denial:
        conn.close()
        return denial
    conn.execute(
        "INSERT INTO actions_log (resource_id, action, detail, executed_at) VALUES (?, 'resize', ?, ?)",
        (resource_id, f"{target_type}로 변경", datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return f"'{resource_id}' 리소스를 '{target_type}'로 변경했습니다."


class AlertArgs(BaseModel):
    channel: str = Field(..., description="알림 채널. 예: 'slack:#finops'")
    message: str = Field(..., description="알림 내용")


@tool(args_schema=AlertArgs)
def send_cost_alert(channel: str, message: str) -> str:
    """비용 알림을 발송한다 (시뮬레이션 — 실제 Slack/이메일 API를 호출하지 않는다)."""
    conn = _connect()
    conn.execute(
        "INSERT INTO actions_log (resource_id, action, detail, executed_at) VALUES (NULL, 'alert', ?, ?)",
        (f"[{channel}] {message}", datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return f"'{channel}'로 알림을 발송했습니다: {message}"


TOOLS: list = [
    get_cost_by_service,
    get_resource_utilization,
    get_budget_status,
    detect_cost_anomaly,
    estimate_savings,
    list_idle_resources,
    stop_resource,
    resize_resource,
    send_cost_alert,
]

TOOL_MAP: dict = {t.name: t for t in TOOLS}
