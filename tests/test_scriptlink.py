"""스크립트 링크 → 글 주소: 실측 학교 게시판의 꼴을 그대로 옮긴 시험(2026-10-11 점검)."""

from __future__ import annotations

import pytest

from open_site_clipper import govweb, scriptlink
from open_site_clipper.k2web_parse import anchor_href


@pytest.fixture(autouse=True)
def _fresh():
    scriptlink.reset_cache()
    yield
    scriptlink.reset_cache()


def _first(page: str, url: str, fetch=None) -> list[scriptlink.Candidate]:
    rows = govweb.parse_list(page.encode(), url)
    assert rows and rows[0].script, rows
    ctx = scriptlink._Ctx(scriptlink.page_parts(page), url, fetch)
    return scriptlink.candidates(rows[0].script, ctx)


def _table(cell: str, n: int = 4) -> str:
    rows = "".join(
        f"<tr><td>{9 - i}</td><td>{cell.format(i=i, no=1000 + i)}</td><td>2026-10-0{i + 1}</td></tr>"
        for i in range(n)
    )
    return f"<table>{rows}</table>"


TITLE = "{i}번째 학사 공지사항 안내입니다"


# ── 꼴마다 ───────────────────────────────────────────────────────────────────
def test_form_action_from_jquery_attr_dongguk():
    page = (
        "<script>function goDetail(article_seq){ $('#articleFrm').attr('action', "
        "\"/article/GENERALNOTICES/detail/\"+article_seq); $('#articleFrm').submit(); }</script>"
        '<form name="articleFrm" id="articleFrm" action="/article/GENERALNOTICES/list" method="post">'
        '<input type="hidden" name="article_seq" value=""><input type="hidden" name="pageIndex" value="1"></form>'
        + _table('<a href="#none" onclick="goDetail({no});">' + TITLE + "</a>")
    )
    got = _first(page, "https://www.dongguk.edu/article/GENERALNOTICES/list")
    assert got[0] == scriptlink.Candidate(
        "form_bare", "https://www.dongguk.edu/article/GENERALNOTICES/detail/1000"
    )


def test_form_field_and_action_egov_hanbat():
    page = (
        "<script>function fn_search_detail(nttId) { document.searchForm.nttId.value = nttId; "
        'document.searchForm.action = "/bbs/BBSMSTR_000000000050/view.do"; document.searchForm.submit(); }</script>'
        '<form name="searchForm" id="searchForm" action="/bbs/BBSMSTR_000000000050/list.do" method="post">'
        '<input name="pageIndex" value="1"><input name="nttId" value=""><input name="mno" value="sub07_01"></form>'
        + _table(
            '<a href="#view" onclick="javascript: fn_search_detail(\'B{no}\'); return false;">'
            + TITLE
            + "</a>"
        )
    )
    got = _first(page, "https://www.hanbat.ac.kr/bbs/BBSMSTR_000000000050/list.do?mno=sub07_01")
    assert got[0].url == "https://www.hanbat.ac.kr/bbs/BBSMSTR_000000000050/view.do?nttId=B1000"
    assert got[1].url.endswith("view.do?pageIndex=1&mno=sub07_01&nttId=B1000")


def test_location_with_var_and_guard_hanseo():
    page = (
        "<script>function goView(reqBoardID, reqBoardSeq, reqLev, reqSecYN, reqStatusYN, reqCurrPage, "
        "reqWriterYN, reqDept) { var url = '/boardCnts/view.do?boardID='+reqBoardID+'&boardSeq='+reqBoardSeq"
        "+'&lev='+reqLev+'&page='+reqCurrPage+'&s=hs'; var auth = ''; if(reqSecYN == 'Y') { auth = '비공개'; "
        "if(auth != 'SUCCESS') { alert(auth); return; } } auth = 'SUCCESS'; "
        "if( auth == 'SUCCESS' || reqWriterYN == 'Y') location.href = url; else { if(confirm(auth)) goLogin(); } }"
        "</script>"
        + _table(
            "<a href=\"#contents\" onclick=\"javascript:goView('299','{no}', '0', 'null', 'W', '1', 'N', '')\">"
            + TITLE
            + "</a>"
        )
    )
    got = _first(page, "https://www.hanseo.ac.kr/boardCnts/list.do?boardID=299&m=040102&s=hs")
    assert got == [
        scriptlink.Candidate(
            "loc",
            "https://www.hanseo.ac.kr/boardCnts/view.do?boardID=299&boardSeq=1000&lev=0&page=1&s=hs",
        )
    ]


