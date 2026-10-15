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
    assert got[0] == scriptlink.Candidate(
        "loc",
        "https://www.hanseo.ac.kr/boardCnts/view.do?boardID=299&boardSeq=1000&lev=0&page=1&s=hs",
    )


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


def test_object_method_template_literal_and_globals_pcu():
    js = (
        "var article = { searchForm: null, view(seq) { "
        'if(typeof article.searchForm.articleSeq!="undefined"){ $(article.searchForm.articleSeq).remove(); } '
        "article.searchForm.action = `${ARTICLE_BASE_URL}/${ARTICLE_CODE}/`+seq; "
        "article.searchForm.method = METHOD.GET; article.searchForm.submit(); } };"
    )
    page = (
        "<script>const ARTICLE_BASE_URL = '/kor/article'; const ARTICLE_CODE = 'notice_bob';</script>"
        '<script src="/js/site/article/Article.js"></script>'
        '<form name="searchForm" id="searchForm" action="/kor/article/notice_bob"><input name="pageIndex" value="1">'
        '<input name="searchKeyword" value=""></form>'
        + _table('<a href="#" onclick="article.view(\'{no}\'); return false;">' + TITLE + "</a>")
    )
    got = _first(
        page,
        "https://www.pcu.ac.kr/kor/article/notice_bob",
        lambda url: js.encode() if url.endswith("Article.js") else None,
    )
    assert got[0].url == "https://www.pcu.ac.kr/kor/article/notice_bob/1000"


def test_do_suffix_variant_for_k2web_kurl():
    page = (
        '<script>function jf_view(siteId, fnctNo, boardId) { $( "form[name=\'frm\']" ).attr( "action", '
        'kurl( "/portalBbs/"+siteId+"/"+fnctNo+"/"+boardId+"/view" ) ); $( "form[name=\'frm\']" ).submit(); }'
        "</script>"
        '<form name="frm" action="/portalBbs/uhs/4/list.do" method="post"><input name="page" value="1"></form>'
        + _table("<a href=\"#this\" onclick=\"jf_view('uhs', '4', '{no}');\">" + TITLE + "</a>")
    )
    got = {
        c.kind: c.url
        for c in _first(page, "https://www.uhs.ac.kr/portalBbs/uhs/4/list.do?layout=unknown")
    }
    assert got["form_bare_do"] == "https://www.uhs.ac.kr/portalBbs/uhs/4/1000/view.do"


def test_enclosing_click_listener_with_closest_kunjang():
    page = (
        "<script>document.addEventListener('click', function(e) { "
        "var target = e.target.closest('.btn-bbs-detail'); if (target) { e.preventDefault(); "
        "var mngNo = target.getAttribute('data-mng-no'); var bbsNo = target.getAttribute('data-bbs-no'); "
        "if (mngNo && bbsNo && typeof fnBbsDetail === 'function') { fnBbsDetail(mngNo, bbsNo); } "
        "else if (bbsNo && typeof fnBbsDetail === 'function') { fnBbsDetail(bbsNo); } } }); "
        "document.addEventListener('error', function(e) { if (e.target) { e.target.src = '/x.png'; } }); "
        "function fnBbsDetail(encBbsNo) { location.href = 'bbsNormalView.do?encMenuId=55&encBbsNo=' + encBbsNo; }"
        "</script>"
        + _table('<a href="#" class="btn-bbs-detail" data-bbs-no="E{no}">' + TITLE + "</a>")
    )
    got = _first(page, "https://www.kunjang.ac.kr/home/main/board/bbsNormalList.do?encMenuId=55")
    assert (
        got[0].url
        == "https://www.kunjang.ac.kr/home/main/board/bbsNormalView.do?encMenuId=55&encBbsNo=E1000"
    )


def test_missing_input_value_is_empty_so_guard_branch_is_skipped():
    page = (
        '<script>function goBdView(bdId) { var masterSecretYn = $("#masterSecretYn").val(); '
        "if (masterSecretYn === 'Y') { $('#searchForm input[name=bdId]').val(bdId); "
        "$('#searchForm').attr('action', '/board/secret.do').submit(); } "
        "else { location.href = '/board/view.do?bdId=' + bdId; } }</script>"
        '<form id="searchForm" action="/board/list.do"><input name="bdId" value=""></form>'
        + _table("<a href=\"javascript:goBdView('BD{no}')\">" + TITLE + "</a>")
    )
    got = _first(page, "https://www.nambu.ac.kr/board/list.do")
    assert got[0].url == "https://www.nambu.ac.kr/board/view.do?bdId=BD1000"


