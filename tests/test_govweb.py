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
    # javascript: 링크 행도 글이다 — 상세 주소를 모르므로 목록 페이지로 건다 → 4건.
    assert len(rows) == 4
    script = next(r for r in rows if r.unit == "국립민속국악원")
    assert script.url.startswith(BASE + "#") and script.title == "국악연주단 기획단원 채용 공고"
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
    assert len(rep.notices) == 4
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


# 대학·신형 누리집 게시판 — 표가 아니라 <li> 목록. 위에는 같은 <li> 로 만든 메뉴가 있다.
ITEM_LIST = """
<nav><ul>
  <li><a href="/intro.do">대학소개</a><ul><li><a href="/greet.do">총장 인사말</a></li></ul></li>
  <li><a href="/admission.do">입학안내</a></li>
</ul></nav>
<ul class="board-list">
  <li><a href="view.do?no=31"><span class="cate">학사</span>
      <strong class="tit">2026학년도 2학기 수강신청 정정 안내</strong>
      <span class="date">2026.10.02</span></a></li>
  <li><dl><dt><a href="view.do?no=30">2027학년도 수시모집 면접 고사장 안내</a></dt>
      <dd>등록일 : 2026-09-30</dd><dd>조회 120</dd></dl></li>
  <li><span class="day">2026.09.28</span><a href="view.do?no=29">교내 장학금 신청 기간 연장</a></li>
</ul>
<script>var x = "<li><a href='/x'>2026.01.01 가짜</a></li>";</script>
"""


def test_reads_list_item_boards_and_skips_menus():
    rows = govweb.parse_list(ITEM_LIST.encode(), "https://www.example.ac.kr/bbs/list.do")
    assert [r.title for r in rows] == [
        "2026학년도 2학기 수강신청 정정 안내",
        "2027학년도 수시모집 면접 고사장 안내",
        "교내 장학금 신청 기간 연장",
    ]
    assert [r.published for r in rows] == [date(2026, 10, 2), date(2026, 9, 30), date(2026, 9, 28)]
    assert rows[0].url == "https://www.example.ac.kr/bbs/view.do?no=31"


def test_table_board_still_wins_over_side_lists():
    page = JOB_LIST + ITEM_LIST
    rows = govweb.parse_list(page.encode(), "https://www.mcst.go.kr/list.do")
    assert all(
        "museum.go.kr" in r.url or "karts" in r.url or "mmca" in r.url or "mcst" in r.url
        for r in rows
    )
    assert not any("수강신청" in r.title for r in rows)


def test_date_only_cell_is_not_a_title():
    assert govweb._is_date_only("2026.10.02")
    assert govweb._is_date_only("등록일 : 2026-09-30")
    assert govweb._is_date_only("2026년 9월 30일 (수)")
    assert not govweb._is_date_only("2026학년도 수시모집 안내")
    assert not govweb._is_date_only("공지사항")


def test_home_pages_are_not_boards():
    from open_site_clipper import probe

    for url in (
        "https://www.customs.go.kr/gwangyang/main.do",
        "http://toronto.mofa.go.kr/ca-toronto-ko/index.do",
        "https://www.better.go.kr/zz.main.PortalMain",
        "https://eclass.dongduk.ac.kr/ilos/main/main_form.acl",
        "https://sc.sogang.ac.kr/soriindex.do",
        "https://www.humanrights.go.kr/base/main/view",
        "https://www.kw.ac.kr/ko/",
        "https://uhr.humanrights.go.kr/",
        "https://www.mofe.go.kr/;jsessionid=abc",
        "https://www.kookje.ac.kr/kor/?pCode=main",
        "https://www.mkc.ac.kr/?main=Y",
    ):
        assert probe.looks_like_home(url), url
        assert probe.classify(ITEM_LIST.encode(), url).verdict == probe.HOME
    for url in (
        "https://www.syu.ac.kr/academic/academic-notice/",
        "https://www.fsc.go.kr/no010101",
        "https://www.mofe.go.kr/nw/nes/nesdta.do",
        "https://www.example.ac.kr/bbs/list.do",
        "https://www.example.ac.kr/notice",
        "https://www.example.ac.kr/?page_id=12",
        "https://www.ipkorea.go.kr/policy/lawList.do",
    ):
        assert not probe.looks_like_home(url), url


