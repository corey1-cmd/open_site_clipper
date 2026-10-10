"""글 한 건의 그림·첨부 주소 — 실측 페이지 구조를 본뜬 조각으로 확인한다.

본문 글자는 돌려주지 않는다는 원칙도 함께 확인한다(그림·첨부 주소와 표 개수뿐).
"""

from __future__ import annotations

import json
import urllib.parse

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
    assert why["https://student.hufs.ac.kr/_res/hufs/img/common/logo.png"].startswith(
        "껍데기 영역(header"
    )
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


# ── 198곳 실측에서 걸러 낸 오탐(사이트 그림·대기 화면·목록 썸네일·남의 사이트) ──────
def _kept(page: str, url: str, title: str, **kw) -> list[str]:
    return [i.src.rsplit("/", 1)[-1] for i in media.extract(page, url, title=title, **kw).images]


def test_site_pictures_that_slipped_through_the_first_check():
    page = """<body><h3>표준상담 사례집 발간 안내</h3><div class="bbs_view">
    <img src="/Web-home/fnct/bbs/JW_bbs_table/images/attachment.png">
    <img src="/images/fileico/ichwp.gif"><img src="/images/sub/img_sub_visual1.jpg">
    <img src="/images/videoNew/main/main_09.png"><img src="/usr/upload/ftp/sub-visual04.jpg">
    <img src="/base/imgs/cmmn/contents/standby.gif"><img src="/Error.jpg">
    <img src="/Board/images/Attach.htm?MENUCODE=1&FILENO=30790">
    <img src="/upload/editor/2026/error.png"><img src="/upload/editor/logo_final.png">
    </div></body>"""
    got = _kept(page, "https://www.x.go.kr/view.do?id=1", "표준상담 사례집 발간 안내")
    # 프로그램이 내주는 그림(쿼리)·올린 그림은 'error'·'logo' 이름이어도 글의 그림이다
    assert got == ["Attach.htm?MENUCODE=1&FILENO=30790", "error.png", "logo_final.png"]


def test_title_not_on_the_page_keeps_only_uploaded_pictures():
    """접속 대기 화면·메뉴 화면 — 제목이 없으면 사이트 그림은 빼고 올린 그림만."""
    page = """<body><img src="/cdn/univ_main6.jpg"><img src="/_Data/Editor/fd96f3aa29c2.jpg">
    <img src="/data/2026/10/poster.png"></body>"""
    got = _kept(page, "https://www.x.ac.kr/main", "생활관 입사 안내문 공지")
    assert got == ["fd96f3aa29c2.jpg", "poster.png"]
    # 제목 없이 부른 경우(본문 iframe)는 그대로 본다
    assert len(_kept(page, "https://www.x.ac.kr/c.do", "")) == 3


def test_xe_list_thumbnails_and_links_to_sibling_posts_are_not_the_post():
    page = """<body><div class="read"><h1>2026 전국체전 결과 보고</h1>
    <img src="/files/attach/images/4735/799/015/c6a68706f13a7b03f38c336af1a829f5.jpeg"></div>
    <ul class="gallery"><li><a href="/s_results/15794"><img src="/files/thumbnails/794/015/300x300.fill.jpg?t=1"></a></li>
    <li><a href="/s_results/15790"><img src="/files/attach/images/4735/790/015/a.jpg"></a></li></ul>
    </body>"""
    m = media.extract(page, "http://sport.x.ac.kr/s_results/15799", title="2026 전국체전 결과 보고")
    assert [i.src.rsplit("/", 1)[-1] for i in m.images] == ["c6a68706f13a7b03f38c336af1a829f5.jpeg"]
    why = {u.rsplit("/", 1)[-1]: r for u, r in m.dropped}
    assert why["300x300.fill.jpg?t=1"] in ("목록 썸네일", "다른 글 링크")
    assert why["a.jpg"] == "다른 글 링크"


