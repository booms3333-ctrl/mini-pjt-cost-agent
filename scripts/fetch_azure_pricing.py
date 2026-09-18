"""Azure Reserved VM Instance 실제 할인율 스냅샷 생성기.

`prices.azure.com` 공개 Retail Prices API(인증 불필요)에서 대표 범용 VM
SKU(Standard_D2_v4, eastus)의 온디맨드(Consumption)와 예약(Reservation, 1yr/3yr)
가격을 실제로 조회해 할인율을 계산하고, `data/pricing_docs/azure_ri_rates.json`으로
저장한다. `src/tools.py`의 `estimate_savings()`가 이 스냅샷을 읽어 Azure 리소스의
절감률 계산에 쓴다.

왜 매 요청마다 실시간 호출이 아니라 스냅샷인가: `estimate_savings()`는 "같은
입력엔 항상 같은 출력"이 원칙인 결정적 계산 함수다(tools.py 다른 도구들과 동일한
원칙). 매번 실시간으로 외부 API를 부르면 그 순간의 가격 변동에 따라 같은 질문에
다른 답이 나올 수 있고, 네트워크 실패가 곧 도구 실패가 된다. 대신 이 스크립트를
필요할 때(가격이 크게 바뀌었을 때) 다시 실행해 스냅샷만 갱신하는 방식을 쓴다
(scripts/generate_data.py와 같은 성격의 "준비 스크립트").

대표 SKU를 하나만 쓰는 이유: `resources`/`costs` 테이블은 provider/service까지만
저장하고 인스턴스 타입(m5.large 등)은 없다. 실제 할인율은 인스턴스 패밀리마다
다르므로, 이 스냅샷은 "일반 범용 인스턴스 기준 근사치"이지 모든 Azure 리소스에
정밀하게 들어맞는 값은 아니다.

실행:
    python scripts/fetch_azure_pricing.py
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

API_BASE = "https://prices.azure.com/api/retail/prices"
REGION = "eastus"
ARM_SKU_NAME = "Standard_D2_v4"  # 범용(Dv4 시리즈) 소형 VM — team-a/b/c 리소스와 성격이 가장 비슷한 대표 SKU
PRODUCT_NAME_LINUX = "Virtual Machines Dv4 Series"  # Windows 없는 Linux 가격만 취함

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "pricing_docs" / "azure_ri_rates.json"

HOURS_PER_YEAR = 8760


def _fetch(filter_expr: str) -> list[dict]:
    url = f"{API_BASE}?$filter={urllib.parse.quote(filter_expr)}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("Items", [])


def fetch_payg_hourly() -> float:
    items = _fetch(
        f"armSkuName eq '{ARM_SKU_NAME}' and armRegionName eq '{REGION}' and type eq 'Consumption'"
    )
    for item in items:
        if item.get("productName") == PRODUCT_NAME_LINUX:
            return float(item["retailPrice"])
    raise RuntimeError(f"{ARM_SKU_NAME} PAYG 가격을 찾을 수 없습니다 (items={len(items)})")


def fetch_reservation_totals() -> dict[str, float]:
    # armRegionName을 안 넣으면 전 리전이 다 섞여 나와서(각 리전마다 가격이 다름),
    # 마지막에 순회된 리전 값으로 조용히 덮어써지는 버그가 있었다 — 실행해서 나온
    # 스냅샷이 eastus PAYG 가격과 안 맞는 걸 보고 직접 재현해서 발견했다.
    items = _fetch(
        f"armSkuName eq '{ARM_SKU_NAME}' and armRegionName eq '{REGION}' and type eq 'Reservation'"
    )
    totals: dict[str, float] = {}
    for item in items:
        if item.get("productName") != PRODUCT_NAME_LINUX:
            continue
        term = item.get("reservationTerm")
        if term in ("1 Year", "3 Years"):
            totals[term] = float(item["retailPrice"])
    missing = {"1 Year", "3 Years"} - totals.keys()
    if missing:
        raise RuntimeError(f"{ARM_SKU_NAME} 예약 가격 중 누락: {missing}")
    return totals


def main() -> None:
    payg_hourly = fetch_payg_hourly()
    totals = fetch_reservation_totals()

    eff_1yr = totals["1 Year"] / HOURS_PER_YEAR
    eff_3yr = totals["3 Years"] / (3 * HOURS_PER_YEAR)
    discount_1yr = round(1 - eff_1yr / payg_hourly, 4)
    discount_3yr = round(1 - eff_3yr / payg_hourly, 4)

    snapshot = {
        "provider": "azure",
        "sku": ARM_SKU_NAME,
        "region": REGION,
        "as_of": date.today().isoformat(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "https://prices.azure.com/api/retail/prices (Azure Retail Prices API, 인증 불필요)",
        "payg_hourly_usd": payg_hourly,
        "reservation_1yr_total_usd": totals["1 Year"],
        "reservation_3yr_total_usd": totals["3 Years"],
        "discount_1yr": discount_1yr,
        "discount_3yr": discount_3yr,
        "note": (
            "일반 범용 인스턴스(Dv4 시리즈) 기준 근사치. 실제 할인율은 인스턴스 "
            "패밀리·리전·결제 옵션에 따라 다르다."
        ),
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Azure 가격 스냅샷 생성 완료: {OUT_PATH}")
    print(f"  SKU: {ARM_SKU_NAME} ({REGION}), 온디맨드: ${payg_hourly:.4f}/hr")
    print(f"  1yr 할인율: {discount_1yr:.1%}  (3yr: {discount_3yr:.1%})")


if __name__ == "__main__":
    main()