def test_article_pages_are_not_boards():
    from open_site_clipper import probe

    for url in (
        "https://www.uu.ac.kr/home/bbs/board.php?bo_table=uu_notice_01&wr_id=3015&sub_index=04",
        "https://www.jvision.ac.kr/?menu=192&mode=view&no=1066",
        "https://www.dcu.ac.kr/dcuLife/notice_0101.htm?ACT=R&CONTENTNO=293724",
        "https://www.mcu.ac.kr/bb/bbBoard.php?action=view&pageID=x&boardID=NOTICE&SEQ=1",
        "https://www.syu.ac.kr/blog/some-post-title/",
        "https://www.example.ac.kr/bbs/k/123/4567/artclView.do",
    ):
        assert probe.not_a_board(url), url
        assert probe.classify(ITEM_LIST.encode(), url).verdict == probe.ARTICLE
    for url in (
        "https://www.uu.ac.kr/home/bbs/board.php?bo_table=uu_notice_01",
        "https://www.jvision.ac.kr?menu=146",
        "https://www.dcu.ac.kr/dcuLife/notice_0101.htm",
        "https://www.mcu.ac.kr/bb/bbBoard.php?boardID=NOTICE&pageID=mcu0701000000",
        "https://www.khcu.ac.kr/notice/list.do?category=PRESS&page=1",
        "https://www.example.ac.kr/bbs/k/123/artclList.do",
    ):
        assert not probe.not_a_board(url), url


# eGov 게시판 — 모든 제목이 href="#" + onclick. 예전에는 행마다 주소가 '#'(목록 자신)이라
# 한 건으로 접혀 '목록이 아님'으로 판정됐다(교육부 등).
EGOV = """<table><tbody>
<tr><td>3</td><td class="tit"><a href="#none" onclick="fn_view('103'); return false;">2026년 국가장학금 2차 신청 안내</a></td><td>2026-10-07</td></tr>
<tr><td>2</td><td class="tit"><a href="#none" onclick="fn_view('102'); return false;">교원 임용시험 시행계획 공고</a></td><td>2026-10-02</td></tr>
<tr><td>1</td><td class="tit"><a onclick="fn_view('101')">학교안전 점검 결과 알림</a></td><td>2026-09-28</td></tr>
</tbody></table>"""


def test_script_links_become_distinct_rows_pointing_at_the_board():
    from open_site_clipper import probe

    url = "https://www.moe.go.kr/boardCnts/listRenew.do?boardID=294"
    rows = govweb.parse_list(EGOV.encode(), url)
    assert [r.title for r in rows] == [
        "2026년 국가장학금 2차 신청 안내",
        "교원 임용시험 시행계획 공고",
        "학교안전 점검 결과 알림",
    ]
    assert len({r.url for r in rows}) == 3 and all(r.url.startswith(url + "#") for r in rows)
    assert probe.classify(EGOV.encode(), url).verdict == probe.LIST


def test_urls_written_inside_scripts_are_read_not_invented():
    page = """<table>
    <tr><td><a href="#" onclick="location.href='/board/view.do?no=7'">장학생 선발 안내</a></td><td>2026.10.07</td></tr>
    <tr><td><a href="javascript:window.open('https://x.go.kr/n/view.jsp?id=8')">채용 공고</a></td><td>2026.10.06</td></tr>
    </table>"""
    rows = govweb.parse_list(page.encode(), "https://x.go.kr/board/list.do")
    assert [r.url for r in rows] == [
        "https://x.go.kr/board/view.do?no=7",
        "https://x.go.kr/n/view.jsp?id=8",
    ]


def test_trailing_new_badge_is_not_part_of_the_title():
    assert govweb._clean_title("[교외] 대산장학생 모집 공고(~11/11) 새글") == (
        "대산장학생 모집 공고(~11/11)",
        "교외",
    )
    assert govweb._clean_title("수강신청 안내 NEW")[0] == "수강신청 안내"


