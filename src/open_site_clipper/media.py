"""글 한 건의 **그림·첨부 주소**를 찾는다 — 휴대폰에서 원문 그림이 잘려 보일 때.

학교 누리집의 글 화면은 그림을 원래 크기(예: 가로 1,000px)로 두고 가로 이동과 확대를
막아 둔 곳이 많다. 휴대폰에서는 포스터의 왼쪽 위 일부만 보이고 나머지는 볼 길이 없다
(한국외대 학생지원 게시판 실측). 원문 화면은 우리가 고칠 수 없으므로, 글에 실린 그림의
**주소**를 찾아 앱이 화면 폭에 맞춰 보여 주고, 누르면 그림만 따로 열어 확대할 수 있게 한다.

원칙은 그대로다 — **본문 글자는 가져오지 않는다.** 돌려주는 것은 그림·첨부의 주소와
표 개수뿐이고, 그림은 이용자의 브라우저가 원래 사이트에서 직접 받는다(이 서버가 복제·
저장하지 않는다). deeplink 가 첨부 링크만 캐내는 것과 같은 선이다.

어떤 그림이 '글의 그림'인가 — 사이트 껍데기를 뺀다(실측 198곳 431개 글로 맞춘 규칙):

  1. 글 제목이 나온 자리 **뒤**에 있는 것만(머리의 로고·배너가 빠진다)
     — 제목을 못 찾은 화면(대기 화면·메뉴 화면)에서는 **올린** 그림만 남긴다
  2. 머리·메뉴·바닥·옆줄·배너 같은 껍데기 영역 안의 것은 뺀다(태그·class·id)
  3. 사이트 꾸밈 그림 경로(/images/common/·/_res/·/layout/ …)·아이콘 이름·60px 미만은 뺀다
     — 단 편집기·첨부로 **올린** 그림 경로(/upload/·/CrossEditor/·날짜 폴더 …)는 살린다
  4. 첨부 링크 안의 단추 그림, 다른 글로 가는 링크 안의 그림(관련 글 썸네일)은 뺀다
  5. '이전글·다음글' 이 나오면 거기서 끝
  6. 같은 그림(작은 그림 → 큰 그림 링크)은 한 번만
  7. (allow 를 주면) 그 밖의 사이트에 있는 그림·첨부는 세기만 한다 — 글쓴이가 남의
     사이트 그림을 붙였거나(책 표지·기사 사진) 문의 게시판에 광고 그림이 올라온 경우

표준 라이브러리 HTMLParser 만 쓴다. 망가진 HTML 도 끝까지 읽는다.
"""

from __future__ import annotations

import itertools
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser

from .deeplink import _EXT_KIND
from .probe import looks_like_article

MAX_IMAGES = 40
MAX_FILES = 20
MIN_ICON_PX = 60  # 가로나 세로가 이보다 작다고 적힌 그림은 아이콘으로 본다
WIDE_PX = 640  # 표 폭이 이보다 넓게 적혀 있으면 휴대폰에서 잘린다

