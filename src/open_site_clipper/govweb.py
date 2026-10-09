"""정부 표준홈페이지 게시판 파서 — RSS 가 없는 채용·입찰 목록을 읽는다.

부처는 공지·보도자료를 RSS 로 내주지만(정보구독서비스), **채용·입찰은 RSS 가
없는 경우가 많다**(문체부 실측: 목록에 4종뿐, 채용·입찰 제외). 그래서 목록
HTML 을 직접 읽는다.

**K2Web 파서와 다른 점**: K2Web 은 글 링크가 `/bbs/{site}/{board}/{no}/artclView.do`
라는 고정 문법이라 그걸 붙잡았다. 정부 표준홈페이지는 그렇지 않다 — 문체부
채용 게시판을 실제로 열어 보니 상세 링크가 이렇게 제각각이었다:

    https://www.museum.go.kr/MUSEUM/contents/M0701030000.do?...   (국립중앙박물관)
    https://www.karts.ac.kr/nri/bbs/NuriBbsDetail.do?...          (한국예술종합학교)
    https://www.mmca.go.kr/pr/employmentDetail.do?...             (국립현대미술관)
    javascript:void(0);                                            (링크 없음)

소속·공공기관 채용공고를 **각 기관 누리집과 연동**해 보여주기 때문이다. 따라서
링크 문법에 기대면 안 된다. 대신 K2Web 파서의 **다른** 원리 하나만 가져온다:

  **표의 칸 순서** — 번호 → 제목 → 게시일 → 마감일 → 조회.
  즉 "행에서 진짜 링크를 단 가장 긴 텍스트 칸"이 제목이고, 그 뒤 날짜꼴 칸이
  발행일이다. 스킨·CMS 가 달라도 게시판이 표인 한 버틴다.

부수적으로 제목 앞 `[기관명]` 접두를 부서(unit)로 뽑는다 — 연동 게시판에서는
이게 실제 작성 기관이다.
"""

from __future__ import annotations

import re
import urllib.parse
from html.parser import HTMLParser

from .k2web_parse import Row, coerce_date, parse_rows

MIN_TITLE_LEN = 4
MAX_UNIT_LEN = 40

# 제목 앞 '[국립중앙박물관] …' 접두 — 연동 게시판에서 실제 작성 기관.
_ORG_PREFIX_RE = re.compile(r"^\[([^\]]{2,40})\]\s*")
# 목록에 섞이는 상태 표시 — 제목의 일부가 아니다.
_BADGE_RE = re.compile(r"^(새글|NEW|신규|공지)\s+", re.I)
# 첨부파일 칸 — '한글 파일 PDF 파일 이미지 파일' 처럼 파일 종류만 나열된다.
# 이 칸이 제목보다 길어져 제목 자리를 빼앗는 일이 실제로 있었다(새만금개발청).
_ATTACH_RE = re.compile(
    r"^(?:(?:한글|워드|MS워드|엑셀|PDF|이미지|기타|압축|한셀|아래아)\s*파일\s*)+$", re.I
)
# 목록이 아니라 안내문·메뉴가 잘못 잡힌 경우 — 주소가 제목 자리에 온다.
_URL_TITLE_RE = re.compile(r"^https?://", re.I)


_DATE_LABEL_RE = re.compile(r"등록일|작성일|게시일|날짜|일자|date|posted", re.I)
_DATE_NOISE_RE = re.compile(r"[\d\s.\-/:()~:]+")


def _is_date_only(text: str) -> bool:
    """'2026.10.01' · '등록일 : 2026-10-01' · '2026년 10월 1일' 처럼 날짜뿐인 칸.

    목록형 게시판은 제목과 날짜가 같은 링크 안에 들어 있어, 날짜 칸이 제목보다
    길면 제목 자리를 빼앗는다 — 그래서 날짜뿐인 칸은 제목 후보에서 뺀다.
    """
    if not coerce_date(text):
        return False
    rest = _DATE_NOISE_RE.sub("", _DATE_LABEL_RE.sub("", text))
    return len(rest) <= 4  # '년월일'·요일 한 글자 정도만 남아야 한다


def _is_junk_title(text: str) -> bool:
    """제목으로 볼 수 없는 칸 — 첨부 목록·주소·지나치게 긴 메뉴 뭉치."""
    t = " ".join((text or "").split())
    if not t or _ATTACH_RE.match(t) or _URL_TITLE_RE.match(t):
        return True
    # 메뉴 전체가 한 칸에 뭉쳐 들어온 경우(성평등가족부·식약처에서 관측)
    return len(t) > 120


def _clean_title(text: str) -> tuple[str, str]:
    """제목에서 '[기관명]' 접두와 '새글' 배지를 떼어 (제목, 기관명)으로."""
    unit = ""
    title = _BADGE_RE.sub("", text.strip())
    m = _ORG_PREFIX_RE.match(title)
    if m:
        unit = m.group(1).strip()[:MAX_UNIT_LEN]
        title = title[m.end() :].strip()
    title = _BADGE_RE.sub("", title)  # '[기관] 새글 제목' 순서도 있다
    return title, unit