def test_search_result_pages_are_not_boards():
    from open_site_clipper import probe

    assert probe.not_a_board("https://www.jbnu.ac.kr/web/search.do?searchKeyword=멘토링")
    assert probe.not_a_board("https://www.x.ac.kr/search/")
    assert not probe.not_a_board("https://www.x.ac.kr/bbs/list.do?searchKeyword=")
    assert not probe.not_a_board("https://www.x.ac.kr/research/notice.do")


def test_page_label_splits_glued_hyphen_names():
    page = "<title>관세청-공지사항</title>".encode()
    assert govweb.page_label(page) == "공지사항"


def test_locked_posts_are_not_notices():
    page = """<table>
    <tr><td><a href="/v1">비공개 - 비밀글이며 관리자와 작성자만 열람할 수 있습니다.</a></td><td>2026.10.07</td></tr>
    <tr><td><a href="/v2">비밀글입니다</a></td><td>2026.10.06</td></tr>
    </table>"""
    assert govweb.parse_list(page.encode(), "https://x.ac.kr/temp/help") == []


def test_paging_rows_and_button_words_are_not_titles():
    """쪽 번호 줄('1 2 3 … 10')과 '자세히보기'가 글 제목으로 잡혔다(농협대·한예종 실측)."""
    assert govweb._is_junk_title("1 2 3 4 5 6 7 8 9 10")
    assert govweb._is_junk_title("처음 이전 1 2 3 다음 마지막")
    assert govweb._is_junk_title("자세히보기")
    assert not govweb._is_junk_title("2026학년도 2학기 국가근로장학생 모집")
    assert not govweb._is_junk_title("2027 수시 1차 합격자 발표")


def test_hidden_mobile_tails_in_the_title_cell_are_not_the_title():
    """반응형 목록 — 제목 칸 안의 휴대폰용 꼬리(새글·첨부·작성자·조회수)는 제목이 아니다."""
    page = """<table><tr><th>번호</th><th>제목</th><th>작성일</th></tr>
    <tr><td>1</td><td class="subject"><a href="/bbs/x/1/45759/artclView.do"><strong>전임연구원 채용 공고</strong></a>
      <span class="new">새글</span><span class="hide">첨부파일이 1개 있음</span></td><td>2026.10.08</td></tr>
    <tr><td>2</td><td class="subject"><a href="view.do?no=2">국가근로장학생 추가 모집 안내(~10/18)</a>
      <span class="m">작성자 학술정보과</span><span class="m">작성일 2026.10.07</span></td></tr>
    </table>"""
    rows = govweb.parse_list(page.encode(), "https://www.x.ac.kr/list.do")
    assert [(r.title, r.published) for r in rows] == [
        ("전임연구원 채용 공고", date(2026, 10, 8)),
        # 날짜가 꼬리에만 있으면 꼬리를 따로 칸으로 두어 게시일을 잃지 않는다
        ("국가근로장학생 추가 모집 안내(~10/18)", date(2026, 10, 7)),
    ]


def test_category_link_before_the_title_does_not_take_the_post_address():
    """그누보드 — 제목 칸 맨 앞의 분류 링크('?sca=학사')가 글 주소 자리를 차지하지 않는다."""
    page = """<table><tr><td class="td_subject">
      <a href="board.php?bo_table=notice&sca=%ED%95%99%EC%82%AC" class="bo_cate_link">학사</a>
      <div class="bo_tit"><a href="board.php?bo_table=notice&wr_id=123">2학기 수강신청 정정 안내</a>
      <span class="new_icon">N</span><span class="cnt_cmt">3</span></div></td>
      <td class="td_datetime">2026-10-08</td></tr>
    <tr><td class="td_subject"><a href="board.php?bo_table=notice&sca=x" class="bo_cate_link">장학</a>
      <a href="board.php?bo_table=notice&wr_id=124">교외 장학생 선발 공고</a></td><td>2026-10-07</td></tr>
    </table>"""
    rows = govweb.parse_list(page.encode(), "https://www.x.ac.kr/bbs/board.php?bo_table=notice")
    assert [(r.title, r.url.rsplit("&", 1)[-1]) for r in rows] == [
        ("학사 2학기 수강신청 정정 안내", "wr_id=123"),
        ("장학 교외 장학생 선발 공고", "wr_id=124"),
    ]


