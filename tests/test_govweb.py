"""정부 표준홈페이지 게시판 파서 — 문체부 채용정보 실측 구조 기준.

실제 표: 번호 | 제목 | 게시일 | 마감일자 | 조회
제목 앞에 [기관명] 접두가 붙고, 상세 링크는 **각 기관 누리집으로 제각각** 나간다
(연동 게시판). 그래서 링크 문법이 아니라 칸 순서로 읽어야 한다.
"""

from __future__ import annotations

from datetime import date

from open_site_clipper import collect, govweb
from open_site_clipper.sources import Source, from_dicts

JOB_LIST = """
<table class="어떤스킨">
<thead><tr><th>번호</th><th>제목</th><th>게시일</th><th>마감일자</th><th>조회</th></tr></thead>
<tbody>
<tr>
  <td>4611</td>
  <td><a href="https://www.museum.go.kr/MUSEUM/contents/M0701030000.do?arcId=23838">[국립중앙박물관] 새글 국립전주박물관 공무원[한시임기제] 채용 재공고</a></td>
  <td>2026.07.21.</td><td>2026.07.27.</td><td>20</td>
</tr>
<tr>
  <td>4609</td>
  <td><a href="https://www.karts.ac.kr/nri/bbs/NuriBbsDetail.do?nttNo=9857582">[한국예술종합학교] 공무직(조리)근로자 채용 최종합격자 공고</a></td>
  <td>2026.07.21.</td><td>2026.08.23.</td><td>11</td>
</tr>
<tr>
  <td>4607</td>
  <td><a href="javascript:void(0);">[국립민속국악원] 국악연주단 기획단원 채용 공고</a></td>
  <td>2026.07.20.</td><td></td><td>115</td>
</tr>
<tr>
  <td>4605</td>
  <td><a href="/site/s_notice/notice/jobView.jsp?pSeq=11202">[문화체육관광부] 공무원(일반임기제) 채용 공고(연장)</a>
      <a href="/file/down.jsp?id=9">첨부</a></td>
  <td>2026.07.20.</td><td>2026.07.30.</td><td>55</td>
</tr>
<tr><td colspan="5">등록된 게시물이 없습니다</td></tr>
</tbody></table>
"""

BASE = "https://www.mcst.go.kr/site/s_notice/notice/jobList.jsp"


def test_parses_rows_by_column_order_not_link_syntax():
    rows = govweb.parse_list(JOB_LIST.encode(), BASE)
    # javascript: 링크 행은 주소가 없어 제외 → 3건.
    assert len(rows) == 3
    first = rows[0]
    assert first.title == "국립전주박물관 공무원[한시임기제] 채용 재공고"  # '새글' 배지 제거
    assert first.unit == "국립중앙박물관"  # [기관명] 접두를 부서로
    assert first.published == date(2026, 7, 21)  # 마감일이 아니라 게시일
    assert first.url.startswith("https://www.museum.go.kr/")  # 외부 기관 링크 그대로
    # 상대경로 상세 링크도 절대화된다.
    mcst = next(r for r in rows if r.unit == "문화체육관광부")
    assert mcst.url == "https://www.mcst.go.kr/site/s_notice/notice/jobView.jsp?pSeq=11202"
    assert mcst.published == date(2026, 7, 20)


def test_attachment_link_does_not_win_over_title():
    """같은 칸에 첨부 링크가 있어도 제목(가장 긴 텍스트)이 이긴다."""
    rows = govweb.parse_list(JOB_LIST.encode(), BASE)
    assert all("down.jsp" not in r.url for r in rows)


def test_ignores_rows_without_real_links():
    empty = "<table><tr><td>안내</td><td>등록된 게시물이 없습니다</td></tr></table>"
    assert govweb.parse_list(empty.encode(), BASE) == []
    assert govweb.parse_list(b"<table><tr><td>x", BASE) == []


def test_clean_title_variants():
    assert govweb._clean_title("[문체부] 새글 채용 공고") == ("채용 공고", "문체부")
    assert govweb._clean_title("새글 [문체부] 채용 공고") == ("채용 공고", "문체부")
    assert govweb._clean_title("접두 없는 제목입니다") == ("접두 없는 제목입니다", "")


def test_collect_govweb_end_to_end():
    src = Source(
        id="mcst-job",
        name="문화체육관광부",
        kind="govweb",
        url=BASE,
        org="문화체육관광부",
        site="본부",
        category="채용",
    )
    rep = collect.collect([src], fetcher=lambda _s: JOB_LIST.encode())
    assert len(rep.notices) == 3
    n = rep.notices[0]
    assert n.org == "문화체육관광부" and n.category == "채용"
    assert n.unit in {"국립중앙박물관", "한국예술종합학교", "문화체육관광부"}
    # 실패 시 조용히 넘어가지 않는다.
    fail = collect.collect([src], fetcher=lambda _s: None)
    assert fail.failed_sources and not fail.notices


def test_from_dicts_accepts_govweb():
    (src,) = from_dicts(
        [
            {
                "name": "문화체육관광부",
                "kind": "govweb",
                "url": BASE,
                "org": "문화체육관광부",
                "category": "채용",
                "rights": "kogl_type1",
            }
        ]
    )
    assert src.kind == "govweb" and src.url == BASE
    # URL 이 없으면 채택하지 않는다(좌표 방식이 아니므로 URL 이 필수).
    assert from_dicts([{"name": "x", "kind": "govweb"}]) == []
