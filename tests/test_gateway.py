"""관문 페이지 추적과 쿠키 세션 — 0.17.0 실행에서 사유가 확정된 문제들.

진단 사유가 찍히면서 '응답 0KB' 가 세 가지였음이 드러났다:
  HTTP 307 (경찰청·국토교통부·법무부·외교부) — 쿠키를 요구하는 리다이렉트
  인증서 오류 (민주평화통일자문회의)
  사유 없는 0KB (공정위·교육부·해수부 …) — 빈 응답이 아니라 1KB 미만 **관문**
"""

from __future__ import annotations

from open_site_clipper import fetch, govdiscover, govpaths, robots

BOARD = (
    "<table><thead><tr><th>번호</th><th>제목</th><th>등록일</th></tr></thead><tbody>"
    '<tr><td>2</td><td><a href="/v?id=2">2026년 채용 공고</a></td><td>2026.07.20</td></tr>'
    '<tr><td>1</td><td><a href="/v?id=1">정기 입찰 공고</a></td><td>2026.07.19</td></tr>'
    "</tbody></table>"
).encode()
HOME = (
    "<html><head><title>OO부</title></head><body>"
    + "".join(f'<a href="/m{i}.do">menu{i}</a>' for i in range(12))
    + '<a href="/board/notice/list.do">공지사항</a></body></html>'
).encode()


# ── 관문이 가리키는 진짜 주소 뽑기 ──────────────────────────────────────────
def test_gateway_target_reads_all_forms():
    base = "https://x.go.kr/"
    cases = {
        b'<meta http-equiv="refresh" content="0;url=/main.do">': "https://x.go.kr/main.do",
        b'<script>location.href="/kor/index.do";</script>': "https://x.go.kr/kor/index.do",
        b'<script>location.replace("/main.jsp");</script>': "https://x.go.kr/main.jsp",
        b'<script>top.location="/portal/";</script>': "https://x.go.kr/portal/",
        b'<frameset><frame src="/portal/main.do"></frameset>': "https://x.go.kr/portal/main.do",
    }
    for html, expected in cases.items():
        assert govpaths.gateway_target(html, base) == expected, html


def test_gateway_target_ignores_real_pages():
    """내용이 있는 페이지는 관문으로 보지 않는다(오탐 방지)."""
    big = b"<html><body>" + b"x" * 5000 + b'<script>location.href="/a"</script></body></html>'
    assert govpaths.gateway_target(big, "https://x.go.kr/") == ""
    assert govpaths.gateway_target(b"", "https://x.go.kr/") == ""
    assert govpaths.gateway_target(b"<html><body>hi</body></html>", "https://x.go.kr/") == ""


def test_gateway_target_rejects_self_and_bad_scheme():
    same = b'<meta http-equiv="refresh" content="0;url=https://x.go.kr/">'
    assert govpaths.gateway_target(same, "https://x.go.kr/") == ""
    bad = b'<script>location.href="javascript:void(0)";</script>'
    assert govpaths.gateway_target(bad, "https://x.go.kr/") == ""


def test_gateway_site_rescued_end_to_end():
    """관문 → 진짜 홈 → 게시판까지 이어진다."""
    gate = (
        b'<html><head><meta http-equiv="refresh" content="0;url=/kor/main.do">'
        b"</head><body></body></html>"
    )
    pages = {
        "https://oo.go.kr/": gate,
        "https://oo.go.kr/kor/main.do": HOME,
        "https://oo.go.kr/board/notice/list.do": BOARD,
    }
    robots.reset_cache()
    robots._CACHE["https://oo.go.kr"] = None
    robots._SITEMAPS["https://oo.go.kr"] = []
    routes, notes = govdiscover.find_routes(
        "https://oo.go.kr/", fetcher=lambda u: pages.get(u, b""), check_robots=False
    )
    assert any(u.endswith("/board/notice/list.do") for _c, _k, u in routes)
    assert any("관문 페이지를 따라갔습니다" in n for n in notes)
    robots.reset_cache()


