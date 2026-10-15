"""스크립트로 불러오는 게시판 목록(AJAX) — 요청을 읽어 그대로 하고, 사이트의 줄 틀로 그린다."""

from __future__ import annotations

import json
import urllib.parse

import pytest

from open_site_clipper import ajaxlist, govcascade, govweb, probe, robots, scriptlink, tmpl
from open_site_clipper.sources import Source


@pytest.fixture(autouse=True)
def _allow(monkeypatch):
    monkeypatch.setattr(robots, "allowed", lambda url, **k: True)
    scriptlink.reset_cache()


# ── 틀 그리기 ─────────────────────────────────────────────────────────────────
def test_jquery_tmpl_fields_conditions_and_methods():
    t = (
        "<tr>{{if NOTICE_YN == 'Y'}}<td>공지</td>{{else}}<td>${RNUM}</td>{{/if}}"
        "<td><a href=\"javascript:fn_view('${BBS_SEQ}')\">${SUBJECT}</a></td>"
        "<td>${REG_DATE.substring(0, 10)}</td><td>{{html WRITER}}</td></tr>"
    )
    item = {
        "NOTICE_YN": "N",
        "RNUM": 7,
        "BBS_SEQ": 2271,
        "SUBJECT": "2학기 <수강> 정정 안내",
        "REG_DATE": "2026-10-08 09:12:33",
        "WRITER": "<b>학사팀</b>",
    }
    out = tmpl.render(t, item)
    assert "<td>7</td>" in out and "공지" not in out
    assert "fn_view('2271')" in out
    assert "2학기 &lt;수강&gt; 정정 안내" in out  # ${} 는 글자로(브라우저와 같다)
    assert "<td>2026-10-08</td>" in out
    assert "<b>학사팀</b>" in out  # {{html}} 은 그대로
    assert "<td>공지</td>" in tmpl.render(t, {**item, "NOTICE_YN": "Y"})


def test_handlebars_each_over_response_and_helpers():
    t = (
        "{{#each noticeList}}<tr class='notice'><td>공지</td>"
        "<td><a href='#' onclick='goView({{bIdx}});'>{{title}}</a></td><td>{{formatDate regDate}}</td></tr>{{/each}}"
        "{{#each resultList}}<tr><td>{{@index}}</td>"
        "<td><a href='#' onclick='goView({{bIdx}});'>{{{title}}}</a></td>"
        "<td>{{#if regDate}}{{regDate}}{{else}}-{{/if}}</td><td>{{../menuName}}</td></tr>{{/each}}"
    )
    data = {
        "menuName": "공지사항",
        "noticeList": [{"bIdx": 1, "title": "고정 공지", "regDate": 1791000000000}],
        "resultList": [
            {"bIdx": 5, "title": "일반 글", "regDate": "2026.10.01"},
            {"bIdx": 6, "title": "둘째"},
        ],
    }
    out = tmpl.render(t, data)
    assert "goView(1);" in out and "goView(5);" in out and "goView(6);" in out
    assert "<td>2026-10-03</td>" in out  # 밀리초 → 날짜(서울 시각)
    assert "<td>2026.10.01</td>" in out and "<td>-</td>" in out
    assert out.count("<td>공지사항</td>") == 2  # ../ 는 바깥 값


def test_placeholders_name_the_fields_a_template_uses():
    assert {"BBS_SEQ", "SUBJECT", "REG_DATE"} <= tmpl.placeholders(
        "<a href=\"javascript:fn_view('${BBS_SEQ}')\">${SUBJECT}</a> ${REG_DATE.substring(0,10)}"
    )


