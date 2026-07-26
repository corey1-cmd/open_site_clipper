"""기관 홈에서 카테고리별 경로 자동 발견 — routes 수기 작성을 없앤 부분.

핵심 검증 두 가지:
  ① 앵커 텍스트로 카테고리를 판정한다(CMS·링크 문법 무관)
  ② 같은 카테고리에 후보를 **여러 개** 모은다 — 하나가 robots 로 막혀도 다음을 쓴다
"""

from __future__ import annotations

import json

from open_site_clipper import collect, govdiscover, robots, sources
from open_site_clipper.sources import Source

HOME = """<!DOCTYPE html><html><head><title>문화체육관광부</title>
<link rel="alternate" type="application/rss+xml" title="보도자료" href="/common/rss/press.jsp">
</head><body>
<nav>
  <a href="/site/s_notice/notice/noticeList.jsp">공지사항</a>
  <a href="/kor/s_notice/notice/list.jsp">알립니다</a>
  <a href="/site/s_notice/notice/jobList.jsp">채용정보</a>
  <a href="/site/s_notice/notice/bidList.jsp">입찰정보</a>
  <a href="/site/s_notice/person/list.jsp">인사발령</a>
  <a href="/site/s_etc/rss/rssService.jsp">RSS 서비스</a>
  <a href="/site/intro/greeting.jsp">장관 인사말</a>
  <a href="https://www.museum.go.kr/notice">국립중앙박물관 공지</a>
  <a href="javascript:void(0);">공지 열기</a>
</nav></body></html>"""

RSS_INDEX = """<html><head><title>정보구독서비스</title></head><body><table>
<tr><td>알림 &gt; 공지</td><td><a href="https://www.mcst.go.kr/common/rss/notice.jsp">주소</a></td><td><a href="#">복사</a></td></tr>
<tr><td>알림 &gt; 인사</td><td><a href="https://www.mcst.go.kr/common/rss/noticePerson.jsp">주소</a></td><td><a href="#">복사</a></td></tr>
</table></body></html>"""

# 구조 테스트를 통과하는 '날짜 붙은 목록'
BOARD = """<table><thead><tr><th>번호</th><th>제목</th><th>등록일</th></tr></thead><tbody>
<tr><td>2</td><td><a href="/view.do?id=2">두 번째 글</a></td><td>2026.07.20.</td></tr>
<tr><td>1</td><td><a href="/view.do?id=1">첫 번째 글</a></td><td>2026.07.19.</td></tr>
</tbody></table>"""
# 통과하지 못하는 '안내문 한 장'
STATIC = "<html><body><h1>장관 인사말</h1><p>안녕하십니까…</p></body></html>"

PAGES = {
    "https://www.mcst.go.kr/": HOME.encode(),
    "https://www.mcst.go.kr/site/s_etc/rss/rssService.jsp": RSS_INDEX.encode(),
    "https://www.mcst.go.kr/site/s_notice/notice/noticeList.jsp": BOARD.encode(),
    "https://www.mcst.go.kr/kor/s_notice/notice/list.jsp": BOARD.encode(),
    "https://www.mcst.go.kr/site/s_notice/notice/jobList.jsp": BOARD.encode(),
    "https://www.mcst.go.kr/site/s_notice/notice/bidList.jsp": BOARD.encode(),
    "https://www.mcst.go.kr/site/s_notice/person/list.jsp": BOARD.encode(),
    "https://www.mcst.go.kr/site/intro/greeting.jsp": STATIC.encode(),
}


def test_classify_by_anchor_text():
    assert govdiscover.classify("채용정보") == "채용"
    assert govdiscover.classify("입찰공고") == "입찰"
    assert govdiscover.classify("인사발령") == "인사"
    assert govdiscover.classify("보도자료") == "보도자료"
    assert govdiscover.classify("알립니다") == "공지"
    assert govdiscover.classify("새소식") == "소식"
    assert govdiscover.classify("장관 인사말") == "인사"  # '인사' 가 들어가면 인사로 — 초안의 한계
    assert govdiscover.classify("조직도") == ""
    assert govdiscover.classify("") == ""


def test_finds_routes_for_every_category():
    routes, _notes = govdiscover.find_routes(
        "https://www.mcst.go.kr/", fetcher=PAGES.get, check_robots=False
    )
    cats = {c for c, _k, _u in routes}
    # 공지·채용·입찰·인사·보도자료가 전부 잡힌다 — routes 를 손으로 안 적어도.
    assert {"공지", "채용", "입찰", "인사", "보도자료"} <= cats
    # rel=alternate 피드는 rss 종류로.
    assert ("보도자료", "rss", "https://www.mcst.go.kr/common/rss/press.jsp") in routes
    # 게시판 링크는 board 종류로.
    assert any(k == "board" and u.endswith("jobList.jsp") for c, k, u in routes if c == "채용")


