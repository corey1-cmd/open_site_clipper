"""글 한 건의 **그림·첨부 주소**를 찾는다 — 휴대폰에서 원문 그림이 잘려 보일 때.

학교 누리집의 글 화면은 그림을 원래 크기(예: 가로 1,000px)로 두고 가로 이동과 확대를
막아 둔 곳이 많다. 휴대폰에서는 포스터의 왼쪽 위 일부만 보이고 나머지는 볼 길이 없다
(한국외대 학생지원 게시판 실측). 원문 화면은 우리가 고칠 수 없으므로, 글에 실린 그림의
**주소**를 찾아 앱이 화면 폭에 맞춰 보여 주고, 누르면 그림만 따로 열어 확대할 수 있게 한다.

원칙은 그대로다 — **본문 글자는 가져오지 않는다.** 돌려주는 것은 그림·첨부의 주소와
표 개수뿐이고, 그림은 이용자의 브라우저가 원래 사이트에서 직접 받는다(이 서버가 복제·
저장하지 않는다). deeplink 가 첨부 링크만 캐내는 것과 같은 선이다.

어떤 그림이 '글의 그림'인가 — 사이트 껍데기(로고·메뉴·배너·공공누리 마크·아이콘)를 뺀다:

  1. 글 제목이 나온 자리 **뒤**에 있는 것만(머리의 로고·배너가 빠진다)
  2. 머리·메뉴·바닥·옆줄 같은 껍데기 영역 안의 것은 뺀다(태그·class·id 로 판단)
  3. 이름(icon·btn·logo·kogl …)이나 크기(60px 미만)가 아이콘인 것은 뺀다
  4. '이전글·다음글' 이 나오면 거기서 끝(다른 글 썸네일이 빠진다)

표준 라이브러리 HTMLParser 만 쓴다. 망가진 HTML 도 끝까지 읽는다.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser

from .deeplink import _EXT_KIND

MAX_IMAGES = 40
MAX_FILES = 20
MIN_ICON_PX = 60  # 가로나 세로가 이보다 작다고 적힌 그림은 아이콘으로 본다
WIDE_PX = 640  # 표 폭이 이보다 넓게 적혀 있으면 휴대폰에서 잘린다

# 사이트 껍데기 — 이 태그 안은 글이 아니다(header·footer 는 article/main 밖일 때만).
_CHROME_TAGS = frozenset({"nav", "aside"})
_SECTION_CHROME_TAGS = frozenset({"header", "footer"})
# class·id 를 낱말로 쪼갰을 때 이 말이면 껍데기.
_CHROME_WORDS = frozenset(
    {
        "header",
        "gnb",
        "lnb",
        "snb",
        "tnb",
        "nav",
        "navi",
        "navigation",
        "menu",
        "allmenu",
        "footer",
        "foot",
        "sitemap",
        "quick",
        "quickmenu",
        "banner",
        "bnr",
        "aside",
        "sidebar",
        "util",
        "utility",
        "breadcrumb",
        "location",
        "copyright",
        "family",
        "familysite",
        "popup",
        "popzone",
        "layer",
        "skip",
        "skipnav",
        "logo",
        "sns",
        "share",
        "social",
        "related",
        "relation",
        "pagination",
        "paging",
        "prevnext",
        "comment",
        "comments",
        "reply",
        "search",
        "login",
    }
)
# 이렇게 시작하는 낱말도 껍데기('gnbWrap'·'footerArea'·'sideMenu').
_CHROME_PREFIXES = (
    "gnb",
    "lnb",
    "snb",
    "header",
    "footer",
    "sitemap",
    "quick",
    "banner",
    "breadcrumb",
    "navi",
    "sidemenu",
    "sidebar",
    "topmenu",
    "allmenu",
    "familysite",
    "popup",
)
_WORD_RE = re.compile(r"[A-Za-z][a-z0-9]*|[a-z0-9]+")

# 아이콘·단추·마크로 보이는 그림 파일 이름(경로의 낱말).
_ICON_WORDS = frozenset(
    {
        "icon",
        "icons",
        "ico",
        "btn",
        "button",
        "bullet",
        "blank",
        "spacer",
        "arrow",
        "logo",
        "sns",
        "share",
        "print",
        "close",
        "kogl",
        "opentype",
        "copyright",
        "loading",
        "spinner",
        "star",
        "rss",
        "facebook",
        "twitter",
        "kakao",
        "kakaotalk",
        "kakaostory",
        "instagram",
        "youtube",
        "naverblog",
        "wa",
        "webmark",
    }
)
# 파일 종류 아이콘('hwp.gif'·'file_pdf.png') — 이름 전체가 종류 이름이면 아이콘이다.
_TYPE_ICON_RE = re.compile(
    r"^(?:(?:icon?|file|attach|f)[_-]?)?(?:hwp|hwpx|pdf|xls|xlsx|doc|docx|ppt|pptx|zip|txt|"
    r"jpg|gif|png|file|attach|etc|img|image|down|download)\.(?:gif|png|jpe?g|svg)$"
)
_PLACEHOLDER_RE = re.compile(r"(?:blank|spacer|loading|lazy|placeholder|transparent|1x1)\b", re.I)
_LAZY_ATTRS = ("data-src", "data-original", "data-lazy-src", "data-lazy", "data-echo", "data-url")
_IMAGE_EXT_RE = re.compile(r"\.(?:jpe?g|png|gif|webp|bmp)$", re.I)
# 그림 대체 글이 이런 말이면 단추다.
_UI_ALT = (
    "인쇄",
    "목록",
    "이전",
    "다음",
    "닫기",
    "공유",
    "페이스북",
    "트위터",
    "카카오",
    "공공누리",
)

# '이전글·다음글' — 글이 끝나고 다른 글 목록이 시작되는 자리.
_END_MARKERS = frozenset({"이전글", "다음글", "이전 글", "다음 글", "윗글", "아랫글"})

# 첨부로 보는 링크 — 확장자(deeplink 와 같은 표) 또는 주소·라벨의 말.
_FILE_HINTS = (
    "download",
    "filedown",
    "file_down",
    "fileid",
    "atchfile",
    "filesn",
    "file_sn",
    "getfile",
    "attach",
    "첨부",
    "붙임",
)
_VIEW_HINTS = ("미리보기", "바로보기", "뷰어", "preview", "viewer")
_SIZE_TAIL_RE = re.compile(r"\s*[\[(]?\s*\d[\d.,]*\s*(?:bytes?|[kmg]i?b|바이트)\s*[\])]?\s*$", re.I)
_PX_RE = re.compile(r"(?:^|;)\s*(width|height)\s*:\s*(\d+(?:\.\d+)?)\s*px", re.I)

_VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_RAW = frozenset({"script", "style", "template", "svg", "textarea"})
_NORM_RE = re.compile(r"[\s\W_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class Image:
    src: str  # 화면에 넣을 주소
    full: str  # 눌렀을 때 열 주소(링크로 감싼 큰 그림이 있으면 그것)
    alt: str = ""
    width: int = 0
    height: int = 0


@dataclass(frozen=True, slots=True)
class File:
    label: str
    url: str
    kind: str  # "PDF" · "HWP" … · "보기"(웹 뷰어) · "파일"


@dataclass(slots=True)
class Media:
    images: list[Image] = field(default_factory=list)
    files: list[File] = field(default_factory=list)
    tables: int = 0
    wide_tables: int = 0
    inline_images: int = 0  # 주소 없이 본문에 박힌 그림(data:) — 원문에서만 보인다
    script_files: int = 0  # 스크립트로만 받는 첨부 — 원문에서만 받을 수 있다
    title_found: bool = False
    frames: list[str] = field(default_factory=list)  # 본문이 든 iframe 주소(같은 사이트)
    dropped: list[tuple[str, str]] = field(default_factory=list)  # (주소, 뺀 이유) — 점검용

    def as_dict(self, *, debug: bool = False) -> dict:
        out = {
            "images": [
                {"src": i.src, "full": i.full, "alt": i.alt, "w": i.width, "h": i.height}
                for i in self.images
            ],
            "files": [{"label": f.label, "url": f.url, "kind": f.kind} for f in self.files],
            "tables": self.tables,
            "wide_tables": self.wide_tables,
            "inline_images": self.inline_images,
            "script_files": self.script_files,
            "title_found": self.title_found,
        }
        if debug:
            out["dropped"] = [list(d) for d in self.dropped[:60]]
            out["frames"] = self.frames
        return out


def _words(value: str) -> list[str]:
    """'gnbWrap sub_menu' → ['gnb', 'wrap', 'sub', 'menu'] + 원래 낱말('gnbwrap')."""
    out: list[str] = []
    for chunk in re.split(r"[^A-Za-z0-9]+", value or ""):
        if not chunk:
            continue
        out.append(chunk.lower())
        parts = _WORD_RE.findall(chunk)
        if len(parts) > 1:
            out.extend(p.lower() for p in parts)
    return out


def _is_chrome_attr(attrs: dict[str, str]) -> bool:
    for key in ("id", "class", "role"):
        for w in _words(attrs.get(key) or ""):
            if w in _CHROME_WORDS or w.startswith(_CHROME_PREFIXES):
                return True
    return (attrs.get("role") or "").lower() in ("navigation", "banner", "contentinfo")


def _px(attrs: dict[str, str], name: str) -> int:
    """width/height 속성이나 style 의 px 값(없으면 0)."""
    raw = (attrs.get(name) or "").strip().lower().removesuffix("px")
    if raw.isdigit():
        return int(raw)
    for key, num in _PX_RE.findall(attrs.get("style") or ""):
        if key.lower() == name:
            return int(float(num))
    return 0


def _norm(text: str) -> str:
    return _NORM_RE.sub("", text or "").lower()


@dataclass(slots=True)
class _Table:
    pos: int
    chrome: bool
    width: int
    rows: int = 0
    cols: int = 0
    _row_cells: int = 0
    nested: bool = False


class _Scan(HTMLParser):
    """한 번 훑으며 그림·링크·표·글자 위치를 문서 순서대로 적는다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pos = 0
        self.stack: list[tuple[str, bool]] = []  # (태그, 껍데기인가)
        self.raw = 0
        self.head = 0
        self.images: list[tuple[int, dict[str, str], bool, str]] = []  # pos, attrs, chrome, a href
        self.anchors: list[tuple[int, str, str, bool]] = []  # pos, href, text, chrome
        self.frames: list[tuple[int, str, bool]] = []
        self.tables: list[_Table] = []
        self.texts: list[tuple[int, str]] = []  # 본문 글자(제목 찾기·끝 표시 찾기용)
        self._open_tables: list[_Table] = []
        self._anchor: tuple[int, str, list[str], bool] | None = None

    def _chrome_now(self) -> bool:
        return bool(self.stack) and self.stack[-1][1]

    def handle_starttag(self, tag: str, attrs_list) -> None:
        self.pos += 1
        attrs = {k.lower(): (v or "") for k, v in attrs_list}
        parent = self._chrome_now()
        in_article = any(t in ("article", "main") for t, _c in self.stack)
        chrome = (
            parent
            or tag in _CHROME_TAGS
            or (tag in _SECTION_CHROME_TAGS and not in_article)
            or _is_chrome_attr(attrs)
        )
        if tag == "head":
            self.head += 1
        if tag in _RAW:
            self.raw += 1
        if tag == "img":
            href = self._anchor[1] if self._anchor else ""
            self.images.append((self.pos, attrs, chrome, href))
        elif tag == "a":
            self._close_anchor()
            self._anchor = (self.pos, attrs.get("href") or "", [], chrome)
        elif tag in ("iframe", "frame") and attrs.get("src"):
            self.frames.append((self.pos, attrs["src"], chrome))
        elif tag == "table":
            if self._open_tables:
                self._open_tables[-1].nested = True
            t = _Table(self.pos, chrome, _px(attrs, "width"))
            self._open_tables.append(t)
            self.tables.append(t)
        elif tag == "tr" and self._open_tables:
            t = self._open_tables[-1]
            t.rows += 1
            t._row_cells = 0
        elif tag in ("td", "th") and self._open_tables:
            t = self._open_tables[-1]
            span = attrs.get("colspan") or "1"
            t._row_cells += int(span) if span.isdigit() else 1
            t.cols = max(t.cols, t._row_cells)
        if tag not in _VOID:
            self.stack.append((tag, chrome))

    def handle_startendtag(self, tag: str, attrs_list) -> None:
        self.handle_starttag(tag, attrs_list)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._close_anchor()
        if not any(t == tag for t, _c in self.stack):
            return  # 짝 없는 닫는 태그 — 무시
        while self.stack:
            t, _c = self.stack.pop()
            if t in _RAW:
                self.raw = max(0, self.raw - 1)
            if t == "head":
                self.head = max(0, self.head - 1)
            if t == "table" and self._open_tables:
                self._open_tables.pop()
            if t == tag:
                break

    def _close_anchor(self) -> None:
        if self._anchor is not None:
            pos, href, buf, chrome = self._anchor
            self.anchors.append((pos, href, " ".join("".join(buf).split()), chrome))
            self._anchor = None

    def handle_data(self, data: str) -> None:
        if self.raw or self.head:
            return
        if self._anchor is not None:
            self._anchor[2].append(data)
        text = data.strip()
        if text:
            self.texts.append((self.pos, text))

    def close(self) -> None:
        super().close()
        self._close_anchor()