# ── 껍데기 영역 ─────────────────────────────────────────────────────────────
# 이 태그 안은 글이 아니다(header·footer 는 article/main 밖일 때만).
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
# 이웃한 두 낱말을 붙이면 껍데기 — 'user_service_list'(대구가톨릭대 바로가기 묶음) …
_CHROME_JOINED = frozenset(
    {"userservice", "quicklink", "quicklinks", "sitelink", "sitelinks", "relatedsite", "linksite"}
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

# ── 그림 거르기 ─────────────────────────────────────────────────────────────
# 아이콘·단추·마크로 보이는 그림 파일 이름의 낱말(끝의 숫자는 떼고, 이웃한 두 낱말을
# 붙여서도 본다: btn01 → btn, sub-visual04 → subvisual). 올린 그림이어도 뺀다.
_ICON_WORDS = frozenset(
    {
        "icon",
        "icons",
        "ico",
        "btn",
        "button",
        "buttons",
        "bullet",
        "bul",
        "blank",
        "spacer",
        "arrow",
        "arr",
        "kogl",
        "opentype",
        "opencode",
        "loading",
        "spinner",
        "standby",  # 접속 대기 화면의 그림(극동대 실측)
        "subvisual",
        "mainvisual",
        "webmark",
        "wamark",
    }
)
# 사이트 그림 경로(올린 그림이 아닌 곳)에서만 아이콘으로 보는 낱말 — 올린 그림이면
# 'error.png'(오류 화면 안내)·'logo.png'(로고 공모 결과)처럼 글의 그림일 수 있다.
_SITE_ICON_WORDS = frozenset(
    {
        "prev",
        "next",
        "home",
        "tel",
        "logo",
        "sns",
        "share",
        "print",
        "close",
        "copyright",
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
        "adobe",
        "viewer",
        "wa",
        "error",  # 기상청 과학관 'Error.jpg'
        "attachment",  # 질병청 게시판 'images/attachment.png'
        "visual",
        "top",
        "gotop",
        "more",
    }
)
# 파일 종류 아이콘('hwp.gif'·'file_pdf.png'·'ichwp.gif') — 이름 전체가 종류 이름이면 아이콘이다.
_TYPE_ICON_RE = re.compile(
    r"^(?:(?:icon?|ic|file|attach|f)[_-]?)?(?:hwp|hwpx|pdf|xls|xlsx|doc|docx|ppt|pptx|zip|txt|"
    r"jpg|gif|png|file|attach|etc|img|image|down|download)\.(?:gif|png|jpe?g|svg)$"
)
# 사이트를 꾸미는 그림이 사는 폴더 — '/_res/' · '/resource/' · '/images/common/' …
_ASSET_DIRS = frozenset(
    {
        "_res",
        "res",
        "resource",
        "resources",
        "static",
        "assets",
        "asset",
        "template",
        "templates",
        "tpl",
        "skin",
        "skins",
        "theme",
        "themes",
        "layout",
        "layouts",
        "design",
        "_img",
        "_images",
        "common",
        "cmmn",
        "icon",
        "icons",
        "ico",
        "fileico",
        "fileicon",
        "btn",
        "button",
        "buttons",
        "bullet",
    }
)
_IMG_DIRS = frozenset({"images", "image", "img", "imgs"})
# 그림 폴더와 함께(앞이든 뒤든) 나오면 꾸밈 그림 — '/bbs/…/images/' · '/images/videoNew/main/'
_IMG_UI_DIRS = frozenset(
    {"board", "bbs", "btn", "button", "buttons", "icon", "icons", "main", "sub", "comm", "cmm"}
)
# XpressEngine 이 목록에 쓰려고 만든 다른 글의 썸네일('files/thumbnails/…/300x300.fill.jpg').
_XE_THUMB_RE = re.compile(r"^\d+x\d+\.(?:fill|crop|ratio)\.(?:jpe?g|png|gif|webp)$", re.I)
# 배너·팝업은 올린 그림이어도 글이 아니다(누리집 공통 띠).
_BANNER_DIRS = frozenset({"banner", "banners", "bnr", "popup", "popups", "popzone", "quick"})
# 편집기·첨부로 **올린** 그림의 폴더 — 여기 있으면 꾸밈 그림 규칙을 적용하지 않는다.
_UPLOAD_DIRS = frozenset(
    {
        "upload",
        "uploads",
        "editor",
        "editorimage",
        "editerimage",
        "data",
        "_data",
        "bbsdata",
        "attach",
        "attachment",
        "attachments",
        "atchmnfl",
        "files",
        "file",
        "binary",
        "fms",
        "crosseditor",
        "synapeditor",
        "namo",
        "smarteditor",
        "se2",
        "ckeditor",
        "cheditor",
        "webzine",
    }
)
# 날짜 폴더·긴 숫자·해시 이름 — 올린 파일의 흔적.
_UPLOADISH_RE = re.compile(r"^(?:(?:19|20)\d{2}|\d{6,}|[0-9a-f]{16,})$", re.I)
# 파일 이름이 이렇게 **시작**하면 올린 파일('20261006134118FJinfe….jpg'·uuid·해시).
_UPLOAD_STEM_RE = re.compile(r"^(?:\d{6,}|[0-9a-f]{16,}|[0-9a-f]{8}-[0-9a-f]{4}-)", re.I)
# 그림 주소의 쿼리가 이 이름뿐이면 캐시용 꼬리('?v=1.2'·'?resVer=…') — 올린 그림의 표시가 아니다.
_VERSION_KEYS = frozenset(
    {"v", "ver", "version", "resver", "t", "ts", "time", "timestamp", "cache", "cb", "_", "rev"}
)
_PLACEHOLDER_RE = re.compile(
    r"(?:blank|spacer|loading|lazy|placeholder|transparent|standby|1x1)\b", re.I
)
_LAZY_ATTRS = ("data-src", "data-original", "data-lazy-src", "data-lazy", "data-echo", "data-url")
_IMAGE_EXT_RE = re.compile(r"\.(?:jpe?g|png|gif|webp|bmp)$", re.I)
# 그림 대체 글 — 이렇게 **시작**하면 단추(본문 그림의 대체 글에도 '다음과 같이'가 들어간다).
_UI_ALT_PREFIX = (
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
    "맨위",
    "위로",
)
# 링크 안 그림의 대체 글에 이 말이 있으면 첨부 단추.
_ALT_FILE_WORDS = (
    "첨부",
    "다운로드",
    "내려받기",
    "자료받기",
    "파일받기",
    "바로보기",
    "미리보기",
    "뷰어",
)
# 관련 글 목록의 썸네일(케이투웹: '… 대표이미지').
_ALT_OTHER_POST = ("대표이미지", "대표 이미지", "썸네일")

# '이전글·다음글' — 글이 끝나고 다른 글 목록이 시작되는 자리.
_END_MARKERS = frozenset({"이전글", "다음글", "이전 글", "다음 글", "윗글", "아랫글"})

# ── 첨부 ────────────────────────────────────────────────────────────────────
# 주소에 이 말이 있으면 첨부(단, 쿼리나 .do 같은 확장자가 붙은 주소만 — '/support/download'
# 같은 안내 페이지는 아니다).
_FILE_URL_HINTS = (
    "download",
    "filedown",
    "file_down",
    "fileid",
    "atchfile",
    "filesn",
    "file_sn",
    "getfile",
    "attach",
)
_VIEW_HINTS = ("미리보기", "바로보기", "뷰어", "preview", "viewer")
_TTS_HINTS = ("음성", "듣기", "inittts", "tts=")
# 첨부를 한꺼번에(ZIP) 받는 단추 — '일괄 다운로드' 에서 '다운로드' 를 떼면 이 말만 남는다.
_ALL_FILES_LABELS = frozenset(
    {"일괄", "전체", "모두", "일괄받기", "전체받기", "전체파일", "첨부일괄"}
)
ALL_FILES_LABEL = "첨부 모두 받기"
# 라벨 끝에 붙는 안내 말 — '(새창)'·'새창열림'·'다운로드'·'바로보기'(여러 개가 이어지기도).
_LABEL_TAIL_RE = re.compile(
    r"(?:\s*(?:\(\s*새\s*창\s*(?:으로\s*)?(?:열림)?\s*\)|새\s*창\s*(?:으로\s*)?열림|"
    r"다운로드|내려받기|바로\s*보기|미리\s*보기|download))+\s*$",
    re.I,
)
_LABEL_NEWWIN_HEAD_RE = re.compile(r"^\s*새\s*창\s*(?:으로\s*)?열림\s*")
# 깨진 파일 이름('????????.jpg') — 이름이 없는 것으로 본다.
_MOJIBAKE_RE = re.compile(r"[?�_\s.\-]*\.[A-Za-z0-9]{2,5}")
# 이 말들로만 된 라벨은 이름이 아니다 — '뷰어보기'·'문서뷰어'·'새창알림'·'바로보기 새창열기'(실측)
_GENERIC_RE = re.compile(
    r"(?:[\s()\[\]·:|/-]|새\s*창|열림|열기|이동|알림|문서|뷰어|바로|미리|보기|다운로드|내려받기|"
    r"받기|파일|첨부|download|view(?:er)?|preview|open)*",
    re.I,
)
# 눈에 안 보이는 글자(폭 없는 공백 등) — '일괄\u200b다운로드' 처럼 낱말 맞추기를 깬다
_INVISIBLE_RE = re.compile("[\u200b-\u200d\u2060\ufeff]")
MAX_LABEL = 80
_NAME_PARAMS = (
    "filenameorg",
    "orgfilename",
    "orignlfilenm",
    "orifilename",
    "origfilename",
    "realname",
    "filename",
    "file_name",
    "filenm",
    "atchfilenm",
    "fname",
    "fn",
    "name",
)
# 크기 꼬리 — '(268.2K)'·'[1.2MB]'·'35 KB'(괄호 없이 'K' 만 있으면 '100m' 같은 이름일 수 있어 뺀다)
_SIZE_TAIL_RE = re.compile(
    r"\s*(?:[\[(]\s*\d[\d.,]*\s*(?:bytes?|[kmg]i?b?|바이트)\s*[\])]|"
    r"\d[\d.,]*\s*(?:bytes?|[kmg]i?b|바이트))\s*$",
    re.I,
)
_LABEL_HEAD_RE = re.compile(
    r"^(?:(?:첨부\s*파일|첨부|붙임|파일)\s*[:：]?\s+|"
    r"(?:pdf|hwpx?|docx?|xlsx?|pptx?|zip|jpe?g|png|gif)\s*(?:문서|파일)\s+)",
    re.I,
)
_HAS_EXT_RE = re.compile(
    r"\.(?:" + "|".join(e.lstrip(".") for e in _EXT_KIND) + r"|jpe?g|png|gif)\b", re.I
)
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
    outside_images: int = 0  # 다른 사이트의 그림(allow 밖) — 원문에서만 보인다
    outside_files: int = 0  # 다른 사이트로 가는 첨부 링크
    title_found: bool = False
    frames: list[str] = field(default_factory=list)  # 본문이 든 iframe 주소(같은 사이트)
    dropped: list[tuple[str, str]] = field(default_factory=list)  # (주소, 뺀 이유) — 점검용
    kept: list[tuple[str, str]] = field(default_factory=list)  # (주소, 놓인 자리) — 점검용

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
            "outside_images": self.outside_images,
            "outside_files": self.outside_files,
            "title_found": self.title_found,
        }
        if debug:
            out["dropped"] = [list(d) for d in self.dropped[:60]]
            out["kept"] = [list(k) for k in self.kept[:60]]
            out["frames"] = self.frames
        return out


