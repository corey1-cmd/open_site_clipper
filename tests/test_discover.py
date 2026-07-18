"""--discover 출처 자동 탐지 — RSS 자동발견, K2Web 좌표, 예산·robots, 라운드트립."""

from __future__ import annotations

import json

from open_site_clipper import discover, robots, sources

HOME = """<!DOCTYPE html><html><head>
<title>한국방송통신대학교 | 대표홈</title>
<meta name="generator" content="K2Web Wizard">
<link rel="alternate" type="application/rss+xml" title="보도자료 RSS" href="/bbs/knou/90/rssList.do?row=50">
</head><body>
<a href="/knou/57/subview.do">공지사항</a>
<a href="/knou/58/subview.do">오시는 길</a>
<a href="/knou/57/subview.do">공지사항(중복)</a>
<a href="/bbs/knou/60/artclList.do">입찰 공고</a>
<a href="https://other.example/x">외부</a>
</body></html>"""

SUBVIEW = """<html><body>
<a href="/bbs/knou/57/rssList.do?row=50">RSS 2.0</a>
<table><tr><td><a href="/bbs/knou/57/1/artclView.do">글</a></td></tr></table>
</body></html>"""

RSS = b'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel></channel></rss>'

PAGES = {
    "https://www.knou.ac.kr/knou/index.do": HOME.encode(),
    "https://www.knou.ac.kr/knou/57/subview.do": SUBVIEW.encode(),
    "https://www.knou.ac.kr/bbs/knou/57/rssList.do?row=50": RSS,
    "https://www.knou.ac.kr/bbs/knou/60/rssList.do?row=50": RSS,
    "https://www.knou.ac.kr/bbs/knou/90/rssList.do?row=50": RSS,
}


def _fx(url: str) -> bytes | None:
    return PAGES.get(url)


def test_discovers_k2web_and_rss_with_verification():
    res = discover.discover("https://www.knou.ac.kr/knou/index.do", fetcher=_fx, check_robots=False)
    assert res.org == "한국방송통신대학교"  # <title> 꼬리('| 대표홈') 제거
    kinds = {(e["kind"], e.get("board_id"), e.get("url")) for e in res.entries}
    # ① 직접 노출 좌표(60), ② 메뉴 따라가 캔 좌표(57, menu_no 바인딩), ③ rel RSS.
    assert ("k2web", 60, None) in kinds and ("k2web", 57, None) in kinds
    board57 = next(e for e in res.entries if e.get("board_id") == 57)
    assert board57["menu_no"] == 57 and "메뉴 '공지사항'" in board57["_evidence"]
    assert board57["category"] == "공지사항" and board57["_verified"] is True
    rss = next(e for e in res.entries if e["kind"] == "rss")
    assert rss["url"].endswith("/bbs/knou/90/rssList.do?row=50")
    assert rss["name"] == "보도자료 RSS" and rss["_verified"] is True
    # '오시는 길' 메뉴는 게시판 문구가 아니라 따라가지 않고, 중복 메뉴는 1회만.
    assert res.fetched == 1 + 1 + 3  # 시작 + subview(57) + rss 검증 3회
    assert res.verified_count == 3


def test_roundtrip_draft_is_valid_sources_file():
    res = discover.discover("https://www.knou.ac.kr/knou/index.do", fetcher=_fx, check_robots=False)
    payload = json.loads(res.to_sources_json())
    assert any("사람 검토" in c for c in payload["_comment"])
    parsed = sources.from_dicts(payload["sources"])  # '_' 필드는 무시되고 파싱된다
    assert len(parsed) == len(res.entries)
    k2 = next(s for s in parsed if s.kind == "k2web" and s.board_id == 57)
    assert k2.host == "www.knou.ac.kr" and k2.site_id == "knou" and k2.menu_no == 57


def test_budget_caps_total_requests():
    calls: list[str] = []

    def fx(url: str) -> bytes | None:
        calls.append(url)
        return PAGES.get(url)

    res = discover.discover(
        "https://www.knou.ac.kr/knou/index.do", fetcher=fx, check_robots=False, budget=2
    )
    assert len(calls) == 2 and res.fetched == 2
    assert any("예산" in n for n in res.notes)
    # 예산 부족으로 검증 못 한 항목은 버리지 않고 미검증으로 남긴다.
    assert any(e["_verified"] is False for e in res.entries)


def test_robots_block_on_start_page(monkeypatch):
    monkeypatch.setattr(robots, "allowed", lambda url, **k: False)
    res = discover.discover("https://www.knou.ac.kr/knou/index.do", fetcher=_fx)
    assert res.entries == [] and any("robots.txt 차단" in n for n in res.notes)


def test_guess_paths_when_no_rel_and_not_k2web():
    pages = {
        "https://blog.example/": "<html><head><title>블로그</title></head><body></body></html>".encode(),
        "https://blog.example/rss": RSS,
    }
    res = discover.discover("https://blog.example/", fetcher=pages.get, check_robots=False)
    (e,) = res.entries
    assert e["kind"] == "rss" and e["url"] == "https://blog.example/rss"
    assert "관용 경로 추측" in e["_evidence"] and e["_verified"] is True


def test_nothing_found_leaves_honest_note():
    pages = {"https://plain.example/": b"<html><title>x</title><body>no links</body></html>"}
    res = discover.discover("https://plain.example/", fetcher=pages.get, check_robots=False)
    assert res.entries == []
    assert any("지원 형식" in n for n in res.notes)
