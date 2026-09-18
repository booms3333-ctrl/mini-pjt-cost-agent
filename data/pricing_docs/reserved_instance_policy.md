# Reserved Instance / Savings Plan 절감 조건

- test_queries.csv #4 ("Reserved Instance로 전환하면 얼마나 절감돼?") 의 근거 문서.
- `estimate_savings` 도구가 절감액을 계산할 때 참조하는 전제 조건.
- 절감률은 클라우드 제공자마다 다르며(`src/tools.py`의 `_RI_TERMS`), 아래 표의
  출처도 제공자마다 다르다 — 전부 이 프로젝트의 가정치이던 것을 GCP/Azure는
  실제 공개 자료 기반으로 교체했다.

## 적용 조건 (제공자별)

| 제공자 | 1년 약정 | 3년 약정 | 근거 |
|---|---|---|---|
| AWS | 30% | 50% | **이 프로젝트의 가정치** — 실제 AWS 공식 수치 아님. AWS Price List API(`pricing:GetProducts`)는 이 프로젝트 자격증명에 권한이 없어 실측으로 못 바꿨다 |
| GCP | 28% | 46% | GCP 공식 문서(Committed Use Discounts, 범용 인스턴스 스펜드 기반 CUD)에 실제로 명시된 수치. https://cloud.google.com/compute/docs/instances/committed-use-discounts-overview (확인일 2026-09-16) |
| Azure | `data/pricing_docs/azure_ri_rates.json` 참고 (스냅샷 생성 시점 기준 약 41%/62%) | 〃 | `scripts/fetch_azure_pricing.py`가 Azure Retail Prices API(`prices.azure.com`, 인증 불필요)로 실제 조회한 스냅샷. Standard_D2_v4(범용, eastus) 기준 — 인스턴스 패밀리·리전에 따라 실제 값은 다를 수 있다 |

공통 조건(위약금·권장 대상)은 세 제공자 모두 아래와 같이 취급한다.

| 약정 유형 | 최소 사용 기간 | 비고 |
|---|---|---|
| 1년 약정 | 12개월 | 중도 해지 시 위약금 발생 |
| 3년 약정 | 36개월 | 사용량이 안정적인 리소스에만 권장 |

## 전환 권장 기준

- 최근 90일간 일별 사용률이 지속적으로 30% 이상인 리소스만 RI/Savings Plan 전환을 권장한다
- 이용률이 낮거나(유휴) 변동이 큰 리소스는 RI 전환을 권장하지 않고, 대신 다운사이징이나 정지를 우선 검토한다

## 절감액 계산 방식

```
절감액 = 현재 온디맨드 월 비용 × 절감률
```

전제 조건(최근 90일 사용률 안정성)을 만족하지 않는 리소스에 대해서는 절감액과 함께
"권장 조건 미충족" 사실을 반드시 함께 안내한다.
