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
    assert rss["name"] == "한국방송통신대학교 보도자료 RSS" and rss["_verified"] is True
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


# ── 피드 목록 페이지(S-A) — korea.kr·부처 '정보구독서비스' 공통 패턴 ──────────
# 실측 구조: 표 한 행에 (이름 | 피드 주소 | 주소복사 버튼). 앵커 텍스트가 전부
# "RSS복사"라서 이름은 같은 행의 링크 없는 첫 칸에서 가져와야 한다.
KOREA_INDEX = """<html><head><title>RSS 서비스 | 대한민국 정책브리핑</title></head><body>
<table><tbody>
<tr><td>국무조정실</td>
    <td><a href="https://www.korea.kr/rss/dept_opm.xml">https://www.korea.kr/rss/dept_opm.xml</a></td>
    <td><a href="#copy">RSS복사</a></td></tr>
<tr><td>산업통상부</td>
    <td><a href="https://www.korea.kr/rss/dept_motir.xml">https://www.korea.kr/rss/dept_motir.xml</a></td>
    <td><a href="#copy">RSS복사</a></td></tr>
<tr><td>고용노동부</td>
    <td><a href="https://www.korea.kr/rss/dept_moel.xml">https://www.korea.kr/rss/dept_moel.xml</a></td>
    <td><a href="#copy">RSS복사</a></td></tr>
</tbody></table></body></html>"""

# 문체부 '정보구독서비스' 실측 구조 — 이름이 'A > B > 공지' 형태이고 .jsp 피드다.
MCST_INDEX = """<html><head><title>서비스 안내 - 정보구독서비스 | 문화체육관광부</title></head><body>
<table><tbody>
<tr><td>알림·소식 &gt; 알림 &gt; 공지</td>
    <td><a href="https://www.mcst.go.kr/common/rss/notice.jsp">주소</a></td>
    <td><a href="http://www.mcst.go.kr/common/rss/notice.jsp">주소복사</a></td></tr>
<tr><td>알림·소식 &gt; 알림 &gt; 인사</td>
    <td><a href="https://www.mcst.go.kr/common/rss/noticePerson.jsp">주소</a></td>
    <td><a href="#">주소복사</a></td></tr>
<tr><td>알림·소식 &gt; 보도·뉴스 &gt; 보도자료</td>
    <td><a href="https://www.mcst.go.kr/common/rss/press.jsp">주소</a></td>
    <td><a href="#">주소복사</a></td></tr>
</tbody></table></body></html>"""

REAL_RSS = (
    b'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
    b"<title>x</title><item><title>a</title></item></channel></rss>"
)


def test_feed_index_page_yields_each_department():
    """korea.kr RSS 목록 한 장에서 부처 피드를 전부 캐낸다(하드코딩 없이)."""
    pages = {"https://www.korea.kr/etc/rss.do": KOREA_INDEX.encode()}

    def fx(u: str) -> bytes | None:
        return pages.get(u) or (REAL_RSS if u.endswith(".xml") else None)

    res = discover.discover("https://www.korea.kr/etc/rss.do", fetcher=fx, check_robots=False)
    urls = {e["url"] for e in res.entries}
    assert urls == {
        "https://www.korea.kr/rss/dept_opm.xml",
        "https://www.korea.kr/rss/dept_motir.xml",
        "https://www.korea.kr/rss/dept_moel.xml",
    }
    # 이름은 앵커('RSS복사')가 아니라 같은 행 첫 칸(기관명)에서 온다.
    names = {e["category"] for e in res.entries}
    assert names == {"국무조정실", "산업통상부", "고용노동부"}
    assert all(e["_verified"] for e in res.entries)
    assert all("피드 목록 표" in e["_evidence"] for e in res.entries)
    # 초안이 그대로 유효한 출처 파일이 된다.
    payload = json.loads(res.to_sources_json())
    assert len(sources.from_dicts(payload["sources"])) == 3


def test_ministry_subscription_page_yields_notice_and_hr():
    """부처 '정보구독서비스' 페이지에서 공지·인사·보도자료를 캐낸다(같은 코드)."""
    pages = {"https://www.mcst.go.kr/site/s_etc/rss/rssService.jsp": MCST_INDEX.encode()}

    def fx(u: str) -> bytes | None:
        return pages.get(u) or (REAL_RSS if u.endswith(".jsp") else None)

    res = discover.discover(
        "https://www.mcst.go.kr/site/s_etc/rss/rssService.jsp", fetcher=fx, check_robots=False
    )
    cats = {e["category"] for e in res.entries}
    assert cats == {"공지", "인사", "보도자료"}  # 'A > B > 공지' 에서 마지막 조각만
    assert any(e["url"].endswith("/common/rss/notice.jsp") for e in res.entries)
    assert all(e["_verified"] for e in res.entries)


def test_guess_paths_skipped_when_index_found():
    """인덱스에서 후보를 찾았으면 관용 경로 추측은 아예 하지 않는다."""
    calls: list[str] = []

    def fx(u: str) -> bytes | None:
        calls.append(u)
        if u == "https://www.korea.kr/etc/rss.do":
            return KOREA_INDEX.encode()
        return REAL_RSS if u.endswith(".xml") else None

    discover.discover("https://www.korea.kr/etc/rss.do", fetcher=fx, check_robots=False)
    assert not any(c.endswith(("/rss", "/feed", "/index.xml", "/feed.xml")) for c in calls)


def test_is_feed_rejects_html_page_mentioning_rss():
    """S-C: 루트 태그만 흉내낸 응답을 피드로 오인하지 않는다."""
    assert discover._is_feed(REAL_RSS) is True
    # 본문 요소(item·entry·channel)가 없으면 거부.
    assert discover._is_feed(b"<rss>\xed\x95\x9c\xea\xb8\x80</rss>") is False
    assert discover._is_feed(b"<html><body>RSS feed guide</body></html>") is False
    assert discover._is_feed(None) is False
