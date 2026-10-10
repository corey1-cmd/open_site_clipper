"""글 한 건의 그림·첨부 주소 — 실측 페이지 구조를 본뜬 조각으로 확인한다.

본문 글자는 돌려주지 않는다는 원칙도 함께 확인한다(그림·첨부 주소와 표 개수뿐).
"""

from __future__ import annotations

import json

import pytest

from open_site_clipper import media, robots, webapp

HUFS = "https://student.hufs.ac.kr/bbs/student/2436/268742/artclView.do"
TITLE = "[기후에너지환경부] 제13회 대학생 물환경 정책•기술 공모전"

# 한국외대(케이투웹) 글 화면 — 머리 로고, 본문 포스터, 첨부, 관련 글 썸네일, 이전글.
K2WEB = f"""<!doctype html><html><head><title>{TITLE} | 한국외대</title></head><body>
<header id="header"><a href="/"><img src="/_res/hufs/img/common/logo.png" alt="한국외대"></a>
<nav class="gnb"><a href="/x"><img src="/img/menu_bg.jpg"></a></nav></header>
<div id="container">
 <div class="artclViewHead"><h2 class="artclViewTitle">{TITLE}</h2><dl><dd>2026.10.08</dd></dl></div>
 <div class="artclView">
  <p>본문 글자는 앱으로 가져오지 않는다.</p>
  <p><img src="/CrossEditor/binary/images/000560/포스터.png" style="width:1000px;height:1414px"
      alt="공모전 포스터"></p>
  <p><img src="/img/ico_print.gif"><img src="data:image/png;base64,AAAA"></p>
  <table width="900"><tr><td>일정</td><td>내용</td></tr><tr><td>10/8</td><td>접수</td></tr></table>
 </div>
 <div class="artclItem viewForm"><dl><dt>첨부파일</dt><dd><ul>
  <li><a href="/bbs/student/2436/268742/download.do">공모전 요강.hwp</a>
      <a href="/bbs/student/2436/268742/preView.do">미리보기</a></li>
  <li><a href="javascript:fnDownload(2)">신청서.hwp</a></li>
  <li><a href="/bbs/student/2436/268742/download.do?seq=3">웹포스터.jpg</a></li>
 </ul></dd></dl></div>
 <ul class="artclList">
  <li><a href="/bbs/student/2436/268700/artclView.do"><img
      src="/sites/student/atchmnfl/bbs/2436/thumbnail/thumb_1.png" alt="다른 공모전 대표이미지">
      다른 공모전 작성자 학생지원팀 조회수 10 첨부파일 0</a></li>
 </ul>
 <div class="artclLinkView"><span>이전글</span><a href="/bbs/student/2436/268700/artclView.do">
   <img src="/upload/2026/thumb_other.jpg"></a></div>
</div>
<footer><img src="/img/wa_mark.png" alt="웹 접근성"></footer></body></html>"""


def test_finds_the_poster_and_attachments_of_a_k2web_post():
    m = media.extract(K2WEB, HUFS, title=TITLE)
    assert m.title_found
    srcs = [i.src for i in m.images]
    assert srcs[0] == "https://student.hufs.ac.kr/CrossEditor/binary/images/000560/포스터.png"
    # 그림 파일로 붙인 포스터도 그림으로 보여 준다(첨부 목록에는 넣지 않는다)
    assert srcs[1].endswith("download.do?seq=3") and len(srcs) == 2
    assert [(f.label, f.kind) for f in m.files] == [
        ("공모전 요강.hwp", "HWP"),
        ("공모전 요강.hwp (바로보기)", "보기"),  # 이름 없는 미리보기 — 바로 앞 첨부의 이름
    ]
    assert m.script_files == 1 and m.inline_images == 1
    assert m.tables == 1 and m.wide_tables == 1
    why = dict(m.dropped)
    assert why["https://student.hufs.ac.kr/_res/hufs/img/common/logo.png"] == "껍데기 영역"
    assert why["https://student.hufs.ac.kr/img/ico_print.gif"].startswith("아이콘 이름")
    assert (
        why["https://student.hufs.ac.kr/sites/student/atchmnfl/bbs/2436/thumbnail/thumb_1.png"]
        == "다른 글 링크"
    )
    assert why["https://student.hufs.ac.kr/upload/2026/thumb_other.jpg"] == "이전글·다음글 뒤"


