"""학교마다 공지·학사·장학·입학·채용 게시판을 갈래마다 찾아 채우기(slots).

가짜 학교 하나를 세운다 — 홈 메뉴에는 공지사항만 있고, 학사공지·채용공고는 사이트맵
화면에, 장학공지는 '장학안내' 화면 안쪽에, 입학 공지는 입학처 하위 사이트에 있다.
사람이 외대 게시판 번호를 찾던 순서 그대로 찾아지는지 본다.
"""

from __future__ import annotations

from open_site_clipper import discover, govdiscover, govpaths, slots

BOARD = """<table><thead><tr><th>번호</th><th>제목</th><th>등록일</th></tr></thead><tbody>
<tr><td>3</td><td><a href="view.do?id=3">세 번째 글</a></td><td>2026.10.08.</td></tr>
<tr><td>2</td><td><a href="view.do?id=2">두 번째 글</a></td><td>2026.10.07.</td></tr>
<tr><td>1</td><td><a href="view.do?id=1">첫 번째 글</a></td><td>2026.10.06.</td></tr>
</tbody></table>"""
STATIC = "<html><body><h1>안내</h1><p>설명문입니다.</p></body></html>"

HOME = """<html><head><title>가나대학교</title></head><body>
<header><a href="/kor/sitemap.do"><img src="/img/sitemap.png" alt="사이트맵"></a></header>
<nav>
  <a href="/kor/notice/list.do">공지사항</a>
  <a href="/kor/life/intro.do">대학생활</a>
  <a href="/kor/scholarship/intro.do">장학안내</a>
  <a href="https://ipsi.gana.ac.kr/">입학처</a>
  <a href="/kor/about/greeting.do">총장 인사말</a>
  <a href="/kor/about/history.do">연혁</a>
  <a href="/kor/about/map.do">찾아오시는 길</a>
  <a href="/kor/about/org.do">조직도</a>
  <a href="/kor/about/symbol.do">상징</a>
  <a href="/kor/about/vision.do">비전</a>
</nav>
<section class="latest">
  <a href="/kor/notice/view.do?id=3">2026학년도 2학기 국가장학금 2차 신청 기간 연장 안내</a>
</section>
</body></html>"""

SITEMAP = """<html><body><ul>
<li><a href="/kor/notice/list.do">공지사항</a></li>
<li><a href="/kor/haksa/notice.do">학사공지</a></li>
<li><a href="/kor/haksa/calendar.do">학사일정</a></li>
<li><a href="/kor/job/list.do">채용공고</a></li>
<li><a href="/kor/qna/list.do">입학 Q&amp;A</a></li>
</ul></body></html>"""

SCHOLARSHIP_HUB = """<html><body><aside>
<a href="/kor/notice/list.do">공지사항</a>
<a href="/kor/scholarship/inner.do">교내장학</a>
<a href="/kor/scholarship/notice.do">장학공지</a>
</aside><p>장학 제도 안내</p></body></html>"""

IPSI_HOME = """<html><body><nav>
<a href="/guide/susi.do">모집요강</a>
<a href="/board/notice.do">공지사항</a>
<a href="/board/counsel.do">입학상담</a>
</nav></body></html>"""

PAGES = {
    "https://www.gana.ac.kr/kor/index.do": HOME,
    "https://www.gana.ac.kr/kor/sitemap.do": SITEMAP,
    "https://www.gana.ac.kr/kor/notice/list.do": BOARD,
    "https://www.gana.ac.kr/kor/haksa/notice.do": BOARD,
    "https://www.gana.ac.kr/kor/haksa/calendar.do": BOARD,  # 날짜가 있어도 일정표는 공지가 아니다
    "https://www.gana.ac.kr/kor/job/list.do": BOARD,
    "https://www.gana.ac.kr/kor/qna/list.do": BOARD,  # 문의 게시판 — 후보에서 빠진다
    "https://www.gana.ac.kr/kor/life/intro.do": STATIC,
    "https://www.gana.ac.kr/kor/scholarship/intro.do": SCHOLARSHIP_HUB,
    "https://www.gana.ac.kr/kor/scholarship/inner.do": STATIC,
    "https://www.gana.ac.kr/kor/scholarship/notice.do": BOARD,
    "https://ipsi.gana.ac.kr/": IPSI_HOME,
    "https://ipsi.gana.ac.kr/guide/susi.do": STATIC,
    "https://ipsi.gana.ac.kr/board/notice.do": BOARD,
    "https://ipsi.gana.ac.kr/board/counsel.do": BOARD,
}


def _fetch(asked: list[str] | None = None):
    def get(url: str) -> bytes | None:
        if asked is not None:
            asked.append(url)
        page = PAGES.get(url)
        return page.encode() if page else None

    return get


