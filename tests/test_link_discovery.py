"""링크 발견 보완 — 21곳이 후보 0개였던 문제(C1)와 40개 상한 문제(C2).

실행 결과에서 '게시판·피드 링크를 찾지 못했습니다' 39곳을 나눠 보니
후보 0개(21곳)와 후보는 찾았으나 전부 탈락(18곳)으로 갈렸다. 원인이 달라
처방도 다르다.
"""

from __future__ import annotations

from open_site_clipper import discover, govdiscover, robots

BOARD = (
    "<table><thead><tr><th>번호</th><th>제목</th><th>등록일</th></tr></thead><tbody>"
    '<tr><td>2</td><td><a href="/v?id=2">2026년 상반기 채용 공고</a></td><td>2026.07.20</td></tr>'
    '<tr><td>1</td><td><a href="/v?id=1">정기 입찰 공고 안내</a></td><td>2026.07.19</td></tr>'
    "</tbody></table>"
).encode()
STATIC = "<html><body><h1>장관 인사말</h1><p>안녕하십니까</p></body></html>".encode()


# ── L-4: 인라인 스크립트가 파서를 교란하던 문제 ─────────────────────────────
def test_strip_noise_removes_script_style_comment():
    raw = (
        "<html><head><style>a{}</style></head><body>"
        "<script>document.write('</div></a>');</script>"
        '<!-- <a href="/hidden">숨김</a> -->'
        '<a href="/real/list.do">공지사항</a></body></html>'
    )
    cleaned = discover.strip_noise(raw)
    assert "document.write" not in cleaned and "hidden" not in cleaned
    assert "/real/list.do" in cleaned  # 진짜 링크는 남는다


def test_anchor_survives_inline_script():
    """스크립트 안의 '</a>' 때문에 이후 메뉴를 통째로 놓치던 상황."""
    html = (
        "<html><body>"
        "<script>var t='<a href=\"/x\">'+'</a></div>';</script>"
        '<a href="/board/notice/list.do">공지사항</a>'
        '<a href="/board/job/list.do">채용정보</a>'
        "</body></html>"
    )
    page = discover._Page()
    page.feed(discover.strip_noise(html))
    hrefs = [h for h, _t in page.anchors]
    assert "/board/notice/list.do" in hrefs and "/board/job/list.do" in hrefs


# ── L-5: href="#" 이고 실제 주소가 data-* 에 있는 접근성 메뉴 ───────────────
def test_data_url_anchor_is_collected():
    html = (
        "<html><body>"
        '<a href="#" data-url="/board/job/list.do">채용정보</a>'
        '<a href="javascript:void(0);" data-href="/board/bid/list.do">입찰공고</a>'
        '<a href="#">진짜 죽은 링크</a>'
        "</body></html>"
    )
    page = discover._Page()
    page.feed(discover.strip_noise(html))
    hrefs = [h for h, _t in page.anchors]
    assert "/board/job/list.do" in hrefs and "/board/bid/list.do" in hrefs
    assert page.data_links == 2 and page.dead_links == 1
    assert page.anchor_tags == 3


# ── L-6: 40개 상한에 소개 메뉴만 차던 문제 ──────────────────────────────────
def test_board_score_prefers_boards_over_intro():
    assert govdiscover.board_score("https://x.go.kr/board/notice/list.do", "공지사항") > (
        govdiscover.board_score("https://x.go.kr/intro/greeting.do", "장관 인사말")
    )
    # 이름만으로도 신호가 잡힌다.
    assert govdiscover.board_score("https://x.go.kr/a/b/c", "채용정보") > 0
    # 소개 계열은 음수로 밀린다.
    assert govdiscover.board_score("https://x.go.kr/about/history.do", "연혁") < 0


def test_candidates_sorted_before_cap():
    """상한이 2여도 게시판이 먼저 시험된다(소개 메뉴에 자리를 뺏기지 않음)."""
    links = (
        "".join(f'<a href="/intro/page{i}.do">소개 {i}</a>' for i in range(30))
        + '<a href="/board/notice/list.do">공지사항</a>'
    )
    pages = {
        "https://x.go.kr/": f"<html><title>X</title><body>{links}</body></html>".encode(),
        "https://x.go.kr/board/notice/list.do": BOARD,
    }
    for i in range(30):
        pages[f"https://x.go.kr/intro/page{i}.do"] = STATIC
    routes, _notes = govdiscover.find_routes(
        "https://x.go.kr/", fetcher=pages.get, check_robots=False, max_candidates=2
    )
    assert any(u.endswith("/board/notice/list.do") for _c, _k, u in routes)


