"""클라우드별 공식 비용 최적화 가이드 스냅샷 생성기.

AWS/GCP/Azure가 공개한 실제 Well-Architected Framework 문서(전부 인증 불필요, 공개
웹페이지)에서 "비용 최적화" 관련 본문을 가져와 `data/policy_docs/{provider}_cost_
optimization_guide.md`로 저장한다. `retrieve_docs`(`src/retriever.py`)가 이 폴더의
모든 `.md`를 자동으로 색인하므로(`_collect_document_paths()`), 이 스크립트만
돌리면 새 도구·에이전트 코드 없이 "각 클라우드별 비용 절감 가이드 알려줘" 같은
질문에 실제 공식 문서를 근거로 답할 수 있게 된다.

왜 매 요청마다 실시간 조회가 아니라 스냅샷인가: `scripts/fetch_azure_pricing.py`와
같은 이유다 — 비용 최적화 원칙 문서는 자주 안 바뀌는 성격이고, RAG 임베딩은 그래프
빌드 시점에 한 번 만들어지므로 애초에 "질문마다 실시간 재조회"와는 안 맞는다. 필요할
때(문서가 크게 개정됐을 때) 이 스크립트를 다시 돌려 스냅샷만 갱신하면 된다.

페이지 선정 근거 (2026-09-17 확인):
- AWS: Well-Architected "Cost Optimization Pillar" 백서는 좌측 내비게이션이
  JS로 렌더링돼 정적 fetch로는 하위 페이지 목록을 못 얻는다. 그래서 5개 핵심 실천
  영역(Best Practice Areas) 페이지를 URL로 직접 나열했다 — 이 5개는 AWS 프레임워크
  문서 자체가 명시하는 고정된 구조(클라우드 재무 관리/지출 인지/비용 효율적 리소스/
  수요-공급 관리/지속적 최적화)라 임의로 고른 게 아니다.
- GCP: 프레임워크 개요 페이지 자체에 "한 페이지로 보기(printable)" 링크가 있어—
  그 단일 페이지 하나면 GCP 필러 전체 내용(약 4만자)을 다 담는다.
- Azure: GCP 같은 단일 페이지가 없어서, 실제 본문이 있는 하위 페이지 3개
  (원칙/체크리스트/트레이드오프)를 합쳤다. 개요 페이지 자체는 다른 페이지로 가는
  목차·요약 링크 모음이라 본문이 거의 없어서 제외했다(실제 확인함).

실행:
    python scripts/fetch_cost_optimization_guides.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "policy_docs"

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cost-optimization-guide-fetcher/1.0)"}

_AWS_BASE = "https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/"
_AZURE_BASE = "https://learn.microsoft.com/en-us/azure/well-architected/cost-optimization/"

# (provider, [(섹션 제목, URL, 본문 셀렉터)])
SOURCES: dict[str, list[tuple[str, str, str]]] = {
    "aws": [
        ("개요", _AWS_BASE + "welcome.html", "#main-content"),
        ("클라우드 재무 관리 실천", _AWS_BASE + "practice-cloud-financial-management.html", "#main-content"),
        ("지출·사용 인지", _AWS_BASE + "expenditure-and-usage-awareness.html", "#main-content"),
        ("비용 효율적 리소스", _AWS_BASE + "cost-effective-resources.html", "#main-content"),
        ("수요·공급 관리", _AWS_BASE + "manage-demand-and-supply-resources.html", "#main-content"),
        ("지속적 최적화", _AWS_BASE + "optimize-over-time.html", "#main-content"),
    ],
    "gcp": [
        (
            "전체 (Well-Architected Framework — Cost Optimization Pillar, 단일 페이지)",
            "https://docs.cloud.google.com/architecture/framework/cost-optimization/printable",
            "main",
        ),
    ],
    "azure": [
        ("설계 원칙", _AZURE_BASE + "principles", "main"),
        ("체크리스트", _AZURE_BASE + "checklist", "main"),
        ("트레이드오프", _AZURE_BASE + "tradeoffs", "main"),
    ],
}

PROVIDER_LABEL = {"aws": "AWS", "gcp": "GCP", "azure": "Azure"}


def _fetch_section(url: str, selector: str) -> str:
    resp = requests.get(url, timeout=20, headers=_HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    el = soup.select_one(selector)
    if el is None:
        raise RuntimeError(f"{url}에서 '{selector}' 요소를 찾을 수 없습니다 (사이트 구조가 바뀌었을 수 있음)")
    # 불필요한 잡음(스크립트/스타일 태그)만 제거하고, 나머지 텍스트는 문단 구분을 살려 추출한다.
    for tag in el.select("script, style, nav"):
        tag.decompose()
    lines = [line.strip() for line in el.get_text("\n").splitlines()]
    return "\n".join(line for line in lines if line)


def fetch_provider_guide(provider: str) -> str:
    sections = SOURCES[provider]
    today = date.today().isoformat()
    parts = [
        f"# {PROVIDER_LABEL[provider]} 공식 비용 최적화 가이드",
        "",
        f"- 출처: {PROVIDER_LABEL[provider]} 공식 문서 (Well-Architected Framework, 인증 불필요)",
        f"- 스냅샷 생성일: {today}",
        "- 이 문서는 scripts/fetch_cost_optimization_guides.py가 아래 공식 URL에서 자동으로 가져온 스냅샷이다. "
        "최신 내용은 원본 링크를 참고하라.",
        "",
    ]
    for title, url, selector in sections:
        text = _fetch_section(url, selector)
        parts.append(f"## {title}")
        parts.append(f"(출처: {url})")
        parts.append("")
        parts.append(text)
        parts.append("")
    return "\n".join(parts)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for provider in SOURCES:
        content = fetch_provider_guide(provider)
        out_path = OUT_DIR / f"{provider}_cost_optimization_guide.md"
        out_path.write_text(content, encoding="utf-8")
        print(f"{PROVIDER_LABEL[provider]} 가이드 저장 완료: {out_path} ({len(content):,}자)")

    print("\nretrieve_docs가 다음 그래프 빌드 시 이 파일들을 자동으로 색인합니다 (data/policy_docs/*.md 전부 대상).")


if __name__ == "__main__":
    main()
