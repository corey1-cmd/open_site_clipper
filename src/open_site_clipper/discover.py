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

from . import robots
from .fetch import decode_text
from .k2web_parse import ARTICLE_RE

PageFetcher = Callable[[str], "bytes | None"]

DEFAULT_BUDGET = 12  # 시작 페이지 포함 총 요청 상한 — 폭주 방지

# K2Web 좌표가 드러나는 링크 문법들.
_BOARD_RE = re.compile(r"/bbs/([A-Za-z0-9_\-]+)/(\d+)/(?:artclList|rssList)\.do", re.I)
_MENU_RE = re.compile(r"/([A-Za-z0-9_\-]+)/(\d+)/subview\.do", re.I)

# 따라가 볼 메뉴를 고르는 앵커 문구 — 게시판일 가능성이 높은 말들.
_BOARD_HINTS = ("공지", "알림", "소식", "뉴스", "공고", "자료", "보도", "게시판", "notice", "news")

# rel=alternate 가 없고 K2Web 도 아닐 때 추측해 볼 관용 경로(feed_seeker 차용).
_GUESS_PATHS = ("/rss", "/feed", "/rss.xml", "/atom.xml", "/index.xml", "/feed.xml")

_FEED_HINT_RE = re.compile(rb"<(rss|feed|rdf)[\s>:]", re.I)


def _is_feed(data: bytes | None) -> bool:
    """앞부분 스니핑으로 RSS/Atom 여부 판정(feedfinder validators 방식)."""
    return bool(data) and bool(_FEED_HINT_RE.search(data[:2048]))