# ── 화면 → 목록 요청 → 그린 목록 ─────────────────────────────────────────────
CAU = "https://www.u.ac.kr/cms/FR_CON/index.do?MENU_ID=100"
CAU_PAGE = (
    "<html><body><div class='board'><table><thead><tr><th>번호</th><th>제목</th><th>등록일</th></tr></thead>"
    "<tbody id='tbody'></tbody></table></div>"
    "<form id='sendForm' method='get'>"
    "<input type='hidden' name='pageNo' value='1'><input type='hidden' name='MENU_ID' value='100'>"
    "<input type='hidden' name='BOARD_SEQ' value='4'><input type='hidden' name='S_CATE_SEQ' value=''>"
    "<select name='SEARCH_FLD'><option value='SUBJECT'>제목</option><option value='ALL'>전체</option></select>"
    "<input type='text' name='SEARCH' value=''><input type='checkbox' name='onlyMine' value='Y'>"
    "<input type='submit' name='go' value='검색'></form>"
    '<script type="text/x-jquery-tmpl" id="listTemplate">'
    "<tr><td>${RNUM}</td><td class='tit'><a href=\"javascript:fn_view('${BBS_SEQ}');\">${SUBJECT}</a></td>"
    "<td>${REG_DATE}</td></tr></script>"
    '<script type="text/x-jquery-tmpl" id="noListTemplate"><tr><td colspan="3">없음</td></tr></script>'
    "<script>"
    "$(function(){ fn_list(); });"
    "function fn_list() {"
    '  $("#sendForm input:hidden[name=S_CATE_SEQ]").val("");'
    '  fn_comm_ajax({ url : "/ajax/FR_SVC/BBSViewList2.do", data : $("#sendForm").serialize(),'
    '    dataType : "json", success : function(data) {'
    '      fn_comm_setList("#tbody", data, "#listTemplate", "#noListTemplate", "#rowCount", "#p_pagingFH"); } });'
    "}"
    "function fn_view(seq) { location.href = '/cms/FR_CON/BoardView.do?MENU_ID=100&BOARD_SEQ=4&BBS_SEQ=' + seq; }"
    "function fn_setCategory(lvl){ fn_comm_ajax({ url : '/ajax/FR_SVC/setCategory.do',"
    ' data : $("#sendForm").serialize() + "&LVL=" + lvl, success: function(d){} }); }'
    "</script></body></html>"
)


def _cau_json(page: int) -> bytes:
    if page > 3:  # 글 30건 — 넷째 쪽부터는 빈 목록
        return json.dumps({"list": [], "pagination": {"totalCount": 30}}).encode()
    base = 30 - (page - 1) * 10
    items = [
        {
            "RNUM": base - i,
            "BBS_SEQ": 9000 + base - i,
            "SUBJECT": f"{page}쪽 {i}번째 학사 공지 제목입니다",
            "REG_DATE": f"2026.10.{12 - i - (page - 1) * 10:02d}"
            if 12 - i - (page - 1) * 10 > 0
            else "2026.09.28",
        }
        for i in range(10)
    ]
    return json.dumps(
        {"list": items, "pagination": {"totalCount": 30}}, ensure_ascii=False
    ).encode()


def _cau_fetch(seen: list[str]):
    def fetch(url: str) -> bytes | None:
        seen.append(url)
        parts = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        if url == CAU:
            return CAU_PAGE.encode()
        if parts.path == "/ajax/FR_SVC/BBSViewList2.do":
            return _cau_json(int(q.get("pageNo", "1")))
        if parts.path == "/cms/FR_CON/BoardView.do":
            seq = int(q["BBS_SEQ"])
            return (
                f"<html><h3>글</h3><div class='view'><h4>{'1쪽 0번째 학사 공지 제목입니다' if seq == 9030 else '다른 글'}"
                "</h4><p>본문</p></div></html>"
            ).encode()
        return None

    return fetch


def test_finds_the_list_request_with_the_serialized_form():
    parts = scriptlink.page_parts(CAU_PAGE)
    calls = ajaxlist.find_calls(scriptlink._Ctx(parts, CAU, None))
    assert len(calls) == 1  # 분류 요청(setCategory)은 목록이 아니다
    url = calls[0].request_url()
    q = urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query, keep_blank_values=True)
    assert url.startswith("https://www.u.ac.kr/ajax/FR_SVC/BBSViewList2.do?")
    # 브라우저의 serialize() 와 같다 — 고르지 않은 체크·단추는 빠지고, 고른 option 은 들어간다
    assert q == [
        ("pageNo", "1"),
        ("MENU_ID", "100"),
        ("BOARD_SEQ", "4"),
        ("S_CATE_SEQ", ""),
        ("SEARCH_FLD", "SUBJECT"),
        ("SEARCH", ""),
    ]
    assert "pageNo=3" in calls[0].request_url(3)


