"""로컬 웹 UI — 조직 스캔, 경로 주입 방지, 파이프라인, HTTP 왕복(전부 오프라인)."""

from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from open_site_clipper import discover, webui
from open_site_clipper.sources import Source

RSS = (
    '<?xml version="1.0"?><rss><channel>'
    "<item><title>장학금 신청 안내</title><link>https://u.ac.kr/bbs/u/1/9/artclView.do</link>"
    "<description>2학기 국가장학금 신청 발췌</description></item>"
    "<item><title>회계 감사 결과</title><link>https://u.ac.kr/bbs/u/1/8/artclView.do</link></item>"
    "</channel></rss>"
)

ORG_JSON = {
    "sources": [
        {
            "id": "u-1",
            "org": "테스트대학교",
            "site": "본부",
            "name": "테스트대학교 본부",
            "kind": "rss",
            "url": "https://u.ac.kr/bbs/u/1/rssList.do",
        }
    ]
}


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "조직-테스트대학교.json").write_text(
        json.dumps(ORG_JSON, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "깨진.json").write_text("{잘못된", encoding="utf-8")
    (tmp_path / "무관.json").write_text('{"hello": 1}', encoding="utf-8")
    return tmp_path


def test_org_options_scans_valid_sources_only(ws):
    opts = webui.org_options(ws)
    assert opts[0].id == webui.GOV_ID and opts[0].count >= 5
    labels = {o.label for o in opts}
    assert "테스트대학교" in labels  # org 필드가 라벨이 된다
    assert all("깨진" not in o.id and "무관" not in o.id for o in opts)


def test_build_sources_merges_and_rejects_unknown(ws):
    merged = webui.build_sources([webui.GOV_ID, "조직-테스트대학교.json"], ws)
    assert any(s.org == "테스트대학교" for s in merged)
    assert len(merged) > 1
    with pytest.raises(ValueError, match="알 수 없는 조직"):
        webui.build_sources(["../../etc/passwd"], ws)


def _fx(_s: Source) -> bytes:
    return RSS.encode()


def test_run_report_normal_and_query_modes(ws):
    html = webui.run_report(
        ["조직-테스트대학교.json"], workspace=ws, group_org=True, quote_full=True, fetcher=_fx
    )
    assert "테스트대학교" in html and "본부" in html
    # 검색어를 주면 브리프로 — 관련 항목만 선별되고, 발췌는 quote_full 로 유지.
    bhtml = webui.run_report(
        ["조직-테스트대학교.json"], workspace=ws, query="장학", quote_full=True, fetcher=_fx
    )
    assert "장학 브리프" in bhtml and "회계 감사" not in bhtml
    assert "국가장학금 신청 발췌" in bhtml  # 일반 표에는 발췌 칸이 없어 브리프에서 검증


def test_run_report_marks_new_with_state(ws):
    webui.run_report(["조직-테스트대학교.json"], workspace=ws, mark_new=True, fetcher=_fx)
    assert (ws / webui.STATE_FILE).exists()
    html2 = webui.run_report(["조직-테스트대학교.json"], workspace=ws, mark_new=True, fetcher=_fx)
    assert "NEW" not in html2  # 두 번째 실행, 새 글 없음


@pytest.fixture()
def server(ws):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webui._Handler)
    srv.workspace = ws
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _request(srv, method, path, body=""):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    headers = {"Content-Type": "application/x-www-form-urlencoded"} if body else {}
    conn.request(method, path, body=body or None, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode()
    conn.close()
    return resp.status, data


def test_http_form_page_lists_orgs(server):
    status, page = _request(server, "GET", "/")
    assert status == 200
    assert "정부·공공기관 (내장 기본)" in page and "테스트대학교" in page
    assert "127.0.0.1 전용" in page  # 로컬 전용 고지


def test_http_run_without_org_is_friendly_400(server):
    status, page = _request(server, "POST", "/run", body="query=")
    assert status == 400 and "조직을 하나 이상" in page


def test_http_discover_saves_and_offers_run(server, ws, monkeypatch):
    fake = discover.Discovery(
        start_url="https://t.ac.kr",
        org="테스트대",
        entries=[
            {
                "id": "t-1",
                "org": "테스트대",
                "name": "테스트대 공지",
                "kind": "k2web",
                "host": "t.ac.kr",
                "site_id": "t",
                "board_id": 1,
                "category": "공지",
                "_verified": True,
                "_evidence": "테스트",
            }
        ],
        notes=["예시 메모"],
        fetched=3,
    )
    monkeypatch.setattr(discover, "discover", lambda url, **k: fake)
    status, page = _request(server, "POST", "/discover", body="url=https%3A%2F%2Ft.ac.kr")
    assert status == 200
    assert "탐지 결과 — 테스트대" in page and "✔ 검증" in page
    assert "이 조직으로 바로 보고서" in page
    saved = ws / "조직-테스트대.json"
    assert saved.exists()
    # 저장된 초안이 조직 목록에 자동 편입된다.
    assert any(o.id == "조직-테스트대.json" for o in webui.org_options(ws))


def test_http_404_and_favicon(server):
    status, _ = _request(server, "GET", "/no-such-page")
    assert status == 404
    status, _ = _request(server, "GET", "/favicon.ico")
    assert status == 204
