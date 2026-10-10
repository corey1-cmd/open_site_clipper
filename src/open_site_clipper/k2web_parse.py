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
# 날짜 표기 — 국내 기관 사이트 실측 형식을 모두 받는다.
#   2026.07.20 · 2026-07-20 · 2026/07/20 · 2026.7.20
_DATE_RE = re.compile(r"\b(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})\b")
#   2026년 7월 20일 (한글 표기 — 정부 게시판에 흔하다)
_DATE_KO_RE = re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
#   26.07.20 (두 자리 연도 — 2000년대만 대상으로 본다)
_DATE_YY_RE = re.compile(r"(?<![\d.])(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})(?![\d.])")
#   20260720 (붙임 표기)
_DATE_COMPACT_RE = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")
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


def anchor_href(attrs: list[tuple[str, str | None]]) -> str:
    """`<a>` 의 주소 — 주소가 스크립트에만 있으면 'javascript:…' 로 돌려준다.

    eGov·옛 학교 스킨은 `<a href="#" onclick="fn_view('123')">` 처럼 주소를
    스크립트에 넣는다. href 만 보면 '#'(= 목록 자기 자신)이라 모든 행이 같은
    주소가 되고, 중복으로 접혀 '글 0~1건'으로 판정됐다(교육부 등 실측).
    """
    a = dict(attrs)
    href = (a.get("href") or "").strip()
    onclick = (a.get("onclick") or "").strip()
    if onclick and (not href or href.startswith("#") or href.lower().startswith("javascript")):
        return "javascript:" + onclick
    return href


# 글자로 그리는 아이콘 글꼴(Material) — 'lock'·'chevron_forward' 같은 글자가 제목에
# 붙는다('lock졸업예정자 누적석차 조회' — 강원대 실측). 이 요소 안의 글자는 읽지 않는다.
GLYPH_CLASSES = ("material-icons", "material-symbols")
_VOID_TAGS = frozenset({"br", "img", "hr", "input", "wbr", "meta", "link", "source", "col"})


# 파일을 바로 내려받는 링크 — 칸의 대표 링크(글 주소)로 삼지 않는다. 제목 칸 옆의 첨부
# 미리보기 칸('첨부파일 1. 입찰공고.hwp 2. 규격서.pdf' — 아주대·이화여대 실측)이 글자가
# 더 길어 제목을 밀어내지 않게.
_FILE_LINK_RE = re.compile(
    r"download|filedown|file_down|getfile|atchfile|mode=down|"
    r"\.(?:pdf|hwpx?|hml|docx?|xlsx?|pptx?|zip|jpe?g|png|gif)(?:$|[?#])",
    re.I,
)


def is_file_link(href: str) -> bool:
    """파일을 바로 내려받는(또는 문서 뷰어로 여는) 주소인가 — 글 주소가 아니다."""
    return bool(_FILE_LINK_RE.search(href or ""))


def is_glyph(attrs: list[tuple[str, str | None]]) -> bool:
    cls = (dict(attrs).get("class") or "").lower()
    return any(g in cls for g in GLYPH_CLASSES)


