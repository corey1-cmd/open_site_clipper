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


UNIV = "대학::테스트대학교"


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "조직-테스트대학교.json").write_text(
        json.dumps(ORG_JSON, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "깨진.json").write_text("{잘못된", encoding="utf-8")
    (tmp_path / "무관.json").write_text('{"hello": 1}', encoding="utf-8")
    return tmp_path


def test_org_options_are_per_institution(ws):
    """선택지는 파일이 아니라 **기관** 단위다."""
    opts = webui.org_options(ws)
    labels = {o.label for o in opts}
    assert "테스트대학교" in labels  # org 필드가 라벨이 된다
    assert all("깨진" not in o.label and "무관" not in o.label for o in opts)
    # 내장 정부 출처도 기관별로 풀려 들어온다.
    assert any(o.group == webui.GROUP_GOV for o in opts)
    univ = next(o for o in opts if o.label == "테스트대학교")
    assert univ.id == f"{webui.GROUP_UNIV}::테스트대학교" and univ.count == 1


def test_groups_are_ordered_and_labeled(ws):
    groups = webui.grouped_options(ws)
    names = [g for g, _ in groups]
    assert names[0] == webui.GROUP_GOV  # 정부가 먼저
    assert webui.GROUP_UNIV in names
    # 같은 기관이 여러 파일에 있어도 한 줄로 합쳐진다.
    all_labels = [o.label for _g, items in groups for o in items]
    assert len(all_labels) == len(set(all_labels))


def test_build_sources_merges_and_rejects_unknown(ws):
    univ_id = f"{webui.GROUP_UNIV}::테스트대학교"
    gov_id = next(o.id for o in webui.org_options(ws) if o.group == webui.GROUP_GOV)
    merged = webui.build_sources([gov_id, univ_id], ws)
    assert any(s.org == "테스트대학교" for s in merged)
    assert len(merged) > 1
    with pytest.raises(ValueError, match="알 수 없는 조직"):
        webui.build_sources(["../../etc/passwd"], ws)


def test_build_sources_dedupes_same_source_across_files(ws, tmp_path):
    """같은 기관이 두 파일에 있어도 출처가 중복되지 않는다."""
    (ws / "사본.json").write_text(json.dumps(ORG_JSON, ensure_ascii=False), encoding="utf-8")
    merged = webui.build_sources([f"{webui.GROUP_UNIV}::테스트대학교"], ws)
    assert len(merged) == 1  # 두 파일에 있지만 같은 출처 → 1건


def _fx(_s: Source) -> bytes:
    return RSS.encode()


def test_run_report_normal_and_query_modes(ws):
    html = webui.run_report([UNIV], workspace=ws, group_org=True, quote_full=True, fetcher=_fx)
    assert "테스트대학교" in html and "본부" in html
    # 검색어를 주면 브리프로 — 관련 항목만 선별되고, 발췌는 quote_full 로 유지.
    bhtml = webui.run_report([UNIV], workspace=ws, query="장학", quote_full=True, fetcher=_fx)
    assert "장학 브리프" in bhtml and "회계 감사" not in bhtml
    assert "국가장학금 신청 발췌" in bhtml  # 일반 표에는 발췌 칸이 없어 브리프에서 검증


def test_run_report_marks_new_with_state(ws):
    webui.run_report([UNIV], workspace=ws, mark_new=True, fetcher=_fx)
    assert (ws / webui.STATE_FILE).exists()
    html2 = webui.run_report([UNIV], workspace=ws, mark_new=True, fetcher=_fx)
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


def test_http_form_page_lists_grouped_orgs(server):
    status, page = _request(server, "GET", "/")
    assert status == 200
    assert "정부·공공기관" in page and "테스트대학교" in page
    assert "모두 선택" in page and "모두 해제" in page  # 일괄 체크/해제
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
    assert any(o.label == "테스트대" for o in webui.org_options(ws))


def test_http_404_and_favicon(server):
    status, _ = _request(server, "GET", "/no-such-page")
    assert status == 404
    status, _ = _request(server, "GET", "/favicon.ico")
    assert status == 204


def test_form_has_bulk_toggle_and_no_duplicate_orgs(ws):
    html = webui.form_page(ws).decode()
    # 그룹마다 모두 선택/해제 버튼
    assert html.count("모두 선택") == len(webui.grouped_options(ws))
    assert "oscPick" in html  # 일괄 토글 스크립트
    # 기관은 한 번씩만 나온다(정부가 세 덩어리로 쪼개져 보이던 문제)
    import re

    ids = re.findall(r'name="org" value="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    # 기본 체크는 없다 — 사용자가 고른 것만 돈다
    assert " checked>" not in html and 'checked="checked"' not in html


def test_discover_button_passes_valid_org_id(ws):
    from open_site_clipper import discover as _d

    res = _d.Discovery(
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
                "_evidence": "x",
            }
        ],
    )
    (ws / "조직-테스트대.json").write_text(res.to_sources_json(), encoding="utf-8")
    page = webui.discover_page(res, "조직-테스트대.json", ws).decode()
    import re

    m = re.search(r'name="org" value="([^"]+)"', page)
    assert m and webui.build_sources([m.group(1)], ws)  # 그 id 로 실제 수집 가능