def test_gateway_hops_are_bounded():
    """관문이 관문을 가리켜도 무한히 돌지 않는다."""
    loop = b'<meta http-equiv="refresh" content="0;url=/next">'
    calls: list[str] = []

    def fx(u: str) -> bytes:
        calls.append(u)
        return loop

    robots.reset_cache()
    robots._CACHE["https://y.go.kr"] = None
    robots._SITEMAPS["https://y.go.kr"] = []
    govdiscover.find_routes("https://y.go.kr/", fetcher=fx, check_robots=False)
    assert calls.count("https://y.go.kr/next") <= 2  # 최대 2홉
    robots.reset_cache()


# ── 쿠키 세션(307 대응) ─────────────────────────────────────────────────────
def test_opener_keeps_cookiejar_per_thread():
    """쿠키를 지키는 것은 정상 클라이언트 동작 — UA 는 그대로 우리 이름."""
    o1 = fetch._opener()
    assert o1 is fetch._opener()  # 같은 스레드면 세션 재사용
    assert any("Cookie" in type(h).__name__ for h in o1.handlers)
    assert fetch.REQUEST_HEADERS["User-Agent"].startswith("open_site_clipper")


# ── 출처 표기 상세화 ────────────────────────────────────────────────────────
def test_origin_label_shows_which_board():
    """'게시판' 한 마디로는 같은 기관의 여러 게시판을 구분할 수 없다."""
    from open_site_clipper.cascade import origin_label

    got = origin_label("https://www.mcst.go.kr/kor/s_notice/notice/noticeList.jsp", "board")
    assert got == "www.mcst.go.kr · 게시판 · /kor/s_notice/notice/noticeList.jsp"


def test_origin_label_keeps_board_ids_drops_noise():
    """게시판을 지목하는 파라미터만 남기고 정렬·페이지 번호는 뺀다."""
    from open_site_clipper.cascade import origin_label

    got = origin_label(
        "https://www.kdca.go.kr/board/board.es?mid=a205&bid=0015&nPage=3&sort=desc", "board"
    )
    assert "bid=0015" in got and "mid=a205" in got
    assert "nPage" not in got and "sort" not in got


def test_origin_label_shortens_long_paths():
    from open_site_clipper.cascade import origin_label

    got = origin_label("https://x.go.kr/" + "a/" * 40 + "list.do", "board")
    assert "…" in got and len(got) < 120


# ── 본문 머리 진단 (0KB 의 정체를 가른다) ───────────────────────────────────
def test_body_head_distinguishes_response_kinds():
    from open_site_clipper.govdiscover import _body_head

    assert "frameset" in _body_head(b'<html><frameset><frame src="/m"></frameset></html>')
    assert "top.location" in _body_head(b"<html><script>top.location=self.location;</script>")
    assert _body_head(b"") == "(빈 응답)"
    head = _body_head("<html><body>비정상적인 접근이 감지되었습니다.</body></html>".encode())
    assert "비정상적인 접근" in head  # WAF 안내문이면 바로 드러난다


def test_body_head_is_single_line_and_bounded():
    from open_site_clipper.govdiscover import _body_head

    got = _body_head(b"<html>\n\n  <body>" + b"x" * 500 + b"</body></html>")
    assert "\n" not in got and len(got) <= 91


def test_diagnosis_note_includes_body_head():
    pages = {"https://z.go.kr/": b'<html><frameset><frame src="/m"></frameset></html>'}
    robots.reset_cache()
    robots._CACHE["https://z.go.kr"] = None
    robots._SITEMAPS["https://z.go.kr"] = []
    _routes, notes = govdiscover.find_routes(
        "https://z.go.kr/", fetcher=lambda u: pages.get(u, b""), check_robots=False
    )
    note = next((n for n in notes if "진단" in n), "")
    assert "본문머리[" in note
    robots.reset_cache()