def test_icon_font_glyphs_and_double_escaped_entities_are_not_in_titles():
    page = """<ul>
    <li><a href="detail.do?pstSn=14454"><span class="material-symbols-outlined">lock</span>졸업예정자 누적석차 조회</a>
        <span>2026.10.08</span></li>
    <li><a href="view.do?idx=2328">신라대 앵커사업단, &amp;lsquo;2026 산학연협력 EXPO&amp;rsquo;서 교육&amp;middo</a>
        <span>2026.10.07</span></li>
    <li><a href="view.do?idx=2329">R&amp;D 지원사업 Q&amp;A 안내</a><span>2026.10.06</span></li>
    </ul>"""
    rows = govweb.parse_list(page.encode(), "https://www.x.ac.kr/bbs/list.do")
    assert [r.title for r in rows] == [
        "졸업예정자 누적석차 조회",
        "신라대 앵커사업단, ‘2026 산학연협력 EXPO’서 교육",
        "R&D 지원사업 Q&A 안내",
    ]


def test_attachment_marks_glued_to_titles():
    for raw, want in [
        ("2026년 3분기 업무추진비 집행내역 공개첨부파일", "2026년 3분기 업무추진비 집행내역 공개"),
        (
            "웹쉘탐지 솔루션 구매 업체 선정 (산학) 새글 첨부파일이 3개 있음",
            "웹쉘탐지 솔루션 구매 업체 선정 (산학)",
        ),
        ("해외문화탐방 참가자 모집 안내 첨부파일 있", "해외문화탐방 참가자 모집 안내"),
        (
            "첨부파일 있음열기 정보공유체계 사업 예비설명회 안내",
            "정보공유체계 사업 예비설명회 안내",
        ),
        ("교원 공개채용 지원서 양식", "교원 공개채용 지원서 양식"),
    ]:
        assert govweb._clean_title(raw)[0] == want


def test_spam_and_user_ids_are_not_titles():
    for junk in (
        "조루치료제{viavvv.com}비아그라효과레비트라 직구",
        "teamWebMaster",
        "webadmin",
        "온라인 카지노 추천",
    ):
        assert govweb._is_junk_title(junk), junk
    for ok in (
        "강원랜드 카지노 부문 채용 공고",
        "TOPIK 시험 안내",
        "iPhone 앱 개발 특강",
        "Notice",
    ):
        assert not govweb._is_junk_title(ok), ok


def test_attachment_preview_cell_does_not_push_out_the_title():
    """제목 옆 첨부 미리보기 칸이 글자가 더 길어도 제목·글 주소를 빼앗지 않는다(아주대·이화여대)."""
    page = """<table><tr><td>1</td>
      <td class="title"><a href="?mode=view&amp;articleNo=377206">아산 북한이탈청소년 장학생 선발 안내</a></td>
      <td class="file"><a href="#none" class="attach">첨부파일</a>
        <ul><li><a href="?mode=download&amp;articleNo=377206&amp;attachNo=1">별첨1_ 2027년 아산북한이탈청소년장학생 선발안내.pdf</a></li></ul></td>
      <td>2026.10.08</td></tr></table>"""
    rows = govweb.parse_list(page.encode(), "https://www.x.ac.kr/kr/notice.do")
    assert [(r.title, r.url.rsplit("?", 1)[-1]) for r in rows] == [
        ("아산 북한이탈청소년 장학생 선발 안내", "mode=view&articleNo=377206")
    ]


