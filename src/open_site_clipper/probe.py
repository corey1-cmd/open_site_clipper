"""구조 테스트 — 이 페이지가 **수집할 만한 목록인지** 모양으로 판정한다.

메뉴 이름으로는 판정할 수 없다는 것이 실측 결론이다. 같은 `정보공개` 라도
어떤 기관에선 날짜 붙은 목록이고 어떤 기관에선 설명문 한 장이다. 키워드 사전은
22개 메뉴명 중 13개를 놓쳤고, 새 기관의 새 메뉴명은 계속 빠진다.

그래서 이름 대신 **내용의 모양**을 본다. 이 프로젝트가 이미 두 번 쓴 원리다 —
k2web_parse 는 CSS 클래스 대신 표 구조에, govweb 은 링크 문법 대신 칸 순서에
기댔다. 세 번째 적용이다.

판정(교육부 메뉴 실측에서 도출한 네 유형):

    LIST     날짜 붙은 목록          → 수집 대상
    STATIC   설명문 한 장(글 없음)    → 가져올 것이 없음
    INDEX    링크 모음(날짜 없음)     → 목록이 아님
    EXTERNAL 기관 밖 도메인          → 별도 수집 대상(법령·공공데이터·민원 등)

STATIC·INDEX·EXTERNAL 은 건너뛰되 **사유를 남긴다**(조용한 실패 금지).
"""

from __future__ import annotations

import base64
import binascii
import re
import urllib.parse
from dataclasses import dataclass

from . import govweb

# 판정 결과
LIST = "list"
STATIC = "static"
INDEX = "index"
EXTERNAL = "external"
HOME = "home"
ARTICLE = "article"

VERDICT_REASON = {
    LIST: "",
    STATIC: "목록이 아님(글 0~1건) — 안내 페이지로 보임",
    INDEX: "날짜 없는 링크 모음 — 목록이 아님",
    EXTERNAL: "기관 밖 도메인 — 별도 출처로 등록해 수집하세요",
    HOME: "첫 화면(다른 홈·하위 사이트) — 최신글 묶음이라 게시판으로 쓰지 않음",
    ARTICLE: "글 한 건(상세 보기) 페이지 — 목록이 아님",
}

# 글 한 건 주소 — '이전·다음 글' 목록 때문에 날짜 달린 목록처럼 보인다(실측: 그누보드
# wr_id · ?mode=view&no= · ?ACT=R&CONTENTNO= · 워드프레스 /blog/글제목/).
_ARTICLE_QUERY_RE = re.compile(
    r"(?:^|&)(?:wr_id|articleno|contentno|nttsn|bbsidx)=\d|(?:^|&)(?:mode|action|act|type|cmd)=(?:view|read|r|detail)(?:&|$)",
    re.I,
)
# '/kcua/boardView?menuCode=…&boardNum=1545' 처럼 확장자 없는 글 보기 주소도(강서대 실측).
# K2Web 메뉴 화면 'subview.do' 는 글이 아니라 목록이 박힌 메뉴다 — 'view.do' 로 끝나도 뺀다
# (그동안 이것 때문에 K2Web 학교의 메뉴 게시판이 후보에서 통째로 빠졌다).
_ARTICLE_PATH_RE = re.compile(
    r"(?:artclview|(?<!sub)view\.(?:do|jsp|php|asp)$|/blog/[^/]+/?$|"
    r"(?:board|article|bbs|notice|post)view$)",
    re.I,
)


def not_a_board(url: str) -> bool:
    """열어 보기 전에 게시판 후보에서 뺄 주소 — 첫 화면·글 한 건·검색 결과."""
    return looks_like_home(url) or looks_like_article(url) or looks_like_search(url)


_SEARCH_PATH_RE = re.compile(r"(?:^|/)(?:search|totalsearch|integratedsearch)(?:\.\w+)?/?$", re.I)


def looks_like_search(url: str) -> bool:
    """사이트 검색 결과(/web/search.do?searchKeyword=멘토링) — 날짜 달린 목록이지만
    게시판이 아니라 그때그때 검색어에 걸린 글 묶음이다(전북대 실측)."""
    path = urllib.parse.urlsplit(url).path.split(";", 1)[0]
    return bool(_SEARCH_PATH_RE.search(path))


def _k2_encoded_view(parts: urllib.parse.SplitResult) -> bool:
    """K2Web 'subview.do?enc=…' 가 글 보기인가 — enc 는 base64 로 싼 안쪽 주소다.

    'fnct1|@@|/bbs/hufs/2180/12345/artclView.do?…' 면 글 한 건, artclList 면 목록 쪽수.
    """
    if not parts.path.lower().endswith("subview.do"):
        return False
    for key, value in urllib.parse.parse_qsl(parts.query):
        if key.lower() != "enc" or not value:
            continue
        raw = value.strip()
        try:
            inner = base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_")
        except (ValueError, binascii.Error):
            return False
        return b"artclview" in urllib.parse.unquote_to_bytes(inner).lower()
    return False


