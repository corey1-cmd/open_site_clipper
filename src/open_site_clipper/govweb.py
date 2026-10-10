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

import html
import re
import urllib.parse
from html.parser import HTMLParser

from .k2web_parse import Row, anchor_href, coerce_date, is_glyph, parse_rows

MIN_TITLE_LEN = 4
MAX_UNIT_LEN = 40

# 제목 앞 '[국립중앙박물관] …' 접두 — 연동 게시판에서 실제 작성 기관.
_ORG_PREFIX_RE = re.compile(r"^\[([^\]]{2,40})\]\s*")
# 목록에 섞이는 상태 표시 — 제목의 일부가 아니다.
_BADGE_RE = re.compile(r"^(새글|NEW|신규|공지)\s+", re.I)
# 제목 **뒤**에 붙는 배지 — K2Web 목록은 '… 모집 공고(~11/11) 새글' 처럼 끝에 단다.
_BADGE_TAIL_RE = re.compile(r"\s+(새글|새 글|NEW|N)$", re.I)
# 첨부 표시 꼬리 — '… 공고 첨부파일이 1개 있음'(인하대)·'… 공개첨부파일'(국민통합위)·
# '… 안내 첨부파일 있'(잘림). 화면 읽기용 숨은 글자가 제목 칸에 섞인 것이다.
_ATTACH_TAIL_RE = re.compile(
    r"\s*첨부\s*파일(?:이|은)?\s*(?:\d+\s*개\s*)?(?:있음|있습니다|있|존재)?\.?$"
)
_ATTACH_HEAD_RE = re.compile(r"^첨부\s*파일\s*있음\s*(?:열기)?\s*")
# 두 번 이스케이프된 문자 참조 — '&lsquo;2026 산학연협력 EXPO&rsquo;'(신라대 실측).
# 세미콜론까지 갖춘 것만 푼다('R&D'·'Q&A' 는 그대로). 잘린 꼬리('…&middo')는 뗀다.
_ENTITY_RE = re.compile(r"&(?:#\d{1,7}|#x[0-9a-f]{1,6}|[a-z][a-z0-9]{1,7});", re.I)
_BROKEN_ENTITY_TAIL_RE = re.compile(r"&[a-z]{2,8}$", re.I)
# 폭 없는 공백 등 보이지 않는 글자 — 같은 제목이 다르게 보여 겹침 정리를 깬다
_INVISIBLE_RE = re.compile("[\u200b-\u200d\u2060\ufeff]")
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


# 잠긴 글 — 제목 대신 '비공개 - 비밀글이며 관리자와 작성자만 …' 이 나온다(민원·문의 게시판).
_PAGING_RE = re.compile(
    r"^(?:[\d\s<>«»‹›|·./\-]|처음|이전|다음|마지막|맨앞|맨뒤|prev|next|first|last)+$", re.I
)
_SECRET_RE = re.compile(r"^(?:비공개|비밀글)|비밀글(?:이며|입니다)|작성자만 열람", re.I)
# 광고 도배 글 — 문의·참여 게시판에 올라온다(전주기전대 실측 '조루치료제{viavvv.com}비아그라…').
# 제목만으로 분명한 말만 둔다('카지노 채용' 같은 진짜 공고는 걸리지 않게).
_SPAM_RE = re.compile(
    r"비아그라|시알리스|레비트라|조루\s*치료|발기\s*부전|바카라|먹튀|토토\s*사이트|카지노\s*사이트|"
    r"온라인\s*카지노|출장\s*(?:안마|마사지)|\{\s*[a-z0-9-]+\.(?:com|net|xyz|top|shop|kr)\s*\}",
    re.I,
)
# 제목 대신 글쓴이 아이디가 잡힌 경우('teamWebMaster' — 중앙대 스포츠단 실측)
_USER_ID_RE = re.compile(
    r"^(?=[A-Za-z0-9_.]*(?:[a-z][A-Z]|admin|master|manager))[A-Za-z][A-Za-z0-9_.]{3,24}$"
)