def test_row_metadata_glued_to_titles_is_trimmed():
    for raw, want in [
        ("교육과정혁신팀 계약직원 채용 인사총무팀 조회수 62 1", "교육과정혁신팀 계약직원 채용"),
        ("캠페인 및 청년 현장 소통 새글 대외협력홍보팀 조회수 11", "캠페인 및 청년 현장 소통"),
        (
            "기술보증기금 상임이사 모집 공고 담당부서 벤처정책과 첨부 등록일 2026.10.08 조회 37",
            "기술보증기금 상임이사 모집 공고",
        ),
        ("스펙업데이 신청 안내 조회 28", "스펙업데이 신청 안내"),
        (
            "My Story Project 집단상담 참여 안내 학생생활상담소 조회수 73",
            "My Story Project 집단상담 참여 안내",
        ),
        (
            "제2회 교정본부 홍보콘텐츠 공모전 최종 심사 결과 공고 새글작성",
            "제2회 교정본부 홍보콘텐츠 공모전 최종 심사 결과 공고",
        ),
        ("중장년 평생대학 공모사업&ap", "중장년 평생대학 공모사업"),
        ("학적사항(졸업예정 여부) 조회(1건)", "학적사항(졸업예정 여부) 조회(1건)"),
        ("논문 작성자 교육 안내", "논문 작성자 교육 안내"),
        ("2026 장학금 지원 조회 시스템 안내", "2026 장학금 지원 조회 시스템 안내"),
    ]:
        assert govweb._clean_title(raw)[0] == want, raw


def test_buttons_menus_and_address_titles_are_not_notices():
    for junk in (
        "다운로드 [미리보기]",
        "(클릭)",
        "[바로보기]",
        "첨부파일 문서보기",
        "Views",
        "| 입학안내",
        "입시홈페이지 바로가기",
        "미륵제 실댄과 1등 더보기",
        "첨부파일 전체다운로드",
        "한글 파일 excel 파일",
        "최신 정보 자료 제공 서비스 주소 http://www.mfds.go.kr/www/rss/brd.do?brdId=rgn0003&itm_seq_1=2",
        # 개인정보처리방침의 권익침해 구제 기관 표(질병청 실측)
        "www.kopico.go.kr",
        "privacy.kisa.or.kr",
        "- 건강정보고속도로(www.myhealthway.co.kr",
    ):
        assert govweb._is_junk_title(junk), junk
    assert not govweb._is_junk_title("한국장학재단(www.kosaf.go.kr) 2학기 국가장학금 신청 안내")
    assert not govweb._is_junk_title(
        "홈페이지 개편 안내(https://new.x.ac.kr) 및 이용 방법과 달라진 메뉴 안내"
    )


def test_unclosed_icon_glyph_does_not_swallow_the_next_rows():
    """닫히지 않은 아이콘 요소가 뒤 칸·행의 글자까지 지우지 않는다."""
    table = """<table><tr><td><a href="view.do?no=1"><i class="material-icons">lock 비밀 안내 글입니다</a></td>
      <td>2026.10.08</td></tr>
    <tr><td><a href="view.do?no=2">둘째 줄 공지 제목입니다</a></td><td>2026.10.07</td></tr></table>"""
    rows = govweb.parse_list(table.encode(), "https://www.x.ac.kr/list.do")
    assert "둘째 줄 공지 제목입니다" in [r.title for r in rows]
    items = """<ul><li><a href="view.do?no=3"><span class="material-symbols-outlined">lock</a>
      <span>2026.10.06</span></li>
    <li><a href="view.do?no=4">셋째 줄 공지 제목입니다</a><span>2026.10.05</span></li>
    <li><a href="view.do?no=5">넷째 줄 공지 제목입니다</a><span>2026.10.04</span></li></ul>"""
    rows = govweb.parse_list(items.encode(), "https://www.x.ac.kr/list.do")
    assert [r.title for r in rows][-2:] == ["셋째 줄 공지 제목입니다", "넷째 줄 공지 제목입니다"]


