"""출처 자동 탐지(--discover) — 홈페이지 주소 하나로 출처 초안을 만든다.

참고 3종을 코드 수준에서 분석해(문서 제외) 원리만 증류했다. 셋 다
requests·bs4·lxml 의존이라(스타 최상위 autoscraper 포함) 통째 채택은
이 도구의 원칙(런타임 의존성 0)과 충돌한다.

  차용 ① autoscraper `_build_stack` — 예시 하나에서 재사용 규칙을 학습한다.
        우리 무대(K2Web)에서는 DOM 경로 대신 **URL 문법이 곧 그 규칙**이다:
        `/bbs/{site_id}/{board_id}/…` 링크 하나만 발견하면 좌표가 복원되고,
        그 좌표로 rss·list·page 세 주소가 전부 재구성된다.
  차용 ② feed_seeker — 탐지 3원(<link rel=alternate> → <a href> 단서 →
        경로 추측)과 **제한 스파이더링**(예산 내 링크 따라가기), 그리고
        페처 주입(오프라인 테스트 가능) 구조.
  차용 ③ feedfinder validators — 후보 수집과 **검증을 분리**하고, 검증은
        내용 스니핑(<rss·<feed·<rdf)으로 한다. 검증 못 한 항목은 버리지
        않고 '미검증'으로 표시해 사람이 판단하게 한다.

원칙: 초안 생성기다. 탐지 근거(_evidence)와 검증 여부(_verified)를 항목마다
남기고, 사람이 확인·수정한 뒤 --sources 로 쓰는 것을 전제한다. robots.txt 를
지키고, 전체 요청 수에 예산을 둔다(기본 12회). 추정을 사실처럼 적지 않는다.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser

from . import k2web_parse, robots
from .fetch import decode_text
from .k2web_parse import ARTICLE_RE

PageFetcher = Callable[[str], "bytes | None"]

DEFAULT_BUDGET = 12  # 시작 페이지 포함 총 요청 상한 — 폭주 방지
ORG_BUDGET = 40  # discover_org 전체 요청 상한(여러 사이트 합산)
DEFAULT_MAX_SITES = 6  # discover_org 가 훑을 서로 다른 호스트 최대 수

# 국내에서 흔한 2단 접미사 — 이 경우 뿌리는 마지막 3라벨(hufs.ac.kr).
_TWO_LABEL_TLDS = frozenset(
    {"ac.kr", "go.kr", "co.kr", "or.kr", "ne.kr", "re.kr", "pe.kr", "hs.kr", "ms.kr", "es.kr"}
)


def _site_root(host: str) -> str:
    """두 호스트가 '같은 조직'인지 비교하기 위한 뿌리 도메인.

    www.hufs.ac.kr 와 student.hufs.ac.kr 은 같은 hufs.ac.kr 로 묶여야 한다.
    ac.kr·go.kr 같은 2단 접미사는 마지막 3라벨을, 그 외(example.com)는 마지막
    2라벨을 뿌리로 본다.
    """
    labels = host.lower().split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in _TWO_LABEL_TLDS:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


# K2Web 좌표가 드러나는 링크 문법들.
_BOARD_RE = re.compile(r"/bbs/([A-Za-z0-9_\-]+)/(\d+)/(?:artclList|rssList)\.do", re.I)
_MENU_RE = re.compile(r"/([A-Za-z0-9_\-]+)/(\d+)/subview\.do", re.I)

# 따라가 볼 메뉴를 고르는 앵커 문구 — 게시판일 가능성이 높은 말들.
_BOARD_HINTS = ("공지", "알림", "소식", "뉴스", "공고", "자료", "보도", "게시판", "notice", "news")

# rel=alternate 가 없고 K2Web 도 아닐 때 추측해 볼 관용 경로(feed_seeker 차용).
_GUESS_PATHS = ("/rss", "/feed", "/rss.xml", "/atom.xml", "/index.xml", "/feed.xml")

_FEED_HINT_RE = re.compile(rb"<(rss|feed|rdf)[\s>:]", re.I)
# 루트 태그만으로는 부족하다 — 'RSS 안내' 같은 HTML 문서도 통과할 수 있어서,
# 실제 피드라면 반드시 있는 본문 요소(item·entry·channel)를 함께 요구한다.
_FEED_BODY_RE = re.compile(rb"<(item|entry|channel)[\s>]", re.I)

# 주소 모양만으로 '피드일 가능성'을 거르는 1차 필터(확정은 스니핑이 한다).
#   /rss/dept_motir.xml · /common/rss/notice.jsp · /feed · news.rss
_FEED_URL_RE = re.compile(
    r"(\.xml(\?|$)|\.rss(\?|$)|/rss/|/rss(\?|$)|rss[a-z]*\.jsp|/feed(/|\?|$))", re.I
)


def _looks_like_feed_url(href: str) -> bool:
    return bool(_FEED_URL_RE.search(href))


def _is_feed(data: bytes | None) -> bool:
    """스니핑으로 RSS/Atom 여부 판정(feedfinder validators 방식 + 본문 확인).

    루트 태그(<rss·<feed·<rdf)가 앞부분에 있고 **동시에** 피드 본문 요소가
    있어야 참으로 본다. 관용 경로 추측이 엉뚱한 200 응답을 피드로 오인해
    유령 출처를 만드는 것을 막는다.
    """
    if not data:
        return False
    return bool(_FEED_HINT_RE.search(data[:2048])) and bool(_FEED_BODY_RE.search(data[:65536]))


# 스크립트·스타일·주석은 앵커를 담지 않으면서 파서를 교란한다. 정부 누리집은
# 인라인 JS 가 많고 그 안의 `</div>` 같은 문자열이 html.parser 를 흔들어 이후
# 메뉴를 통째로 놓치게 만든다. 파싱 전에 통으로 걷어낸다(비용 0).
_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.I | re.S)
_STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.I | re.S)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
# 링크가 href="#" 이고 실제 주소를 data-* 에 두는 접근성 메뉴가 흔하다.
_DATA_HREF_KEYS = ("data-url", "data-href", "data-link", "data-target-url", "data-menu-url")


def _is_dead_href(href: str) -> bool:
    """실제로 이동하지 않는 링크 — 주소가 data-* 에 숨어 있을 수 있다."""
    low = (href or "").strip().lower()
    return not low or low == "#" or low.startswith(("javascript:", "#"))


def strip_noise(text: str) -> str:
    """앵커 수집 전에 스크립트·스타일·주석을 제거한다."""
    for pattern in (_SCRIPT_RE, _STYLE_RE, _COMMENT_RE):
        text = pattern.sub(" ", text)
    return text


class _Page(HTMLParser):
    """한 페이지에서 필요한 것만 줍는 최소 파서.

    <link rel=alternate type=…rss/atom> · <a href>(또는 data-url)와 앵커 텍스트 ·
    <meta name=generator> · <title>. 진단용 계수도 함께 센다.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.alternates: list[tuple[str, str]] = []  # (href, title)
        self.anchors: list[tuple[str, str]] = []  # (href, text)
        self.generator = ""
        self.title = ""
        self._href: str | None = None
        self._buf: list[str] = []
        # 글자 없는 그림 링크(사이트맵·전체메뉴 아이콘)의 이름 — title·aria-label·img alt
        self._hint: list[str] = []
        self._in_title = False
        # 진단용 — 왜 후보가 0개였는지 사람이 알 수 있게 센다.
        self.anchor_tags = 0  # <a> 태그 총수(href 유무 무관)
        self.dead_links = 0  # href="#"·javascript: 처럼 주소가 없는 것
        self.data_links = 0  # data-* 에서 건진 것

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "link":
            rel = a.get("rel", "").lower()
            typ = a.get("type", "").lower()
            if "alternate" in rel and ("rss" in typ or "atom" in typ) and a.get("href"):
                self.alternates.append((a["href"].strip(), a.get("title", "").strip()))
        elif tag == "meta" and a.get("name", "").lower() == "generator":
            self.generator = a.get("content", "")
        elif tag == "a":
            self.anchor_tags += 1
            href = a.get("href", "").strip()
            if _is_dead_href(href):
                # href 가 비었거나 '#'·javascript: 면 실제 주소가 data-* 에 있을 수 있다.
                alt = next((a[k].strip() for k in _DATA_HREF_KEYS if a.get(k, "").strip()), "")
                if alt:
                    self.data_links += 1
                    href = alt
                else:
                    self.dead_links += 1
                    href = ""
            if href:
                self._href, self._buf = href, []
                self._hint = [a.get("title", ""), a.get("aria-label", "")]
        elif tag == "img" and self._href is not None:
            self._hint.append(a.get("alt", ""))
        elif tag == "title":
            self._in_title = True

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._buf.append(data)
        if self._in_title and not self.title:
            self.title = " ".join(data.split())

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = " ".join("".join(self._buf).split())
            if not text:  # 보이는 글자가 없을 때만 — 글자가 있으면 그것이 이름이다
                text = next((" ".join(h.split()) for h in self._hint if h.strip()), "")
            self.anchors.append((self._href, text))
            self._href = None
        elif tag == "title":
            self._in_title = False