def looks_like_article(url: str) -> bool:
    """게시판 목록이 아니라 글 한 건(상세 보기) 주소인가."""
    parts = urllib.parse.urlsplit(url)
    path = parts.path.split(";", 1)[0]
    if _ARTICLE_PATH_RE.search(path) or _k2_encoded_view(parts):
        return True
    return bool(_ARTICLE_QUERY_RE.search(parts.query))


# 첫 화면 주소의 마지막 조각 — index.do · main.do · PortalMain · soriindex.do · main_form.acl
_SITE_ROOTS = frozenset(
    {
        "ko",
        "kor",
        "kr",
        "korean",
        "en",
        "eng",
        "english",
        "cn",
        "chn",
        "jp",
        "jpn",
        "www",
        "web",
        "site",
    }
)
_HOME_WORDS = frozenset({"main", "index", "home"})
_HOME_STEM_RE = re.compile(r"^(?:index|main|home|default)|(?:index|main)$", re.I)


def looks_like_home(url: str) -> bool:
    """홈·하위 사이트 첫 화면인가.

    `<li>` 목록형 게시판을 읽게 되면서, 첫 화면의 '최신 소식' 칸도 날짜 달린 목록으로
    보이게 됐다(관세청 세관별 main.do · 외교부 공관 index.do · 대학 LMS 첫 화면).
    거기서 모은 글은 여러 게시판이 뒤섞여 분류가 틀리고 같은 글이 겹친다 —
    진짜 게시판은 따로 잡히므로 첫 화면은 게시판 후보에서 뺀다.
    """
    parts = urllib.parse.urlsplit(url)
    segs = [s for s in parts.path.split(";", 1)[0].split("/") if s]
    # '?pCode=main' · '?main=Y' — 쿼리로 첫 화면을 고르는 사이트
    for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in _HOME_WORDS or value.lower() in _HOME_WORDS:
            return True
    if not segs:
        return not parts.query  # '/' — 쿼리 없는 사이트 뿌리
    if "main" in (s.lower() for s in segs[:-1]):
        return True  # /base/main/view
    stem = segs[-1].rsplit(".", 1)[0]
    if _HOME_STEM_RE.search(stem):
        return True
    # '/ko/' · '/eng/' · '/www/' 처럼 언어·사이트 이름 한 조각 = 하위 사이트 뿌리
    return len(segs) == 1 and segs[0].lower() in _SITE_ROOTS and not parts.query


# 수집 대상으로 보려면 이만큼은 있어야 한다.
MIN_ROWS = 2
# 행 중 날짜가 붙은 비율이 이보다 낮으면 목록이 아니라 링크 모음으로 본다.
MIN_DATED_RATIO = 0.5

# 기관 사이트가 아니라 별도 시스템 — 요청대로 법령은 여기서 제외된다.
# 도메인만 보고 판정하므로 새 시스템이 생겨도 기관 밖이면 EXTERNAL 로 잡힌다.
KNOWN_EXTERNAL = (
    "law.go.kr",  # 국가법령정보센터
    "data.go.kr",  # 공공데이터포털
    "epeople.go.kr",  # 국민신문고
    "open.go.kr",  # 정보공개포털
    "g2b.go.kr",  # 나라장터
    "gov.kr",  # 정부24
    "work24.go.kr",
    "kosis.kr",
)


@dataclass(frozen=True, slots=True)
class Probe:
    """한 후보 주소에 대한 판정."""

    url: str
    verdict: str
    rows: int = 0
    dated: int = 0

    @property
    def collectible(self) -> bool:
        return self.verdict == LIST

    @property
    def reason(self) -> str:
        return VERDICT_REASON.get(self.verdict, "")


def is_external(url: str, home_host: str) -> bool:
    """기관 사이트 밖인가 — 서브도메인은 같은 기관으로 본다."""
    host = urllib.parse.urlsplit(url).netloc.lower()
    if not host:
        return True
    if any(host == d or host.endswith("." + d) for d in KNOWN_EXTERNAL):
        return True
    home = (home_host or "").lower()
    if not home:
        return False
    # www.moe.go.kr 와 moe.go.kr · sub.moe.go.kr 를 같은 기관으로 묶는다.
    base = home[4:] if home.startswith("www.") else home
    return not (host == base or host.endswith("." + base))


def classify(data: bytes | None, url: str, *, home_host: str = "") -> Probe:
    """페이지 내용으로 유형을 판정한다. 받아오지 못했으면 STATIC 취급."""
    if home_host and is_external(url, home_host):
        return Probe(url=url, verdict=EXTERNAL)
    if looks_like_home(url):
        return Probe(url=url, verdict=HOME)
    if looks_like_article(url):
        return Probe(url=url, verdict=ARTICLE)
    if not data:
        return Probe(url=url, verdict=STATIC)

    rows = govweb.parse_list(data, url)
    dated = sum(1 for r in rows if r.published is not None)
    if len(rows) < MIN_ROWS:
        return Probe(url=url, verdict=STATIC, rows=len(rows), dated=dated)
    if dated / len(rows) < MIN_DATED_RATIO:
        return Probe(url=url, verdict=INDEX, rows=len(rows), dated=dated)
    return Probe(url=url, verdict=LIST, rows=len(rows), dated=dated)