def test_file_name_links_do_not_take_the_title_or_the_post_address():
    """목록에 첨부 파일 이름을 늘어놓는 게시판 — 파일 이름이 제목보다 길어도 글 링크가 제목이다
    (금융위·해수부·성균관대 실측). 글 링크가 없으면 예전처럼 파일 링크라도 건다."""
    items = """<ul>
      <li><div class="subject"><a href="/no010101/87900?curPage=1">국민참여성장펀드 중간 판매 현황</a></div>
        <div class="file"><a href="/comm/getFile?srvcId=BBSTY1&amp;upperNo=87900&amp;fileNo=1">\
261007(보도자료) 국민참여성장펀드 중간(5영업일)판매 현황.hwpx</a></div>
        <span class="date">2026-10-07</span></li>
      <li><div class="subject"><a href="/no010101/87899?curPage=1">제2차 국민참여성장펀드 판매 결과</a></div>
        <div class="file"><a href="/comm/getFile?srvcId=BBSTY1&amp;upperNo=87899&amp;fileNo=1">\
(보도참고) 제2차 국민참여성장펀드 판매 결과 잔여물량 현황(10.6일).hwpx</a></div>
        <span class="date">2026-10-06</span></li>
    </ul>"""
    rows = govweb.parse_list(items.encode(), "https://www.fsc.go.kr/no010101")
    assert [(r.title, r.url, str(r.published)) for r in rows] == [
        (
            "국민참여성장펀드 중간 판매 현황",
            "https://www.fsc.go.kr/no010101/87900?curPage=1",
            "2026-10-07",
        ),
        (
            "제2차 국민참여성장펀드 판매 결과",
            "https://www.fsc.go.kr/no010101/87899?curPage=1",
            "2026-10-06",
        ),
    ]
    table = """<table>
      <tr><td>3</td><td><a href="/doc/view.do?seq=68962">해파리 대량 발생 위기 경보 전면 해제</a></td>
        <td><a href="/jfile/readDownloadFile.do?fileTypeSeq=68962&amp;fileNum=1">\
(즉시) 해파리 대량 발생 위기 경보 전면 해제(수산자원정책과).pdf</a></td><td>2026-10-08</td></tr>
      <tr><td>2</td><td><a href="/doc/view.do?seq=68961">N</a></td>
        <td><a href="/jfile/readDownloadFile.do?fileTypeSeq=68961&amp;fileNum=1">입찰공고문(청사 시설관리).hml</a></td>
        <td>2026-10-07</td></tr>
      <tr><td>1</td><td>규정 개정 알림</td>
        <td><a href="/regltn/7/6378/1/download.do">3-1-26_취업 규칙(전문)_20260618.hwp</a></td>
        <td>2026-10-06</td></tr>
    </table>"""
    rows = govweb.parse_list(table.encode(), "https://www.mof.go.kr/doc/list.do")
    assert [(r.title, r.url.rsplit("/", 1)[-1]) for r in rows] == [
        ("해파리 대량 발생 위기 경보 전면 해제", "view.do?seq=68962"),
        # 글 링크 글자가 너무 짧거나('N') 글 링크가 아예 없으면 파일 링크라도 건다
        ("입찰공고문(청사 시설관리).hml", "readDownloadFile.do?fileTypeSeq=68961&fileNum=1"),
        ("3-1-26_취업 규칙(전문)_20260618.hwp", "download.do"),
    ]


def test_hot_issue_badge_is_not_part_of_the_title():
    assert govweb._clean_title("2027학년도 수시 1차 면접 신청 안내 핫이슈")[0] == (
        "2027학년도 수시 1차 면접 신청 안내"
    )