@dataclass
class Discovery:
    """탐지 결과 — 초안 항목들과 사람이 읽을 메모."""

    start_url: str
    org: str = ""
    entries: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    fetched: int = 0
    sites: list[str] = field(default_factory=list)  # 훑은 호스트들(discover_org)
    _last_hosts: list[str] = field(default_factory=list)  # 직전 페이지의 동일조직 링크

    @property
    def verified_count(self) -> int:
        return sum(1 for e in self.entries if e.get("_verified"))

    def to_sources_json(self) -> str:
        comment = [
            f"--discover {self.start_url} 가 만든 출처 초안 — 사람 검토 후 사용하세요.",
            "org·site·name·category 를 다듬고, _verified 가 false 인 항목은 주소를 직접 확인하세요.",
            "'_'로 시작하는 필드는 탐지 근거 기록이며 수집 시 무시됩니다.",
        ]
        if len(self.sites) > 1:
            comment.append(
                "여러 사이트를 훑었습니다: " + ", ".join(self.sites) + ". "
                "필요없는 항목은 지우거나 enabled:false 로 꺼두세요."
            )
        comment.extend(self.notes)
        payload = {"_comment": comment, "sources": self.entries}
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


class _Session:
    """예산·robots·중복을 한곳에서 관리하는 페처 래퍼."""

    def __init__(self, fetcher: PageFetcher | None, check_robots: bool, budget: int):
        self._fetch = fetcher or _live_fetch
        self._check = check_robots
        self.budget = budget
        self.blocked: list[str] = []
        self.fetched = 0
        self.last_reason = ""  # 직전 요청이 실패한 사유(진단용)

    def get(self, url: str) -> bytes | None:
        if self.budget <= 0:
            self.last_reason = "요청 예산 소진"
            return None
        if self._check and not robots.allowed(url):
            self.blocked.append(url)
            self.last_reason = "robots.txt 차단"
            return None
        self.budget -= 1
        self.fetched += 1
        data = self._fetch(url)
        if data:
            self.last_reason = ""
        else:
            # 왜 못 받았는지 페처가 알면 그대로 받아 둔다. 이것이 없으면
            # '요청 실패'와 '빈 200 응답'이 똑같이 '0KB'로 찍혀 구분이 안 된다.
            why = getattr(self._fetch, "why", None)
            self.last_reason = why(url) if callable(why) else "응답 없음"
        return data