def _words(value: str) -> list[str]:
    """'gnbWrap sub_menu' → ['gnbwrap', 'gnb', 'wrap', 'sub', 'menu']."""
    out: list[str] = []
    for chunk in re.split(r"[^A-Za-z0-9]+", value or ""):
        if not chunk:
            continue
        out.append(chunk.lower())
        parts = _WORD_RE.findall(chunk)
        if len(parts) > 1:
            out.extend(p.lower() for p in parts)
    return out


def _chrome_word(attrs: dict[str, str]) -> str:
    """id·class·role 에서 껍데기를 뜻하는 낱말(없으면 "")."""
    for key in ("id", "class", "role"):
        words = _words(attrs.get(key) or "")
        for w in words:
            if w in _CHROME_WORDS or w.startswith(_CHROME_PREFIXES):
                return w
        for a, b in itertools.pairwise(words):
            if a + b in _CHROME_JOINED:
                return a + b
    role = (attrs.get("role") or "").lower()
    return role if role in ("navigation", "banner", "contentinfo") else ""


def _tag_label(tag: str, attrs: dict[str, str]) -> str:
    """'div#content.board_view' — 점검 출력에서 자리를 알아보게."""
    out = tag
    if attrs.get("id"):
        out += "#" + attrs["id"][:24]
    cls = (attrs.get("class") or "").split()
    if cls:
        out += "." + cls[0][:24]
    return out


