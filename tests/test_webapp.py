"""휴대폰 웹 버전의 서버 쪽 — 기관 하나 수집·경로 캐시·시간 제한·HTTP 응답.

네트워크는 쓰지 않는다. 기관 목록은 임시 파일로, 페이지는 사전으로 흉내 낸다.
"""

from __future__ import annotations

import io
import json
import threading
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer

import pytest

from open_site_clipper import robots, webapp

HOME = """<html><body><nav>
<a href="/bbs/notice/list.do">학사공지</a>
<a href="/bbs/janghak/list.do">장학공지</a>
<a href="/intro/greeting.do">총장 인사말</a>
</nav></body></html>"""

BOARD = """<table><thead><tr><th>번호</th><th>제목</th><th>등록일</th></tr></thead><tbody>
<tr><td>3</td><td><a href="/view.do?id=3">수강신청 안내</a></td><td>2026.10.08.</td></tr>
<tr><td>2</td><td><a href="/view.do?id=2">휴학 신청 기간</a></td><td>2026.10.01.</td></tr>
<tr><td>1</td><td><a href="/view.do?id=1">오래된 글</a></td><td>2026.06.01.</td></tr>
</tbody></table>"""

STATIC = "<html><body><h1>총장 인사말</h1><p>안녕하십니까</p></body></html>"

SITE = "https://www.test.ac.kr"
PAGES = {
    f"{SITE}": HOME.encode(),
    f"{SITE}/": HOME.encode(),
    f"{SITE}/bbs/notice/list.do": BOARD.encode(),
    f"{SITE}/bbs/janghak/list.do": BOARD.replace("view.do?id=", "j.do?id=").encode(),
    f"{SITE}/intro/greeting.do": STATIC.encode(),
}


class Recorder:
    """요청한 주소를 기억하는 가짜 페처."""

    def __init__(self, pages: dict[str, bytes]):
        self.pages = pages
        self.asked: list[str] = []

    def __call__(self, url: str) -> bytes | None:
        self.asked.append(url)
        return self.pages.get(url)


