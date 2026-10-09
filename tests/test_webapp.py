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
    assert sum(o.section == "정부" for o in orgs.values()) == 65
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
    rows = webapp.verify(["u-test", "nope"], days=30, fetcher=Recorder(PAGES))
    assert [r["id"] for r in rows] == ["u-test"]  # 모르는 id 는 조용히가 아니라 아예 받지 않는다
    assert rows[0]["count"] > 0 and rows[0]["routes"]
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
    rows = webapp.verify(["u-test"], stage="discover", fetcher=Recorder(PAGES))
    found = {u for _c, _k, u in rows[0]["found"]}
    assert f"{SITE}/bbs/notice/list.do" in found and "count" not in rows[0]