def test_form_elements_khu():
    page = (
        "<script>function view(boardId, catId) { var form = document.item; "
        'form.elements["boardId"].value = boardId; form.elements["catId"].value = catId; '
        'form.elements["pageIndex"].value = $(".pager a.active").text(); form.submit(); }</script>'
        '<form name="item" id="item" action="view.do" method="post"><input name="menuNo" value="200316">'
        '<input name="boardId" value=""><input name="catId" value=""><input name="pageIndex" value=""></form>'
        + _table("<a href=\"javascript:view('{no}','');\">" + TITLE + "</a>")
    )
    got = _first(page, "https://www.khu.ac.kr/kor/user/bbs/BMSR00040/list.do?menuNo=200316")
    assert got[0].url == "https://www.khu.ac.kr/kor/user/bbs/BMSR00040/view.do?boardId=1000"
    assert (
        got[1].url
        == "https://www.khu.ac.kr/kor/user/bbs/BMSR00040/view.do?menuNo=200316&boardId=1000"
    )


def test_condition_on_input_value_ibuilder():
    page = (
        "<script>function fn_view(bbs_mst_idx, data_idx, menuIdx) { if ($(\"#memberAuth\").val() != 'N') { "
        "var f = document.bbsfrm; f.bbs_mst_idx.value = bbs_mst_idx; f.data_idx.value = data_idx; "
        'if( menuIdx != "" ){ f.submenu_idx.value = menuIdx; } f.action = "/bbs/data/view.do"; f.submit(); '
        "} else { alert('직원회원만'); } }</script>"
        '<form name="bbsfrm" id="bbsfrm" method="get"><input name="pageIndex" value="1">'
        '<input name="bbs_mst_idx" value="BM2077"><input name="menu_idx" value="2617">'
        '<input name="submenu_idx" value=""><input name="data_idx" value="">'
        '<input id="memberAuth" name="memberAuth" value="Y"></form>'
        + _table("<a href=\"javascript:fn_view('BM2077','BD{no}','');\">" + TITLE + "</a>")
    )
    got = _first(page, "https://www.mjc.ac.kr/bbs/data/list.do?menu_idx=2617")
    assert got[0].url == "https://www.mjc.ac.kr/bbs/data/view.do?bbs_mst_idx=BM2077&data_idx=BD1000"


def test_closest_form_sethidden_external_script_eulji():
    js = (
        "function submitForm(f, a, n) { frm = $(f).closest(\"form\"); frm.setHidden('act', a); "
        "if (a == \"view\") { frm.setHidden('bbspasswd', ''); frm.setHidden('bbsno', n); "
        "frm.ajaxSubmit(options); return false; } else if (a == \"list\") { frm.setHidden('page', n); "
        "frm.submit(); } }"
    )
    page = (
        '<script src="/skin/board/notice/js/list.js"></script>'
        '<form id="frontBoardVo" name="board" action="/index.html?menuno=4005" method="post">'
        '<input name="keyword" value=""><input name="siteno" value="47"><input name="page" value="1">'
        + _table("<a href='###' onclick=\"return submitForm(this,'view',{no});\">" + TITLE + "</a>")
        + "</form>"
    )
    seen = []

    def fetch(url):
        seen.append(url)
        return js.encode() if url.endswith("/list.js") else None

    got = _first(page, "https://www.eulji.ac.kr/index.html?menuno=4005", fetch)
    assert seen == ["https://www.eulji.ac.kr/skin/board/notice/js/list.js"]
    assert got[0].url == "https://www.eulji.ac.kr/index.html?menuno=4005&act=view&bbsno=1000"