def test_title_keys_skip_short_heads_but_not_shared_suffixes():
    titles = [
        "국제 [심리상담센터] 타고난 나의 기본 설정인 기질 이해",
        "공통 [창업교육센터] KHU 창업멘토링 신청 안내",
    ]
    page = (
        b"<html><h2>[\xec\x8b\xac\xeb\xa6\xac\xec\x83\x81\xeb\x8b\xb4\xec\x84\xbc\xed\x84\xb0] "
        + ("타고난 나의 기본 설정인 기질 이해</h2></html>".encode())
    )
    assert scriptlink.looks_like_post(page, titles[0], titles[1:])


def test_global_constant_built_from_other_constants():
    js = (
        "var article = { view(seq) { article.searchForm.action = `${ARTICLE_BASE_URL}/${ARTICLE_CODE}/`+seq; "
        "article.searchForm.submit(); } };"
    )
    page = (
        "<script>const SITE_CODE = 'kor'; const ARTICLE_BASE_URL = `/${SITE_CODE}/article`; "
        "const ARTICLE_CODE = 'notice_bob';</script>"
        '<script src="/js/site/article/Article.js"></script>'
        '<form name="searchForm" id="searchForm" action="/kor/article/notice_bob"></form>'
        + _table('<a href="#" onclick="article.view(\'{no}\'); return false;">' + TITLE + "</a>")
    )
    got = _first(
        page,
        "https://www.pcu.ac.kr/kor/article/notice_bob",
        lambda url: js.encode() if url.endswith("Article.js") else None,
    )
    assert got[0].url == "https://www.pcu.ac.kr/kor/article/notice_bob/1000"


def test_action_set_without_readable_submit_is_still_a_candidate():
    page = (
        "<script>function onView(url){ frmBbs.action = url; dcpPaging(1); }</script>"
        '<form name="frmBbs" action="?mode=list" method="post"><input name="group" value="0"></form>'
        + _table("<a href=\"javascript:onView('?mode=view&id={no}&group=0')\">" + TITLE + "</a>")
    )
    got = _first(page, "https://www.handong.edu/kor/square/inform/news/")
    assert got[0].url == "https://www.handong.edu/kor/square/inform/news/?mode=view&id=1000&group=0"


def test_query_replace_helper_dongduk():
    page = (
        "<script>var queryString = '&schM=list&page=1&viewCount=10&id=&schBdcode=';"
        'function fn_goView(id, notice, no, secret) { if(secret === "Y" && !""){ $("#schM").val("view"); '
        "return false; } var tmpQuery = queryString; "
        'tmpQuery = common_js.fn_replaceQueryString(tmpQuery, "schM", "view"); '
        'tmpQuery = common_js.fn_replaceQueryString(tmpQuery, "id", id); '
        'if(no){ tmpQuery = common_js.fn_replaceQueryString(tmpQuery, "etc1", no); } '
        'if (notice) { tmpQuery += "&notice="+notice; } location.href="?" + tmpQuery; }</script>'
        + _table(
            "<a href=\"#none\" onclick=\"fn_goView('{no}', false, '9801', '')\">" + TITLE + "</a>"
        )
    )
    got = _first(page, "https://www.dongduk.ac.kr/www/contents/kor-campus.do")
    assert got[0].url == (
        "https://www.dongduk.ac.kr/www/contents/kor-campus.do"
        "?schM=view&page=1&viewCount=10&id=1000&schBdcode=&etc1=9801"
    )


def test_doubled_javascript_prefix_dongguk_news():
    page = _table(
        '<a href="#none" onclick="javascript:location.href=\'/article/SCHOOLNEWS/detail/{no}\'">'
        + TITLE
        + "</a>"
    )
    got = _first(page, "https://www.dongguk.edu/article/SCHOOLNEWS/list")
    assert got[0].url == "https://www.dongguk.edu/article/SCHOOLNEWS/detail/1000"


