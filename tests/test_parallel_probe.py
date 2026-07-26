"""구조 테스트(probe)와 병렬 실행(parallel) — 수집 기준과 예의를 함께 검증한다."""

from __future__ import annotations

import threading
import time

import pytest

from open_site_clipper import parallel, probe, robots

# 날짜가 붙은 진짜 목록
BOARD = """<table><thead><tr><th>번호</th><th>제목</th><th>등록일</th></tr></thead><tbody>
<tr><td>3</td><td><a href="/view.do?id=3">세 번째</a></td><td>2026.07.20.</td></tr>
<tr><td>2</td><td><a href="/view.do?id=2">두 번째</a></td><td>2026.07.19.</td></tr>
<tr><td>1</td><td><a href="/view.do?id=1">첫 번째</a></td><td>2026.07.18.</td></tr>
</tbody></table>""".encode()

# 설명문 한 장 — 가져올 '글'이 없다
STATIC = "<html><body><h1>일반현황</h1><p>교육부는…</p></body></html>".encode()

# 링크 모음 — 행은 많은데 날짜가 없다
INDEX = """<table><tbody>
<tr><td><a href="/a.do">영유아 교육·보육</a></td><td><a href="/b.do">초·중·고 교육</a></td></tr>
<tr><td><a href="/c.do">대학(원)교육</a></td><td><a href="/d.do">평생교육</a></td></tr>
<tr><td><a href="/e.do">지역대학육성</a></td><td><a href="/f.do">유보통합</a></td></tr>
</tbody></table>""".encode()

HOME = "www.moe.go.kr"


# ── 구조 테스트(P-1) ─────────────────────────────────────────────────────────
def test_dated_list_is_collectible():
    r = probe.classify(BOARD, "https://www.moe.go.kr/notice/list.do", home_host=HOME)
    assert r.verdict == probe.LIST and r.collectible
    assert r.rows == 3 and r.dated == 3 and r.reason == ""


def test_static_page_is_not_collectible():
    """이름이 '정보공개'여도 목록이 아니면 안 가져온다 — 이름이 아니라 모양."""
    r = probe.classify(STATIC, "https://www.moe.go.kr/info/open.do", home_host=HOME)
    assert r.verdict == probe.STATIC and not r.collectible
    assert "안내 페이지" in r.reason


def test_link_index_is_not_a_list():
    """행은 많은데 날짜가 없으면 목록이 아니라 링크 모음(정책 메뉴 등)."""
    r = probe.classify(INDEX, "https://www.moe.go.kr/policy/", home_host=HOME)
    assert r.verdict == probe.INDEX and not r.collectible
    assert r.rows >= 3 and r.dated == 0


def test_external_domains_are_skipped_not_fetched():
    """법령·공공데이터·국민신문고는 기관 밖 — 건너뛰고 기록만."""
    for url in (
        "https://www.law.go.kr/법령/초중등교육법",
        "https://www.data.go.kr/data/1234",
        "https://www.epeople.go.kr/index.jsp",
        "https://www.open.go.kr/",
    ):
        r = probe.classify(BOARD, url, home_host=HOME)
        assert r.verdict == probe.EXTERNAL, url
        assert "별도 출처" in r.reason


def test_subdomains_count_as_same_org():
    assert not probe.is_external("https://moe.go.kr/x", "www.moe.go.kr")
    assert not probe.is_external("https://sub.moe.go.kr/x", "www.moe.go.kr")
    assert probe.is_external("https://www.mcst.go.kr/x", "www.moe.go.kr")
    assert probe.is_external("notaurl", "www.moe.go.kr")


def test_missing_page_is_static():
    assert probe.classify(None, "https://www.moe.go.kr/x", home_host=HOME).verdict == probe.STATIC


# ── 병렬 실행(P-3) ───────────────────────────────────────────────────────────
def test_run_parallel_preserves_input_order():
    """보고서가 실행할 때마다 달라지면 안 된다 — 순서를 보존한다."""
    items = list(range(20))
    out = parallel.run_parallel(items, lambda i: i * 2, jobs=8)
    assert out == [i * 2 for i in items]


def test_one_failure_does_not_stop_the_rest():
    def work(i: int) -> str:
        if i == 3:
            raise RuntimeError("서버 오류")
        return f"ok{i}"

    out = parallel.run_parallel(list(range(6)), work, jobs=4, on_error=lambda i, e: f"실패{i}:{e}")
    assert out[3].startswith("실패3:") and out[0] == "ok0" and out[5] == "ok5"


def test_jobs_capped_and_empty_input():
    assert parallel.run_parallel([], lambda x: x) == []
    # jobs 를 아무리 크게 줘도 상한을 넘지 않는다.
    out = parallel.run_parallel([1, 2], lambda x: x, jobs=999)
    assert out == [1, 2]


def test_host_limiter_spaces_requests_to_same_host():
    """같은 서버로 가는 요청은 간격을 지킨다."""
    lim = parallel.HostLimiter(0.05, use_robots=False)
    stamps: list[float] = []
    for _ in range(3):
        lim.wait("https://a.example/page")
        stamps.append(time.monotonic())
    gaps = [stamps[i + 1] - stamps[i] for i in range(2)]
    assert all(g >= 0.04 for g in gaps), gaps


def test_host_limiter_does_not_block_other_hosts():
    """다른 서버는 서로 기다리지 않는다 — 병렬의 이점이 여기서 나온다."""
    lim = parallel.HostLimiter(0.2, use_robots=False)
    start = time.monotonic()

    def hit(host: str) -> None:
        lim.wait(f"https://{host}/x")

    threads = [threading.Thread(target=hit, args=(f"h{i}.example",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert time.monotonic() - start < 0.2  # 서로 기다렸다면 1.6초가 걸린다


def test_crawl_delay_from_robots_takes_priority(monkeypatch):
    """사이트가 robots.txt 에 적어 둔 간격을 우선한다."""
    monkeypatch.setattr(robots, "stated_delay", lambda url, **k: 3.0)
    lim = parallel.HostLimiter(1.0)
    assert lim.delay_for("https://slow.example/x") == 3.0
    # 지정이 없으면 기본값.
    monkeypatch.setattr(robots, "stated_delay", lambda url, **k: None)
    lim2 = parallel.HostLimiter(1.0)
    assert lim2.delay_for("https://plain.example/x") == 1.0


def test_absurd_crawl_delay_is_capped(monkeypatch):
    """터무니없이 긴 지연은 상한을 둔다 — 수집이 사실상 멈추지 않게."""
    monkeypatch.setattr(robots, "stated_delay", lambda url, **k: 3600.0)
    lim = parallel.HostLimiter(1.0)
    assert lim.delay_for("https://x.example/y") == parallel.MAX_HONORED_DELAY


def test_stated_delay_reads_crawl_delay_and_request_rate(monkeypatch):
    from urllib.robotparser import RobotFileParser

    def fake(url):
        p = RobotFileParser()
        p.parse(["User-agent: *", "Crawl-delay: 2", "Request-rate: 1/10"])
        return p

    monkeypatch.setattr(robots, "_parser_for", fake)
    # 둘 다 있으면 더 여유 있는(긴) 쪽 — 상대가 요구한 최소 간격을 지켜야 하므로.
    assert robots.stated_delay("https://x.example/") == pytest.approx(10.0)


def test_limiter_wraps_fetcher():
    lim = parallel.HostLimiter(0.01, use_robots=False)
    calls: list[str] = []
    wrapped = lim.wrap(lambda u: calls.append(u) or b"ok")
    assert wrapped("https://a.example/1") == b"ok"
    assert calls == ["https://a.example/1"]