def _live_fetch(url: str) -> bytes | None:
    from .fetch import fetch_url

    return fetch_url(url)


def _slug(text: str) -> str:
    out = re.sub(r"[^a-z0-9가-힣]+", "-", text.lower()).strip("-")
    return out[:40] or "src"


def _clean_org(title: str, host: str) -> str:
    """<title>에서 기관명만 — '| 공지사항' 같은 꼬리를 자른다."""
    head = re.split(r"[|\-–:·]", title)[0].strip() if title else ""
    return head or host


def _same_org_hosts(page: _Page, base_url: str, root: str) -> list[str]:
    """페이지의 절대 링크 중 시작과 같은 뿌리 도메인인 '다른 호스트'들."""
    out: list[str] = []
    seen: set[str] = set()
    for href, _ in page.anchors:
        netloc = urllib.parse.urlsplit(urllib.parse.urljoin(base_url, href)).netloc
        if not netloc or netloc in seen:
            continue
        seen.add(netloc)
        if _site_root(netloc) == root and netloc != urllib.parse.urlsplit(base_url).netloc:
            out.append(netloc)
    return out


def discover(
    url: str,
    *,
    fetcher: PageFetcher | None = None,
    check_robots: bool = True,
    budget: int = DEFAULT_BUDGET,
    _session: _Session | None = None,
    _result: Discovery | None = None,
) -> Discovery:
    """홈페이지 한 장에서 출발해 RSS·K2Web 출처 초안을 모은다.

    _session·_result 는 discover_org 가 예산과 누적 결과를 여러 사이트에 걸쳐
    공유하기 위한 내부 인자다(단독 호출 시 무시).
    """
    if "://" not in url:
        url = "https://" + url  # 스킴 생략 입력('www.knou.ac.kr')을 조용히 보정
    result = _result or Discovery(start_url=url)
    session = _session or _Session(fetcher, check_robots, budget)
    host = urllib.parse.urlsplit(url).netloc

    data = session.get(url)
    if data is None:
        reason = "robots.txt 차단" if session.blocked else "응답 없음"
        result.notes.append(f"페이지를 열지 못했습니다({reason}): {url}")
        result.fetched = session.fetched
        return result

    page = _Page()
    try:
        page.feed(strip_noise(decode_text(data)))
    except Exception:
        result.notes.append(f"HTML 파싱 실패({url}) — 이 사이트의 결과가 없을 수 있습니다.")
    if not result.org:
        result.org = _clean_org(page.title, host)
    result._last_hosts = _same_org_hosts(page, url, _site_root(host))  # discover_org 용

    _find_k2web(result, session, page, url, host)
    _find_rss(result, session, page, url, host, page_bytes=data)

    if _result is None:  # 단독 호출일 때만 종합 메모(org 순회는 자체 메모를 단다)
        if not result.entries:
            result.notes.append(
                "지원 형식(RSS 자동발견·K2Web 문법)을 찾지 못했습니다 — JS로만 그리는 메뉴이거나 "
                "다른 CMS 일 수 있습니다. 게시판 페이지 주소를 직접 --discover 에 줘 보세요."
            )
        if session.blocked:
            result.notes.append(f"robots.txt 로 건너뛴 주소 {len(session.blocked)}건")
        if session.budget <= 0:
            result.notes.append(f"요청 예산({budget}회) 소진 — 일부 후보는 확인하지 못했습니다.")
    result.fetched = session.fetched
    return result