_TAG_HEAD_RE = re.compile(r"^(?:\s*[\[(【<〈][^\])】>〉]{1,12}[\])】>〉])+\s*")


def _title_pos(texts: list[tuple[int, str]], title: str) -> int:
    """본문에서 글 제목이 처음 나온 위치(못 찾으면 -1).

    제목은 태그로 쪼개져 있기도 하다('<b>[공지]</b> 장학생 모집') — 글자를 이어 붙여
    공백·기호를 뺀 채 앞부분(최대 16자)을 찾는다. 목록과 글 화면의 말머리가 다를 수
    있어('[공통][교외] …' ↔ '…') 말머리를 뗀 제목으로도 찾는다.
    """
    joined: list[str] = []
    owners: list[int] = []
    for pos, text in texts:
        n = _norm(text)
        joined.append(n)
        owners.extend([pos] * len(n))
    body = "".join(joined)
    for candidate in (title, _TAG_HEAD_RE.sub("", title)):
        key = _norm(candidate)[:16]
        if len(key) < 6:
            continue
        hit = body.find(key)
        if hit >= 0:
            return owners[hit]
    return -1


def _end_pos(texts: list[tuple[int, str]], start: int) -> int:
    """제목 뒤 '이전글·다음글' 위치(없으면 아주 큰 수)."""
    for pos, text in texts:
        if pos > start and " ".join(text.split()) in _END_MARKERS:
            return pos
    return 1 << 60