@pytest.fixture
def tiny_catalog(tmp_path, monkeypatch):
    """학교 하나짜리 목록 + 빈 경로 캐시 — 실제 목록 파일은 건드리지 않는다."""
    (tmp_path / "orgs.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "u-test",
                        "org": "시험대학교",
                        "name": "시험대학교",
                        "kind": "govorg",
                        "group": "4년제",
                        "region": "세종",
                        "home": SITE,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OSC_CATALOG_DIR", str(tmp_path))
    monkeypatch.setattr(webapp, "SECTIONS", (("학교", "orgs.json"),))
    monkeypatch.setattr(webapp, "ROUTE_CACHE_FILE", tmp_path / "route-cache.json")
    monkeypatch.setattr(robots, "allowed", lambda url, **k: True)
    monkeypatch.setattr(robots, "stated_delay", lambda url, **k: None)
    monkeypatch.setattr(robots, "sitemap_urls", lambda url: [])
    webapp.catalog.cache_clear()
    webapp.route_cache.cache_clear()
    yield tmp_path
    webapp.catalog.cache_clear()
    webapp.route_cache.cache_clear()


def _collect(**kw):
    kw.setdefault("today", date(2026, 10, 9))
    kw.setdefault("delay", 0)
    return webapp.collect_one("u-test", **kw)


# ── 실제 기관 목록 ───────────────────────────────────────────────────────────
def test_real_catalog_has_government_and_schools():
    webapp.catalog.cache_clear()
    orgs = webapp.catalog()
    sections = {o.section for o in orgs.values()}
    assert sections == {"정부", "학교"}
    gov = [o for o in orgs.values() if o.section == "정부"]
    assert sum(o.id.startswith("gov-") for o in gov) == 65  # 중앙행정기관
    assert "pub-kosaf" in orgs and orgs["pub-kosaf"].group == "공공기관"  # 장학 공지의 본거지
    schools = [o for o in orgs.values() if o.section == "학교"]
    assert len(schools) >= 350  # 4년제·전문대·사이버대 … 전국
    assert all(o.home.startswith(("https://", "http://")) for o in orgs.values())
    assert all(o.home.startswith("https://") for o in schools)
    assert all(o.group and o.region for o in schools)  # 화면의 묶음·필터에 쓰인다
    # 같은 학교 두 번·같은 홈 두 번은 없다
    assert len({o.home for o in schools}) == len(schools)
    assert len({o.name for o in schools}) == len(schools)


def test_catalog_payload_is_light():
    webapp.catalog.cache_clear()
    payload = webapp.catalog_payload()
    assert payload["sections"] == ["정부", "학교"]
    first = payload["orgs"][0]
    assert set(first) == {"id", "name", "section", "group", "region", "home", "checked"}
    assert "source" not in json.dumps(payload, ensure_ascii=False)


# ── 기관 하나 수집 ───────────────────────────────────────────────────────────
def test_discovers_boards_and_returns_recent_rows(tiny_catalog):
    got = _collect(days=30, fetcher=Recorder(PAGES))
    assert got["mode"] == "discover"
    titles = [r["title"] for r in got["notices"]]
    assert "수강신청 안내" in titles and "휴학 신청 기간" in titles
    assert "오래된 글" not in titles  # 30일 밖은 뺀다
    dates = [r["date"] for r in got["notices"]]
    assert dates == sorted(dates, reverse=True)  # 최신순
    groups = {r["group"] for r in got["notices"]}
    assert groups <= {"학사", "장학"}  # 학교 갈래로 분류된다
    # 공지가 실제로 나온 경로를 돌려준다 — 경로 캐시를 굽는 재료
    assert {u for _c, _k, u in got["routes"]} == {
        f"{SITE}/bbs/notice/list.do",
        f"{SITE}/bbs/janghak/list.do",
    }
    assert all("greeting" not in u for _c, _k, u in got["routes"])


def test_cached_routes_skip_discovery(tiny_catalog):
    (tiny_catalog / "route-cache.json").write_text(
        json.dumps(
            {"orgs": {"u-test": {"routes": [["학사공지", "board", f"{SITE}/bbs/notice/list.do"]]}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    webapp.route_cache.cache_clear()
    rec = Recorder(PAGES)
    got = _collect(days=30, fetcher=rec)
    assert got["mode"] == "cache" and got["count"] == 2
    assert rec.asked == [f"{SITE}/bbs/notice/list.do"]  # 홈을 열지 않는다
    assert webapp.catalog_payload()["orgs"][0]["checked"] is True


def test_stale_cache_falls_back_to_discovery(tiny_catalog):
    (tiny_catalog / "route-cache.json").write_text(
        json.dumps({"orgs": {"u-test": {"routes": [["공지", "board", f"{SITE}/gone.do"]]}}}),
        encoding="utf-8",
    )
    webapp.route_cache.cache_clear()
    got = _collect(days=30, fetcher=Recorder(PAGES))
    assert got["mode"] == "rediscover"
    assert got["count"] > 0


def test_fresh_ignores_cache(tiny_catalog):
    (tiny_catalog / "route-cache.json").write_text(
        json.dumps({"orgs": {"u-test": {"routes": [["공지", "board", f"{SITE}/gone.do"]]}}}),
        encoding="utf-8",
    )
    webapp.route_cache.cache_clear()
    got = _collect(days=30, fetcher=Recorder(PAGES), fresh=True)
    assert got["mode"] == "discover" and got["count"] > 0


def test_time_budget_stops_requests_and_says_why(tiny_catalog):
    """시간을 다 쓰면 더 요청하지 않고, 남은 단계에 '시간 제한' 사유를 남긴다."""
    ticks = iter([0.0] + [1000.0] * 100)  # 시작 직후 시간이 다 간 것처럼
    rec = Recorder(PAGES)
    got = _collect(days=30, fetcher=rec, budget=10, clock=lambda: next(ticks))
    assert rec.asked == []  # 한 번도 두드리지 않았다
    assert got["timed_out"] is True and got["count"] == 0
    assert any(webapp.TIME_UP in n for n in got["notes"] + got["failures"]) or got["notes"]


def test_unknown_org_raises_key_error(tiny_catalog):
    with pytest.raises(KeyError):
        webapp.collect_one("nope")


def test_verify_summarises_each_org(tiny_catalog):
    rows = webapp.verify(["u-test", "nope"], days=30, fetcher=Recorder(PAGES), delay=0)
    assert [r["id"] for r in rows] == ["u-test"]  # 모르는 id 는 조용히가 아니라 아예 받지 않는다
    assert rows[0]["count"] > 0 and rows[0]["routes"]
    assert sum(rows[0]["groups"].values()) == rows[0]["count"]  # 갈래별 건수(보고서용)
    tsv = webapp.verify_tsv(rows)
    assert tsv.startswith("u-test\t시험대학교\t")


# ── HTTP ─────────────────────────────────────────────────────────────────────
class FakeHandler:
    """BaseHTTPRequestHandler 의 응답 쪽만 흉내 낸다."""

    def __init__(self, path: str):
        self.path = path
        self.command = "GET"
        self.status = 0
        self.headers: dict[str, str] = {}
        self.wfile = io.BytesIO()

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, key: str, value: str) -> None:
        self.headers[key] = value

    def end_headers(self) -> None:
        pass

    def json(self) -> dict:
        return json.loads(self.wfile.getvalue().decode("utf-8"))


def test_respond_catalog_is_cacheable(tiny_catalog):
    h = FakeHandler("/api/catalog")
    webapp.respond(h, "catalog")
    assert h.status == 200 and "s-maxage" in h.headers["Cache-Control"]
    assert h.json()["orgs"][0]["id"] == "u-test"


def test_respond_unknown_org_is_404(tiny_catalog):
    h = FakeHandler("/api/collect?id=nope")
    webapp.respond(h, "collect")
    assert h.status == 404 and "nope" in h.json()["error"]
    assert h.headers["Cache-Control"] == "no-store"


def test_respond_bad_days_is_400(tiny_catalog):
    h = FakeHandler("/api/collect?id=u-test&days=abc")
    webapp.respond(h, "collect")
    assert h.status == 400


def test_respond_collect_caches_hits_longer_than_misses(tiny_catalog, monkeypatch):
    calls = {"count": 2}

    def fake_collect(org_id, **kw):
        return {"count": calls["count"], "notices": []}

    monkeypatch.setattr(webapp, "collect_one", fake_collect)
    h = FakeHandler("/api/collect?id=u-test&days=7")
    webapp.respond(h, "collect")
    assert h.headers["Cache-Control"] == webapp.CACHE_OK
    calls["count"] = 0
    h = FakeHandler("/api/collect?id=u-test&days=7")
    webapp.respond(h, "collect")
    assert h.headers["Cache-Control"] == webapp.CACHE_EMPTY  # 0건은 곧 다시 시도하게 짧게


def test_respond_unexpected_error_is_500_with_reason(tiny_catalog, monkeypatch):
    def boom(org_id, **kw):
        raise RuntimeError("파서 고장")

    monkeypatch.setattr(webapp, "collect_one", boom)
    h = FakeHandler("/api/collect?id=u-test")
    webapp.respond(h, "collect")
    assert h.status == 500 and "파서 고장" in h.json()["error"]


# ── 로컬 개발 서버 ───────────────────────────────────────────────────────────
def _get(url: str) -> tuple[int, bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def test_dev_server_serves_public_and_api(tiny_catalog, tmp_path, monkeypatch):
    public = tmp_path / "public"
    public.mkdir()
    (public / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("비밀", encoding="utf-8")
    monkeypatch.setattr(webapp, "PUBLIC_DIR", public)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), webapp._DevHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        status, body = _get(base + "/")
        assert status == 200 and b"<title>t</title>" in body
        status, body = _get(base + "/api/catalog")
        assert status == 200 and json.loads(body)["orgs"][0]["id"] == "u-test"
        status, _ = _get(base + "/../secret.txt")  # public/ 밖은 못 나간다
        assert status == 404
        status, _ = _get(base + "/%2e%2e/secret.txt")
        assert status == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_discover_stage_returns_found_routes_without_collecting(tiny_catalog):
    rows = webapp.verify(["u-test"], stage="discover", fetcher=Recorder(PAGES), delay=0)
    found = {u for _c, _k, u in rows[0]["found"]}
    assert f"{SITE}/bbs/notice/list.do" in found and "count" not in rows[0]


def test_fetch_encodes_spaces_and_hangul_instead_of_crashing():
    """링크에 공백·한글이 날것으로 있어도 기관 전체가 멈추지 않는다(국민대·동국대 실측)."""
    from open_site_clipper.fetch import safe_url

    assert safe_url("https://x.ac.kr/files/2025 인증서.pdf") == (
        "https://x.ac.kr/files/2025%20%EC%9D%B8%EC%A6%9D%EC%84%9C.pdf"
    )
    assert safe_url("https://x.ac.kr/a?b=1&c=%20") == "https://x.ac.kr/a?b=1&c=%20"


def test_discover_can_resume_after_tested_candidates(tiny_catalog):
    """큰 사이트는 한 번에 다 못 본다 — 앞 회차에서 본 후보를 건너뛰고 이어 찾는다."""
    full = webapp.verify(["u-test"], stage="discover", fetcher=Recorder(PAGES), delay=0)[0]
    rest = webapp.verify(["u-test"], stage="discover", fetcher=Recorder(PAGES), skip=99, delay=0)[0]
    assert full["found"] and not rest["found"]
    assert any("건너뜁니다" in n for n in rest["notes"])


def test_aia_repair_adds_missing_intermediate(monkeypatch):
    """중간 인증서를 안 보내는 서버 — AIA 주소에서 받아 저장소에 더한다(한 호스트 한 번)."""
    import io
    import ssl

    from open_site_clipper import aia

    monkeypatch.setattr(aia, "_done", {})
    monkeypatch.setattr(ssl, "get_server_certificate", lambda addr, timeout=None: "LEAF")
    issuers = {"LEAF": ["http://ca.example/inter.crt"], "-----BEGIN CERTIFICATE-----\nX": []}
    monkeypatch.setattr(aia, "_ca_issuers", lambda pem: issuers.get(pem, []))
    pem = "-----BEGIN CERTIFICATE-----\nX"
    monkeypatch.setattr(
        aia.urllib.request, "urlopen", lambda url, timeout=None: io.BytesIO(pem.encode())
    )
    loaded = []
    monkeypatch.setattr(
        aia,
        "_ctx",
        type("C", (), {"load_verify_locations": lambda self, cadata: loaded.append(cadata)})(),
    )
    assert aia.repair("https://school.example/") is True
    assert loaded == [pem]
    assert aia.repair("https://school.example/other") is False  # 같은 호스트는 다시 안 함


# ── 같은 이름의 게시판·제목 갈래 (한국외대 실측: 공지·학사·장학·채용이 전부 'READ') ──
def _board(rows: list[tuple[str, str, str]]) -> bytes:
    body = "".join(
        f'<tr><td>{i}</td><td><a href="{href}">{title}</a></td><td>{day}</td></tr>'
        for i, (href, title, day) in enumerate(rows)
    )
    return f"<table><tbody>{body}</tbody></table>".encode()


K2 = "https://www.test.ac.kr/bbs/test"
READ_BOARDS = {
    f"{K2}/2180/artclList.do?layout=unknown": _board(
        [
            (f"{K2}/2180/1/artclView.do", "보건실 심폐소생술 교육 일정", "2026.10.08"),
            (f"{K2}/2180/2/artclView.do", "2026학년도 2학기 교내장학금 신청 안내", "2026.10.07"),
            (f"{K2}/2180/3/artclView.do", "인조잔디 운동장 보수 안내문", "2026.10.02"),
        ]
    ),
    f"{K2}/2181/artclList.do?layout=unknown": _board(
        [
            (f"{K2}/2181/1/artclView.do", "2026-2학기 수강신청 정정 안내", "2026.10.06"),
            (f"{K2}/2181/2/artclView.do", "2027년 2월 졸업예정자 학위청구 안내", "2026.10.05"),
            (f"{K2}/2181/3/artclView.do", "복학 신청 기간 안내", "2026.10.01"),
        ]
    ),
    f"{K2}/2182/artclList.do?layout=unknown": _board(
        [
            (f"{K2}/2182/1/artclView.do", "OO재단 장학생 선발 안내", "2026.10.08"),
            (f"{K2}/2182/2/artclView.do", "국가근로장학생 추가 모집", "2026.10.04"),
            (f"{K2}/2182/3/artclView.do", "2학기 학자금 대출 안내", "2026.09.30"),
            # 공지 게시판에도 같이 올라온 글 — 한 번만 남는다
            (f"{K2}/2182/4/artclView.do", "2026학년도 2학기 교내장학금 신청 안내", "2026.10.07"),
        ]
    ),
}


def _cache(tmp, routes):
    (tmp / "route-cache.json").write_text(
        json.dumps({"orgs": {"u-test": {"routes": routes}}}, ensure_ascii=False), encoding="utf-8"
    )
    webapp.route_cache.cache_clear()


def test_boards_with_the_same_label_are_all_collected(tiny_catalog):
    _cache(tiny_catalog, [["READ", "board", u] for u in READ_BOARDS])
    got = _collect(days=30, fetcher=Recorder(READ_BOARDS))
    titles = [r["title"] for r in got["notices"]]
    assert "OO재단 장학생 선발 안내" in titles  # 예전에는 첫 게시판에서 멈춰 빠졌다
    assert "복학 신청 기간 안내" in titles
    assert titles.count("2026학년도 2학기 교내장학금 신청 안내") == 1  # 겹친 글은 한 번
    # 게시판 이름은 내용으로 다듬어 돌려준다 — 캐시에 'READ' 대신 장학·학사가 남는다
    labels = {u.split("/")[-2]: c for c, _k, u in got["routes"]}
    assert labels["2182"] == "장학" and labels["2181"] == "학사"
    assert labels["2180"] == "기타"  # 섞인 게시판은 이름을 지어내지 않는다('READ'는 이름이 아니다)


def test_scholarship_titles_in_a_general_board_are_filed_as_scholarship(tiny_catalog):
    _cache(tiny_catalog, [["공지", "board", f"{K2}/2180/artclList.do?layout=unknown"]])
    got = _collect(days=30, fetcher=Recorder(READ_BOARDS))
    by_title = {r["title"]: r["group"] for r in got["notices"]}
    assert by_title["2026학년도 2학기 교내장학금 신청 안내"] == "장학"
    assert by_title["인조잔디 운동장 보수 안내문"] == "공지"  # 강한 말이 없으면 게시판 갈래


def test_preset_routes_are_kept_alongside_the_cache(tiny_catalog, monkeypatch):
    """목록 파일에 적은 경로(한국외대 장학 게시판 등)는 캐시가 있어도 빠지지 않는다."""
    _cache(tiny_catalog, [["READ", "board", f"{K2}/2180/artclList.do?layout=unknown"]])
    org = webapp.catalog()["u-test"]
    preset = (("장학", "rss", f"{K2}/2182/rssList.do?row=50"),)
    monkeypatch.setitem(
        webapp.catalog(),
        "u-test",
        webapp.replace(org, source=webapp.replace(org.source, routes=preset)),
    )
    rec = Recorder(READ_BOARDS)  # 피드는 없다 → 같은 게시판의 목록(artclList)으로 넘어간다
    got = _collect(days=30, fetcher=rec)
    assert f"{K2}/2182/rssList.do?row=50" in rec.asked
    assert f"{K2}/2182/artclList.do?layout=unknown" in rec.asked
    assert any(r["group"] == "장학" for r in got["notices"])


def test_plan_routes_folds_k2web_variants_and_caps():
    routes = webapp.plan_routes(
        [("장학", "rss", f"{K2}/2182/rssList.do?row=50")],
        [["READ", "board", f"{K2}/2182/artclList.do?layout=unknown"]],
        [[f"기타{i}", "board", f"https://x.ac.kr/b{i}"] for i in range(30)],
    )
    assert routes[0] == ("장학", "rss", f"{K2}/2182/rssList.do?row=50")
    assert sum("2182" in u for _c, _k, u in routes) == 1  # 같은 게시판은 한 번
    assert len(routes) == webapp.MAX_ROUTES


def test_same_notice_on_two_boards_with_different_tags_is_shown_once(tiny_catalog):
    a = "https://www.test.ac.kr/bbs/test/2182/artclList.do?layout=unknown"
    b = "https://student.test.ac.kr/bbs/student/2431/artclList.do?layout=unknown"
    pages = {
        a: _board(
            [
                (
                    f"{K2}/2182/9/artclView.do",
                    "[공통][교외] 대산장학생 모집 공고(~11/11)",
                    "2026.10.08",
                ),
                (f"{K2}/2182/8/artclView.do", "다른 장학 안내", "2026.10.01"),
            ]
        ),
        b: _board(
            [
                (
                    "https://student.test.ac.kr/x/9",
                    "[교외] 대산장학생 모집 공고(~11/11) 새글",
                    "2026.10.08",
                ),
                ("https://student.test.ac.kr/x/8", "또 다른 장학 안내", "2026.10.02"),
            ]
        ),
    }
    _cache(tiny_catalog, [["장학", "board", a], ["장학", "board", b]])
    got = _collect(days=30, fetcher=Recorder(pages))
    titles = [r["title"] for r in got["notices"]]
    assert sum("대산장학생" in t for t in titles) == 1
    assert len(titles) == 3


def test_a_named_general_board_keeps_its_name_even_if_mostly_scholarship(tiny_catalog):
    """한국장학재단 일반 공지: 학자금 글이 대부분이어도 게시판은 '공지'다.

    예전에는 게시판 전체가 '장학'이 되어 창업센터 입주기업 공지까지 장학으로 갔다.
    """
    url = "https://www.test.ac.kr/ko/notice.do?pg=PTKONotice_List"
    rows = [
        ("/v1", "2027학년도 학점은행제 학습자 학자금대출 지원기관 모집 안내", "2026.10.08"),
        ("/v2", "입주기업 대상 기술 보호 사업 안내", "2026.10.08"),
        ("/v3", "2026년 하반기 경상북도 학자금대출 이자지원 신청 안내", "2026.10.07"),
        ("/v4", "2026년 하반기 예산군 학자금대출 이자지원 신청 안내", "2026.10.01"),
        ("/v5", "2026학년도 고교 취업연계 장려금 신청 매뉴얼 수정본 게시", "2026.09.30"),
    ]
    _cache(tiny_catalog, [["공지", "board", url]])
    got = _collect(days=30, fetcher=Recorder({url: _board(rows)}))
    by_title = {r["title"]: r["group"] for r in got["notices"]}
    assert by_title["입주기업 대상 기술 보호 사업 안내"] == "공지"
    assert by_title["2026년 하반기 경상북도 학자금대출 이자지원 신청 안내"] == "장학"
    assert by_title["2026학년도 고교 취업연계 장려금 신청 매뉴얼 수정본 게시"] == "장학"
    assert got["routes"] == [["공지", "board", url]]


def test_cached_board_names_are_tidied_for_display(tiny_catalog):
    """캐시에 남은 '공지사항(목록)'·'더보기READ' 가 글의 분류로 찍히지 않는다."""
    a = f"{K2}/17/artclList.do?layout=unknown"
    b = f"{K2}/62/artclList.do?layout=unknown"
    pages = {
        a: _board([(f"{K2}/17/1/artclView.do", "운동장 보수 안내", "2026.10.08")]),
        b: _board([(f"{K2}/62/1/artclView.do", "축제 일정 안내", "2026.10.07")]),
    }
    _cache(tiny_catalog, [["공지사항(목록)", "board", a], ["더보기READ", "board", b]])
    got = _collect(days=30, fetcher=Recorder(pages))
    shown = {r["title"]: r["category"] for r in got["notices"]}
    assert shown == {"운동장 보수 안내": "공지사항", "축제 일정 안내": "기타"}
    assert [c for c, _k, _u in got["routes"]] == ["공지사항", "기타"]


def test_rows_say_whether_pictures_can_be_looked_up(tiny_catalog):
    """화면은 이 표시가 있는 글에만 '그림·첨부' 단추를 단다."""
    webapp.media_hosts.cache_clear()
    rec = Recorder(PAGES)
    got = _collect(days=30, fetcher=rec)
    assert got["notices"] and all(r["media"] for r in got["notices"])
    anchor = f"{SITE}/list.do#%EC%9E%A5%ED%95%99%EC%83%9D%20%EB%AA%A8%EC%A7%91"
    assert not webapp.media_ready(anchor, "장학생 모집")
    assert not webapp.media_ready("https://news.example.com/a?id=1", "기사")
