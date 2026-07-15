"""K2Web 어댑터 — 단계적 폴백(RSS → 목록 → 메뉴), 목록 파서, robots 준수."""

from __future__ import annotations

from datetime import date

from open_site_clipper import k2web, k2web_parse, robots
from open_site_clipper.model import Report
from open_site_clipper.sources import Source, from_dicts

# 실제 HUFS 공지 목록의 구조를 본뜬 조각 — 클래스명은 일부러 다르게 넣어
# 파서가 선택자가 아니라 구조에 기대는지 확인한다.
LIST_HTML = """
<table class="어떤스킨_board"><thead>
<tr><th>NO</th><th>제목</th><th>작성자</th><th>작성일</th><th>조회수</th><th>첨부</th></tr>
</thead><tbody>
<tr>
  <td>일반공지</td>
  <td class="x"><a href="/bbs/hufs/2180/258897/artclView.do">하계방학 단축근무 시행 안내</a></td>
  <td>행정지원처</td><td>2026.06.29</td><td>1568</td><td>0</td>
</tr>
<tr>
  <td>5514</td>
  <td><a href="/bbs/hufs/2180/259122/artclView.do?layout=unknown">개방감사 초빙 공고</a></td>
  <td>전략기획팀</td><td>2026.07.02</td><td>1281</td><td>2</td>
</tr>
<tr>
  <td>5513</td>
  <td><a href="/bbs/hufs/2180/258897/artclView.do?page=1">하계방학 단축근무 시행 안내</a></td>
  <td>행정지원처</td><td>2026.06.29</td><td>1568</td><td>0</td>
</tr>
<tr><td colspan="6">게시물이 없습니다</td></tr>
<tr><td><a href="/hufs/11281/subview.do">공지 메뉴</a></td><td>메뉴</td></tr>
</tbody></table>
"""

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><title>RSS로 받은 공지</title><link>https://www.hufs.ac.kr/bbs/hufs/2180/1/artclView.do</link>
<pubDate>Thu, 02 Jul 2026 09:00:00 +0900</pubDate></item>
</channel></rss>"""

SRC = Source(
    id="hufs-notice",
    name="한국외국어대학교 대학본부",
    kind="k2web",
    url="",
    org="한국외국어대학교",
    site="대학본부",
    host="www.hufs.ac.kr",
    site_id="hufs",
    board_id=2180,
    menu_no=11281,
    category="공지",
)


def test_url_builders_and_candidate_order():
    assert k2web.rss_url("h", "s", 1, 50) == "https://h/bbs/s/1/rssList.do?row=50"
    assert k2web.list_url("h", "s", 1) == "https://h/bbs/s/1/artclList.do"
    assert k2web.page_url("h", "s", 9) == "https://h/s/9/subview.do"
    assert [c[0] for c in k2web.candidates(SRC)] == ["rss", "list", "page"]
    # menu_no 가 없으면 3순위는 후보에서 빠진다.
    from dataclasses import replace

    assert [c[0] for c in k2web.candidates(replace(SRC, menu_no=None))] == ["rss", "list"]
    # 좌표가 없으면 후보 자체가 없다.
    assert k2web.candidates(replace(SRC, board_id=None)) == []


def test_list_parser_structure_not_selectors():
    rows = k2web_parse.parse_list(LIST_HTML.encode(), "https://www.hufs.ac.kr/bbs/hufs/2180/")
    # 같은 글의 다른 표기(?layout=/?page=)는 하나로 접힌다 → 2건.
    assert len(rows) == 2
    first = rows[0]
    assert first.title == "하계방학 단축근무 시행 안내"
    assert first.unit == "행정지원처"  # 작성자 칸 = 부서
    assert first.published == date(2026, 6, 29)
    assert first.url.startswith("https://www.hufs.ac.kr/bbs/hufs/2180/258897/artclView.do")
    # 글 링크가 없는 행(안내문구·메뉴 링크)은 걸러진다.
    assert all("subview" not in r.url for r in rows)
    assert k2web_parse.parse_list(b"<table><tr><td>x", "https://h/") == []


def test_cascade_uses_rss_first():
    calls: list[str] = []

    def fx(url: str) -> bytes:
        calls.append(url)
        return RSS_XML.encode()

    out = k2web.collect_board(SRC, fetcher=fx, check_robots=False)
    assert out.strategy == "rss" and len(out.notices) == 1
    assert len(calls) == 1  # 1순위에서 성공하면 나머지는 두드리지 않는다
    n = out.notices[0]
    assert n.org == "한국외국어대학교" and n.site == "대학본부"
    assert out.trail() == "rss: 1건"


def test_cascade_falls_through_to_list_when_rss_blocked(monkeypatch):
    # robots 가 /bbs/.../rssList.do 만 막는 상황을 만든다.
    monkeypatch.setattr(robots, "allowed", lambda url, **k: "rssList.do" not in url)

    def fx(url: str) -> bytes:
        return LIST_HTML.encode()

    out = k2web.collect_board(SRC, fetcher=fx)
    assert out.strategy == "list" and len(out.notices) == 2
    assert out.attempts[0].reason == k2web.ROBOTS_BLOCKED
    assert out.trail() == "rss: robots.txt 차단 → list: 2건"
    # 목록 수단은 부서명을 준다 — RSS 로는 못 얻는 정보.
    assert {n.unit for n in out.notices} == {"행정지원처", "전략기획팀"}


def test_cascade_falls_through_on_empty_and_failure():
    # RSS는 응답 없음, 목록은 0건 → 메뉴 페이지에서 성공.
    def fx(url: str) -> bytes | None:
        if "rssList" in url:
            return None
        if "artclList" in url:
            return "<table><tr><td>게시물이 없습니다</td></tr></table>".encode()
        return LIST_HTML.encode()

    out = k2web.collect_board(SRC, fetcher=fx, check_robots=False)
    assert out.strategy == "page" and len(out.notices) == 2
    assert [a.reason for a in out.attempts[:2]] == [k2web.FETCH_FAILED, k2web.NO_ITEMS]
    assert out.trail() == "rss: 응답 없음 → list: 글 0건 → page: 2건"


def test_cascade_all_fail_reports_full_trail():
    out = k2web.collect_board(SRC, fetcher=lambda _u: None, check_robots=False)
    assert out.notices == [] and out.strategy == ""
    assert out.trail() == "rss: 응답 없음 → list: 응답 없음 → page: 응답 없음"


def test_from_dicts_accepts_k2web_coordinates():
    (src,) = from_dicts(
        [
            {
                "name": "본부",
                "kind": "k2web",
                "org": "한국외국어대학교",
                "site": "대학본부",
                "host": "www.hufs.ac.kr",
                "site_id": "hufs",
                "board_id": "2180",
                "menu_no": 11281,
            }
        ]
    )
    assert src.board_id == 2180 and src.menu_no == 11281 and src.row == 50
    assert src.org == "한국외국어대학교"
    # 좌표가 모자라면 채택하지 않는다(URL도 없으므로 시도할 방법이 없다).
    assert from_dicts([{"name": "x", "kind": "k2web", "host": "h"}]) == []


def test_by_org_nests_sites_under_one_org():
    from open_site_clipper.model import Notice

    def n(t, site, unit):
        return Notice(
            title=t,
            url=f"https://g/{t}",
            agency="한국외국어대학교",
            org="한국외국어대학교",
            site=site,
            unit=unit,
            published=date(2026, 7, 1),
        )

    rep = Report(
        notices=[
            n("a", "대학본부", "행정지원처"),
            n("b", "대학본부", "홍보실"),
            n("c", "학생지원·장학팀", "장학팀"),
        ]
    )
    grouped = rep.by_org()
    assert list(grouped) == ["한국외국어대학교"]  # 사이트가 달라도 한 기관으로
    assert list(grouped["한국외국어대학교"]) == ["대학본부", "학생지원·장학팀"]
    assert len(grouped["한국외국어대학교"]["대학본부"]) == 2
