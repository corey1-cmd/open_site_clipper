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


def test_site_root_groups_subdomains():
    assert discover._site_root("www.hufs.ac.kr") == "hufs.ac.kr"
    assert discover._site_root("student.hufs.ac.kr") == "hufs.ac.kr"
    assert discover._site_root("grad.hufs.ac.kr") == "hufs.ac.kr"
    assert discover._site_root("news.example.com") == "example.com"
    assert discover._site_root("a.b.example.co.kr") == "example.co.kr"


def test_k2web_uses_link_host_not_start_host():
    """다른 서브도메인 게시판 링크는 그 서브도메인으로 좌표가 조립돼야 한다."""
    home = (
        "<html><head><title>대학</title></head><body>"
        '<a href="https://student.hufs.ac.kr/bbs/student/2431/artclList.do">장학 공지</a>'
        '<a href="/bbs/hufs/2180/artclList.do">본부 공지</a>'
        "</body></html>"
    )
    pages = {
        "https://www.hufs.ac.kr/": home.encode(),
        "https://student.hufs.ac.kr/bbs/student/2431/rssList.do?row=50": RSS,
        "https://www.hufs.ac.kr/bbs/hufs/2180/rssList.do?row=50": RSS,
    }
    res = discover.discover("https://www.hufs.ac.kr/", fetcher=pages.get, check_robots=False)
    by_host = {(e["host"], e["board_id"]) for e in res.entries if e["kind"] == "k2web"}
    # 학생 게시판은 student. 호스트로, 본부는 www 로 — 시작 host 로 뭉개지지 않는다.
    assert ("student.hufs.ac.kr", 2431) in by_host
    assert ("www.hufs.ac.kr", 2180) in by_host
    student = next(e for e in res.entries if e.get("board_id") == 2431)
    assert student["_verified"] is True  # 올바른 호스트라 RSS 검증도 통과


HUB = (
    "<html><head><title>한국외국어대학교</title></head><body>"
    '<a href="/bbs/hufs/2180/artclList.do">공지사항</a>'
    '<a href="https://student.hufs.ac.kr/main/index.do">학생지원</a>'
    '<a href="https://grad.hufs.ac.kr/main/index.do">대학원</a>'
    '<a href="https://other-univ.ac.kr/x">외부 대학</a>'
    "</body></html>"
)
STUDENT = (
    "<html><head><title>학생지원</title></head><body>"
    '<a href="/bbs/student/2431/artclList.do">장학 공지</a></body></html>'
)
GRAD = (
    "<html><head><title>대학원</title></head><body>"
    '<a href="/bbs/grad/500/artclList.do">모집 공지</a></body></html>'
)

ORG_PAGES = {
    "https://www.hufs.ac.kr/": HUB.encode(),
    "https://www.hufs.ac.kr/bbs/hufs/2180/rssList.do?row=50": RSS,
    "https://student.hufs.ac.kr/": STUDENT.encode(),
    "https://student.hufs.ac.kr/bbs/student/2431/rssList.do?row=50": RSS,
    "https://grad.hufs.ac.kr/": GRAD.encode(),
    "https://grad.hufs.ac.kr/bbs/grad/500/rssList.do?row=50": RSS,
}


def test_discover_org_walks_subdomains_and_merges():
    calls: list[str] = []

    def fx(u: str) -> bytes | None:
        calls.append(u)
        return ORG_PAGES.get(u)

    res = discover.discover_org("https://www.hufs.ac.kr/", fetcher=fx, check_robots=False)
    # 세 사이트를 훑고(본부·학생·대학원), 외부 대학은 뿌리가 달라 제외.
    assert set(res.sites) == {"www.hufs.ac.kr", "student.hufs.ac.kr", "grad.hufs.ac.kr"}
    hosts = {e["host"] for e in res.entries}
    assert hosts == {"www.hufs.ac.kr", "student.hufs.ac.kr", "grad.hufs.ac.kr"}
    assert all(not c.startswith("https://other-univ") for c in calls)
    # 병합 결과가 그대로 유효한 출처 파일이 된다.
    payload = json.loads(res.to_sources_json())
    assert len(sources.from_dicts(payload["sources"])) == 3
    assert any("여러 사이트를 훑었습니다" in c for c in payload["_comment"])


def test_discover_org_respects_max_sites():
    res = discover.discover_org(
        "https://www.hufs.ac.kr/", fetcher=ORG_PAGES.get, check_robots=False, max_sites=1
    )
    assert len(res.sites) == 1
    assert any("사이트 상한" in n for n in res.notes)


def test_discover_org_budget_cap():
    res = discover.discover_org(
        "https://www.hufs.ac.kr/", fetcher=ORG_PAGES.get, check_robots=False, budget=2
    )
    assert res.fetched <= 2
    assert any("예산" in n for n in res.notes)


def test_discover_org_bare_domain_seeds_www():
    """등록도메인만 줘도 www. 를 자동 시드해 대표 사이트에 도달한다."""
    res = discover.discover_org("hufs.ac.kr", fetcher=ORG_PAGES.get, check_robots=False)
    assert "www.hufs.ac.kr" in res.sites
    assert any(e["host"] == "www.hufs.ac.kr" for e in res.entries)
    pages = {"https://plain.example/": b"<html><title>x</title><body>no links</body></html>"}
    res = discover.discover("https://plain.example/", fetcher=pages.get, check_robots=False)
    assert res.entries == []
    assert any("지원 형식" in n for n in res.notes)