class _ItemParser(HTMLParser):
    """`<li>` 하나를 한 행으로, 그 안의 요소 하나하나를 칸으로 읽는다.

    대학·신형 정부 누리집 게시판은 표 대신 목록을 쓴다:

        <li><a href="view.do?no=1"><strong>제목</strong><span>2026.10.01</span></a></li>
        <li><dl><dt><a href="…">제목</a></dt><dd class="date">2026-10-01</dd></dl></li>

    칸 = 요소 경계에서 끊은 글 조각, 링크 안의 조각은 그 링크 주소를 단다.
    그러면 표와 같은 원리(가장 긴 링크 칸 = 제목, 그 뒤 날짜 = 게시일)가 그대로 선다.
    `<li>` 안에 `<li>` 가 있으면(펼침 메뉴) 안쪽이 따로 한 행이 된다.
    """

    _VOID = frozenset({"br", "img", "hr", "input", "wbr", "meta", "link", "source"})
    _SKIP = frozenset({"script", "style", "template", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, str]]] = []
        self._stack: list[list[tuple[str, str]]] = []  # 열린 <li> 마다 칸 목록
        self._buf: list[str] = []
        self._href: list[str] = []  # 열린 <a> 의 주소(중첩 대비 스택)
        self._skip = 0

    def _flush(self) -> None:
        text = " ".join("".join(self._buf).split())
        self._buf = []
        if text and self._stack:
            self._stack[-1].append((text, self._href[-1] if self._href else ""))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip += 1
            return
        self._flush()
        if tag == "li":
            self._stack.append([])
        elif tag == "a":
            self._href.append((dict(attrs).get("href") or "").strip())

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip and self._stack:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if tag in self._VOID:
            return
        self._flush()
        if tag == "a" and self._href:
            self._href.pop()
        elif tag == "li" and self._stack:
            row = self._stack.pop()
            if row:
                self.rows.append(row)


def parse_items(html_bytes: bytes) -> list[list[tuple[str, str]]]:
    """`<li>` 목록을 행·칸으로. 깨진 HTML 은 빈 목록(fail-open)."""
    from .fetch import decode_text

    try:
        parser = _ItemParser()
        parser.feed(decode_text(html_bytes))
        parser.close()
    except Exception:
        return []
    return parser.rows


def parse_list(html_bytes: bytes, base_url: str) -> list[Row]:
    """게시판 목록 HTML 에서 글 행을 뽑는다(링크 문법에 의존하지 않음).

    표(`<tr>`)를 먼저 읽고, 표에서 날짜 달린 글이 MIN_DATED 건도 안 나오면
    `<li>` 목록을 읽는다. 목록 쪽은 **날짜가 있는 행만** 글로 본다 — 날짜 없는
    `<li>` 는 거의 언제나 메뉴라서, 섞이면 메뉴를 글로 내보내게 된다.
    """
    table = _rows_from(parse_rows(html_bytes), base_url)
    dated = sum(1 for r in table if r.published)
    if dated >= MIN_DATED:
        return table
    items = [r for r in _rows_from(parse_items(html_bytes), base_url) if r.published]
    return items if len(items) > dated else table


MIN_DATED = 2


def _rows_from(rows: list[list[tuple[str, str]]], base_url: str) -> list[Row]:
    out: list[Row] = []
    seen: set[str] = set()

    for cells in rows:
        # ① 제목 칸 = 진짜 http(s) 링크를 달고 텍스트가 가장 긴 칸.
        #    (첨부파일 아이콘 링크는 텍스트가 짧아 자연히 밀린다)
        best: int | None = None
        best_url = ""
        for i, (text, href) in enumerate(cells):
            if not href or not text.strip() or _is_junk_title(text) or _is_date_only(text):
                continue
            url = urllib.parse.urljoin(base_url, href)
            if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
                continue  # javascript:void(0) · #none 등 제외
            if best is None or len(text) > len(cells[best][0]):
                best, best_url = i, url
        if best is None:
            continue

        title, unit = _clean_title(cells[best][0])
        if len(title) < MIN_TITLE_LEN:
            continue
        if best_url in seen:
            continue
        seen.add(best_url)

        # ② 발행일 = 제목 칸 **뒤쪽**의 첫 날짜(게시일). 마감일이 그다음에 오므로
        #    앞에서부터 찾아야 게시일을 잡는다.
        published = None
        for text, _ in cells[best + 1 :]:
            published = coerce_date(text)
            if published:
                break
        if published is None:
            # 목록형은 날짜가 제목 앞에 오기도 한다('<span>10.01</span><a>제목</a>').
            # 제목 칸 자체(제목 속 '2026년 …' 같은 숫자)는 보지 않는다.
            for text, _ in reversed(cells[:best]):
                published = coerce_date(text) if _is_date_only(text) else None
                if published:
                    break

        out.append(Row(title=title, url=best_url, unit=unit, published=published))
    return out