def test_expand_renders_rows_that_the_board_parser_reads():
    seen: list[str] = []
    data = ajaxlist.expand(CAU_PAGE.encode(), CAU, _cau_fetch(seen))
    assert data is not None and ajaxlist.MARK in data
    rows = govweb.parse_list(data, CAU)
    assert len(rows) == 10
    assert rows[0].title == "1쪽 0번째 학사 공지 제목입니다"
    assert str(rows[0].published) == "2026-10-12"
    assert rows[0].script.startswith("javascript:fn_view('9030')")
    assert ajaxlist.original(data) == CAU_PAGE.encode()


def test_board_stage_reads_the_ajax_list_and_resolves_post_links():
    src = Source(
        id="u", name="시험대", kind="govorg", url="", org="시험대", routes=(("공지", "board", CAU),)
    )
    seen: list[str] = []
    (res,) = govcascade.collect_routes(src, fetcher=_cau_fetch(seen))
    assert len(res.notices) == 10
    first = res.notices[0]
    assert (
        first.url
        == "https://www.u.ac.kr/cms/FR_CON/BoardView.do?MENU_ID=100&BOARD_SEQ=4&BBS_SEQ=9030"
    )
    assert all("BBS_SEQ=" in n.url for n in res.notices)


def test_next_pages_of_an_ajax_board_change_only_the_page_value():
    from datetime import date

    src = Source(
        id="u", name="시험대", kind="govorg", url="", org="시험대", routes=(("공지", "board", CAU),)
    )
    seen: list[str] = []
    (res,) = govcascade.collect_routes(src, fetcher=_cau_fetch(seen), since=date(2026, 9, 25))
    assert len(res.notices) == 30
    assert any("pageNo=2" in u for u in seen) and any("pageNo=3" in u for u in seen)


def test_discovery_sees_an_ajax_board_as_a_list():
    seen: list[str] = []
    fetch = _cau_fetch(seen)
    plain = probe.classify(CAU_PAGE.encode(), CAU, home_host="www.u.ac.kr")
    assert plain.verdict == probe.STATIC
    got = probe.classify_page(CAU_PAGE.encode(), CAU, home_host="www.u.ac.kr", fetch=fetch)
    assert got.collectible and got.dated == 10


TW = "https://www.t.ac.kr/bbs/board.do?bsIdx=8&menuId=933"
TW_PAGE = (
    "<table id='boardList'><tbody></tbody></table>"
    "<form id='form' name='form' method='post'><input type='hidden' id='bsIdx' name='bsIdx' value='8'>"
    "<input type='hidden' id='bcIdx' name='bcIdx' value='0'><input type='hidden' id='page' name='page' value='1'>"
    "</form>"
    '<script id="list-template" type="text/x-handlebars-template">'
    "{{#each noticeList}}<tr><td>공지</td><td><a href='#' onclick='goView({{bIdx}}); return false;'>{{title}}</a></td>"
    "<td>{{regDate}}</td></tr>{{/each}}"
    "{{#each resultList}}<tr><td>{{num}}</td><td><a href='#' onclick='goView({{bIdx}}); return false;'>{{title}}</a>"
    "</td><td>{{regDate}}</td></tr>{{/each}}</script>"
    "<script>"
    "var listTemplate = Handlebars.compile($('#list-template').html());"
    "var setPageList = function(json){ var boardListHtml = getRenderingSource(listTemplate, json);"
    " $('#boardList').find('tbody').html(boardListHtml); };"
    "var goPage = function(page) { $('#page').val(page); $.ajax({ type:'post', url: '/bbs/ajax/boardList.do',"
    " async: true, cache: false, dataType: 'json', data: { menuId : '933', bsIdx: $('#bsIdx').val(), page: page,"
    " bcIdx: $('#bcIdx').val(), searchKeyword: $('#searchKeyword').val(), categoryAllYn : 'Y' },"
    " success: function(json) { setPageList(json); showPaging(page, json.paginationInfo); } }); };"
    "function goView(idx){ location.href = '/bbs/boardView.do?bsIdx=8&menuId=933&bIdx=' + idx; }"
    "$(function(){ goPage(1); });"
    "</script>"
)


