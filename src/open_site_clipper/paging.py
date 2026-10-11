"""게시판 다음 쪽 — 첫 쪽의 글이 모두 기간 안이면 사이트의 쪽 번호 링크를 따라 더 읽는다.

큰 학교의 공지 게시판은 한 쪽(10줄)이 사흘도 안 된다(실측 2026-10-11: 고려대 공지 30일 글
17건 — 첫 쪽만 읽었다). 그래서 첫 쪽의 **마지막 글**(가장 오래된 일반 글 — 위의 고정 공지는
오래되어도 상관없다)까지 기간 안이면 다음 쪽을 읽는다.

다음 쪽 주소는 지어내지 않는다 — 화면의 쪽 번호 링크('2')를 쓴다. 링크가 스크립트
(`fn_egov_link_page(2)`·`goPage(2)`)면 scriptlink 가 사이트 스크립트에서 주소를 읽는다.
읽은 쪽에 새 글이 없으면(주소가 통하지 않으면) 거기서 멈춘다.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Callable

from . import scriptlink

_NEXT_TEXT_RE = re.compile(r"^(?:다음(?:\s*페이지)?|next|›|»|>)$", re.I)


def next_urls(
    data: bytes,
    page_url: str,
    page_no: int,
    fetch: Callable[[str], bytes | None] | None = None,
    allowed: Callable[[str], bool] | None = None,
) -> list[str]:
    """page_no 쪽으로 가는 주소 후보들(앞이 유력하다). 없으면 []."""
    from .fetch import decode_text

    parts = scriptlink.page_parts(decode_text(data))
    want = str(page_no)
    exact, nexts = [], []
    for a in parts.anchors:
        text = a.text.strip().strip("[]()")
        if text == want:
            exact.append(a)
        elif page_no == 2 and _NEXT_TEXT_RE.match(text):
            nexts.append(a)
    out: list[str] = []
    ctx = None
    for a in exact + nexts:
        href = (a.attrs.get("href") or "").strip()
        onclick = (a.attrs.get("onclick") or "").strip()
        if href and not href.startswith("#") and not href.lower().startswith("javascript"):
            url = urllib.parse.urljoin(page_url, href)
            if urllib.parse.urlsplit(url).scheme in ("http", "https") and url not in out:
                out.append(url.split("#", 1)[0])
            continue
        js = onclick or (href if href.lower().startswith("javascript") else "")
        if not js:
            continue
        if ctx is None:
            ctx = scriptlink._Ctx(parts, page_url, fetch, allowed)
        script = js if js.lower().startswith("javascript") else "javascript:" + js
        cands = scriptlink.candidates(script, ctx)
        # 쪽 넘기기는 폼의 숨은 값(게시판 번호·메뉴)을 다 실은 꼴부터 — 값만 바꾼 꼴은 다른
        # 게시판의 첫 쪽이 나올 수 있다
        cands.sort(key=lambda c: _PAGE_ORDER.get(c.kind, 9))
        for cand in cands:
            if cand.url not in out and cand.url != page_url:
                out.append(cand.url)
        if out:
            break
    return out[:3]


_PAGE_ORDER = {"loc": 0, "form_all": 1, "form_set": 2, "form_bare": 3}