def _is_junk_title(text: str) -> bool:
    """제목으로 볼 수 없는 칸 — 첨부 목록·주소·잠긴 글·지나치게 긴 메뉴 뭉치."""
    t = " ".join((text or "").split())
    if not t or _ATTACH_RE.match(t) or _URL_TITLE_RE.match(t) or _SECRET_RE.search(t):
        return True
    if _SPAM_RE.search(t) or _USER_ID_RE.match(t):
        return True
    # 쪽 번호 줄('1 2 3 4 5 … 10')·'자세히보기' 같은 단추 글자가 글로 잡혔다(농협대·한예종 실측)
    from . import categories

    if _PAGING_RE.match(t) or categories.is_meaningless(t):
        return True
    # 메뉴 전체가 한 칸에 뭉쳐 들어온 경우(성평등가족부·식약처에서 관측)
    return len(t) > 120


def _unescape_twice(text: str) -> str:
    if "&" not in text:
        return text
    fixed = _ENTITY_RE.sub(lambda m: html.unescape(m.group(0)), text)
    if fixed != text:
        fixed = _BROKEN_ENTITY_TAIL_RE.sub("", fixed)
    return fixed


def _clean_title(text: str) -> tuple[str, str]:
    """제목에서 '[기관명]' 접두와 '새글'·'첨부파일 있음' 표시를 떼어 (제목, 기관명)으로."""
    unit = ""
    title = _unescape_twice(" ".join(_INVISIBLE_RE.sub("", text).split()))
    title = _ATTACH_HEAD_RE.sub("", title)
    title = _BADGE_RE.sub("", title)
    m = _ORG_PREFIX_RE.match(title)
    if m:
        unit = m.group(1).strip()[:MAX_UNIT_LEN]
        title = title[m.end() :].strip()
    title = _BADGE_RE.sub("", title)  # '[기관] 새글 제목' 순서도 있다
    for _ in range(2):  # '… 새글 첨부파일이 1개 있음' — 꼬리가 겹친다
        title = _BADGE_TAIL_RE.sub("", _ATTACH_TAIL_RE.sub("", title)).strip()
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
        self._glyph: list[str] = []  # 열린 아이콘 글꼴 요소(그 안 글자는 읽지 않는다)

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
        if tag not in self._VOID and is_glyph(attrs):
            self._glyph.append(tag)
        if tag == "li":
            self._stack.append([])
        elif tag == "a":
            self._href.append(anchor_href(attrs))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip and not self._glyph and self._stack:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if tag in self._VOID:
            return
        if self._glyph and tag == self._glyph[-1]:
            self._glyph.pop()
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


def _real_link(href: str, base_url: str) -> str:
    """진짜 글 주소면 절대 주소, 아니면 "" — '#'·'#none' 은 목록 자기 자신이다."""
    h = (href or "").strip()
    if not h or h.startswith("#") or h.lower().startswith("javascript"):
        return ""
    url = urllib.parse.urljoin(base_url, h)
    return url if urllib.parse.urlsplit(url).scheme in ("http", "https") else ""


# 스크립트 안에 주소가 문자열로 들어 있는 경우 — location.href='/bbs/view.do?id=3' ·
# window.open("https://…") · fn_move('/notice/view.do?no=3'). 지어내지 않고 **읽는다**.
_SCRIPT_URL_RE = re.compile(r"""['"]((?:https?://|/)[^'"\s]+)['"]""")


def _script_url(href: str, base_url: str) -> str:
    if not (href or "").lower().startswith("javascript"):
        return ""
    for m in _SCRIPT_URL_RE.finditer(href):
        path = m.group(1)
        tail = path.split("?", 1)[0].rsplit("/", 1)[-1]
        if "?" in path or "." in tail:  # 파일·화면 주소꼴만(그냥 '/' 같은 것은 버린다)
            url = urllib.parse.urljoin(base_url, path)
            if urllib.parse.urlsplit(url).scheme in ("http", "https"):
                return url
    return ""