def test_script_link_titles_beat_file_names_and_take_the_attachment_address():
    """제목이 스크립트 링크인 게시판 — 파일 이름·'첨부파일 문서보기'가 제목이 되지 않는다.
    글 주소를 모르니 같은 행의 첨부(문서 보기가 있으면 그것)로, 없으면 목록으로 건다
    (해수부·재정경제부·가야대 실측)."""
    table = """<table>
      <tr><td>187</td><td><a href="javascript:fn_selectDoc('68648')">국제해사기구(IMO) 소식 및 국제해사동향(제26-34호)</a></td>
        <td>해사안전정책과</td>
        <td><a href="/jfile/readDownloadFile.do?fileType=MOF_ARTICLE&amp;fileTypeSeq=68648&amp;fileNum=1">\
(26-34호) imo소식 및 국제해사동향.f.pdf</a></td><td>2026.09.15.</td></tr>
      <tr><td>185</td><td><a href="javascript:fn_selectDoc('68966')">인사발령(국장급 전보) 알림</a></td>
        <td>운영지원과</td><td></td><td>2026.10.08.</td></tr>
    </table>"""
    base = "https://www.mof.go.kr/doc/ko/selectDocList.do?menuSeq=380"
    rows = govweb.parse_list(table.encode(), base)
    assert [(r.title, str(r.published)) for r in rows] == [
        ("국제해사기구(IMO) 소식 및 국제해사동향(제26-34호)", "2026-09-15"),
        ("인사발령(국장급 전보) 알림", "2026-10-08"),
    ]
    assert rows[0].url.startswith("https://www.mof.go.kr/jfile/readDownloadFile.do?")
    assert rows[1].url.startswith(base + "#")  # 첨부가 없으면 목록으로

    items = """<ul>
      <li><a href="javascript:fn_egov_select('MOSF_000000000079565');">'생활비 경감 정책 아이디어 공모전' 시상</a>
        <span>2026.10.08.</span><span>민생안정지원단</span>
        <a href="/com/cmm/fms/AtchZipFileDown.do?atchFileId=ATCH_000000000032877">첨부파일 전체다운로드</a>
        <a href="/com/synap/synapView.do?atchFileId=ATCH_000000000032877&amp;fileSn=1">첨부파일 문서보기</a></li>
      <li><a href="javascript:fn_egov_select('MOSF_000000000079576');">관계부처 합동 10월 일자리전담반(TF) 개최</a>
        <span>2026.10.08.</span><span>인력정책과</span></li>
    </ul>"""
    base = "https://www.mofe.go.kr/nw/nes/nesdta.do?bbsId=MOSFBBS_000000000028"
    rows = govweb.parse_list(items.encode(), base)
    assert [r.title for r in rows] == [
        "'생활비 경감 정책 아이디어 공모전' 시상",
        "관계부처 합동 10월 일자리전담반(TF) 개최",
    ]
    # 내려받기(zip)보다 문서 보기 단추
    assert rows[0].url.startswith("https://www.mofe.go.kr/com/synap/synapView.do?")
    assert rows[1].url.startswith(base + "#")


def test_card_lists_with_only_a_details_button_take_the_text_title():
    """링크가 '자세히보기' 단추뿐인 카드형 목록 — 링크 밖의 제목 글을 쓰고 주소는 단추의 것
    (한예종 뉴스레터·매거진 실측). 번호·'발행일 -'·'by 아이디' 는 제목감이 아니고, '바로가기'
    단추뿐인 안내 표(원서접수 기간 — 대구공업대 실측)는 글 목록이 아니다."""
    page = """<ul>
      <li><span class="new">N</span><span>K-Arts</span><strong>매거진 K-Arts Vol.59</strong>
        <span>발행일 -</span><span>2026-09-28</span>
        <a href="/cop/bbs/selectBoardViewCnt.do?bbsId=B150&amp;nttNo=70558">자세히보기</a></li>
      <li><span>K-Arts</span><strong>뉴스레터 vol.223</strong><span>발행일 -</span><span>2026-09-29</span>
        <a href="/cop/bbs/selectBoardViewCnt.do?bbsId=B22&amp;nttNo=70559">자세히보기</a></li>
      <li><span>04</span><span>Oct</span><span>by teamWebMaster</span>
        <a href="/s_results/15799">2026/10/04</a><a href="/s_results/15799">teamWebMaster</a>
        <a href="/s_results/15799">Views</a></li>
      <li><span>2026-09-01</span><p>캠퍼스 소식 모음</p><a href="/cop/bbs/list.do">더보기</a></li>
    </ul>
    <table><tr><td>원서접수</td><td>2026-09-07∼2026-09-30</td><td>서비스 기간이 아닙니다.</td>
      <td><a href="/contents/application/application01.do">바로가기</a></td></tr>
    <tr><td>합격조회</td><td>2026-10-23∼2026-12-31</td><td>서비스 기간이 아닙니다.</td>
      <td><a href="/contents/application/application03.do">바로가기</a></td></tr></table>"""
    base = "https://www.karts.ac.kr/cop/bbs/list.do"
    rows = govweb.parse_list(page.encode(), base)
    assert [(r.title, r.url.rsplit("=", 1)[-1], str(r.published)) for r in rows] == [
        ("매거진 K-Arts Vol.59", "70558", "2026-09-28"),
        ("뉴스레터 vol.223", "70559", "2026-09-29"),
    ]