def test_object_data_with_input_values_and_handlebars_template():
    payload = {
        "noticeList": [{"bIdx": 77, "title": "입시 일정 고정 공지", "regDate": "2026-09-01"}],
        "resultList": [
            {"num": 2, "bIdx": 81, "title": "장학금 신청 안내 공지", "regDate": "2026-10-10"},
            {"num": 1, "bIdx": 80, "title": "수강 정정 기간 안내", "regDate": "2026-10-09"},
        ],
        "paginationInfo": {"totalRecordCount": 2},
    }
    seen: list[str] = []

    def fetch(url):
        seen.append(url)
        if urllib.parse.urlsplit(url).path == "/bbs/ajax/boardList.do":
            return json.dumps(payload, ensure_ascii=False).encode()
        return None

    data = ajaxlist.expand(TW_PAGE.encode(), TW, fetch)
    assert data is not None
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(seen[0]).query, keep_blank_values=True))
    assert (
        q["bsIdx"] == "8"
        and q["menuId"] == "933"
        and q["page"] == "1"
        and q["categoryAllYn"] == "Y"
    )
    rows = govweb.parse_list(data, TW)
    assert [r.title for r in rows] == [
        "입시 일정 고정 공지",
        "장학금 신청 안내 공지",
        "수강 정정 기간 안내",
    ]
    assert rows[1].script.startswith("javascript:goView(81)")


def test_load_fragment_and_untemplated_json_and_refusals():
    page = (
        "<div id='list'></div><form id='frm'><input type='hidden' name='boardId' value='B7'></form>"
        "<script>$('#list').load('/board/listAjax.do', $('#frm').serialize());</script>"
    )
    url = "https://www.l.ac.kr/board/notice.do?boardId=B7"

    def fetch(u):
        return (
            b"<ul><li><a href='/board/view.do?id=3'>\xea\xb3\xb5\xec\xa7\x80 \xec\xb2\xab \xea\xb8\x80\xec\x9e\x85\xeb\x8b\x88\xeb\x8b\xa4</a>"
            b"<span>2026-10-01</span></li><li><a href='/board/view.do?id=2'>\xeb\x91\x98\xec\xa7\xb8 \xea\xb8\x80\xec\x9e\x85\xeb\x8b\x88\xeb\x8b\xa4</a>"
            b"<span>2026-09-30</span></li></ul>"
        )

    data = ajaxlist.expand(page.encode(), url, fetch)
    rows = govweb.parse_list(data, url)
    assert [r.url for r in rows] == [
        "https://www.l.ac.kr/board/view.do?id=3",
        "https://www.l.ac.kr/board/view.do?id=2",
    ]

    # 틀이 없는 JSON — 제목·날짜·주소 칸을 이름으로 고른다
    page2 = (
        "<form id='f'><input name='bbsId' value='N1'></form>"
        "<script>$.post('/api/noticeList.do', $('#f').serialize(), function(r){ draw(r); });</script>"
    )
    rows2 = govweb.parse_list(
        ajaxlist.expand(
            page2.encode(),
            "https://www.j.ac.kr/notice.do?bbsId=N1",
            lambda u: json.dumps(
                {
                    "data": {
                        "items": [
                            {
                                "nttSj": "첫 번째 공지입니다",
                                "frstRegistPnttm": "2026-10-02",
                                "linkUrl": "/v?n=1",
                            },
                            {
                                "nttSj": "두 번째 공지입니다",
                                "frstRegistPnttm": "2026-10-01",
                                "linkUrl": "/v?n=2",
                            },
                        ]
                    }
                },
                ensure_ascii=False,
            ).encode(),
        ),
        "https://www.j.ac.kr/notice.do?bbsId=N1",
    )
    assert [(r.title, str(r.published), r.url) for r in rows2] == [
        ("첫 번째 공지입니다", "2026-10-02", "https://www.j.ac.kr/v?n=1"),
        ("두 번째 공지입니다", "2026-10-01", "https://www.j.ac.kr/v?n=2"),
    ]

    # 다른 화면의 곁다리 목록(이 화면의 값을 싣지 않는다)·JSON 본문 요청·다른 사이트는 따라 하지 않는다
    for script in (
        "$.ajax({ url: '/main/latestList.do', data: { cnt: 5 }, success: function(d){ $('#tbody').html(d); } });",
        "$.ajax({ url: '/board/list.do', contentType: 'application/json', data: JSON.stringify({ a: 1 }) });",
        "$.ajax({ url: 'https://other.example.com/list.do', data: $('#f').serialize() });",
    ):
        bare = f"<form id='f'><input name='x' value='1'></form><script>{script}</script>".encode()
        assert ajaxlist.expand(bare, "https://www.k.ac.kr/sub/info.do?m=9", lambda u: b"[]") is None


