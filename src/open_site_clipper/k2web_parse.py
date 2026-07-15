"""K2Web 게시판 목록 HTML 파서 — RSS가 막혔을 때의 2·3순위 수단.

**클래스명에 의존하지 않는다.** CMS 스킨은 사이트마다 다르고 개편도 잦아서
`td.artclTdTitle` 같은 선택자에 기대면 곧 깨진다. 대신 이 CMS가 절대 바꿀 수
없는 것 두 가지만 붙잡는다:

  1. 게시글 링크는 반드시 `/bbs/{site}/{board}/{글번호}/artclView.do` 형태다.
  2. 그 링크는 목록 표의 한 행(`<tr>`) 안에 있고, 같은 행에 작성자·작성일 칸이 있다.

그래서 행 단위로 훑으며 (a) artclView 링크가 있는 칸 → 제목·URL, (b) 날짜꼴
칸 → 발행일, (c) 남은 짧은 텍스트 칸 → 작성 부서로 본다. 스킨이 바뀌어도
링크 문법과 표 구조가 유지되는 한 계속 동작한다.

표준 `html.parser`만 쓴다(의존성 0). 본문은 가져오지 않는다 — 목록에 이미
있는 메타데이터(제목·링크·부서·날짜)만 취한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser

from .parse import parse_date

# /bbs/{siteId}/{boardId}/{artclNo}/artclView.do — 이 CMS의 고정 문법.
ARTICLE_RE = re.compile(r"/bbs/([^/]+)/(\d+)/(\d+)/artclView\.do", re.I)
# 2026.07.02 · 2026-07-02 · 2026/07/02
_DATE_RE = re.compile(r"\b(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})\b")
# 조회수·번호 같은 순수 숫자 칸은 부서 후보에서 제외한다.
_NUM_RE = re.compile(r"^\d+$")

MAX_UNIT_LEN = 40


@dataclass(frozen=True, slots=True)
class Row:
    """목록 표의 한 행에서 건진 것."""

    title: str
    url: str
    unit: str = ""  # 작성 부서
    published: date | None = None


class _RowParser(HTMLParser):
    """<tr> 단위로 칸(<td>/<th>) 텍스트와 링크를 모으는 최소 파서."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, str]]] = []  # 행 → [(텍스트, href)]
        self._row: list[tuple[str, str]] | None = None
        self._cell: list[str] | None = None
        self._href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell, self._href = [], ""
        elif tag == "a" and self._cell is not None:
            href = dict(attrs).get("href") or ""
            if href and not self._href:
                self._href = href.strip()

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            text = " ".join("".join(self._cell).split())
            self._row.append((text, self._href))
            self._cell, self._href = None, ""
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _row_date(cells: list[tuple[str, str]]) -> date | None:
    for text, _ in cells:
        m = _DATE_RE.search(text)
        if m:
            y, mo, d = (int(x) for x in m.groups())
            return parse_date(f"{y:04d}-{mo:02d}-{d:02d}")
    return None


def _row_unit(cells: list[tuple[str, str]], title_idx: int) -> str:
    """작성 부서 추출.

    게시판 목록의 칸 순서는 사실상 고정이다: 번호 → 제목 → 작성자 → 작성일 →
    조회수. 그래서 **제목 칸보다 뒤**만 본다. 앞쪽을 보면 번호 칸의 '일반공지'
    (상단 고정 글 표시) 같은 값을 부서로 오인한다. 뒤쪽에서 숫자·날짜·링크
    칸을 걸러 첫 텍스트를 취한다.
    """
    for text, href in cells[title_idx + 1 :]:
        if not text or href:
            continue
        if _NUM_RE.match(text) or _DATE_RE.search(text):
            continue
        if len(text) > MAX_UNIT_LEN:
            continue
        return text
    return ""


def parse_list(html_bytes: bytes, base_url: str) -> list[Row]:
    """게시판 목록/메뉴 페이지 HTML에서 글 행을 뽑는다.

    같은 글이 상단 고정(공지)과 본문에 중복 등장하므로 URL 기준으로 1회만 남긴다.
    """
    import urllib.parse

    try:
        text = html_bytes.decode("utf-8", errors="replace")
    except (AttributeError, UnicodeDecodeError):
        return []
    parser = _RowParser()
    try:
        parser.feed(text)
    except Exception:
        return []

    out: list[Row] = []
    seen: set[str] = set()
    for cells in parser.rows:
        idx = next(
            (i for i, (t, h) in enumerate(cells) if h and ARTICLE_RE.search(h) and t.strip()),
            None,
        )
        if idx is None:
            continue
        title, href = cells[idx]
        url = urllib.parse.urljoin(base_url, href)
        # 같은 글의 다른 표기(?layout=unknown 등)를 하나로 접는다.
        m = ARTICLE_RE.search(url)
        key = m.group(0) if m else url
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Row(
                title=title,
                url=url,
                unit=_row_unit(cells, idx),
                published=_row_date(cells),
            )
        )
    return out
