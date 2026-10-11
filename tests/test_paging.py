"""게시판 다음 쪽 — 첫 쪽의 마지막 글까지 기간 안이면 사이트의 쪽 번호 링크를 따라 더 읽는다."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from open_site_clipper import govcascade, paging, robots, scriptlink
from open_site_clipper.sources import Source

LIST = "https://www.u.ac.kr/bbs/notice/list.do?bbsId=B1"
SRC = Source(
    id="u", name="시험대", kind="govorg", url="", org="시험대", routes=(("공지", "board", LIST),)
)


@pytest.fixture(autouse=True)
def _allow(monkeypatch):
    monkeypatch.setattr(robots, "allowed", lambda url, **k: True)
    scriptlink.reset_cache()


def _page(n: int, first_day: date, *, paging_html: str, pinned: str = "", rows: int = 10) -> bytes:
    body = "".join(
        f'<tr><td>{n}-{i}</td><td><a href="/bbs/notice/view.do?id={n * 100 + i}">'
        f"{n}쪽 {i}번째 공지사항 제목입니다</a></td><td>{(first_day - timedelta(days=i)).isoformat()}</td></tr>"
        for i in range(rows)
    )
    return f"<table>{pinned}{body}</table>{paging_html}".encode()


PINNED = '<tr><td>공지</td><td><a href="/bbs/notice/view.do?id=1">고정 공지 오래된 안내문입니다</a></td><td>2024-03-01</td></tr>'


def _collect(fetch, since):
    (res,) = govcascade.collect_routes(SRC, fetcher=fetch, since=since)
    return res


def test_reads_next_pages_while_the_last_row_is_inside_the_window():
    today = date(2026, 10, 10)
    pages = {
        LIST: _page(1, today, paging_html='<a href="?bbsId=B1&page=2">2</a>', pinned=PINNED),
        LIST + "&page=2": _page(
            2,
            today - timedelta(days=10),
            paging_html='<a href="?bbsId=B1&page=3">3</a>',
            pinned=PINNED,
        ),
        LIST + "&page=3": _page(3, today - timedelta(days=20), paging_html="", pinned=PINNED),
    }
    seen = []

    def fetch(url):
        seen.append(url)
        return pages.get(url)

    res = _collect(fetch, today - timedelta(days=15))
    # 1쪽(10일치) → 2쪽(10~19일 전, 마지막 글이 기간 밖) → 3쪽은 읽지 않는다
    assert seen == [LIST, LIST + "&page=2"]
    assert len(res.notices) == 21  # 고정 공지 1 + 10 + 10 (고정 공지는 한 번만)
    assert res.notices[0].origin == res.notices[-1].origin


def test_no_paging_without_window_or_when_first_page_already_reaches_past_it():
    today = date(2026, 10, 10)
    first = _page(1, today, paging_html='<a href="?bbsId=B1&page=2">2</a>')
    seen = []

    def fetch(url):
        seen.append(url)
        return first

    _collect(fetch, None)
    assert seen == [LIST]
    seen.clear()
    _collect(fetch, today - timedelta(days=3))  # 첫 쪽 마지막 글(9일 전)이 이미 기간 밖
    assert seen == [LIST]


def test_stops_when_next_page_repeats_or_is_newer():
    today = date(2026, 10, 10)
    first = _page(1, today, paging_html='<a href="?bbsId=B1&page=2">2</a>')
    seen = []

    def same(url):
        seen.append(url)
        return first  # 쪽 값을 무시하고 같은 쪽을 주는 서버

    res = _collect(same, today - timedelta(days=30))
    assert len(res.notices) == 10 and seen == [LIST, LIST + "&page=2"]


def test_script_paging_uses_form_with_hidden_board_fields():
    today = date(2026, 10, 10)
    paging_html = (
        "<script>function fn_egov_link_page(pageNo){ document.listForm.pageIndex.value = pageNo; "
        'document.listForm.action = "/bbs/notice/list.do"; document.listForm.submit(); }</script>'
        '<form name="listForm" method="post"><input name="bbsId" value="B1"><input name="pageIndex" value="1"></form>'
        '<a href="#" onclick="fn_egov_link_page(2); return false;">2</a>'
    )
    page2 = "https://www.u.ac.kr/bbs/notice/list.do?bbsId=B1&pageIndex=2"
    pages = {
        LIST: _page(1, today, paging_html=paging_html),
        page2: _page(2, today - timedelta(days=10), paging_html=""),
    }
    urls = paging.next_urls(pages[LIST], LIST, 2)
    assert urls[0] == page2
    res = _collect(pages.get, today - timedelta(days=30))
    assert len(res.notices) == 20


def test_next_text_link_for_second_page():
    data = b'<div class="paging"><a href="?page=1">1</a><a href="list.do?page=2">\xeb\x8b\xa4\xec\x9d\x8c</a></div>'
    assert paging.next_urls(data, "https://www.u.ac.kr/bbs/list.do", 2) == [
        "https://www.u.ac.kr/bbs/list.do?page=2"
    ]
    assert paging.next_urls(data, "https://www.u.ac.kr/bbs/list.do", 3) == []