def test_query_only_location_seojeong():
    page = _table(
        '<a href="#none" onclick="location.href=\'?mode=view&articleNo={no}&article.offset=0\';">'
        + TITLE
        + "</a>"
    )
    got = _first(page, "https://www.seojeong.ac.kr/main/campus-life/notice.do")
    assert got[0].url == (
        "https://www.seojeong.ac.kr/main/campus-life/notice.do?mode=view&articleNo=1000&article.offset=0"
    )


def test_input_ids_and_jsessionid_kcn():
    page = (
        "<script>function boardView(code, no) { $('#boardViewCode').val(code); $('#boardViewNo').val(no); "
        "var form = $('#boardViewForm'); form.submit(); }</script>"
        '<form id="boardViewForm" action="/awon/notice/view.do;jsessionid=F01DA710" method="post">'
        '<input id="boardViewCode" name="code" value=""><input id="boardViewNo" name="no" value="">'
        '<input name="cn" value="1"></form>'
        + _table("<a href=\"javascript:boardView('square_notice',{no})\">" + TITLE + "</a>")
    )
    got = _first(page, "https://www.kcn.ac.kr/awon/notice.do")
    assert got[0].url == "https://www.kcn.ac.kr/awon/notice/view.do?code=square_notice&no=1000"


def test_wrapper_helper_without_definition_k2web():
    page = (
        '<script>function jf_view(siteId, fnctNo, boardId) { $( "form[name=\'frm\']" ).attr( "action", '
        'kurl( "/portalBbs/"+siteId+"/"+fnctNo+"/"+boardId+"/view" ) ); $( "form[name=\'frm\']" ).submit(); }'
        "</script>"
        '<form name="frm" action="/portalBbs/uhs/4/list.do" method="post"><input name="page" value="1"></form>'
        + _table("<a href=\"#this\" onclick=\"jf_view('uhs', '4', '{no}');\">" + TITLE + "</a>")
    )
    got = _first(page, "https://www.uhs.ac.kr/portalBbs/uhs/4/list.do?layout=unknown")
    assert got[0].url == "https://www.uhs.ac.kr/portalBbs/uhs/4/1000/view"


def test_bare_form_name_and_helper_call_handong():
    page = (
        "<script>function onView(url){ frmBbs.action = url; dcpPaging(1); } "
        "function dcpPaging(p){ frmBbs.page.value = p; frmBbs.submit(); }</script>"
        '<form name="frmBbs" action="?mode=list" method="post"><input name="group" value="0">'
        '<input name="page" value=""></form>'
        + _table("<a href=\"javascript:onView('?mode=view&id={no}&group=0')\">" + TITLE + "</a>")
    )
    got = _first(page, "https://www.handong.edu/kor/square/inform/news/")
    assert (
        got[0].url
        == "https://www.handong.edu/kor/square/inform/news/?mode=view&id=1000&group=0&page=1"
    )


def test_data_attribute_with_delegated_handler():
    js = (
        "$(document).on('click', '.nttInfoBtn', function(e) { e.preventDefault(); "
        "var nttSn = $(this).data('id'); $('#srchForm input[name=nttSn]').val(nttSn); "
        "$('#srchForm').attr('action', 'selectNttInfo.do').submit(); });"
    )
    page = (
        '<script src="/js/common.js"></script>'
        '<form name="srchForm" id="srchForm" method="post"><input name="bbsId" value="1040">'
        '<input name="nttSn" value=""><input name="mi" value="1188"></form>'
        + _table('<a href="javascript:" data-id="{no}" class="nttInfoBtn">' + TITLE + "</a>")
    )
    got = _first(
        page,
        "https://www.dju.ac.kr/dju/na/ntt/selectNttList.do?mi=1188&bbsId=1040",
        lambda url: js.encode() if url.endswith("common.js") else None,
    )
    assert got[0].url == "https://www.dju.ac.kr/dju/na/ntt/selectNttInfo.do?nttSn=1000"
    assert (
        got[1].url
        == "https://www.dju.ac.kr/dju/na/ntt/selectNttInfo.do?bbsId=1040&mi=1188&nttSn=1000"
    )


