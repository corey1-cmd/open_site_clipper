"""접근 진단(--check-access) — 전면 차단과 경로별 차단을 갈라낸다.

이 구분이 핵심이다. 전면 차단(`Disallow: /`)은 어떤 주소를 찾아도 소용없지만,
경로별 차단은 다른 진입 경로가 열려 있을 수 있다(한국외대 subview.do 사례).
"""

from __future__ import annotations

from open_site_clipper import access
from open_site_clipper.sources import Source

MCST = Source(
    id="mcst",
    name="문화체육관광부",
    kind="govorg",
    url="",
    org="문화체육관광부",
    korea_feed="dept_mcst",
    routes=(
        ("보도자료", "rss", "https://www.mcst.go.kr/common/rss/press.jsp"),
        ("채용", "board", "https://www.mcst.go.kr/site/s_notice/notice/jobList.jsp"),
    ),
)

HUFS = Source(
    id="hufs",
    name="한국외국어대학교",
    kind="k2web",
    url="",
    org="한국외국어대학교",
    host="www.hufs.ac.kr",
    site_id="hufs",
    board_id=2180,
    menu_no=11281,
)


def test_candidate_urls_reuse_cascade():
    """진단이 두드리는 주소는 실제 수집이 쓸 주소와 같아야 한다."""
    labels = [lab for lab, _ in access.candidate_urls(MCST)]
    assert any(lab.startswith("보도자료/") for lab in labels)
    assert any(lab.startswith("채용/") for lab in labels)
    assert any("korea" in lab for lab in labels)  # 보도자료 안전망 포함
    # k2web 은 4단 후보를 그대로 쓴다.
    assert [lab for lab, _ in access.candidate_urls(HUFS)] == ["rss", "list", "page"]
    # url 도 좌표도 없으면 후보 없음.
    assert access.candidate_urls(Source(id="x", name="x", kind="rss", url="")) == []


def test_full_access():
    (r,) = access.check([MCST], allowed=lambda _u: True)
    assert r.verdict == access.FULL and r.allowed_count == len(r.checks)
    assert "전 경로 허용" in r.label


def test_blocked_everywhere_including_root():
    """루트까지 막히면 전면 차단 — 대체 경로를 찾아도 소용없다."""
    (r,) = access.check([MCST], allowed=lambda _u: False)
    assert r.verdict == access.BLOCKED
    assert "전면 차단" in r.label and "korea.kr" in r.label


def test_paths_blocked_but_root_open_is_different():
    """루트는 열렸는데 후보만 막힘 → 대체 경로 탐색 여지가 있다(전면 차단과 구분)."""

    def allowed(url: str) -> bool:
        return url.rstrip("/").endswith(".go.kr")  # 루트만 허용

    (r,) = access.check([MCST], allowed=allowed)
    assert r.verdict == access.PATHS_ONLY
    assert "대체 경로" in r.label


def test_partial_access_reports_which_paths_failed():
    """한국외대 실제 상황 — /bbs/ 만 막히고 subview.do 는 열린 경우."""

    def allowed(url: str) -> bool:
        return "/bbs/" not in url

    (r,) = access.check([HUFS], allowed=allowed)
    assert r.verdict == access.PARTIAL and r.allowed_count == 1
    blocked = [c.label for c in r.checks if not c.allowed]
    assert blocked == ["rss", "list"]  # 막힌 단계가 정확히 나온다


def test_sources_grouped_by_org():
    """한 기관의 여러 출처는 한 줄로 묶인다."""
    other = Source(
        id="mcst2",
        name="문화체육관광부",
        kind="rss",
        url="https://www.mcst.go.kr/x.xml",
        org="문화체육관광부",
    )
    results = access.check([MCST, other], allowed=lambda _u: True)
    assert len(results) == 1 and results[0].org == "문화체육관광부"


def test_render_lists_failures_and_summary():
    def allowed(url: str) -> bool:
        return "korea.kr" in url

    text = access.render(access.check([MCST, HUFS], allowed=allowed))
    assert "문화체육관광부" in text and "한국외국어대학교" in text
    assert "✗ 채용/board:" in text  # 막힌 경로를 주소까지 보여준다
    assert "요약: 기관 2곳" in text
    assert "User-Agent" in text  # 판정 주체 고지
    assert access.render([]) == "진단할 출처가 없습니다."
