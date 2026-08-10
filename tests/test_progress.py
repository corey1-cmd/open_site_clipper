"""수집 진행 표시 — 몇 분씩 걸리는 동안 무엇을 하는지 보여 준다."""

from __future__ import annotations

import http.client
import json
import re
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer

import pytest

from open_site_clipper import collect, progress, sources, webui

RSS = (
    '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
    "<item><title>공고 하나</title><link>https://x/1</link></item></channel></rss>"
).encode()


# ── 추적기 ─────────────────────────────────────────────────────────────────
def test_tracker_counts_and_eta():
    t = progress.Tracker(total=4)
    assert t.snapshot().eta == -1  # 아직 모른다 — 지어내지 않는다
    t.start("가기관")
    t.fetching("가기관", "https://a.go.kr/list.do")
    snap = t.snapshot()
    assert snap.active == (("가기관", "https://a.go.kr/list.do"),)
    assert snap.done == 0 and snap.percent == 0
    t.finish("가기관", 12)
    snap = t.snapshot()
    assert snap.done == 1 and snap.collected == 12 and snap.percent == 25
    assert snap.eta >= 0  # 하나 끝났으니 어림할 수 있다
    assert snap.active == () and snap.finished == (("가기관", 12),)


def test_tracker_is_thread_safe():
    t = progress.Tracker(total=50)

    def work(i: int) -> None:
        t.start(f"기관{i}")
        t.fetching(f"기관{i}", f"https://x{i}/")
        t.finish(f"기관{i}", 1)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(50)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    snap = t.snapshot()
    assert snap.done == 50 and snap.collected == 50 and snap.active == ()


def test_tracker_wrap_keeps_failure_reason():
    """진행 보고를 끼워도 실패 사유 전달 경로를 잃지 않는다."""

    class F:
        def __call__(self, url):
            return None

        def why(self, url):
            return "접근 거부(403)"

    wrapped = progress.Tracker(total=1).wrap("기관", F())
    assert wrapped.why("https://x/") == "접근 거부(403)"


def test_collect_reports_progress():
    srcs = [
        sources.Source(
            id=f"s{i}", name=f"기관{i}", kind="rss", url=f"https://x{i}/f.xml", org=f"기관{i}"
        )
        for i in range(4)
    ]
    t = progress.Tracker(total=len(srcs))
    collect.collect(srcs, fetcher=lambda _s: RSS, tracker=t, delay=0)
    snap = t.snapshot()
    assert snap.done == 4 and snap.collected == 4 and snap.percent == 100


# ── 웹 UI 왕복 ─────────────────────────────────────────────────────────────
@pytest.fixture()
def server(tmp_path):
    (tmp_path / "조직-테스트.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": f"t{i}",
                        "org": "테스트기관",
                        "name": "테스트기관",
                        "kind": "rss",
                        "url": f"https://t{i}.example/f.xml",
                    }
                    for i in range(3)
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webui._Handler)
    srv.workspace = tmp_path
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _req(srv, method, path, body=""):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    headers = {"Content-Type": "application/x-www-form-urlencoded"} if body else {}
    conn.request(method, path, body=body or None, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode()
    conn.close()
    return resp.status, data


def test_run_returns_progress_page_immediately(server):
    """수집이 끝나기를 기다리지 않고 진행 화면을 먼저 준다."""
    oid = urllib.parse.quote("기타::테스트기관")
    status, page = _req(server, "POST", "/run", f"org={oid}")
    assert status == 200
    assert "수집 중" in page and 'class="side"' in page  # 오른쪽 패널
    assert "지금 하는 일" in page and "남은 예상" in page


def test_progress_then_result(server):
    oid = urllib.parse.quote("기타::테스트기관")
    _s, page = _req(server, "POST", "/run", f"org={oid}")
    job = re.search(r'var id = "([a-f0-9]+)"', page).group(1)

    data = {}
    for _ in range(40):
        _s, body = _req(server, "GET", f"/progress?job={job}")
        data = json.loads(body)
        if data["ready"]:
            break
        time.sleep(0.1)
    assert data["ready"] and data["total"] == 3
    for key in ("done", "percent", "collected", "elapsed", "eta", "active", "finished"):
        assert key in data, key

    status, result = _req(server, "GET", f"/result?job={job}")
    assert status == 200 and "공지 보고서" in result


def test_unknown_job_is_handled(server):
    status, _ = _req(server, "GET", "/progress?job=deadbeef")
    assert status == 404
    status, _ = _req(server, "GET", "/result?job=deadbeef")
    assert status == 404