def _entry_key(entry: dict) -> tuple:
    """출처 초안 하나의 고유 키 — 여러 사이트 결과를 합쳐도 중복을 막는다."""
    if entry.get("kind") == "k2web":
        return ("k2web", entry.get("host"), entry.get("site_id"), entry.get("board_id"))
    return ("rss", entry.get("url"))


def _find_k2web(
    result: Discovery, session: _Session, page: _Page, base_url: str, host: str
) -> None:
    """K2Web 좌표 수집 — 직접 노출 링크 + 게시판스러운 메뉴 한 단계 따라가기.

    좌표를 조립할 host 는 시작 페이지가 아니라 **그 링크가 실제로 가리키는
    호스트**를 쓴다. 대학 홈페이지에는 student.·grad. 같은 다른 서브도메인의
    게시판 링크가 섞여 있어서, 시작 host 로 조립하면 엉뚱한 도메인 주소가 된다.
    """
    is_k2web = "k2web" in page.generator.lower()
    # 이미 쌓인 항목으로 중복셋을 초기화 — 여러 사이트를 병합해도 누적이 안전하다.
    seen: set[tuple] = {_entry_key(e) for e in result.entries}

    def add(
        link_host: str, site_id: str, board_id: str, name: str, menu_no: int | None, evidence: str
    ) -> None:
        key = ("k2web", link_host, site_id, int(board_id))
        if key in seen:
            return
        seen.add(key)
        rss = f"https://{link_host}/bbs/{site_id}/{board_id}/rssList.do?row=50"
        verified = _is_feed(session.get(rss))
        entry: dict = {
            "id": _slug(f"{site_id}-{board_id}"),
            "org": result.org,
            "site": result.org,
            "name": f"{result.org} {name}".strip(),
            "kind": "k2web",
            "host": link_host,
            "site_id": site_id,
            "board_id": int(board_id),
            "category": name,
            "_evidence": evidence,
            "_verified": verified,
        }
        if menu_no is not None:
            entry["menu_no"] = menu_no
        result.entries.append(entry)

    # ① 시작 페이지에 좌표가 그대로 노출된 링크(artclList/rssList/artclView).
    for href, text in page.anchors:
        m = _BOARD_RE.search(href) or ARTICLE_RE.search(href)
        if m:
            is_k2web = True
            name = (text or "게시판")[:30]
            link_host = urllib.parse.urlsplit(urllib.parse.urljoin(base_url, href)).netloc or host
            add(link_host, m.group(1), m.group(2), name, None, f"시작 페이지 링크: {href}")

    if not is_k2web and not any(_MENU_RE.search(h) for h, _ in page.anchors):
        return  # K2Web 흔적이 전혀 없으면 따라가지 않는다

    # ② 게시판스러운 메뉴(subview.do)를 예산 내에서 한 단계 따라가 좌표를 캔다.
    followed: set[tuple[str, str]] = set()
    for href, text in page.anchors:
        m = _MENU_RE.search(href)
        if not m or not any(h in text.lower() for h in _BOARD_HINTS):
            continue
        menu_url = urllib.parse.urljoin(base_url, href)
        menu_host = urllib.parse.urlsplit(menu_url).netloc or host
        menu_key = (menu_host, m.group(0))
        if menu_key in followed:
            continue
        followed.add(menu_key)
        sub = session.get(menu_url)
        if not sub:
            continue
        # 따라간 페이지의 실제 호스트로 좌표를 조립한다(리다이렉트·상대경로 대비).
        bm = _BOARD_RE.search(decode_text(sub))
        if bm:
            add(
                menu_host,
                bm.group(1),
                bm.group(2),
                (text or "게시판")[:30],
                int(m.group(2)),
                f"메뉴 '{text}'({menu_url}) 안에서 발견",
            )