class _RowParser(HTMLParser):
    """<tr> 단위로 칸(<td>/<th>) 텍스트와 링크를 모으는 최소 파서.

    링크가 든 칸은 **글자가 가장 긴 링크(파일 링크 말고)가 끝나는 데까지**가 그 칸의 글이다. 반응형
    목록은 제목 칸 안에 휴대폰용 꼬리('새글'·'첨부파일이 1개 있음'·작성자·조회수)를
    숨겨 두는데, 그것까지 이으면 제목이 '… 공고 새글 작성자 학술정보과 작성일 2026.1'
    처럼 된다(인하대·인천대·아주대 실측). 꼬리에 날짜가 있으면 그 꼬리는 바로 뒤의
    칸으로 따로 둔다(게시일을 잃지 않게). 칸의 주소도 그 링크의 주소다 — 앞에 붙은
    분류 링크('?sca=학사')·첨부 아이콘 링크가 글 주소 자리를 차지하지 않게.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, str]]] = []  # 행 → [(텍스트, href)]
        self._row: list[tuple[str, str]] | None = None
        self._cell: list[str] | None = None
        self._size = 0  # 칸에 모인 글자 수
        self._href = ""  # 칸의 첫 링크 주소
        self._links: list[tuple[int, int, str]] = []  # 글자 있는 링크 (시작, 끝, 주소)
        self._open_link: tuple[int, str] | None = None
        self._glyph: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("tr", "td", "th"):
            self._glyph = []  # 닫히지 않은 아이콘 요소가 다음 칸의 글자까지 삼키지 않게
        if tag not in _VOID_TAGS and is_glyph(attrs):
            self._glyph.append(tag)
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell, self._href, self._size = [], "", 0
            self._links, self._open_link = [], None
        elif tag == "a" and self._cell is not None:
            href = anchor_href(attrs)
            if href and not self._href:
                self._href = href
            self._open_link = (self._size, href)

    def handle_data(self, data: str) -> None:
        if self._cell is not None and not self._glyph:
            self._cell.append(data)
            self._size += len(data)

    def handle_endtag(self, tag: str) -> None:
        if self._glyph and tag == self._glyph[-1]:
            self._glyph.pop()
        elif tag in ("tr", "td", "th", "a"):
            self._glyph = []
        if tag == "a" and self._open_link is not None and self._cell is not None:
            start, href = self._open_link
            self._open_link = None
            if "".join(self._cell)[start:].strip():
                self._links.append((start, self._size, href))
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._end_cell()
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def _end_cell(self) -> None:
        assert self._cell is not None and self._row is not None
        raw = "".join(self._cell)
        text, href, tail = raw, self._href, ""
        pages = [span for span in self._links if not is_file_link(span[2])]
        if pages:
            _start, end, link_href = max(
                pages, key=lambda span: len(raw[span[0] : span[1]].strip())
            )
            text, tail = raw[:end], raw[end:]
            href = link_href or self._href
        self._row.append((" ".join(text.split()), href))
        tail = " ".join(tail.split())
        if tail and coerce_date(tail):
            self._row.append((tail, ""))
        self._cell, self._href, self._links = None, "", []


def coerce_date(text: str) -> date | None:
    """흔한 날짜 표기에서 날짜를 캔다(없으면 None — 지어내지 않는다).

    국내 기관 사이트 실측 형식을 모두 받는다:
      2026.07.20 · 2026-07-20 · 2026/07/20 · 2026년 7월 20일 · 26.07.20 · 20260720

    목록 표(_row_date)와 JSON API(jsonapi)와 RSS 보강이 같은 규칙을 쓰게 하는
    공용 함수. 두 자리 연도는 2000년대로 해석한다(정부 게시판에 과거 자료가
    남아 있어도 1900년대 표기는 사실상 쓰이지 않는다).
    """
    raw = text or ""
    for pattern in (_DATE_RE, _DATE_KO_RE, _DATE_COMPACT_RE):
        m = pattern.search(raw)
        if m:
            y, mo, d = (int(x) for x in m.groups())
            return parse_date(f"{y:04d}-{mo:02d}-{d:02d}")
    m = _DATE_YY_RE.search(raw)
    if m:
        yy, mo, d = (int(x) for x in m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return parse_date(f"{2000 + yy:04d}-{mo:02d}-{d:02d}")
    return None


def _row_date(cells: list[tuple[str, str]]) -> date | None:
    for text, _ in cells:
        found = coerce_date(text)
        if found:
            return found
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


def parse_rows(html_bytes: bytes) -> list[list[tuple[str, str]]]:
    """표의 행들을 (칸 텍스트, 칸의 첫 링크) 목록으로 돌려준다.

    게시판 목록(parse_list)과 피드 목록 페이지(discover) 가 같은 원리 —
    "행 안에서 칸 순서로 읽는다" — 를 공유하기 위한 공개 함수. 깨진 HTML 은
    빈 목록으로 끝난다(fail-open).
    """
    from .fetch import decode_text

    try:
        text = decode_text(html_bytes)
    except AttributeError:
        return []
    parser = _RowParser()
    try:
        parser.feed(text)
    except Exception:
        return []
    return parser.rows


def parse_list(html_bytes: bytes, base_url: str) -> list[Row]:
    """게시판 목록/메뉴 페이지 HTML에서 글 행을 뽑는다.

    같은 글이 상단 고정(공지)과 본문에 중복 등장하므로 URL 기준으로 1회만 남긴다.
    """
    import urllib.parse

    rows = parse_rows(html_bytes)

    out: list[Row] = []
    seen: set[str] = set()
    for cells in rows:
        idx = next(
            (i for i, (t, h) in enumerate(cells) if h and ARTICLE_RE.search(h) and t.strip()),
            None,
        )
        if idx is None:
            continue
        title, href = cells[idx]
        if href.lower().startswith("javascript"):
            href = ARTICLE_RE.search(href).group(0)  # 스크립트 속 글 주소를 그대로 읽는다
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