def _is_script_link(href: str) -> bool:
    h = (href or "").strip().lower()
    return h.startswith("#") or h.startswith("javascript")


def _board_anchor(base_url: str, title: str) -> str:
    page = urllib.parse.urlsplit(base_url)._replace(fragment="").geturl()
    words = " ".join(title.split())[:80]
    return f"{page}#{urllib.parse.quote(words)}"


def _rows_from(rows: list[list[tuple[str, str]]], base_url: str) -> list[Row]:
    out: list[Row] = []
    seen: set[str] = set()

    for cells in rows:
        # ① 제목 칸 = 진짜 http(s) 링크를 달고 텍스트가 가장 긴 칸.
        #    (첨부파일 아이콘 링크는 텍스트가 짧아 자연히 밀린다)
        best: int | None = None
        best_url = ""
        script: int | None = None  # 주소가 스크립트에만 있는 제목 칸(진짜 링크가 없을 때만 쓴다)
        for i, (text, href) in enumerate(cells):
            if not href or not text.strip() or _is_junk_title(text) or _is_date_only(text):
                continue
            url = _real_link(href, base_url) or _script_url(href, base_url)
            if not url:
                if _is_script_link(href) and (script is None or len(text) > len(cells[script][0])):
                    script = i
                continue  # javascript:void(0) · #none 등 — 진짜 주소가 아니다
            if best is None or len(text) > len(cells[best][0]):
                best, best_url = i, url
        if best is None and script is not None:
            # 글 주소를 알 수 없으면 **목록 페이지**로 건다(제목을 조각으로 붙여 글마다
            # 다른 주소가 되게). 지어낸 상세 주소가 아니라, 글이 실제로 보이는 곳이다.
            best = script
            best_url = _board_anchor(base_url, cells[script][0])
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


# ── 게시판 이름 ──────────────────────────────────────────────────────────────
# 제목 칸의 구분자 — '장학공지 | 한국외국어대학교' · '대학생활 > 장학 > 장학공지'
_NAME_SEP_RE = re.compile(r"\s*(?:[|>:·</]|\s[-–—]\s|(?<=[가-힣])-(?=[가-힣]))\s*")
MAX_NAME_LEN = 14


class _HeadParser(HTMLParser):
    """`<title>` 과 앞쪽 제목 태그(h1~h3)의 글만 모은다."""

    _SKIP = frozenset({"script", "style", "template", "noscript", "nav", "footer"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.heads: list[str] = []
        self._tag = ""
        self._buf: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip += 1
        elif not self._skip and tag in ("title", "h1", "h2", "h3") and not self._tag:
            self._tag, self._buf = tag, []

    def handle_data(self, data: str) -> None:
        if self._tag:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == self._tag:
            text = " ".join("".join(self._buf).split())
            if tag == "title":
                self.title = self.title or text
            elif text and len(self.heads) < 12:
                self.heads.append(text)
            self._tag = ""


def page_label(html_bytes: bytes | None) -> str:
    """목록 페이지가 스스로 밝힌 게시판 이름 — '장학공지'·'학사 공지사항' 같은 것.

    앵커가 'READ'·'더보기'뿐이라 이름을 모르는 게시판에 쓴다. 갈래 사전에 걸리는
    짧은 조각만 받는다(기관 이름·메뉴 뭉치는 버린다). 못 찾으면 "".
    """
    from . import categories
    from .fetch import decode_text

    if not html_bytes:
        return ""
    parser = _HeadParser()
    try:
        parser.feed(decode_text(html_bytes))
    except Exception:
        return ""
    for text in [parser.title, *parser.heads]:
        for part in _NAME_SEP_RE.split(text or ""):
            part = categories.tidy_label(part)
            if 2 <= len(part) <= MAX_NAME_LEN and categories.classify(part):
                return part
    return ""