def test_slot_names_follow_the_menu_word_and_skip_questions_and_calendars():
    assert slots.slot_of("장학공지") == "장학"
    assert slots.slot_of("학사공지") == "학사"
    assert slots.slot_of("입시공지") == "입학"
    assert slots.slot_of("취업정보") == "채용"
    assert slots.slot_of("공지사항") == "공지"
    assert slots.slot_of("입학상담") == ""  # 학생이 묻는 게시판
    assert slots.slot_of("입학 Q&A") == ""
    assert slots.slot_of("학사일정") == ""  # 일정표
    assert slots.slot_of("자유게시판") == ""
    assert slots.slot_of("대학소개") == ""
    # 최근 글 상자의 긴 제목은 메뉴 이름이 아니다
    assert slots.slot_of("2026학년도 2학기 국가장학금 2차 신청 기간 연장 안내") == ""


def test_icon_links_take_their_alt_text_as_the_name():
    page = discover._Page()
    page.feed(
        '<a href="/s.do"><img src="s.png" alt="사이트맵"></a><a href="/m.do" title="전체메뉴"></a>'
    )
    page.feed('<a href="/n.do" title="새 창">공지사항</a>')
    assert page.anchors == [("/s.do", "사이트맵"), ("/m.do", "전체메뉴"), ("/n.do", "공지사항")]


def test_every_kind_is_found_through_the_sitemap_hub_pages_and_the_admissions_site():
    tested: dict[str, str] = {}
    trace: list[str] = []
    home = "https://www.gana.ac.kr/kor/index.do"
    found = slots.fill(
        _fetch(),
        home,
        slots.anchors(PAGES[home].encode()),
        "www.gana.ac.kr",
        board_score=govdiscover.board_score,
        tested=tested,
        trace=trace,
    )
    by_kind = {govdiscover.classify(label): (label, url) for label, _k, url in found}
    assert by_kind["공지"] == ("공지사항", "https://www.gana.ac.kr/kor/notice/list.do")
    assert by_kind["학사"] == ("학사공지", "https://www.gana.ac.kr/kor/haksa/notice.do")  # 사이트맵
    assert by_kind["채용"] == ("채용공고", "https://www.gana.ac.kr/kor/job/list.do")  # 사이트맵
    # 장학안내 화면 안쪽의 장학공지
    assert by_kind["장학"] == ("장학공지", "https://www.gana.ac.kr/kor/scholarship/notice.do")
    # 입학처 하위 사이트의 '공지사항' = 입학 공지
    assert by_kind["입학"] == ("입학 공지사항", "https://ipsi.gana.ac.kr/board/notice.do")
    assert [govdiscover.classify(label) for label, _k, _u in found] == list(slots.TARGETS)
    # 문의 게시판·일정표·글 한 건은 열지도 않는다
    for url in tested:
        assert "qna" not in url and "counsel" not in url and "calendar" not in url
        assert "view.do" not in url
    assert any(t.startswith("사이트맵 ") for t in trace)
    assert any("갈래 화면" in t for t in trace)


def test_the_universitys_own_notice_on_an_inner_page_is_not_relabelled():
    """본교 장학 안내 화면에 있는 '공지사항'(대학 공지)은 장학 공지가 아니다."""
    pool = slots._Pool("www.gana.ac.kr", slots.TARGETS, govdiscover.board_score)
    hub = "https://www.gana.ac.kr/kor/scholarship/intro.do"
    pool.add(hub, [("/kor/board/general.do", "공지사항")], hub_slot="장학")
    assert pool.first["https://www.gana.ac.kr/kor/board/general.do"] == ("공지", "공지사항")
    sub = "https://ipsi.gana.ac.kr/"
    pool.add(sub, [("/board/notice.do", "공지사항")], hub_slot="입학")
    assert pool.first["https://ipsi.gana.ac.kr/board/notice.do"] == ("입학", "입학 공지사항")


def test_find_routes_fills_kinds_only_for_schools_and_keeps_the_trace():
    home = "https://www.gana.ac.kr/kor/index.do"
    trace: list[str] = []
    routes, _notes = govdiscover.find_routes(
        home, fetcher=_fetch(), check_robots=False, targets=slots.TARGETS, trace=trace
    )
    kinds = {govdiscover.classify(c) for c, _k, _u in routes}
    assert {"공지", "학사", "장학", "입학", "채용"} <= kinds
    assert trace and trace[0].startswith("홈 ")
    # 정부 기관처럼 갈래를 주지 않으면 홈 메뉴만 본다(예전 동작)
    plain, _ = govdiscover.find_routes(home, fetcher=_fetch(), check_robots=False)
    plain_kinds = {govdiscover.classify(c) for c, _k, _u in plain}
    assert "장학" not in plain_kinds and "입학" not in plain_kinds