class _Page(HTMLParser):
    """한 페이지에서 필요한 네 가지만 줍는 최소 파서.

    <link rel=alternate type=…rss/atom> · <a href>와 앵커 텍스트 ·
    <meta name=generator> · <title>.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.alternates: list[tuple[str, str]] = []  # (href, title)
        self.anchors: list[tuple[str, str]] = []  # (href, text)
        self.generator = ""
        self.title = ""
        self._href: str | None = None
        self._buf: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "link":
            rel = a.get("rel", "").lower()
            typ = a.get("type", "").lower()
            if "alternate" in rel and ("rss" in typ or "atom" in typ) and a.get("href"):
                self.alternates.append((a["href"].strip(), a.get("title", "").strip()))
        elif tag == "meta" and a.get("name", "").lower() == "generator":
            self.generator = a.get("content", "")
        elif tag == "a" and a.get("href", "").strip():
            self._href, self._buf = a["href"].strip(), []
        elif tag == "title":
            self._in_title = True

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._buf.append(data)
        if self._in_title and not self.title:
            self.title = " ".join(data.split())

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.anchors.append((self._href, " ".join("".join(self._buf).split())))
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

    @property
    def verified_count(self) -> int:
        return sum(1 for e in self.entries if e.get("_verified"))

    def to_sources_json(self) -> str:
        payload = {
            "_comment": [
                f"--discover {self.start_url} 가 만든 출처 초안 — 사람 검토 후 사용하세요.",
                "org·site·name·category 를 다듬고, _verified 가 false 인 항목은 주소를 직접 확인하세요.",
                "'_'로 시작하는 필드는 탐지 근거 기록이며 수집 시 무시됩니다.",
                *self.notes,
            ],
            "sources": self.entries,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


class _Session:
    """예산·robots·중복을 한곳에서 관리하는 페처 래퍼."""

    def __init__(self, fetcher: PageFetcher | None, check_robots: bool, budget: int):
        self._fetch = fetcher or _live_fetch
        self._check = check_robots
        self.budget = budget
        self.blocked: list[str] = []
        self.fetched = 0

    def get(self, url: str) -> bytes | None:
        if self.budget <= 0:
            return None
        if self._check and not robots.allowed(url):
            self.blocked.append(url)
            return None
        self.budget -= 1
        self.fetched += 1
        return self._fetch(url)


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


def discover(
    url: str,
    *,
    fetcher: PageFetcher | None = None,
    check_robots: bool = True,
    budget: int = DEFAULT_BUDGET,
) -> Discovery:
    """홈페이지 한 장에서 출발해 RSS·K2Web 출처 초안을 모은다."""
    if "://" not in url:
        url = "https://" + url  # 스킴 생략 입력('www.knou.ac.kr')을 조용히 보정
    result = Discovery(start_url=url)
    session = _Session(fetcher, check_robots, budget)
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc

    data = session.get(url)
    if data is None:
        reason = "robots.txt 차단" if session.blocked else "응답 없음"
        result.notes.append(f"시작 페이지를 열지 못했습니다({reason}): {url}")
        result.fetched = session.fetched
        return result

    page = _Page()
    try:
        page.feed(decode_text(data))
    except Exception:
        result.notes.append("시작 페이지 HTML 파싱 실패 — 탐지 결과가 없을 수 있습니다.")
    result.org = _clean_org(page.title, host)

    _find_k2web(result, session, page, url, host)
    _find_rss(result, session, page, url, host)

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


def _find_k2web(
    result: Discovery, session: _Session, page: _Page, base_url: str, host: str
) -> None:
    """K2Web 좌표 수집 — 직접 노출 링크 + 게시판스러운 메뉴 한 단계 따라가기."""
    is_k2web = "k2web" in page.generator.lower()
    seen: set[tuple[str, str, str]] = set()

    def add(site_id: str, board_id: str, name: str, menu_no: int | None, evidence: str) -> None:
        key = (host, site_id, board_id)
        if key in seen:
            return
        seen.add(key)
        rss = f"https://{host}/bbs/{site_id}/{board_id}/rssList.do?row=50"
        verified = _is_feed(session.get(rss))
        entry: dict = {
            "id": _slug(f"{site_id}-{board_id}"),
            "org": result.org,
            "site": result.org,
            "name": f"{result.org} {name}".strip(),
            "kind": "k2web",
            "host": host,
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
            add(m.group(1), m.group(2), name, None, f"시작 페이지 링크: {href}")

    if not is_k2web and not any(_MENU_RE.search(h) for h, _ in page.anchors):
        return  # K2Web 흔적이 전혀 없으면 따라가지 않는다

    # ② 게시판스러운 메뉴(subview.do)를 예산 내에서 한 단계 따라가 좌표를 캔다.
    followed: set[str] = set()
    for href, text in page.anchors:
        m = _MENU_RE.search(href)
        if not m or not any(h in text.lower() for h in _BOARD_HINTS):
            continue
        menu_key = m.group(0)
        if menu_key in followed:
            continue
        followed.add(menu_key)
        menu_url = urllib.parse.urljoin(base_url, href)
        sub = session.get(menu_url)
        if not sub:
            continue
        bm = _BOARD_RE.search(decode_text(sub))
        if bm:
            add(
                bm.group(1),
                bm.group(2),
                (text or "게시판")[:30],
                int(m.group(2)),
                f"메뉴 '{text}'({menu_url}) 안에서 발견",
            )


def _find_rss(result: Discovery, session: _Session, page: _Page, base_url: str, host: str) -> None:
    """표준 RSS 자동발견 → (아무것도 없으면) 관용 경로 추측."""
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
                "name": title or f"{result.org} RSS",
                "kind": "rss",
                "url": feed_url,
                "_evidence": evidence,
                "_verified": verified,
            }
        )

    for href, title in page.alternates:
        add(urllib.parse.urljoin(base_url, href), title, "<link rel=alternate> 자동발견")

    if not result.entries:  # rel 도 K2Web 도 없을 때만 추측(feed_seeker 방식)
        for path in _GUESS_PATHS:
            if session.budget <= 0:
                break
            guess = f"{urllib.parse.urlsplit(base_url).scheme}://{host}{path}"
            data = session.get(guess)
            if _is_feed(data):
                add(guess, "", f"관용 경로 추측 적중: {path}", verified=True)
