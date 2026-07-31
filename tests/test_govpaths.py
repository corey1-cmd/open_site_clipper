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
    assert len(fams) >= 6
    names = {f for f, _p, _e in fams}
    # 실측으로 확인한 패밀리들이 들어 있다.
    assert {"entry", "moel", "pps", "mcst-jsp", "article-do", "generic"} <= names
    assert all(paths for _f, paths, _e in fams)
    # 진입점 패밀리가 맨 앞이다 — 진짜 홈을 먼저 찾아야 나머지가 쉬워진다.
    assert fams[0][0] == "entry" and fams[0][2] is True


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


def test_paths_are_tried_round_robin_across_families():
    """패밀리 경계 없이 한 줄로 세운다 — 각 패밀리의 첫 경로가 먼저 온다.

    한 패밀리를 끝까지 파면 뒤쪽 패밀리에 예산이 못 가고, 첫 경로만 보고 접으면
    번호만 다른 경로를 놓친다(교육부 boardID=333 은 없고 294 가 있다).
    """
    calls: list[str] = []

    def fx(u: str) -> bytes:
        calls.append(u)
        return EMPTY

    govpaths.probe_paths("https://x.go.kr", fetcher=fx, budget=20, home_host="x.go.kr")
    # 앞쪽에 여러 패밀리의 '첫 경로'가 섞여 나온다(한 패밀리에 몰리지 않는다).
    heads = {c.split("/", 3)[3].split("/")[0] for c in calls[:8] if c.count("/") > 3}
    assert len(heads) >= 3


def test_second_path_of_family_is_reachable():
    """같은 패밀리의 두 번째 경로에만 게시판이 있어도 찾아낸다(교육부 사례)."""
    url = "https://www.moe.go.kr/boardCnts/listRenew.do?boardID=294&m=020402&s=moe"
    routes, _n = govpaths.probe_paths(
        "https://www.moe.go.kr",
        fetcher=lambda u: BOARD if u == url else EMPTY,
        home_host="www.moe.go.kr",
    )
    assert routes and routes[0][2] == url


def test_cycle_respects_budget():
    calls: list[str] = []

    def fx(u: str) -> bytes:
        calls.append(u)
        return EMPTY

    routes, notes = govpaths.probe_paths(
        "https://x.go.kr", fetcher=fx, budget=3, home_host="x.go.kr"
    )
    assert routes == [] and len(calls) <= 3
    assert any(("소진" in n) or ("시도했으나" in n) for n in notes)


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


# ── 진입점 사이클 — '/' 가 관문이라 빈 응답인 기관 ─────────────────────────
MENU = (
    "<html><head><title>OO부</title></head><body>"
    + "".join(f'<a href="/menu{i}.do">메뉴{i}</a>' for i in range(12))
    + '<a href="/board/notice/list.do">공지사항</a></body></html>'
).encode()


def test_find_entry_locates_real_home():
    """'/' 가 비어도 /index.do 같은 진입점에서 메뉴를 찾는다."""
    pages = {"https://oo.go.kr/index.do": MENU}
    url, data = govpaths.find_entry("https://oo.go.kr/", fetcher=lambda u: pages.get(u, EMPTY))
    assert url == "https://oo.go.kr/index.do" and data == MENU


def test_find_entry_ignores_thin_gateway():
    """앵커가 몇 개 없는 관문 페이지는 진짜 홈으로 보지 않는다."""
    thin = b'<html><body><a href="/a">a</a><a href="/b">b</a></body></html>'
    pages = {"https://oo.go.kr/index.do": thin}
    url, _d = govpaths.find_entry("https://oo.go.kr/", fetcher=lambda u: pages.get(u, EMPTY))
    assert url == ""


def test_find_entry_respects_budget():
    calls: list[str] = []
    govpaths.find_entry("https://x.go.kr/", fetcher=lambda u: calls.append(u) or EMPTY, budget=3)
    assert len(calls) <= 3


def test_gateway_site_rescued_end_to_end():
    """홈이 관문인 기관이 진입점을 거쳐 게시판까지 연결된다."""
    pages = {
        "https://oo.go.kr/": EMPTY,
        "https://oo.go.kr/index.do": MENU,
        "https://oo.go.kr/board/notice/list.do": BOARD,
    }
    robots.reset_cache()
    robots._CACHE["https://oo.go.kr"] = None
    robots._SITEMAPS["https://oo.go.kr"] = []
    routes, notes = govdiscover.find_routes(
        "https://oo.go.kr/", fetcher=lambda u: pages.get(u, EMPTY), check_robots=False
    )
    assert any(u.endswith("/board/notice/list.do") for _c, _k, u in routes)
    assert any("진입점을 찾았습니다" in n for n in notes)
    robots.reset_cache()