def test_euc_kr_page_stays_readable_after_rows_are_added():
    page = CAU_PAGE.replace("<html>", "<html><title>공지사항</title>").encode("cp949")
    data = ajaxlist.expand(page, CAU, _cau_fetch([]))
    assert data is not None
    assert "공지사항" in data.decode("utf-8")


def test_post_only_list_request_is_sent_as_the_same_post():
    """GET 에 405 를 주는 목록 요청(동원대) — 사이트가 POST 로 보내면 같은 POST 로 다시."""
    from open_site_clipper.fetch import POST_MARK

    payload = {
        "resultList": [
            {"bIdx": 9, "title": "포스트로만 오는 공지", "regDate": "2026-10-11"},
            {"bIdx": 8, "title": "두 번째 포스트 공지", "regDate": "2026-10-10"},
        ]
    }
    seen: list[str] = []

    def fetch(url):
        seen.append(url)
        if urllib.parse.urlsplit(url).path != "/bbs/ajax/boardList.do":
            return None
        return json.dumps(payload, ensure_ascii=False).encode() if url.endswith(POST_MARK) else None

    ajaxlist._METHOD.clear()
    data = ajaxlist.expand(TW_PAGE.encode(), TW, fetch)
    assert data is not None and len(govweb.parse_list(data, TW)) == 2
    assert not seen[0].endswith(POST_MARK) and seen[1].endswith(POST_MARK)
    seen.clear()
    ajaxlist.expand(TW_PAGE.encode(), TW, fetch)  # 한 번 POST 로 통한 요청은 바로 POST
    assert len(seen) == 1 and seen[0].endswith(POST_MARK)


def test_fetch_detail_sends_marked_urls_as_form_posts():
    import http.server
    import threading

    from open_site_clipper import fetch as fetch_mod

    got: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            got.update(
                path=self.path, body=self.rfile.read(n).decode(), ctype=self.headers["Content-Type"]
            )
            body = b'{"list": []}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/ajax/list.do?pageNo=1&MENU_ID=100{fetch_mod.POST_MARK}"
        data, why = fetch_mod.fetch_detail(url, timeout=5)
    finally:
        server.shutdown()
    assert why == "" and data == b'{"list": []}'
    assert got == {
        "path": "/ajax/list.do",
        "body": "pageNo=1&MENU_ID=100",
        "ctype": "application/x-www-form-urlencoded; charset=UTF-8",
    }


# 실측 꼴(2026-10-12): 중앙대 FR_CON — 구분자를 바꾼 jquery.tmpl('{%= … %}') · <li> 목록 ·
# 도우미(fn_comm_ajax)가 방식을 감추고 폼은 POST(삼육보건대)
FR = "https://www.f.ac.kr/cms/FrCon/index.do?MENU_ID=1800"
FR_PAGE = (
    "<ul id='tbody'></ul>"
    "<form id='sendForm' method='post'><input type='hidden' name='pageNo' value=''>"
    "<input type='hidden' name='MENU_ID' value='1800'><input type='hidden' name='BOARD_SEQ' value='29'></form>"
    '<script type="text/x-jquery-tmpl" id="listTemplate">'
    '<li class="{%if NOTICE_YN == \'Y\'%} typeNoti{%/if%}" id="board_{%= BBS_SEQ%}"> <div class="txtL">'
    "{%if NOTICE_YN == 'Y'%} <span class=\"mark_noti\">[공지]</span> {%/if%}"
    " <a href=\"javascript:fn_goDetail('{%= BBS_SEQ%}','{%= LINK_URL_YN%}','{%= LINK_URL%}','{%= SECRET_YN%}')\">"
    '{%= SUBJECT%}</a> </div> <span class="txtR"><span class="date">{%= WRITE_DT%}</span></span></li>'
    "</script>"
    '<script>function fn_list(){ fn_comm_ajax({ url : "/ajaxf/FrBoardSvc/bbsViewList.do",'
    ' data : $("#sendForm").serialize(), dataType : "json", success : function(data) {'
    ' fn_comm_setList("#tbody", data, "#listTemplate", "#noListTemplate"); } }); }'
    "function fn_goDetail(seq, yn, url, secret){ location.href = '/cms/FrCon/BoardView.do?MENU_ID=1800&BBS_SEQ=' + seq; }"
    "</script>"
)