def _feed_index_rows(page_bytes: bytes, base_url: str) -> list[tuple[str, str]]:
    """'피드 목록' 페이지의 표에서 (이름, 피드 주소)를 캔다.

    korea.kr `/etc/rss.do` 와 각 부처의 '정보구독서비스' 페이지가 같은 모양이다 —
    표 한 행에 (메뉴·기관 이름 | 피드 주소 | 주소복사 버튼). 이름을 앵커 텍스트에서
    가져오면 전부 "RSS복사"·"주소복사"가 되므로, **같은 행에서 링크 없는 첫 칸**을
    이름으로 쓴다(k2web_parse 의 '칸 순서로 읽는다' 원리 재사용).
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for cells in k2web_parse.parse_rows(page_bytes):
        href = next((h for _, h in cells if h and _looks_like_feed_url(h)), "")
        if not href:
            continue
        url = urllib.parse.urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        # 이름 = 같은 행에서 링크가 없는 첫 텍스트 칸. 'A > B > 공지' 는 마지막 조각만.
        label = next((t for t, h in cells if t and not h), "")
        name = label.split(">")[-1].strip()[:40]
        out.append((name, url))
    return out


def _find_rss(
    result: Discovery,
    session: _Session,
    page: _Page,
    base_url: str,
    host: str,
    page_bytes: bytes | None = None,
) -> None:
    """RSS 자동발견 → 피드 목록 표 → (그래도 없으면) 관용 경로 추측."""
    seen_urls = {e.get("url") for e in result.entries}

    def add(feed_url: str, title: str, evidence: str, *, verified: bool | None = None) -> None:
        if feed_url in seen_urls:
            return
        seen_urls.add(feed_url)
        if verified is None:
            verified = _is_feed(session.get(feed_url))
        result.entries.append(
            {
                "id": _slug(f"rss-{urllib.parse.urlsplit(feed_url).path}"),
                "org": result.org,
                "name": f"{result.org} {title}".strip() if title else f"{result.org} RSS",
                "kind": "rss",
                "url": feed_url,
                "category": title,
                "_evidence": evidence,
                "_verified": verified,
            }
        )

    # ① 표준 자동발견
    for href, title in page.alternates:
        add(urllib.parse.urljoin(base_url, href), title, "<link rel=alternate> 자동발견")

    # ② 피드 목록 페이지(표) — korea.kr·부처 '정보구독서비스' 공통 패턴
    if page_bytes:
        for name, url in _feed_index_rows(page_bytes, base_url):
            if session.budget <= 0:
                result.notes.append("피드 목록이 예산보다 많아 일부는 확인하지 못했습니다.")
                break
            add(url, name, f"피드 목록 표의 '{name}' 항목")

    # ③ 아무것도 못 찾았을 때만 추측(feed_seeker 방식)
    if not result.entries:
        for path in _GUESS_PATHS:
            if session.budget <= 0:
                break
            guess = f"{urllib.parse.urlsplit(base_url).scheme}://{host}{path}"
            data = session.get(guess)
            if _is_feed(data):
                add(guess, "", f"관용 경로 추측 적중: {path}", verified=True)


def discover_org(
    url: str,
    *,
    fetcher: PageFetcher | None = None,
    check_robots: bool = True,
    budget: int = ORG_BUDGET,
    max_sites: int = DEFAULT_MAX_SITES,
) -> Discovery:
    """조직 대표 주소 하나에서 산하 여러 사이트(서브도메인)를 훑어 전부 병합한다.

    시작 URL 을 탐지하며 같은 뿌리 도메인(_site_root)의 다른 호스트 링크를 만나면
    큐에 넣고, 그 사이트도 홈페이지부터 다시 탐지해 하나의 Discovery 로 합친다.
    외부 검색 없이 링크만 따라가며, 전체 요청 예산(budget)과 사이트 수(max_sites)
    두 상한으로 폭주를 막는다. 초안이므로 사람이 검토 후 쓰는 전제는 그대로다.
    """
    if "://" not in url:
        url = "https://" + url
    start_host = urllib.parse.urlsplit(url).netloc
    root = _site_root(start_host)

    result = Discovery(start_url=url)
    session = _Session(fetcher, check_robots, budget)

    queue: list[str] = [url]
    # 사용자가 등록도메인만 준 경우(hufs.ac.kr), www. 변형도 시드에 넣어 본다
    # — 많은 대학이 대표 콘텐츠를 www 에 두고 나체 도메인은 리다이렉트만 한다.
    if start_host == root:
        queue.append(f"https://www.{root}/")
    visited: set[str] = set()
    capped = False  # max_sites 때문에 남은 사이트를 못 본 적이 있는가

    while queue:
        if len(visited) >= max_sites or session.budget <= 0:
            capped = capped or bool(queue)
            break
        site_url = queue.pop(0)
        host = urllib.parse.urlsplit(site_url).netloc
        if host in visited:
            continue
        visited.add(host)
        result.sites.append(host)

        discover(site_url, _session=session, _result=result)

        # 이 사이트에서 본 '같은 조직의 다른 호스트'를 큐에 추가한다.
        for h in result._last_hosts:
            if (
                h not in visited
                and _site_root(h) == root
                and h not in {urllib.parse.urlsplit(q).netloc for q in queue}
            ):
                queue.append(f"https://{h}/")

    if not result.entries:
        result.notes.append(
            "산하 사이트에서 지원 형식을 찾지 못했습니다 — 대표 홈페이지 대신 게시판이 "
            "있는 서브도메인 주소를 직접 넣어 보세요."
        )
    if session.blocked:
        result.notes.append(f"robots.txt 로 건너뛴 주소 {len(session.blocked)}건")
    if capped and session.budget > 0:
        result.notes.append(
            f"사이트 상한({max_sites}곳)에 도달 — 훑지 못한 서브도메인이 남았습니다"
            "(--max-sites 로 늘릴 수 있습니다)."
        )
    if session.budget <= 0:
        result.notes.append(f"요청 예산({budget}회) 소진 — 일부 후보는 확인하지 못했습니다.")
    result.fetched = session.fetched
    return result