def test_same_picture_as_thumbnail_and_full_size_is_shown_once():
    page = """<body><h3>포항 관제센터 개국식 사진</h3>
    <a href="/upload/ntt_1/img_a.jpg"><img src="/upload/ntt_1/thumb/thumb_img_a.jpg" alt="사진 1"></a>
    <a href="/upload/ntt_1/img_b.jpg"><img src="/upload/ntt_1/thumb/thumb_img_b.jpg" alt="사진 2"></a>
    <img src="/upload/ntt_1/img_a.jpg"><img src="/upload/ntt_1/img_b.jpg"></body>"""
    m = media.extract(page, "https://www.x.go.kr/v.do?nttSn=1", title="포항 관제센터 개국식 사진")
    assert [(i.src.rsplit("/", 1)[-1], i.full.rsplit("/", 1)[-1]) for i in m.images] == [
        ("thumb_img_a.jpg", "img_a.jpg"),
        ("thumb_img_b.jpg", "img_b.jpg"),
    ]


def test_pictures_and_files_on_other_sites_are_only_counted():
    page = """<body><h3>신착 도서 안내합니다</h3>
    <img src="https://image.aladin.co.kr/product/1/cover.jpg"><img src="/upload/2026/a.png">
    <a href="https://viagra.isweb.co.kr/image?code=1"><img src="https://viagra.isweb.co.kr/image?code=1"></a>
    <a href="https://cdn.example.com/files/guide.pdf">안내서.pdf</a><a href="/down.do?id=1">요강.hwp</a>
    <a href="https://img.example.com/big.jpg"><img src="/upload/2026/small.png"></a></body>"""
    m = media.extract(
        page,
        "https://lib.x.go.kr/v.do?id=1",
        title="신착 도서 안내합니다",
        allow=lambda u: ".go.kr" in u,
    )
    assert [i.src.rsplit("/", 1)[-1] for i in m.images] == ["a.png", "small.png"]
    assert m.images[1].full == m.images[1].src  # 큰 그림이 남의 사이트면 작은 그림을 연다
    assert (m.outside_images, m.outside_files) == (2, 1)
    assert [f.label for f in m.files] == ["요강.hwp"]
    d = m.as_dict()
    assert d["outside_images"] == 2 and d["outside_files"] == 1


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("공고문(제2026-127호).hwpx (크기:0.056MB , 다운로드:15)", "공고문(제2026-127호).hwpx"),
        ("퇴직공직자 취업사실 공개.pdf (pdf,", "퇴직공직자 취업사실 공개.pdf"),
        ("은평구민장학재단 선발공고.pdf (268.2K)", "은평구민장학재단 선발공고.pdf"),
        ("출입국 서비스.hwp (다운로드 : 148회)", "출입국 서비스.hwp"),
        ("구제역 확진(9.19.).pdf (파일 용량 :", "구제역 확진(9.19.).pdf"),
        ("붙임1 공고문.hwp", "붙임1 공고문.hwp"),
        ("결과 보고서 (12KB) 다운로드", "결과 보고서"),
        ("육상 100m 기록표", "육상 100m 기록표"),
        ("모집요강.pdf.pdf", "모집요강.pdf.pdf"),
    ],
)
def test_attachment_names_lose_size_and_count_tails(text, label):
    page = f'<body><h3>첨부 이름 정리 확인</h3><a href="/download.do?id=1">{text}</a></body>'
    m = media.extract(page, "https://www.x.go.kr/v.do?id=1", title="첨부 이름 정리 확인")
    assert [f.label for f in m.files] == [label]


def test_attachment_links_with_icon_glyphs_new_window_words_and_zip_buttons():
    page = """<body><h3>첨부 이름 정리 확인</h3>
    <a href="/down.do?id=1">협약체결.hwpx <span class="material-symbols-outlined">chevron_forward</span></a>
    <a href="/viewer/doc.html?fn=1">새창열림</a>
    <a href="/common/downloadAllZip.do?bbs_seq=1">일괄다운로드</a>
    <a href="/editor/view.do?f=2">????????.jpg 바로보기(새창)</a></body>"""
    m = media.extract(page, "https://www.x.go.kr/v.do?id=1", title="첨부 이름 정리 확인")
    assert [(f.label, f.kind) for f in m.files] == [
        ("협약체결.hwpx", "HWP"),
        ("협약체결.hwpx (바로보기)", "보기"),
        (media.ALL_FILES_LABEL, "ZIP"),
        ("첨부 모두 받기 (바로보기)", "보기"),
    ]


