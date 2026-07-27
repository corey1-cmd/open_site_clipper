"""경로 사이클 — 홈을 못 읽는 기관을 알려진 패턴으로 뚫는다.

'응답 0KB · <a> 0개' 로 실패한 19곳을 조사한 결과, 게시판 주소는 CMS 패밀리
몇 종으로 수렴했다. 기관별 코드 대신 데이터 + 사이클로 처리한다.
"""

from __future__ import annotations

from open_site_clipper import govdiscover, govpaths, robots

BOARD = (
    "<table><thead><tr><th>번호</th><th>제목</th><th>등록일</th></tr></thead><tbody>"
    '<tr><td>2</td><td><a href="/v?id=2">2026년 상반기 채용 공고</a></td><td>2026.07.20</td></tr>'
    '<tr><td>1</td><td><a href="/v?id=1">정기 입찰 공고 안내</a></td><td>2026.07.19</td></tr>'
    "</tbody></table>"
).encode()
EMPTY = b""


def test_data_file_loads():
    fams = govpaths.families()
    assert len(fams) >= 5
    names = {f for f, _p in fams}
    # 실측으로 확인한 패밀리들이 들어 있다.
    assert {"moel", "pps", "mcst-jsp", "article-do", "generic"} <= names
    assert all(paths for _f, paths in fams)


def test_host_variants_covers_www_and_bare():
    assert govpaths.host_variants("https://www.pps.go.kr") == [
        "https://www.pps.go.kr",
        "https://pps.go.kr",
    ]
    assert govpaths.host_variants("pps.go.kr")[0] == "https://pps.go.kr"
    assert govpaths.host_variants("not a url") == [] or govpaths.host_variants("") == []


def test_cycle_finds_board_by_known_pattern():
    """홈이 빈 응답이어도 알려진 경로로 게시판을 찾는다(고용노동부형)."""
    pages = {"https://www.moel.go.kr/news/notice/noticeList.do?searchDivCd=001": BOARD}
    routes, notes = govpaths.probe_paths(
        "https://www.moel.go.kr",
        fetcher=lambda u: pages.get(u, EMPTY),
        home_host="www.moel.go.kr",
    )
    assert routes and routes[0][2].endswith("noticeList.do?searchDivCd=001")
    assert any("적중" in n for n in notes)


def test_cycle_tries_bare_host():
    """조달청은 www 없는 호스트에서 게시판이 열린다(실측)."""
    pages = {"https://pps.go.kr/kor/bbs/list.do?key=00641": BOARD}
    routes, _notes = govpaths.probe_paths(
        "https://www.pps.go.kr",
        fetcher=lambda u: pages.get(u, EMPTY),
        home_host="www.pps.go.kr",
    )
    assert routes and routes[0][2].startswith("https://pps.go.kr/")


def test_family_hit_pulls_sibling_paths():
    """첫 경로가 통하면 같은 패밀리의 나머지도 함께 건진다(요청 절약)."""
    base = "https://www.mcst.go.kr"
    pages = {
        f"{base}/kor/s_notice/notice/noticeList.jsp": BOARD,
        f"{base}/site/s_notice/notice/jobList.jsp": BOARD,
        f"{base}/site/s_notice/notice/bidList.jsp": BOARD,
    }
    routes, _n = govpaths.probe_paths(
        base, fetcher=lambda u: pages.get(u, EMPTY), home_host="www.mcst.go.kr"
    )
    urls = {u for _c, _k, u in routes}
    assert len(urls) >= 3  # 첫 경로 + 짝 경로들
    assert any(u.endswith("jobList.jsp") for u in urls)


def test_cycle_respects_budget():
    calls: list[str] = []

    def fx(u: str) -> bytes:
        calls.append(u)
        return EMPTY

    routes, notes = govpaths.probe_paths(
        "https://x.go.kr", fetcher=fx, budget=3, home_host="x.go.kr"
    )
    assert routes == [] and len(calls) <= 3
    assert any("시도했으나" in n for n in notes)


def test_wired_into_discovery():
    """홈이 빈 응답인 기관이 파이프라인 끝에서 경로 사이클로 구제된다."""
    pages = {
        "https://www.moel.go.kr/": EMPTY,
        "https://www.moel.go.kr/news/notice/noticeList.do?searchDivCd=001": BOARD,
    }
    robots.reset_cache()
    robots._CACHE["https://www.moel.go.kr"] = None
    robots._SITEMAPS["https://www.moel.go.kr"] = []
    routes, notes = govdiscover.find_routes(
        "https://www.moel.go.kr/", fetcher=lambda u: pages.get(u, EMPTY), check_robots=False
    )
    assert any("noticeList.do" in u for _c, _k, u in routes)
    assert any("적중" in n for n in notes)
    robots.reset_cache()