def test_percent_delimited_template_li_rows_and_post_form_helper():
    from open_site_clipper.fetch import POST_MARK

    payload = {
        "data": {
            "list": [
                {
                    "BBS_SEQ": 501,
                    "SUBJECT": "학사 일정 변경 안내",
                    "NOTICE_YN": "Y",
                    "LINK_URL_YN": "N",
                    "LINK_URL": None,
                    "SECRET_YN": "N",
                    "WRITE_DT": "2026.10.10",
                },
                {
                    "BBS_SEQ": 500,
                    "SUBJECT": "장학금 신청 기간 안내",
                    "NOTICE_YN": "N",
                    "LINK_URL_YN": "N",
                    "LINK_URL": None,
                    "SECRET_YN": "N",
                    "WRITE_DT": "2026.10.09",
                },
            ]
        }
    }
    seen: list[str] = []

    def fetch(url):
        seen.append(url)
        if urllib.parse.urlsplit(url).path != "/ajaxf/FrBoardSvc/bbsViewList.do":
            return None
        # GET 에는 빈 응답을 주는 서버 — POST 여야 목록을 준다
        return (
            json.dumps(payload, ensure_ascii=False).encode() if url.endswith(POST_MARK) else b"{}"
        )

    ajaxlist._METHOD.clear()
    parts = scriptlink.page_parts(FR_PAGE)
    (call,) = ajaxlist.find_calls(scriptlink._Ctx(parts, FR, None))
    assert call.method == "post"  # 도우미는 방식을 감췄지만 폼이 POST
    data = ajaxlist.expand(FR_PAGE.encode(), FR, fetch)
    assert data is not None and seen[-1].endswith(POST_MARK)
    rows = govweb.parse_list(data, FR)
    assert [(r.title, str(r.published)) for r in rows] == [
        ("학사 일정 변경 안내", "2026-10-10"),
        ("장학금 신청 기간 안내", "2026-10-09"),
    ]
    assert rows[0].script.startswith("javascript:fn_goDetail('501','N','','N')")


def test_untemplated_rows_take_every_list_of_the_same_shape_and_skip_image_links():
    page = (
        "<form id='form'><input type='hidden' id='bsIdx' name='bsIdx' value='8'></form>"
        "<script>var goPage = function(page){ $.ajax({ type:'post', url:'/bbs/ajax/boardList.do',"
        " dataType:'json', data:{ menuId:'933', bsIdx: $('#bsIdx').val(), page: page },"
        " success: function(json){ setPageList(json); } }); };</script>"
    )
    payload = {
        "noticeList": [
            {
                "B_IDX": "1",
                "SUBJECT": "고정된 중간고사 공고",
                "WRITE_DATE": "2026-09-23",
                "THUMB_URL": "/cmmn/viewImage.do?idx=1",
            }
        ],
        "resultList": [
            {
                "B_IDX": "3",
                "SUBJECT": "취업역량 강화반 모집",
                "WRITE_DATE": "2026-10-07",
                "THUMB_URL": "/cmmn/viewImage.do?idx=3",
            },
            {
                "B_IDX": "2",
                "SUBJECT": "독감 예방접종 안내",
                "WRITE_DATE": "2026-09-29",
                "THUMB_URL": "",
            },
        ],
    }
    url = "https://www.tw.ac.kr/bbs/board.do?bsIdx=8&menuId=933"
    data = ajaxlist.expand(
        page.encode(), url, lambda u: json.dumps(payload, ensure_ascii=False).encode()
    )
    rows = govweb.parse_list(data, url)
    assert [r.title for r in rows] == [
        "고정된 중간고사 공고",
        "취업역량 강화반 모집",
        "독감 예방접종 안내",
    ]
    assert all("viewImage" not in r.url for r in rows)  # 그림 주소는 글 주소가 아니다
    assert all(r.url.startswith(url + "#") for r in rows)  # 글 주소를 모르면 목록#제목