# ── L-1: robots.txt 의 Sitemap 을 추가 요청 없이 활용 ───────────────────────
def test_robots_sitemap_extracted(monkeypatch):
    import io

    class Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    body = (
        b"User-agent: *\nDisallow: /admin/\n"
        b"Sitemap: https://x.go.kr/sitemap.xml\n"
        b"sitemap: https://x.go.kr/sitemap_news.xml\n"
    )
    monkeypatch.setattr(robots.urllib.request, "urlopen", lambda *a, **k: Resp(body))
    robots.reset_cache()
    assert robots.sitemap_urls("https://x.go.kr/any") == [
        "https://x.go.kr/sitemap.xml",
        "https://x.go.kr/sitemap_news.xml",
    ]
    assert robots.allowed("https://x.go.kr/notice") is True  # 판정은 그대로


def test_sitemap_rescues_site_with_no_usable_home():
    """홈에 단서가 하나도 없어도 사이트맵으로 게시판을 찾는다(C1 구제)."""
    sitemap = (
        b'<?xml version="1.0"?><urlset>'
        b"<url><loc>https://oo.go.kr/intro/greeting.do</loc></url>"
        b"<url><loc>https://oo.go.kr/board/notice/list.do</loc></url></urlset>"
    )
    pages = {
        "https://oo.go.kr/": b"<html><head><title>OO</title></head><body>x</body></html>",
        "https://oo.go.kr/sitemap.xml": sitemap,
        "https://oo.go.kr/board/notice/list.do": BOARD,
        "https://oo.go.kr/intro/greeting.do": STATIC,
    }
    robots.reset_cache()
    robots._CACHE["https://oo.go.kr"] = None
    robots._SITEMAPS["https://oo.go.kr"] = ["https://oo.go.kr/sitemap.xml"]
    routes, notes = govdiscover.find_routes(
        "https://oo.go.kr/", fetcher=pages.get, check_robots=False
    )
    assert any(u.endswith("/board/notice/list.do") for _c, _k, u in routes)
    assert any("사이트맵에서 목록" in n for n in notes)
    robots.reset_cache()


# ── L-0 대체: 실패 시 원인을 숫자로 남긴다 ──────────────────────────────────
def test_failure_note_carries_diagnosis():
    pages = {"https://z.go.kr/": b"<html><head><title>Z</title></head><body>x</body></html>"}
    robots.reset_cache()
    robots._CACHE["https://z.go.kr"] = None
    robots._SITEMAPS["https://z.go.kr"] = []
    _routes, notes = govdiscover.find_routes(
        "https://z.go.kr/", fetcher=pages.get, check_robots=False
    )
    note = next(n for n in notes if "찾지 못했습니다" in n)
    # 어느 단계에서 끊겼는지 숫자로 드러난다 — 추측 대신 근거.
    for token in ("응답", "<a>", "주소없음", "data속성", "내부", "외부제외", "후보"):
        assert token in note, token
    robots.reset_cache()


# ── 진단이 '요청 실패'와 '빈 200 응답'을 구분해야 한다 ──────────────────────
def test_diagnosis_distinguishes_failure_from_empty_body():
    """'응답 0KB' 만으로는 요청이 막힌 것인지 본문이 빈 것인지 알 수 없었다."""

    class Blocked:
        def __call__(self, url):
            return None

        def why(self, url):
            return "접근 거부(403)"

    robots.reset_cache()
    robots._CACHE["https://x.go.kr"] = None
    robots._SITEMAPS["https://x.go.kr"] = []
    _routes, notes = govdiscover.find_routes(
        "https://x.go.kr/", fetcher=Blocked(), check_robots=False
    )
    note = next(n for n in notes if "진단" in n)
    assert "접근 거부(403)" in note  # 사유가 진단에 실린다
    robots.reset_cache()


def test_session_records_reason():
    session = discover._Session(lambda u: None, False, 5)
    session.get("https://x/1")
    assert session.last_reason == "응답 없음"
    session2 = discover._Session(lambda u: b"ok", False, 5)
    session2.get("https://x/1")
    assert session2.last_reason == ""


def test_candidate_limit_follows_budget():
    """후보가 상한보다 많아도 예산이 허락하면 더 본다(국세청 614개 중 40개 문제)."""
    links = "".join(f'<a href="/intro/p{i}.do">intro{i}</a>' for i in range(50))
    links += '<a href="/board/notice/list.do">공지사항</a>'
    pages = {
        "https://x.go.kr/": f"<html><title>X</title><body>{links}</body></html>".encode(),
        "https://x.go.kr/board/notice/list.do": BOARD,
    }
    for i in range(50):
        pages[f"https://x.go.kr/intro/p{i}.do"] = STATIC
    robots.reset_cache()
    robots._CACHE["https://x.go.kr"] = None
    robots._SITEMAPS["https://x.go.kr"] = []
    routes, _n = govdiscover.find_routes(
        "https://x.go.kr/", fetcher=lambda u: pages.get(u, b""), check_robots=False
    )
    assert any(u.endswith("/board/notice/list.do") for _c, _k, u in routes)
    robots.reset_cache()