def test_hidden_tail_inside_the_title_link_that_repeats_the_row_is_dropped():
    """제목 링크 안의 휴대폰용 꼬리(부서·날짜·조회)가 같은 행의 칸을 되풀이하면 뗀다(한국항공대)."""
    page = """<table>
      <tr><td>3969</td><td><a href="notice.php?mode=read&amp;seq=11308">[의료지원실] 「헌혈 X 치킨원정대」 참여 안내
        <span class="m">학생지원팀 2026-10-08 157</span></a></td>
        <td>학생지원팀</td><td>2026-10-08</td><td>157</td></tr>
      <tr><td>3968</td><td><a href="notice.php?mode=read&amp;seq=11290">2학기 중간 시험 감독 모집 2026-10-06</a></td>
        <td>인문자연학부</td><td>2026-10-06</td><td>232</td></tr>
    </table>"""
    rows = govweb.parse_list(page.encode(), "https://kau.ac.kr/kaulife/notice.php")
    assert [(r.title, r.unit, str(r.published)) for r in rows] == [
        ("「헌혈 X 치킨원정대」 참여 안내", "의료지원실", "2026-10-08"),
        # 꼬리가 날짜 칸만 되풀이해도 뗀다(게시일은 따로 보인다)
        ("2학기 중간 시험 감독 모집", "", "2026-10-06"),
    ]
    assert govweb._is_junk_title("※ 다운받기 바로보기")
    # 날짜가 없는 꼬리(부서 이름만 같은 것)는 제목의 일부일 수 있어 그대로 둔다
    assert govweb._drop_echoed_tail("학생지원팀 안내 학생지원팀", [("학생지원팀", "")]) == (
        "학생지원팀 안내 학생지원팀"
    )


def test_document_tables_with_a_download_button_take_the_text_title():
    """'예결산 공고' 표 — 제목은 링크 밖 글, 링크는 '다운로드' 단추(문서 파일)뿐(동명대·아주대 실측)."""
    page = """<table>
      <tr><td>44</td><td>2026학년도 법인회계 제1차 추가경정 자금예산 공고</td><td>2026-08-19</td>
        <td><a href="?mode=download&amp;articleNo=423225&amp;attachNo=86018">다운로드</a></td></tr>
      <tr><td>법인일반업무회계 본예산 자금예산서</td><td>2026.02.12</td>
        <td><a href="/cms/etcResourceDown.do?site=x&amp;key=y">다운로드</a></td></tr>
      <tr><td>예산 편성 지침(안내)</td><td></td>
        <td><a href="/cms/etcResourceDown.do?site=x&amp;key=z">다운로드</a></td></tr>
    </table>"""
    rows = govweb.parse_list(page.encode(), "https://www.tu.ac.kr/tuhome/sub01_03_09.do")
    assert [(r.title, r.url.rsplit("/", 1)[-1][:28], str(r.published)) for r in rows] == [
        (
            "2026학년도 법인회계 제1차 추가경정 자금예산 공고",
            "sub01_03_09.do?mode=download",
            "2026-08-19",
        ),
        ("법인일반업무회계 본예산 자금예산서", "etcResourceDown.do?site=x&ke", "2026-02-12"),
        # 날짜 없는 행의 링크 밖 글은 제목으로 삼지 않는다
    ]
