"""클라우드 제공자 공개 상태/장애 피드 — 인증 불필요.

이상 비용 탐지(`detect_cost_anomaly`) 결과가 진짜 문제인지, 그날 클라우드 자체
장애 때문인지 추측만 하지 않고 실제로 확인하기 위한 모듈이다. `anomaly_agent`는
지금까지 "공휴일·배치 작업·클라우드 장애 등이 있었는지 확인해보라"고 사용자에게
떠넘기기만 했는데(가정치/추측), 이 세 피드는 전부 실제 공개 데이터라 검증된
사실로 답할 수 있게 해준다.

세 피드의 성격이 서로 다르다는 걸 반드시 알아야 한다 (직접 확인함):
- GCP(`status.cloud.google.com/incidents.json`): 시작/종료 시각이 있는 **과거
  이력**을 몇 달치 제공한다. 특정 과거 날짜 조회에 실제로 쓸 수 있다.
- AWS(`status.aws.amazon.com/data.json`): **현재 진행 중인 이슈만** 보여주는
  실시간 대시보드 데이터다(UTF-16 인코딩). 과거 날짜 조회에는 쓸모가 거의 없다.
- Azure(상태 RSS 피드): 마찬가지로 **현재 이슈 중심**이고, 이슈가 없으면 그냥
  빈 피드가 온다.

그래서 AWS/Azure 결과에는 "현재 상태 기준이라 과거 조회엔 한계가 있다"는 안내를
항상 덧붙인다 — 없는 걸 있는 것처럼 보이게 하지 않기 위해서다.
"""

from __future__ import annotations

import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

_TIMEOUT = 10


def _overlaps(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end


def fetch_gcp_incidents(start: date, end: date) -> list[dict]:
    """GCP 공개 인시던트 이력(과거分 포함)에서 [start, end]와 겹치는 것만 돌려준다."""
    url = "https://status.cloud.google.com/incidents.json"
    with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results = []
    for item in data:
        begin_raw = item.get("begin")
        if not begin_raw:
            continue
        begin_dt = datetime.fromisoformat(begin_raw)
        end_raw = item.get("end")
        end_dt = datetime.fromisoformat(end_raw) if end_raw else begin_dt
        if _overlaps(begin_dt.date(), end_dt.date(), start, end):
            results.append(
                {
                    "begin": begin_raw,
                    "end": end_raw,
                    "description": (item.get("external_desc") or "").strip()[:300],
                }
            )
    return results


def fetch_aws_incidents(start: date, end: date) -> list[dict]:
    """AWS 공개 상태 피드 — 현재 진행 중인 이슈만 포함(과거 이력 아님)."""
    url = "https://status.aws.amazon.com/data.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-16"))

    results = []
    for item in data:
        ts = item.get("date")
        if not ts:
            continue
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        if start <= dt.date() <= end:
            results.append(
                {
                    "begin": dt.isoformat(),
                    "end": None,
                    "description": f"[{item.get('region_name', '?')}] "
                    f"{item.get('service_name', '')}: {item.get('summary', '')}"[:300],
                }
            )
    return results


def fetch_azure_incidents(start: date, end: date) -> list[dict]:
    """Azure 공개 상태 RSS 피드 — 현재 진행 중인 이슈만 포함(과거 이력 아님)."""
    url = "https://azurestatuscdn.azureedge.net/en-us/status/feed/"
    with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)

    results = []
    for item in root.iter("item"):
        pub_date = item.findtext("pubDate")
        if not pub_date:
            continue
        dt = parsedate_to_datetime(pub_date)
        if start <= dt.date() <= end:
            title = item.findtext("title") or ""
            description = item.findtext("description") or ""
            results.append(
                {
                    "begin": dt.isoformat(),
                    "end": None,
                    "description": f"{title}: {description}"[:300],
                }
            )
    return results


_FETCHERS = {
    "aws": fetch_aws_incidents,
    "gcp": fetch_gcp_incidents,
    "azure": fetch_azure_incidents,
}

# AWS/Azure는 "현재 진행 중" 기준이라 과거 날짜 조회 결과가 비어 있어도 "장애가
# 없었다"는 뜻이 아니다 — 이 캐비앗을 도구 출력에 항상 붙여서 오해를 막는다.
_HISTORICAL_COVERAGE_NOTE = {
    "aws": "AWS 공개 상태 피드는 현재 진행 중인 이슈만 제공합니다 — 과거 날짜에 "
    "대한 조회 결과가 비어 있어도 그 날짜에 장애가 없었다고 단정할 수 없습니다.",
    "gcp": None,  # GCP는 실제 과거 이력을 제공하므로 별도 안내 불필요
    "azure": "Azure 상태 피드는 현재 진행 중인 이슈만 제공합니다 — 과거 날짜에 "
    "대한 조회 결과가 비어 있어도 그 날짜에 장애가 없었다고 단정할 수 없습니다.",
}


def check_incidents(provider: str, start_date: str, end_date: str) -> str:
    """provider의 공개 상태 피드에서 [start_date, end_date]와 겹치는 장애를 찾아 텍스트로 돌려준다."""
    fetch = _FETCHERS.get(provider)
    if fetch is None:
        return f"'{provider}'는 지원하지 않는 제공자입니다 (aws/gcp/azure)."

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    try:
        incidents = fetch(start, end)
    except Exception as exc:  # noqa: BLE001 — 외부 공개 API 실패는 도구 실패가 아니라 "조회 불가"로 답한다
        return f"{provider} 상태 피드 조회에 실패했습니다: {exc}"

    note = _HISTORICAL_COVERAGE_NOTE.get(provider)
    if not incidents:
        base = f"{start_date}~{end_date} 기간에 {provider} 공개 상태 피드에서 겹치는 장애를 찾지 못했습니다."
        return f"{base}\n(참고: {note})" if note else base

    lines = []
    for i in incidents:
        span = f"{i['begin']} ~ {i['end']}" if i.get("end") else i["begin"]
        lines.append(f"- {span}: {i['description']}")
    header = f"{start_date}~{end_date} 기간과 겹치는 {provider} 장애 {len(incidents)}건:"
    body = "\n".join(lines)
    return f"{header}\n{body}\n(참고: {note})" if note else f"{header}\n{body}"