def test_closest_form_on_index_page_eulji():
    js = (
        "function submitForm(f, a, n) { frm = $(f).closest(\"form\"); frm.setHidden('act', a); "
        "if (a == \"view\") { frm.setHidden('bbsno', n); frm.ajaxSubmit(options); return false; } }"
    )
    page = (
        '<script src="/skin/board/notice/js/list.js"></script>'
        '<form name="search"><input name="qt" value=""></form>'
        '<form id="frontBoardVo" name="board" action="/index.html?menuno=4005" method="post">'
        '<input name="siteno" value="47">'
        + _table("<a href='###' onclick=\"return submitForm(this,'view',{no});\">" + TITLE + "</a>")
        + "</form>"
    )
    got = _first(page, "https://www.eulji.ac.kr?menuno=4005", lambda url: js.encode())
    assert got[0].url == "https://www.eulji.ac.kr/index.html?menuno=4005&act=view&bbsno=1000"


def test_trailing_comma_arguments_du():
    assert scriptlink.call_of("pop_pass_open('27924','N', 4515, );") == (
        "pop_pass_open",
        ["27924", "N", "4515"],
    )


def test_data_link_is_the_declared_item_address():
    attrs = [
        ("class", "js-show-popup"),
        ("href", "#video1716"),
        ("data-link", "https://m.blog.naver.com/x/1"),
    ]
    assert anchor_href(attrs) == "https://m.blog.naver.com/x/1"
    attrs = [("href", "#"), ("onclick", "go(1)"), ("data-url", "/a/1")]
    assert anchor_href(attrs) == "javascript:go(1)"


def test_qna_boards_are_not_notice_lists():
    from open_site_clipper import probe

    rows = "".join(
        f"<tr><td>{i}</td><td><a href='#n' onclick=\"openBoardChkPasswd(this,'view','20','{i}')\">질문 {i}번 문의드립니다</a>"
        f"<img alt='비밀글'></td><td>답변대기</td><td>2026-10-0{i}</td></tr>"
        for i in range(1, 6)
    )
    data = f"<table>{rows}</table>".encode()
    assert govweb.looks_like_qna(data)
    assert (
        probe.classify(data, "https://www.cue.ac.kr/kor/CMS/Board/Board.do?mCode=MN080").verdict
        == probe.QNA
    )
    notice = _table("<a href='/v?{no}'>" + TITLE + "</a>").encode()
    assert not govweb.looks_like_qna(notice)


def test_form_from_helper_returning_form_kaya():
    page = (
        "<script>function getForm(){ return document.searchVO; } "
        'function fn_viewData(idx){ getForm().schIdx.value = idx; getForm().action = "/Home//BBSView.mbz"; '
        "getForm().submit(); }</script>"
        '<form name="searchVO" id="form" action="/Home//BBSList.mbz" method="get">'
        '<input name="action" value="MAPP_0000000017"><input name="schIdx" value="0"></form>'
        + _table("<a href=\"javascript:fn_viewData('{no}');\">" + TITLE + "</a>")
    )
    got = _first(page, "https://www.kaya.ac.kr/Home/BBSList.mbz?action=MAPP_0000000017")
    assert got[0].url == "https://www.kaya.ac.kr/Home//BBSView.mbz?schIdx=1000"
    assert any(c.url.endswith("BBSView.mbz?action=MAPP_0000000017&schIdx=1000") for c in got)


def test_auth_helper_with_unknown_branches_does_not_block_view_nambu():
    js = (
        "function goBdView(bdId, masterBoardAuthV, authV, secretYn) { var $form = $('#searchForm'); "
        'var boardId = $("#boardId").val(), masterSecretYn = $("#masterSecretYn").val(); '
        "if(!checkBoardAuth(masterBoardAuthV, authV, '로그인', '권한')){ return false; } "
        "if(masterSecretYn === 'Y'){ $('#searchForm input[name=bdId]').val(bdId); "
        "if(secretYn == 'Y'){ $form.ajaxSubmit({}); } else { board_view(bdId); } } else { board_view(bdId); } }\n"
        "function checkBoardAuth(masterAuth, userAuth, loginMsg, denyMsg) { if(hasBoardAuth(masterAuth, userAuth)){ "
        "return true; } var auth = parseInt(masterAuth, 10); alert(denyMsg); return false; }\n"
        "function board_view(bdId){ $('#searchForm input[name=bdId]').val(bdId); $('#searchForm').attr({ "
        "action : prMap['cpath'] + '/board/' + $(\"#searchForm input[name=boardId]\").val() + '/boardView.do', "
        "method : 'get', target : '_self' }).submit(); }"
    )
    page = (
        '<script src="/site/nambu/nambukr/js/common-util.js?cpath=&v=1"></script>'
        '<form name="searchForm" id="searchForm" method="get"><input name="menuCd" value="KR006006001">'
        '<input id="boardId" name="boardId" value="NAMBU_BOARD_0003"><input name="bdId" value=""></form>'
        + _table("<a href=\"javascript:goBdView('BD{no}', '0', '', '');\">" + TITLE + "</a>")
    )
    got = _first(
        page,
        "https://www.nambu.ac.kr/board/NAMBU_BOARD_0003/boardList.do?menuCd=KR006006001",
        lambda url: js.encode() if "common-util" in url else None,
    )
    assert got[0].url == "https://www.nambu.ac.kr/board/NAMBU_BOARD_0003/boardView.do?bdId=BD1000"