def test_anchor_href_marks_data_links():
    assert anchor_href([("href", "javascript:"), ("data-id", "55"), ("class", "nttInfoBtn")]) == (
        "#data:data-id=55&class=nttInfoBtn"
    )
    assert (
        anchor_href([("href", "#"), ("onclick", "go(1)"), ("data-id", "55")]) == "javascript:go(1)"
    )
    assert anchor_href([("href", "/view.do?id=5"), ("data-id", "55")]) == "/view.do?id=5"
    assert anchor_href([("href", "javascript:fn(1)"), ("data-id", "55")]) == "javascript:fn(1)"


# ── 확인 ─────────────────────────────────────────────────────────────────────
LIST_URL = "https://www.dongguk.edu/article/GENERALNOTICES/list"
LIST = (
    "<script>function goDetail(s){ $('#f').attr('action', '/article/G/detail/'+s); $('#f').submit(); }</script>"
    '<form id="f" action="/article/G/list" method="post"></form>'
    + _table('<a href="#none" onclick="goDetail({no});">' + TITLE + "</a>", n=6)
)


def _detail(i: int, extra: str = "") -> bytes:
    return f"<html><h3>{TITLE.format(i=i)}</h3>{extra}<p>본문</p></html>".encode()


def test_resolve_rows_uses_verified_urls_and_remembers():
    calls = []

    def fetch(url):
        calls.append(url)
        if url.endswith("/detail/1000"):
            return _detail(0, f"<a>이전글 {TITLE.format(i=1)}</a>")
        return None

    rows = govweb.parse_list(LIST.encode(), LIST_URL)
    out = scriptlink.resolve_rows(rows, LIST.encode(), LIST_URL, fetch)
    assert [r.url for r in out][:2] == [
        "https://www.dongguk.edu/article/G/detail/1000",
        "https://www.dongguk.edu/article/G/detail/1001",
    ]
    assert calls == ["https://www.dongguk.edu/article/G/detail/1000"]
    # 같은 호스트·같은 함수는 다시 열지 않는다
    again = scriptlink.resolve_rows(rows, LIST.encode(), LIST_URL, fetch)
    assert again == out and len(calls) == 1


def test_resolve_rows_keeps_anchor_when_server_returns_the_list():
    rows = govweb.parse_list(LIST.encode(), LIST_URL)
    out = scriptlink.resolve_rows(rows, LIST.encode(), LIST_URL, lambda url: LIST.encode())
    assert out == rows and "#" in out[0].url


def test_resolve_rows_keeps_anchor_when_title_missing_or_blocked():
    rows = govweb.parse_list(LIST.encode(), LIST_URL)
    out = scriptlink.resolve_rows(rows, LIST.encode(), LIST_URL, lambda url: b"<html>error</html>")
    assert out == rows
    scriptlink.reset_cache()
    seen = []
    out = scriptlink.resolve_rows(
        rows,
        LIST.encode(),
        LIST_URL,
        lambda url: seen.append(url) or _detail(0),
        allowed=lambda url: False,
    )
    assert out == rows and seen == []


def test_looks_like_post_rejects_list_like_pages():
    titles = [TITLE.format(i=i) for i in range(6)]
    listing = _table("<a href='/v?{no}'>" + TITLE + "</a>", n=6).encode()
    assert not scriptlink.looks_like_post(listing, titles[0], titles[1:])
    assert scriptlink.looks_like_post(
        _detail(0, f"<a>{titles[1]}</a><a>{titles[2]}</a>"), titles[0], titles[1:]
    )
    assert not scriptlink.looks_like_post(b"%PDF-1.4 ...", titles[0], titles[1:])
    assert not scriptlink.looks_like_post(_detail(3), titles[0], titles[1:])