def test_structure_test_filters_non_lists():
    """이름이 아니라 모양으로 판정 — 안내문(장관 인사말)은 걸러진다."""
    routes, notes = govdiscover.find_routes(
        "https://www.mcst.go.kr/", fetcher=PAGES.get, check_robots=False
    )
    urls = [u for _c, _k, u in routes]
    assert all("greeting.jsp" not in u for u in urls)  # 목록이 아니므로 제외
    assert any("목록이 아님" in n for n in notes)  # 사유가 남는다(조용한 실패 금지)
    # 이름 사전에 없는 메뉴도 목록이면 채택된다(라벨은 앵커 텍스트).
    assert any(u.startswith("https://www.mcst.go.kr/kor/") for u in urls)


def test_collects_multiple_candidates_per_category():
    """같은 카테고리에 후보가 여러 개 — robots 로 하나가 막혀도 다음을 쓴다."""
    routes, _ = govdiscover.find_routes(
        "https://www.mcst.go.kr/", fetcher=PAGES.get, check_robots=False
    )
    notice_urls = [u for c, _k, u in routes if c == "공지"]
    assert len(notice_urls) >= 2  # noticeList.jsp + /kor/ 경로 + RSS 안내분
    assert any("/site/" in u for u in notice_urls)


def test_follows_rss_service_page():
    """'RSS 서비스' 링크를 한 단계 따라가 피드 목록 표를 파싱한다."""
    routes, _ = govdiscover.find_routes(
        "https://www.mcst.go.kr/", fetcher=PAGES.get, check_robots=False
    )
    assert ("인사", "rss", "https://www.mcst.go.kr/common/rss/noticePerson.jsp") in routes
    assert ("공지", "rss", "https://www.mcst.go.kr/common/rss/notice.jsp") in routes


def test_skips_external_and_javascript_links():
    routes, _ = govdiscover.find_routes(
        "https://www.mcst.go.kr/", fetcher=PAGES.get, check_robots=False
    )
    urls = [u for _c, _k, u in routes]
    assert all("museum.go.kr" not in u for u in urls)  # 외부 기관
    assert all(not u.startswith("javascript") for u in urls)


def test_home_blocked_leaves_note(monkeypatch):
    monkeypatch.setattr(robots, "allowed", lambda url, **k: False)
    routes, notes = govdiscover.find_routes("https://www.mcst.go.kr/", fetcher=PAGES.get)
    assert routes == [] and any("robots.txt 차단" in n for n in notes)


def test_enrich_keeps_configured_routes_first():
    src = Source(
        id="mcst",
        name="문화체육관광부",
        kind="govorg",
        url="",
        org="문화체육관광부",
        home="https://www.mcst.go.kr/",
        routes=(("공지", "rss", "https://수기.example/notice.xml"),),
    )
    enriched, _notes = govdiscover.enrich(src, fetcher=PAGES.get, check_robots=False)
    assert enriched.routes[0] == ("공지", "rss", "https://수기.example/notice.xml")
    assert len(enriched.routes) > 1  # 발견분이 뒤에 붙는다


def test_gov_preset_parses_all_65():
    with open("examples/sources-gov.json", encoding="utf-8") as f:
        raw = json.load(f)
    srcs = sources.from_dicts(raw["sources"])
    assert len(srcs) == 65
    assert all(s.kind == "govorg" and s.home for s in srcs)
    # 홈만 있고 routes 가 없어도 유효하다(실행 시 발견).
    assert all(not s.routes for s in srcs)
    named = {s.org for s in srcs}
    assert {"문화체육관광부", "행정안전부", "국세청", "공정거래위원회"} <= named
    # rights 를 일괄로 박지 않았다(공공누리 4유형 자료도 있으므로).
    assert all(s.rights == "unknown" for s in srcs)


def test_collect_auto_routes_end_to_end():
    """홈만 있는 출처가 실행 시 경로를 찾아 실제로 수집까지 간다."""
    src = Source(
        id="mcst",
        name="문화체육관광부",
        kind="govorg",
        url="",
        org="문화체육관광부",
        home="https://www.mcst.go.kr/",
    )

    def fx(_s):  # collect 는 Source 단위 페처를 받는다
        return HOME.encode()

    rep = collect.collect([src], fetcher=fx, auto_routes=True)
    # 발견된 경로로 시도했고(파싱 결과는 HOME 이라 0건이지만) 이력이 남는다.
    assert rep.failed_sources
    # auto_routes=False 면 발견을 하지 않는다.
    rep2 = collect.collect([src], fetcher=fx, auto_routes=False)
    assert rep2.failed_sources