def _pick_src(attrs: dict[str, str]) -> str:
    """지연 로딩(data-src …)을 먼저 — src 가 자리표시 그림이면 진짜 주소가 거기 있다."""
    src = (attrs.get("src") or "").strip()
    if src and not src.startswith("data:") and not _PLACEHOLDER_RE.search(src):
        return src
    for key in _LAZY_ATTRS:
        val = (attrs.get(key) or "").strip()
        if val and not val.startswith("data:"):
            return val
    return src


def _icon_reason(url: str, attrs: dict[str, str]) -> str:
    path = urllib.parse.urlsplit(url).path.lower()
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".svg"):
        return "svg"
    if _TYPE_ICON_RE.match(name):
        return "파일 종류 아이콘"
    for w in _words(path):
        if w in _ICON_WORDS:
            return f"아이콘 이름({w})"
    w, h = _px(attrs, "width"), _px(attrs, "height")
    if (w and w < MIN_ICON_PX) or (h and h < MIN_ICON_PX):
        return f"작음({w}x{h})"
    alt = attrs.get("alt") or ""
    if alt and any(alt.strip().startswith(u) for u in _UI_ALT):
        return f"단추({alt[:10]})"
    return ""


def _file_kind(url: str, label: str) -> str:
    path = urllib.parse.urlsplit(url).path.lower()
    for ext, kind in _EXT_KIND.items():
        if path.endswith(ext) or label.lower().endswith(ext):
            return kind
    hay = f"{url} {label}".lower()
    if any(h in hay for h in _VIEW_HINTS):
        return "보기"
    if any(h in hay for h in _FILE_HINTS):
        return "파일"
    return ""