# 글자로 그리는 아이콘 글꼴(Material) — 'chevron_forward'·'lock' 같은 글자가 이름에 섞인다.
_GLYPH_CLASSES = ("material-icons", "material-symbols")


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
    chrome: str  # 껍데기면 그 자리('nav'·'div.footer'), 아니면 ""
    width: int
    rows: int = 0
    cols: int = 0
    _row_cells: int = 0
    nested: bool = False


@dataclass(slots=True)
class _Anchor:
    pos: int
    href: str
    chrome: str
    title: str  # title 속성
    before: str  # 링크 바로 앞의 글자(파일 이름이 링크 밖에 적힌 첨부 목록)
    where: str = ""  # 놓인 자리(점검용)
    text: list[str] = field(default_factory=list)
    alts: list[str] = field(default_factory=list)  # 링크 안 그림의 대체 글


@dataclass(slots=True)
class _Img:
    pos: int
    attrs: dict[str, str]
    chrome: str
    href: str  # 감싼 링크 주소
    where: str  # 놓인 자리(점검용)


@dataclass(slots=True)
class _Open:
    tag: str
    chrome: str
    label: str
    glyph: bool


class _Scan(HTMLParser):
    """한 번 훑으며 그림·링크·표·글자 위치를 문서 순서대로 적는다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pos = 0
        self.stack: list[_Open] = []
        self.raw = 0
        self.head = 0
        self.glyph = 0  # 아이콘 글꼴 요소 안(글자를 읽지 않는다)
        self.images: list[_Img] = []
        self.anchors: list[_Anchor] = []
        self.frames: list[tuple[int, str, str]] = []
        self.tables: list[_Table] = []
        self.texts: list[tuple[int, str]] = []  # 본문 글자(제목 찾기·끝 표시 찾기용)
        self._open_tables: list[_Table] = []
        self._anchor: _Anchor | None = None
        self._last_text = ""

    def _where(self) -> str:
        return " > ".join(o.label for o in self.stack[-3:])

    def handle_starttag(self, tag: str, attrs_list) -> None:
        self.pos += 1
        attrs = {k.lower(): (v or "") for k, v in attrs_list}
        parent = self.stack[-1].chrome if self.stack else ""
        label = _tag_label(tag, attrs)
        chrome = parent
        if not chrome:
            in_article = any(o.tag in ("article", "main") for o in self.stack)
            if tag in _CHROME_TAGS or (tag in _SECTION_CHROME_TAGS and not in_article):
                chrome = tag
            elif _chrome_word(attrs):
                chrome = label
        if tag == "head":
            self.head += 1
        if tag in _RAW:
            self.raw += 1
        if tag == "img":
            href = self._anchor.href if self._anchor else ""
            if self._anchor is not None and attrs.get("alt"):
                self._anchor.alts.append(attrs["alt"])
            self.images.append(_Img(self.pos, attrs, chrome, href, self._where()))
        elif tag == "a":
            self._close_anchor()
            self._anchor = _Anchor(
                self.pos,
                attrs.get("href") or "",
                chrome,
                attrs.get("title") or "",
                self._last_text,
                self._where(),
            )
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
            cls = (attrs.get("class") or "").lower()
            glyph = any(g in cls for g in _GLYPH_CLASSES)
            self.glyph += glyph
            self.stack.append(_Open(tag, chrome, label, glyph))

    def handle_startendtag(self, tag: str, attrs_list) -> None:
        self.handle_starttag(tag, attrs_list)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._close_anchor()
        if not any(o.tag == tag for o in self.stack):
            return  # 짝 없는 닫는 태그 — 무시
        while self.stack:
            o = self.stack.pop()
            if o.tag in _RAW:
                self.raw = max(0, self.raw - 1)
            if o.tag == "head":
                self.head = max(0, self.head - 1)
            if o.glyph:
                self.glyph = max(0, self.glyph - 1)
            if o.tag == "table" and self._open_tables:
                self._open_tables.pop()
            if o.tag == tag:
                break

    def _close_anchor(self) -> None:
        if self._anchor is not None:
            self.anchors.append(self._anchor)
            self._anchor = None

    def handle_data(self, data: str) -> None:
        if self.raw or self.head or self.glyph:
            return
        text = " ".join(data.split())
        if self._anchor is not None:
            self._anchor.text.append(data)
        elif text:
            self._last_text = text[-120:]
        if text:
            self.texts.append((self.pos, text))

    def close(self) -> None:
        super().close()
        self._close_anchor()


# 목록 제목 앞에 붙는 상태 말('채용중'·'진행중'·'모집'·'N') — 글 화면 제목에는 없다.
_STATUS_HEAD_RE = re.compile(r"^\s*(?:\S{1,4}\s+)")
_TAG_HEAD_RE = re.compile(r"^(?:\s*[\[(【<〈][^\])】>〉]{1,12}[\])】>〉])+\s*")


def _title_pos(texts: list[tuple[int, str]], title: str) -> int:
    """본문에서 글 제목이 처음 나온 위치(못 찾으면 -1).

    제목은 태그로 쪼개져 있기도 하다('<b>[공지]</b> 장학생 모집') — 글자를 이어 붙여
    공백·기호를 뺀 채 앞부분을 찾는다. 목록의 제목은 글 화면과 다를 수 있어
    (말머리 '[공통][교외]', 상태 '채용중', 꼬리 'NEW 관리자 2026.10.09') 차례로 줄여 본다.
    """
    joined: list[str] = []
    owners: list[int] = []
    for pos, text in texts:
        n = _norm(text)
        joined.append(n)
        owners.extend([pos] * len(n))
    body = "".join(joined)
    bare = _TAG_HEAD_RE.sub("", title)
    keys = [_norm(title)[:16], _norm(bare)[:16], _norm(title)[:10], _norm(bare)[:10]]
    keys.append(_norm(_STATUS_HEAD_RE.sub("", bare))[:10])
    for key in keys:
        if len(key) < 6:
            continue
        hit = body.find(key)
        if hit >= 0:
            return owners[hit]
    return -1


def _end_pos(texts: list[tuple[int, str]], start: int) -> int:
    """제목 뒤 '이전글·다음글' 위치(없으면 아주 큰 수)."""
    for pos, text in texts:
        if pos > start and text in _END_MARKERS:
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


def _segments(path: str) -> list[str]:
    return [s.lower() for s in path.split("/") if s]


def looks_uploaded(url: str) -> bool:
    """편집기·첨부로 **올린** 그림의 주소인가 — 사이트를 꾸미는 그림과 가르는 표시.

    올린 폴더(/upload/·/CrossEditor/ …)·날짜나 해시로 된 폴더·이름, 또는 캐시용이
    아닌 쿼리('getImage.do?atchFileId=…'·'Attach.htm?FILENO=…' 처럼 프로그램이 내주는 그림).
    """
    parts = urllib.parse.urlsplit(url)
    segs = _segments(parts.path)
    stem = segs[-1].rsplit(".", 1)[0] if segs else ""
    if any(s in _UPLOAD_DIRS or _UPLOADISH_RE.match(s) for s in segs[:-1]):
        return True
    if _UPLOAD_STEM_RE.match(stem):
        return True
    keys = [k.lower() for k, _v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)]
    return any(k not in _VERSION_KEYS for k in keys)


def _asset_reason(path: str) -> str:
    """사이트를 꾸미는 그림의 폴더인가(올린 그림이 아닐 때만 묻는다)."""
    dirs = _segments(path)[:-1]
    if any(s in _ASSET_DIRS for s in dirs):
        return "꾸밈 그림 경로"
    if any(s in _IMG_DIRS for s in dirs) and any(s in _IMG_UI_DIRS for s in dirs):
        return "꾸밈 그림 경로"
    return ""


def _name_words(stem: str) -> list[str]:
    """그림 이름의 낱말(끝 숫자를 뗀 것)과 이웃한 두 낱말을 붙인 것."""
    words = [w.rstrip("0123456789") for w in _words(stem)]
    words = [w for w in words if w]
    return words + [a + b for a, b in itertools.pairwise(words)]


def _icon_reason(url: str, attrs: dict[str, str]) -> str:
    path = urllib.parse.urlsplit(url).path
    segs = _segments(path)
    name = segs[-1] if segs else ""
    if name.endswith(".svg"):
        return "svg"
    if _TYPE_ICON_RE.match(name):
        return "파일 종류 아이콘"
    if any(s in _BANNER_DIRS for s in segs[:-1]):
        return "배너 경로"  # 배너·팝업은 올린 그림이어도 글이 아니다
    if "thumbnails" in segs and _XE_THUMB_RE.match(name):
        return "목록 썸네일"
    uploaded = looks_uploaded(url)
    for w in _name_words(name.rsplit(".", 1)[0]):
        if w in _ICON_WORDS or (not uploaded and w in _SITE_ICON_WORDS):
            return f"아이콘 이름({w})"
    if not uploaded:
        why = _asset_reason(path)
        if why:
            return why
    w, h = _px(attrs, "width"), _px(attrs, "height")
    if (w and w < MIN_ICON_PX) or (h and h < MIN_ICON_PX):
        return f"작음({w}x{h})"
    alt = " ".join((attrs.get("alt") or "").split())
    if alt.startswith(_UI_ALT_PREFIX):
        return f"단추({alt[:10]})"
    if any(k in alt for k in _ALT_OTHER_POST):
        return "다른 글 대표 그림"
    return ""


def _url_file_hint(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    last = parts.path.rsplit("/", 1)[-1]
    if not (parts.query or "." in last):
        return False  # '/support/download' 같은 안내 페이지
    hay = f"{parts.path}?{parts.query}".lower()
    return any(h in hay for h in _FILE_URL_HINTS)


def _file_kind(url: str, label: str) -> str:
    path = urllib.parse.urlsplit(url).path.lower()
    low = label.lower()
    for ext, kind in _EXT_KIND.items():
        if path.endswith(ext) or low.endswith(ext):
            return kind
    if _IMAGE_EXT_RE.search(path) or _IMAGE_EXT_RE.search(low):
        return "그림"
    hay = f"{url} {label}".lower()
    if any(h in hay for h in _VIEW_HINTS):
        return "보기"
    if _url_file_hint(url):
        # 'downloadAllZip.do'·'AtchZipFileDown.do' — 첨부를 한꺼번에 묶어 받는 주소
        return "ZIP" if "zip" in path.rsplit("/", 1)[-1] else "파일"
    return ""


_DOWNLOAD_QUERY_RE = re.compile(
    r"(?:^|&)(?:mode|act|cmd|type|method)=(?:download|down|filedown)(?:&|$)", re.I
)


def looks_like_file(url: str) -> bool:
    """글 화면이 아니라 파일이 바로 내려오는 주소인가 — 목록의 '글'이 첨부 그 자체인 경우.

    ('readDownloadFile.do?…'·'getFile?…'·'….pdf'·'press.do?mode=download&…' — 실측 15건)
    """
    parts = urllib.parse.urlsplit(url or "")
    last = parts.path.rsplit("/", 1)[-1].lower()
    if any(last.endswith(ext) for ext in _EXT_KIND) or _IMAGE_EXT_RE.search(last):
        return True
    if any(h in last for h in ("download", "filedown", "getfile")):
        return True
    return bool(_DOWNLOAD_QUERY_RE.search(parts.query))


def _name_from_url(url: str) -> str:
    """주소의 쿼리(filenameOrg= …)나 경로 끝에서 파일 이름."""
    parts = urllib.parse.urlsplit(url)
    params = {k.lower(): v for k, v in urllib.parse.parse_qsl(parts.query)}
    for key in _NAME_PARAMS:
        val = (params.get(key) or "").strip()
        if val and _HAS_EXT_RE.search(val):
            return val
    name = urllib.parse.unquote(parts.path.rsplit("/", 1)[-1])
    return name if _HAS_EXT_RE.search(name) else ""


def _cut_after_ext(label: str) -> str:
    """파일 이름 뒤의 꼬리를 뗀다 — '공고문.hwpx (크기:0.056MB , 다운로드:15)' → '공고문.hwpx'.

    ('(pdf,'·'(268.2K)'·'(다운로드 : 148회)'·'바로보기(새창)'·아이콘 글자 'chevron_forward' 실측)
    """
    last = None
    for m in _HAS_EXT_RE.finditer(label):
        last = m
    if last is not None and last.start() > 0 and last.end() < len(label):
        return label[: last.end()]
    return label


def _is_generic(label: str) -> bool:
    return bool(_GENERIC_RE.fullmatch(label or ""))


def _shorten(label: str, limit: int = MAX_LABEL) -> str:
    """긴 이름은 줄이되 확장자는 남긴다(무슨 파일인지는 보이게)."""
    if len(label) <= limit:
        return label
    m = re.search(r"\.[A-Za-z0-9]{2,5}$", label)
    ext = m.group(0) if m else ""
    return label[: limit - len(ext) - 1].rstrip() + "…" + ext


def _clean(text: str) -> str:
    label = _cut_after_ext(" ".join(_INVISIBLE_RE.sub("", text or "").split()))
    for _ in range(3):  # '공고문 (12KB) 다운로드' 처럼 꼬리가 겹친다
        before = label
        label = _SIZE_TAIL_RE.sub("", _LABEL_TAIL_RE.sub("", label)).strip()
        if label == before:
            break
    label = _LABEL_NEWWIN_HEAD_RE.sub("", label)
    label = _LABEL_HEAD_RE.sub("", label).strip()
    return "" if _MOJIBAKE_RE.fullmatch(label) else label


def _file_label(a: _Anchor, url: str, text: str) -> str:
    """링크 글자 → 없거나 '다운로드'뿐이면 title 속성·주소의 파일 이름, 그다음 그림 대체
    글·링크 바로 앞 글자(파일 이름처럼 확장자가 있을 때만) 순으로 찾는다. 못 찾으면 ""."""
    label = _clean(text)
    if label.replace(" ", "") in _ALL_FILES_LABELS:
        return ALL_FILES_LABEL
    if not _is_generic(label):
        return label
    tries = [(a.title, False), (_name_from_url(url), False)]
    tries += [(alt, True) for alt in a.alts] + [(a.before, True)]
    for cand, need_ext in tries:
        c = _clean(cand)
        if c and not _is_generic(c) and (not need_ext or _HAS_EXT_RE.search(c)):
            return c
    return ""


def _same_page(url: str, page: str) -> bool:
    strip = lambda u: urllib.parse.urlsplit(u)._replace(fragment="").geturl()  # noqa: E731
    return strip(url) == strip(page)


def _other_post(url: str, page: str) -> bool:
    """같은 사이트의 **다른 글** 주소인가 — 그 링크 안의 그림은 관련 글·목록 썸네일이다.

    글 주소 꼴이거나, 이 글과 같은 자리의 번호만 다른 주소('/s_results/15794' ↔ '/15799'),
    같은 경로·같은 쿼리 이름에 값만 다른 주소('?mode=view&mv_data=…').
    """
    a, b = urllib.parse.urlsplit(url), urllib.parse.urlsplit(page)
    if (a.hostname or "").lower() != (b.hostname or "").lower() or _same_page(url, page):
        return False
    if looks_like_article(url):
        return True
    dir_a, _s, last_a = a.path.rpartition("/")
    dir_b, _s, last_b = b.path.rpartition("/")
    if dir_a == dir_b and last_a.isdigit() and last_b.isdigit():
        return True
    if a.path == b.path and a.query and b.query:
        keys_a = {k for k, _v in urllib.parse.parse_qsl(a.query, keep_blank_values=True)}
        keys_b = {k for k, _v in urllib.parse.parse_qsl(b.query, keep_blank_values=True)}
        return bool(keys_a) and keys_a == keys_b
    return False


def extract(
    html: str,
    base_url: str,
    *,
    title: str = "",
    allow: Callable[[str], bool] | None = None,
) -> Media:
    """글 화면 HTML → 그림·첨부 주소와 표 개수(본문 글자는 취하지 않는다).

    allow: 화면에 넣어도 되는 주소인가(목록 기관의 사이트) — 아니면 개수만 센다.
    """
    scan = _Scan()
    try:
        scan.feed(html or "")
        scan.close()
    except Exception:  # 망가진 HTML — 읽은 데까지만 쓴다
        pass
    media = Media()
    start = _title_pos(scan.texts, title) if title else -1
    media.title_found = start >= 0
    # 제목을 받았는데 화면에 없다 — 대기 화면·메뉴 화면일 수 있어 **올린** 그림만 남긴다
    strict = bool(title) and not media.title_found
    start = max(start, 0)
    end = _end_pos(scan.texts, start) if media.title_found else 1 << 60

    seen: set[str] = set()
    for img in scan.images:
        attrs = img.attrs
        raw = _pick_src(attrs)
        if raw.startswith("data:"):
            if start <= img.pos <= end and not img.chrome:
                media.inline_images += 1
            continue
        url = urllib.parse.urljoin(base_url, raw) if raw else ""
        href = img.href
        link = urllib.parse.urljoin(base_url, href) if href and "javascript:" not in href else ""
        alt = " ".join((attrs.get("alt") or "").split())
        why = ""
        if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            why = "주소 없음"
        elif img.chrome:
            why = f"껍데기 영역({img.chrome})"
        elif img.pos < start:
            why = "제목 앞"
        elif img.pos > end:
            why = "이전글·다음글 뒤"
        elif link and _file_kind(link, "") and any(k in alt for k in _ALT_FILE_WORDS):
            why = "첨부 단추"
        elif link and _other_post(link, base_url):
            why = "다른 글 링크"
        else:
            why = _icon_reason(url, attrs)
            if not why and strict and not looks_uploaded(url):
                why = "제목 못 찾음 — 올린 그림 아님"
        if why:
            media.dropped.append((url or raw, why))
            continue
        big = link if link and _IMAGE_EXT_RE.search(urllib.parse.urlsplit(link).path) else ""
        full = big or url
        if allow is not None and full != url and not allow(full):
            full = url  # 큰 그림이 남의 사이트에 있으면 작은 그림을 연다
        if url in seen or full in seen:
            continue  # 같은 그림(작은 그림과 그 큰 그림)
        seen.update(u for u in (url, full, big) if u)
        if allow is not None and not allow(url):
            media.outside_images += 1
            media.dropped.append((url, "다른 사이트"))
            continue
        media.images.append(
            Image(
                src=url,
                full=full,
                alt=(alt or " ".join((attrs.get("title") or "").split()))[:80],
                width=_px(attrs, "width"),
                height=_px(attrs, "height"),
            )
        )
        media.kept.append((url, img.where))

    files_seen: set[str] = set()
    body_images = bool(media.images)  # 본문(편집기)에 실린 그림이 있는가
    attached: list[tuple[str, str, str]] = []  # 그림 파일 첨부 (이름, 주소, 자리)
    last_label = ""  # 바로 앞 첨부의 이름 — 이름 없는 단추('바로보기'·'다운로드')에 붙인다
    for a in scan.anchors:
        if a.chrome or a.pos < start or a.pos > end:
            continue
        href = a.href.strip()
        text = " ".join("".join(a.text).split())
        low = href.lower()
        if low.startswith("javascript:"):
            if _file_kind(href, text) or any(h in text for h in ("다운로드", "내려받기")):
                media.script_files += 1
            continue
        if not href or low.startswith(("#", "mailto:", "tel:")):
            continue
        url = urllib.parse.urljoin(base_url, href)
        if (
            urllib.parse.urlsplit(url).scheme not in ("http", "https")
            or url in files_seen
            or _same_page(url, base_url)
        ):
            continue
        hay = f"{text} {url}".lower()
        if any(h in hay for h in _TTS_HINTS):
            continue  # 첨부를 소리로 읽어 주는 링크
        name = _file_label(a, url, text)
        if any(h in hay for h in _VIEW_HINTS):
            # 문서 뷰어(바로보기·미리보기) — 이름은 링크 주소나 바로 앞 첨부에서
            base = name or last_label
            if base and body_images and _IMAGE_EXT_RE.search(base):
                files_seen.add(url)
                continue  # 본문에 이미 실린 사진의 '바로보기'
            kind = "보기"
            label = f"{_shorten(base)} (바로보기)" if base else "바로보기"
            last_label = name or last_label
        else:
            kind = _file_kind(url, name)  # 종류는 이 링크 자신으로만(빌린 이름으로 정하지 않는다)
            if not kind:
                continue
            if not name and last_label:
                if any(f.label == _shorten(last_label) for f in media.files):
                    files_seen.add(url)
                    continue  # 같은 첨부의 다른 단추(이름 없는 '받기')
                name = last_label
                if kind == "파일":
                    kind = _file_kind(url, name) or kind
            label = _shorten(name) if name else "첨부"
            last_label = name or last_label
        files_seen.add(url)
        if allow is not None and not allow(url):
            if kind == "그림":
                media.outside_images += url not in seen
                seen.add(url)
            else:
                media.outside_files += 1
            media.dropped.append((url, "다른 사이트 첨부"))
            continue
        if kind == "그림":
            attached.append((label, url, a.where))
            continue
        media.files.append(File(label, url, kind))
        media.kept.append((url, a.where))
        if len(media.files) >= MAX_FILES:
            break
    # 그림 파일 첨부 — 본문에 그림이 없으면(포스터를 파일로만 붙인 글) 그림으로 보여 주고,
    # 본문에 그림이 있으면 같은 사진을 두 번 보이지 않게 첨부 목록에 둔다.
    for label, url, where in attached:
        if url in seen:
            continue
        seen.add(url)
        if body_images:
            if len(media.files) < MAX_FILES:
                media.files.append(File(label, url, "그림"))
                media.kept.append((url, where))
        elif len(media.images) < MAX_IMAGES:
            media.images.append(Image(src=url, full=url, alt=label))
            media.kept.append((url, where))
    media.images = media.images[:MAX_IMAGES]

    for t in scan.tables:
        if t.chrome or t.pos < start or t.pos > end:
            continue
        if t.rows >= 2 and t.cols >= 2 and not t.nested:
            media.tables += 1
            if t.width >= WIDE_PX or t.cols >= 7:
                media.wide_tables += 1

    host = (urllib.parse.urlsplit(base_url).hostname or "").lower()
    for pos, src, chrome in scan.frames:
        url = urllib.parse.urljoin(base_url, src)
        same = (urllib.parse.urlsplit(url).hostname or "").lower() == host
        if same and not chrome and start < pos < end:
            media.frames.append(url)
    return media