def test_no_fetcher_means_no_change():
    rows = govweb.parse_list(LIST.encode(), LIST_URL)
    assert scriptlink.resolve_rows(rows, LIST.encode(), LIST_URL, None) == rows


# ── 부품 ─────────────────────────────────────────────────────────────────────
def test_call_of_and_find_function():
    assert scriptlink.call_of("javascript:fn_view('1234', 5); return false;") == (
        "fn_view",
        ["1234", "5"],
    )
    assert scriptlink.call_of("javascript:void(0)") is None
    assert scriptlink.call_of("article.view('18'); return false;") == ("article.view", ["18"])
    code = "var article = { view(seq) { location.href = '/a/' + seq; }, list: function(p){} };"
    params, body = scriptlink.find_function([code], "article.view")
    assert params == ["seq"] and "location.href" in body
    assert scriptlink.find_function(["if (view(x)) { go(); }"], "view") is None


def test_inline_click_handler_attr_data_gnu():
    page = (
        "<script>$(function(){ $(\".nttInfoBtn\").click(function() { var nttSn = $(this).attr('data-id'); "
        '$("#bbsId").remove(); $("#srchForm").attr(\'action\', '
        '"/main/na/ntt/selectNttInfo.do?mi=1070&bbsId=1021&nttSn="+nttSn).submit(); }); });</script>'
        '<form name="srchForm" id="srchForm" method="post"><input id="bbsId" name="bbsId" value="1021"></form>'
        + _table('<a href="javascript:" data-id="{no}" class="nttInfoBtn">' + TITLE + "</a>")
    )
    got = _first(page, "https://www.gnu.ac.kr/main/na/ntt/selectNttList.do?mi=1070&bbsId=1021")
    assert (
        got[0].url
        == "https://www.gnu.ac.kr/main/na/ntt/selectNttInfo.do?mi=1070&bbsId=1021&nttSn=1000"
    )


def test_handler_calls_function_with_data_gw():
    page = (
        '<script>$(function(){ $(".btn-board-view").click(function(event) { goPage($(this).data("seq")); }); }); '
        "function goPage(articleSeq) { var f = document.mForm; f.articleSeq.value = articleSeq; "
        "f.target = ''; f.submit(); }</script>"
        '<form name="mForm" id="mForm" action="/po/portal/community/notice" method="post">'
        '<input name="pageIndex" value="1"><input name="mode" value=""><input name="articleSeq" value=""></form>'
        + _table('<a href="#nolink" class="btn-board-view" data-seq="{no}">' + TITLE + "</a>")
    )
    got = _first(page, "https://www.gw.ac.kr/po/portal/community/notice")
    assert got[0].url == "https://www.gw.ac.kr/po/portal/community/notice?articleSeq=1000"


def test_location_search_and_unknown_helper_cufs():
    page = (
        '<script>function boView(no) { var rowInParam = ""; var nttNo = no; '
        'if(no.indexOf("|") != -1){ rowInParam = "&rowNum="+no.split("|")[1]; nttNo = no.split("|")[0]; } '
        'let queryString = location.search; let modifiedQueryString = removeQueryParam(queryString, "nttNo"); '
        'location.href = "/bbs/view.do" + modifiedQueryString + "&nttNo=" + nttNo + rowInParam; }</script>'
        + _table(
            '<a href="javascript:void(0)" onclick="boView(\'{no}\')" class="txtLink02"/>'
            + TITLE
            + "</a>"
        )
    )
    got = _first(page, "https://www.cufs.ac.kr/bbs/list.do?bbsId=BBS000063&menuId=MENU000170")
    assert (
        got[0].url
        == "https://www.cufs.ac.kr/bbs/view.do?bbsId=BBS000063&menuId=MENU000170&nttNo=1000"
    )