def _clean_label(text: str, url: str) -> str:
    label = _SIZE_TAIL_RE.sub("", " ".join((text or "").split()))
    for word in ("다운로드", "내려받기", "첨부파일"):
        label = label.removesuffix(word).strip()
    if not label:
        name = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
        label = name if "." in name else "첨부"
    return label[:80]


def extract(html: str, base_url: str, *, title: str = "") -> Media:
    """글 화면 HTML → 그림·첨부 주소와 표 개수(본문 글자는 취하지 않는다)."""
    scan = _Scan()
    try:
        scan.feed(html or "")
        scan.close()
    except Exception:  # 망가진 HTML — 읽은 데까지만 쓴다
        pass
    media = Media()
    start = _title_pos(scan.texts, title) if title else -1
    media.title_found = start >= 0
    start = max(start, 0)
    end = _end_pos(scan.texts, start) if media.title_found else 1 << 60

    seen: set[str] = set()
    picks: list[tuple[int, Image]] = []
    for pos, attrs, chrome, href in scan.images:
        raw = _pick_src(attrs)
        if raw.startswith("data:"):
            if pos > start and not chrome:
                media.inline_images += 1
            continue
        url = urllib.parse.urljoin(base_url, raw) if raw else ""
        why = ""
        if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            why = "주소 없음"
        elif chrome:
            why = "껍데기 영역"
        elif pos < start:
            why = "제목 앞"
        elif pos > end:
            why = "이전글·다음글 뒤"
        else:
            why = _icon_reason(url, attrs)
        if why:
            media.dropped.append((url or raw, why))
            continue
        if url in seen:
            continue
        seen.add(url)
        full = url
        if href and not href.lower().startswith(("javascript:", "#")):
            target = urllib.parse.urljoin(base_url, href)
            if _IMAGE_EXT_RE.search(urllib.parse.urlsplit(target).path):
                full = target
        img = Image(
            src=url,
            full=full,
            alt=" ".join((attrs.get("alt") or attrs.get("title") or "").split())[:80],
            width=_px(attrs, "width"),
            height=_px(attrs, "height"),
        )
        picks.append((pos, img))
    media.images = [img for _p, img in picks[:MAX_IMAGES]]

    files_seen: set[str] = set()
    for pos, href, text, chrome in scan.anchors:
        if chrome or pos < start or pos > end:
            continue
        low = href.strip().lower()
        if low.startswith("javascript:"):
            if _file_kind(href, text):
                media.script_files += 1
            continue
        if not href.strip() or low.startswith(("#", "mailto:", "tel:")):
            continue
        url = urllib.parse.urljoin(base_url, href.strip())
        if urllib.parse.urlsplit(url).scheme not in ("http", "https") or url in files_seen:
            continue
        kind = _file_kind(url, text)
        if not kind:
            continue
        files_seen.add(url)
        media.files.append(File(_clean_label(text, url), url, kind))
        if len(media.files) >= MAX_FILES:
            break

    for t in scan.tables:
        if t.chrome or t.pos < start or t.pos > end:
            continue
        if t.rows >= 2 and t.cols >= 2 and not t.nested:
            media.tables += 1
            if t.width >= WIDE_PX or t.cols >= 7:
                media.wide_tables += 1

    host = urllib.parse.urlsplit(base_url).hostname or ""
    for pos, src, chrome in scan.frames:
        url = urllib.parse.urljoin(base_url, src)
        same = (urllib.parse.urlsplit(url).hostname or "") == host
        if same and not chrome and pos > start and pos < end:
            media.frames.append(url)
    return media