# ── 제목이 단추·줄 클릭인 게시판(2026-10-12) ──────────────────────────────────
def test_title_button_with_onclick_dgist():
    page = (
        "<script>function fn_search_detail(nttId) { document.searchForm.nttId.value = nttId; "
        'document.searchForm.action = "/bbs/BBSMSTR_000000000184/view.do"; document.searchForm.submit(); }</script>'
        '<form name="searchForm" id="searchForm" action="/bbs/BBSMSTR_000000000184/list.do" method="post">'
        '<input name="pageIndex" value="1"><input name="nttId" value=""></form>'
        + _table(
            '<button onclick="fn_search_detail(\'B{no}\'); return false;" class="link">'
            '<div class="bbs-subject-con"><strong class="bbs-subject-txt">'
            + TITLE
            + "</strong></div></button>"
        )
    )
    url = "https://www.dgist.ac.kr/bbs/BBSMSTR_000000000184/list.do"
    rows = govweb.parse_list(page.encode(), url)
    assert len(rows) == 4 and rows[0].title == "0번째 학사 공지사항 안내입니다"
    got = _first(page, url)
    assert got[0] == scriptlink.Candidate(
        "form_set", "https://www.dgist.ac.kr/bbs/BBSMSTR_000000000184/view.do?nttId=B1000"
    )


def test_clickable_row_with_data_attributes_bnue():
    rows = "".join(
        f'<tr style="cursor: pointer;" data-board-id="BOARD_000000104" data-wr-id="" data-idx="{44830 + i}">'
        f'<td class="board_number">{2700 + i}</td><td>안내</td><td class="left title"><p>'
        f'<span class="label">공지</span> <button class="board_title_btn" aria-label="보기">{i}번째 공지 제목입니다'
        f'</button></p></td><td>미래교육원</td><td class="date">2026-10-0{i + 1} 11:38:13</td></tr>'
        for i in range(4)
    )
    page = (
        '<form name="searchFrm" id="searchFrm" action="/board/community01_01" method="get">'
        '<input type="hidden" name="_method" value="get"><input type="hidden" name="boardId" value="BOARD_000000104">'
        '<input type="hidden" name="pageIndex" value="1"></form>'
        f"<table><tbody>{rows}</tbody></table>"
        '<script>$(function(){ $("tbody tr[data-wr-id]").click(function(event) {'
        " if($(event.target).is('input:checkbox')){ return; }"
        ' $("form[name=searchFrm]").attr("method", "get").attr("action", "/board/detail/community01_01/"'
        '+$(this).data("idx")).submit(); return false; }); });</script>'
    )
    url = "https://www.bnue.ac.kr/board/community01_01"
    parsed = govweb.parse_list(page.encode(), url)
    assert [r.title for r in parsed][:2] == ["0번째 공지 제목입니다", "1번째 공지 제목입니다"]
    got = _first(page, url)
    assert got[0] == scriptlink.Candidate(
        "form_bare", "https://www.bnue.ac.kr/board/detail/community01_01/44830"
    )


def test_whole_row_onclick_gives_the_title_cell_its_script():
    page = (
        "<table>"
        + "".join(
            f"<tr onclick=\"location.href='/notice/view.do?no={i}'\"><td>{i}</td><td>{i}번째 행 전체 클릭 공지</td>"
            f"<td>2026-10-0{i + 1}</td></tr>"
            for i in range(1, 4)
        )
        + "</table>"
    )
    rows = govweb.parse_list(page.encode(), "https://www.r.ac.kr/notice/list.do")
    assert [r.url for r in rows] == [
        f"https://www.r.ac.kr/notice/view.do?no={i}" for i in range(1, 4)
    ]