def test_never_returns_body_text():
    """돌려주는 것은 주소·개수뿐 — 본문 문장이 응답 어디에도 없다."""
    out = json.dumps(
        media.extract(K2WEB, HUFS, title=TITLE).as_dict(debug=True), ensure_ascii=False
    )
    assert "본문 글자는" not in out and "접수" not in out


# 산림청(전자정부 표준) 글 — 첨부 단추 그림, 쪽 넘김 화살표, 공공누리 마크, 본문 사진.
FOREST_URL = "https://www.forest.go.kr/kfsweb/cop/bbs/selectBoardArticle.do?nttId=1&bbsId=B"
FOREST = """<html><body><div id="header"><img src="/kfs/images/common/logo.png"></div>
<div class="board_view"><h3>산불연구과 기간제근로자 채용</h3>
<table class="view"><tr><th>첨부</th><td>
 <a href="/kfsweb/cmm/fms/FileDown.do;jsessionid=AB?atchFileId=A1&fileSn=1">채용공고.hwpx
  <img src="/kfs/images/common/bul_down.png" alt="첨부파일 자료받기"></a>
 <a href="/kfsweb/viewer/view.do?atchFileId=A1"><img src="/kfs/images/common/bul_viewer.png"
   alt="첨부파일 뷰어로 보기"></a></td></tr></table>
<div class="cont"><img src="/kfsweb/cmm/fms/getImage.do?atchFileId=A2&fileSn=0" alt="현장 사진">
 <img src="https://static.kosaf.go.kr/www/images/n_skin/common/img_opentype04.jpg"></div>
<div class="paging"><a href="?page=2"><img src="/kfs/images/board/page_arr_left.png"></a></div>
<p><a href="/kfs/images/board/x"><img src="/kfs/images/board/page_arr_right.png"></a></p>
</div></body></html>"""


def test_drops_attachment_buttons_paging_arrows_and_license_marks():
    m = media.extract(FOREST, FOREST_URL, title="산불연구과 기간제근로자 채용")
    assert [i.alt for i in m.images] == ["현장 사진"]
    why = {u.rsplit("/", 1)[-1]: r for u, r in m.dropped}
    assert why["bul_down.png"] == "첨부 단추"
    assert why["bul_viewer.png"] == "첨부 단추"
    assert why["img_opentype04.jpg"].startswith("아이콘 이름(opentype")
    assert why["page_arr_right.png"].startswith("아이콘 이름(arr")
    assert [f.label for f in m.files] == ["채용공고.hwpx", "채용공고.hwpx (바로보기)"]


# 국민권익위 — 파일 이름은 링크 밖에, 링크는 '음성듣기·바로보기·(빈) 다운로드'.
ACRC_URL = "https://www.acrc.go.kr/board.es?mid=a1&bid=2B&act=view&list_no=9"
ACRC = """<html><body><h3>(제2026-102호) 일반임기제 채용 공고</h3>
<ul class="file"><li><span>채용 공고문.pdf</span>
 <a href="/attachPreview.es?bid=2B&seq=1&filenameOrg=%EC%B1%84%EC%9A%A9.pdf&initTTS=true">음성듣기</a>
 <a href="/attachPreview.es?bid=2B&seq=1&filenameOrg=%EC%B1%84%EC%9A%A9%20%EA%B3%B5%EA%B3%A0%EB%AC%B8.pdf">바로보기</a>
 <a href="/boardDownload.es?bid=2B&list_no=9&seq=1"></a></li></ul>
<p><a href="https://www.cu.ac.kr/support/download">모바일앱</a></p>
</body></html>"""


def test_names_attachments_from_url_or_nearby_text_and_skips_read_aloud_links():
    m = media.extract(ACRC, ACRC_URL, title="(제2026-102호) 일반임기제 채용 공고")
    assert [(f.label, f.kind) for f in m.files] == [
        ("채용 공고문.pdf (바로보기)", "보기"),
        ("채용 공고문.pdf", "PDF"),  # 빈 링크 — 바로 앞 글자의 파일 이름
    ]