def test_requests_stay_within_the_slot_budget():
    asked: list[str] = []
    home = "https://www.gana.ac.kr/kor/index.do"
    slots.fill(
        _fetch(asked),
        home,
        slots.anchors(PAGES[home].encode()),
        "www.gana.ac.kr",
        board_score=govdiscover.board_score,
        tested={},
        trace=[],
        max_requests=3,
    )
    assert len(asked) <= 3


INTRO = (
    "<html><head><title>입시 인트로</title><style>"
    + ("body{background:url(/img/intro.jpg)}" * 200)
    + "</style></head><body>"
    '<a href="https://ipsi.intro.ac.kr/">2027 입시 홈페이지</a>'
    '<a href="/eng/index.do">English</a>'
    '<a href="/kor/main.do">대학 홈페이지 바로가기</a>'
    "</body></html>"
)
MAIN = "<html><body>" + "".join(f'<a href="/kor/m{i}.do">메뉴{i}</a>' for i in range(12))
MAIN += '<a href="/kor/notice.do">공지사항</a></body></html>'


def test_intro_pages_lead_to_the_page_that_carries_the_menu():
    pages = {
        "https://www.intro.ac.kr/": INTRO,
        "https://www.intro.ac.kr/kor/main.do": MAIN,
        "https://www.intro.ac.kr/kor/notice.do": BOARD,
        "https://www.intro.ac.kr/eng/index.do": MAIN,
    }
    assert len(INTRO) > govpaths.GATEWAY_MAX_BYTES  # 관문 크기를 넘는 인트로
    targets = govpaths.intro_targets(INTRO.encode(), "https://www.intro.ac.kr/", "www.intro.ac.kr")
    assert targets[0] == "https://www.intro.ac.kr/kor/main.do"  # '바로가기'가 먼저
    assert all("/eng/" not in t for t in targets)  # 영문 화면은 홈으로 삼지 않는다

    def get(url: str) -> bytes | None:
        page = pages.get(url)
        return page.encode() if page else None

    trace: list[str] = []
    routes, notes = govdiscover.find_routes(
        "https://www.intro.ac.kr/", fetcher=get, check_robots=False, trace=trace
    )
    assert any(
        "관문 페이지를 따라갔습니다: https://www.intro.ac.kr/kor/main.do" in n for n in notes
    )
    assert ("공지", "board", "https://www.intro.ac.kr/kor/notice.do") in routes


def test_gateway_strings_do_not_lead_to_manifests_or_login_pages():
    gateway = (
        b'<html><head><script>var a="/manifest.json"; var b="/kor/index.do";</script></head></html>'
    )
    targets = govpaths.gateway_targets(gateway, "https://www.spa.ac.kr/")
    assert "https://www.spa.ac.kr/manifest.json" not in targets
    assert "https://www.spa.ac.kr/kor/index.do" in targets
    intro = b'<a href="/topLogin/view.do">login</a><a href="/kor/index.do">home</a>'
    picked = govpaths.intro_targets(intro, "https://www.spa.ac.kr/", "www.spa.ac.kr")
    assert picked == ["https://www.spa.ac.kr/kor/index.do"]


def test_a_sub_sites_notice_does_not_take_the_universitys_notice_slot():
    """사이트맵에 걸린 취업지원센터의 '공지사항'은 대학 공지 자리에 앉지 않는다(외대 실측)."""
    pool = slots._Pool("www.gana.ac.kr", slots.TARGETS, govdiscover.board_score)
    pool.add(
        "https://www.gana.ac.kr/kor/sitemap.do",
        [
            ("https://job.gana.ac.kr/board/notice.do", "공지사항"),
            ("https://gana.ac.kr/kor/notice.do", "공지사항"),  # www 없는 본교 주소는 본교
        ],
    )
    assert pool.pop("공지") == ("공지사항", "https://gana.ac.kr/kor/notice.do")
    assert pool.pop("공지") is None


def test_department_pages_are_not_hubs_and_rank_below_university_boards():
    pool = slots._Pool("www.gana.ac.kr", slots.TARGETS, govdiscover.board_score)
    pool.add(
        "https://www.gana.ac.kr/kor/index.do",
        [
            ("https://public.gana.ac.kr/", "공공인재학부"),  # '인재' → 채용이지만 학과 홈
            ("/kor/dept/job.do", "기계공학과 채용"),
            ("/kor/job/list.do", "채용공고"),
        ],
    )
    assert pool.pop_hub("채용") is None
    assert pool.pop("채용") == ("채용공고", "https://www.gana.ac.kr/kor/job/list.do")
    assert slots.slot_of("학부입학") == "입학"  # 학부 입학은 학과가 아니다
    assert slots.slot_of("모집요강") == "입학"  # 모집(채용)이 아니라 입학