@pytest.mark.parametrize(
    ("url", "is_file"),
    [
        (
            "https://www.mof.go.kr/jfile/readDownloadFile.do?fileType=A&fileTypeSeq=1&fileNum=1",
            True,
        ),
        ("https://www.fsc.go.kr/comm/getFile?srvcId=BBSTY1&upperNo=1&fileTy=ATTACH&fileNo=2", True),
        ("https://www.seowon.ac.kr/regltn/seowon/7/6378/2/download.do", True),
        ("https://www.skku.edu/skku/campus/press.do?mode=download&articleNo=1&attachNo=2", True),
        ("https://www.mofe.go.kr/com/cmm/fms/AtchZipFileDown.do?atchFileId=A", True),
        ("https://www.dgau.ac.kr/file/s1360/06/규정.pdf", True),
        ("https://www.x.ac.kr/bbs/x/1/2/artclView.do", False),
        ("https://www.x.ac.kr/board/view.do?mode=view&no=1", False),
        ("https://www.x.ac.kr/pds/download/list.do", False),
    ],
)
def test_notices_that_are_files_themselves(url, is_file):
    assert media.looks_like_file(url) is is_file


@pytest.mark.parametrize(
    ("url", "uploaded"),
    [
        ("https://x.ac.kr/storage/board/1/20261006134118FJinfeKKOrU3.jpg", True),
        ("https://x.go.kr/upload/kcg/na/bbs_315/ntt_72603/img_025a4127.jpg", True),
        ("https://x.ac.kr/utl/web/imageSrc.do?path=abc&physical=def", True),
        ("https://x.ac.kr/files/doc_form/a.png?resVer=2025", True),
        ("https://x.ac.kr/images/common/logo.png?v=1.2", False),
        ("https://x.ac.kr/cdn/univ_main6.jpg", False),
    ],
)
def test_uploaded_picture_addresses(url, uploaded):
    assert media.looks_uploaded(url) is uploaded


def test_board_anchors_with_heads_tails_or_no_title(allow_all):
    """목록 칸의 날 글자로 만든 조각 — 말머리·꼬리가 붙어도 알아본다(질병청·춘해보건대 실측)."""
    raw = "[답변] 면접 질문"
    url = "https://ipsi.x.ac.kr/board/boardList.do?menuCd=1#" + urllib.parse.quote(raw)
    assert webapp._board_anchor(url, "면접 질문") and not webapp.media_ready(url, "면접 질문")
    long = "https://www.x.go.kr/bbs/42/artclList.do#" + urllib.parse.quote(
        "[10.8.목.조간] 임신당뇨병 산모의 자녀, 당뇨병 위험 최대 4배 이상 높아 새글"
    )
    assert webapp._board_anchor(long, "임신당뇨병 산모의 자녀, 당뇨병 위험 최대 4배 이상 높아")
    assert webapp._board_anchor(long, "")  # 제목 없이도 — 한글 조각
    assert not webapp._board_anchor("https://www.x.ac.kr/view.do?id=1#content", "제목입니다")
    assert not webapp.media_ready("https://www.x.ac.kr/down/notice.pdf", "공고문")
    assert webapp.media_ready("https://www.x.ac.kr/bbs/x/1/2/artclView.do", "공고문")


def test_media_for_counts_other_site_pictures(allow_all):
    pages = {
        "https://www.test.ac.kr/view.do?id=8": (
            "<body><h3>도서 안내 공지입니다</h3><img src='https://image.aladin.co.kr/c.jpg'>"
            "<img src='/upload/2026/p.png'></body>"
        ).encode()
    }
    got = webapp.media_for(
        "https://www.test.ac.kr/view.do?id=8", "도서 안내 공지입니다", fetcher=pages.get
    )
    assert [i["src"] for i in got["images"]] == ["https://www.test.ac.kr/upload/2026/p.png"]
    assert got["outside_images"] == 1 and got["outside_files"] == 0