def test_lazy_images_and_title_with_list_decorations():
    page = """<body><div class="view"><h4>동물세포실증센터장 모집 공고문</h4>
    <img src="/images/loading.gif" data-src="/upload/editor/2026/10/notice.png">
    <img src="/Upload/IMAGE/Board/3355/2026/10/f39bd693c0bf4aebba807ee2b80971e4.JPG">
    <img src="/images/board/b_next.gif"></div></body>"""
    m = media.extract(
        page, "https://x.go.kr/view.do?id=1", title="채용중 동물세포실증센터장 모집 공고문"
    )
    assert m.title_found
    assert [i.src.rsplit("/", 1)[-1] for i in m.images] == [
        "notice.png",
        "f39bd693c0bf4aebba807ee2b80971e4.JPG",  # 날짜 폴더 — 올린 그림
    ]
    tail = media.extract(
        "<body><h3>580돌 한글날 경축식 축하말씀</h3><img src='/up/2026/a.jpg'></body>",
        "https://x.go.kr/v.do?id=2",
        title="580돌 한글날 경축식 축하말씀 NEW 연설문관리자 2026.10.09",
    )
    assert tail.title_found and len(tail.images) == 1


def test_tables_before_the_title_and_layout_tables_are_not_counted():
    page = """<body><table><tr><td><table class="info"><tr><th>제목</th><td>장학생 모집 안내</td></tr>
    <tr><th>작성일</th><td>2026.10.08</td></tr></table>
    <table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>
    </td></tr></table></body>"""
    m = media.extract(page, "https://x.ac.kr/v.do?idx=1", title="장학생 모집 안내")
    assert m.tables == 1 and m.wide_tables == 0


def test_body_in_an_iframe_is_reported():
    page = """<body><h3>공지 제목입니다 안내</h3><iframe src="/board/viewContent.do?id=7"></iframe>
    <iframe src="https://www.youtube.com/embed/x"></iframe></body>"""
    m = media.extract(page, "https://x.go.kr/view.do?id=7", title="공지 제목입니다 안내")
    assert m.frames == ["https://x.go.kr/board/viewContent.do?id=7"]


# ── 서버 쪽(주소 제한·robots·파일 주소·iframe) ─────────────────────────────────
@pytest.fixture
def allow_all(monkeypatch):
    monkeypatch.setattr(robots, "allowed", lambda url, **k: True)
    webapp.media_hosts.cache_clear()
    yield
    webapp.media_hosts.cache_clear()


def test_only_public_or_catalog_sites_can_be_opened(allow_all):
    with pytest.raises(ValueError):
        webapp.media_for("https://www.veritas-a.com/news/articleView.html?idxno=1", "기사")
    with pytest.raises(ValueError):
        webapp.media_for("http://127.0.0.1/x", "x")
    assert webapp.media_allowed("http://entrance.kcu.ac.kr/kcui/boardView?boardNum=1")
    assert webapp.media_allowed("https://www.kosaf.go.kr/ko/notice.do?mode=view")
    assert not webapp.media_allowed("https://evil.example.com/hufs.ac.kr")


def test_media_for_reads_one_page_and_follows_a_body_iframe(allow_all):
    pages = {
        "https://www.test.ac.kr/view.do?id=7": (
            "<body><h3>공지 제목입니다 안내</h3><iframe src='/c.do?id=7'></iframe></body>"
        ).encode(),
        "https://www.test.ac.kr/c.do?id=7": b"<body><img src='/upload/2026/p.png'></body>",
    }
    got = webapp.media_for(
        "https://www.test.ac.kr/view.do?id=7", "공지 제목입니다 안내", fetcher=pages.get
    )
    assert [i["src"] for i in got["images"]] == ["https://www.test.ac.kr/upload/2026/p.png"]
    assert "공지 제목" not in json.dumps(got, ensure_ascii=False).replace(
        got["url"], ""
    )  # 제목·본문 글자를 되돌려 주지 않는다


def test_media_for_explains_what_it_cannot_open(allow_all, monkeypatch):
    anchor = "https://www.test.ac.kr/list.do#%EC%9E%A5%ED%95%99%EC%83%9D%20%EB%AA%A8%EC%A7%91"
    assert "주소가 따로 없는" in webapp.media_for(anchor, "장학생 모집")["error"]
    assert not webapp.media_ready(anchor, "장학생 모집")
    pdf = {"https://www.test.ac.kr/down.do?id=1": b"%PDF-1.7 ..."}
    got = webapp.media_for("https://www.test.ac.kr/down.do?id=1", "파일", fetcher=pdf.get)
    assert "파일 주소" in got["error"]
    monkeypatch.setattr(robots, "allowed", lambda url, **k: False)
    assert webapp.media_for("https://www.test.ac.kr/v.do?id=1", "x")["error"] == "robots.txt 차단"