def test_junk_boards_and_the_home_itself_are_not_notice_boards():
    for name in ("Q&A", "분실물/습득물", "개인정보처리방침", "입학상담", "자주 묻는 질문"):
        assert slots.not_notice(name), name
    assert not slots.not_notice("공지사항")
    assert slots.same_page(
        "https://www.chugye.ac.kr/mbs/university/",
        "https://www.chugye.ac.kr/mbs/university/index.jsp",
    )
    assert not slots.same_page(
        "https://www.chugye.ac.kr/mbs/university/jsp/board/list.jsp?boardId=6784",
        "https://www.chugye.ac.kr/mbs/university/index.jsp",
    )


def test_an_intro_address_with_a_dozen_banner_links_is_not_the_home():
    banners = "".join(f'<a href="/popup/{i}.asp">배너{i}</a>' for i in range(14))
    intro = f'<html><body>{banners}<a href="/www/main/main.asp">홈페이지 바로가기</a></body></html>'
    assert govpaths.needs_hop(intro.encode(), "https://www.puts.ac.kr/www/main/intro/intro.asp")
    assert not govpaths.needs_hop(intro.encode(), "https://www.puts.ac.kr/www/main/main.asp")


def test_a_board_page_that_loads_its_list_by_script_gives_up_the_list_address():
    """K2Web 메뉴 화면은 목록을 스크립트로 부른다 — 소스 속 artclList 주소를 시험한다."""
    subview = (
        "<html><body><h2>장학공지</h2><div id='list'></div>"
        "<script>jf_load('/bbs/gana/2182/artclList.do', 'list');</script></body></html>"
    )
    pages = {
        "https://www.gana.ac.kr/gana/index.do": (
            "<html><body>"
            + "".join(f'<a href="/gana/{i}/subview.do">메뉴{i}</a>' for i in range(12))
            + '<a href="/gana/9001/subview.do">장학공지</a></body></html>'
        ),
        "https://www.gana.ac.kr/gana/9001/subview.do": subview,
        "https://www.gana.ac.kr/bbs/gana/2182/artclList.do": BOARD,
    }

    def get(url: str) -> bytes | None:
        page = pages.get(url)
        return page.encode() if page else None

    trace: list[str] = []
    home = "https://www.gana.ac.kr/gana/index.do"
    found = slots.fill(
        get,
        home,
        slots.anchors(pages[home].encode()),
        "www.gana.ac.kr",
        board_score=govdiscover.board_score,
        tested={},
        trace=trace,
        mine=govdiscover.mine_url_literals,
    )
    assert ("장학공지", "board", "https://www.gana.ac.kr/bbs/gana/2182/artclList.do") in found
    assert any("화면 속 목록 주소" in t for t in trace)


def test_login_systems_and_recruiting_words_alone_are_not_hubs():
    pool = slots._Pool("www.gana.ac.kr", slots.TARGETS, govdiscover.board_score)
    pool.add(
        "https://www.gana.ac.kr/kor/index.do",
        [
            ("https://portal.gana.ac.kr/", "학사정보시스템"),
            ("https://sugang.gana.ac.kr/", "수강신청"),
            ("https://rotc.gana.ac.kr/", "학군단 생활/모집"),
            ("https://job.gana.ac.kr/", "진로취업센터"),
        ],
    )
    assert pool.pop_hub("학사") is None
    assert pool.pop_hub("채용") == ("진로취업센터", "https://job.gana.ac.kr/")
    assert pool.pop_hub("채용") is None


def test_board_names_lose_glued_more_buttons():
    from open_site_clipper import categories, probe

    assert categories.tidy_label("학사더보기") == "학사"
    assert categories.tidy_label("등록/장학더보기") == "등록/장학"
    assert categories.tidy_label("학사 더") == "학사"
    assert categories.tidy_label("리더") == "리더"
    assert probe.looks_like_article(
        "http://gangseo.ac.kr/kcua/boardView?menuCode=MC0508&boardNum=1"
    )
    assert not probe.looks_like_article("http://gangseo.ac.kr/kcua/boardList?menuCode=BC0702")


def test_k2web_menu_pages_are_boards_but_their_encoded_article_views_are_not():
    import base64
    import urllib.parse

    from open_site_clipper import probe

    def enc(inner: str) -> str:
        return base64.b64encode(urllib.parse.quote(inner).encode()).decode()

    menu = "https://www.hufs.ac.kr/hufs/11281/subview.do"
    assert not probe.looks_like_article(menu)  # 메뉴 화면 — 목록이 박혀 있다
    assert probe.looks_like_article(menu + "?enc=" + enc("fnct1|@@|/bbs/hufs/2180/1/artclView.do"))
    assert not probe.looks_like_article(
        menu + "?enc=" + enc("fnct1|@@|/bbs/hufs/2180/artclList.do")
    )
    assert probe.looks_like_article("https://www.x.ac.kr/board/view.do?id=1")
