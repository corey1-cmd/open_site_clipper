"""휴대폰에서 쓰는 웹 버전의 서버 쪽 — Vercel 함수와 로컬 개발 서버가 같이 쓴다.

화면(public/)은 기관을 **한 곳씩** 요청한다. 수십 곳을 한 요청에 몰면 함수
제한 시간(300초)을 넘기고, 진행 상황도 보여 줄 수 없기 때문이다:

    화면 ── /api/catalog ──────────────▶ 기관 목록(정부 65 + 학교)
         ── /api/collect?id=…&days=7 ──▶ 그 기관 하나의 공지(JSON)
         ── /api/verify?ids=…  ────────▶ 여러 기관 일괄 점검(배포 후 실측용)

한 기관을 모으는 순서는 CLI 와 같다(발견 → 카테고리별 캐스케이드). 다른 점은
두 가지뿐이다:

  ① **경로 캐시** — 실측 점검에서 공지가 실제로 나온 게시판 주소를
     data/route-cache.json 에 적어 두고, 있으면 발견을 건너뛴다(수 초).
     캐시 경로가 낡아 0건이면 그 자리에서 다시 발견한다.
  ② **시간 제한** — 요청 직전에 남은 시간을 본다. 다 쓰면 남은 단계는
     '시간 제한'이라는 사유를 남기고 건너뛴다(조용한 실패 금지).

공지 본문은 담지 않는다(제목·링크·날짜·분류·출처만). 공공누리 등급과 무관하게
안전한 범위다.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
import urllib.parse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, categories, govcascade, govdiscover, media, parallel, robots
from .cascade import origin_label
from .collect import KST
from .fetch import TrackingFetcher, decode_text
from .model import Notice
from .probe import looks_like_article
from .sources import Source, from_dicts

PageFetcher = Callable[[str], "bytes | None"]

# 저장소 뿌리 — Vercel 함수 묶음(/var/task)과 로컬 저장소가 같은 배치다.
ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIR = ROOT / "public"
ROUTE_CACHE_FILE = Path(__file__).with_name("data") / "route-cache.json"

# 화면의 큰 묶음 → 기관 목록 파일. 목록을 늘리려면 여기에 파일만 더하면 된다.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("정부", "examples/sources-gov.json"),
    # 공공기관(한국장학재단 …) — 같은 '정부 기관' 탭의 '공공기관' 묶음으로 보인다
    ("정부", "examples/sources-public.json"),
    ("학교", "examples/sources-schools.json"),
)

DEFAULT_DAYS = 7
MAX_DAYS = 90
# Vercel 함수 제한(300초)보다 넉넉히 짧게 — 마지막 요청(최대 30초)과 응답 몫.
DEFAULT_BUDGET = float(os.environ.get("OSC_TIME_BUDGET", "240"))
REDISCOVER_MIN_LEFT = 60.0  # 캐시 경로가 0건일 때 다시 찾으려면 이만큼은 남아야
VERIFY_MAX_IDS = 20
TIME_UP = "시간 제한"

# 캐시 지시 — 같은 기관을 여러 사람이 요청해도 30분 동안은 CDN 이 대신 답한다.
CACHE_OK = "public, max-age=0, s-maxage=1800, stale-while-revalidate=3600"
CACHE_EMPTY = "public, max-age=0, s-maxage=300, stale-while-revalidate=600"
CACHE_CATALOG = "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400"
# 점검은 무겁다 — 같은 요청이 10분 안에 또 오면(새로 고침·중복 실행) CDN 이 답한다.
CACHE_VERIFY = "public, max-age=0, s-maxage=600"
# 그림·첨부 주소는 글이 고쳐지지 않는 한 그대로다 — 하루 동안 CDN 이 대신 답한다.
CACHE_MEDIA = "public, max-age=0, s-maxage=86400, stale-while-revalidate=86400"
MEDIA_TIMEOUT = 12.0
NO_STORE = "no-store"


# ── 기관 목록 ────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Org:
    """화면에서 고르는 단위 하나 — 기관(또는 학교) 하나."""

    id: str
    name: str
    section: str  # "정부" | "학교"
    group: str  # 부·청·위원회 … / 4년제·전문대·사이버대 …
    region: str
    home: str
    source: Source


def _catalog_dir() -> Path:
    """목록 파일을 찾을 뿌리 — 환경변수로 바꿀 수 있다(배포 구조가 다를 때)."""
    return Path(os.environ.get("OSC_CATALOG_DIR") or ROOT)


@lru_cache(maxsize=1)
def catalog() -> dict[str, Org]:
    """id → Org. 파일 순서를 그대로 지킨다(화면 정렬의 기준)."""
    out: dict[str, Org] = {}
    for section, rel in SECTIONS:
        path = _catalog_dir() / rel
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # 파일이 없으면 그 묶음만 빠진다 — 화면에서 바로 드러난다
        items = raw.get("sources") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            continue
        for item, src in zip(_valid(items), from_dicts(_valid(items)), strict=True):
            if src.kind != "govorg" or not src.home or src.id in out:
                continue
            out[src.id] = Org(
                id=src.id,
                name=src.org or src.name,
                section=section,
                group=str(item.get("group") or ""),
                region=str(item.get("region") or ""),
                home=src.home,
                source=src,
            )
    return out


def _valid(items: list) -> list[dict]:
    """from_dicts 가 받아들이는 항목만 — 원본 dict 와 짝을 맞추려고 먼저 거른다."""
    return [
        i
        for i in items
        if isinstance(i, dict)
        and str(i.get("name") or "").strip()
        and str(i.get("kind") or "rss").strip().lower() == "govorg"
        and (i.get("routes") or i.get("korea_feed") or i.get("home"))
    ]


@lru_cache(maxsize=1)
def route_cache() -> dict[str, dict]:
    """실측 점검에서 공지가 나온 경로들(id → {routes, count, checked})."""
    try:
        raw = json.loads(ROUTE_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    orgs = raw.get("orgs") if isinstance(raw, dict) else None
    return orgs if isinstance(orgs, dict) else {}


def catalog_payload() -> dict:
    cache = route_cache()
    return {
        "version": __version__,
        "sections": list(dict.fromkeys(name for name, _rel in SECTIONS)),
        "orgs": [
            {
                "id": o.id,
                "name": o.name,
                "section": o.section,
                "group": o.group,
                "region": o.region,
                "home": o.home,
                "checked": bool(cache.get(o.id, {}).get("routes")),
            }
            for o in catalog().values()
        ],
    }


# ── 한 기관 수집 ─────────────────────────────────────────────────────────────
class _Deadline:
    """요청 직전에 남은 시간을 보는 페처 — 다 쓰면 요청하지 않고 사유를 남긴다."""

    def __init__(self, inner: PageFetcher, stop_at: float, clock=time.monotonic):
        self._inner = inner
        self._stop_at = stop_at
        self._clock = clock
        self._late: set[str] = set()

    def left(self) -> float:
        return self._stop_at - self._clock()

    def __call__(self, url: str) -> bytes | None:
        if self.left() <= 0:
            self._late.add(url)
            return None
        return self._inner(url)

    def why(self, url: str) -> str:
        if url in self._late:
            return TIME_UP
        why = getattr(self._inner, "why", None)
        return why(url) if callable(why) else "응답 없음"


_ROUTE_KIND = {govcascade.RSS: "rss", govcascade.DATAGO: "datago"}

# 한 기관에서 볼 게시판 수의 상한 — 캐시·발견 모두. 장학·학사·입학처럼 갈래가 분명한
# 것을 앞에 둔다(같은 갈래 안에서는 설정·발견 순서를 지킨다).
MAX_ROUTES = 12
_SPECIFIC_FIRST = {name: i for i, name in enumerate(categories.ORDER)}


def _route_rank(route: tuple[str, str, str] | list[str]) -> int:
    group = categories.canonical(route[0])
    if group in categories.SPECIFIC:
        return _SPECIFIC_FIRST.get(group, 50)
    return 100 + _SPECIFIC_FIRST.get(group, 50)


def plan_routes(*groups) -> tuple[tuple[str, str, str], ...]:
    """설정(프리셋) → 캐시 → 발견 순으로 합쳐 같은 주소를 접고 상한까지 고른다."""
    merged: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for group in groups:
        for route in group or ():
            cat, kind, url = (str(x) for x in route)
            key = _url_key(url)
            if key in seen:
                continue
            seen.add(key)
            merged.append((cat, kind, url))
    ranked = sorted(range(len(merged)), key=lambda i: (_route_rank(merged[i]), i))
    return tuple(merged[i] for i in sorted(ranked[:MAX_ROUTES]))


def _url_key(url: str) -> str:
    """같은 게시판의 다른 표기를 접는다 — K2Web 은 (호스트, 사이트, 번호)."""
    parts = urllib.parse.urlsplit(url.strip())
    m = govcascade._K2_BOARD_RE.search(parts.path)
    if m:
        return f"k2:{parts.netloc.lower()}{parts.path[: m.start(1)].lower()}"
    return urllib.parse.urlunsplit(parts._replace(fragment="")).lower()


def _cascade(source: Source, fetch: PageFetcher) -> tuple[list[Notice], list[str], list[list[str]]]:
    """경로마다 모아 공지·실패 사유·**실제로 나온 경로(다듬은 이름)**를 돌려준다.

    게시판 이름이 갈래를 말하지 않으면(READ·더보기·공지 …) 글 제목에서 우세한
    갈래로 이름을 다듬고, 글 하나하나는 제목에 장학·학사·입학 같은 말이 있으면 그
    갈래로 분류한다 — '공지사항'에 올라온 장학 공지도 [장학]으로 거를 수 있게.
    """
    notices: list[Notice] = []
    used: list[list[str]] = []
    ok_cats: set[str] = set()
    tried: dict[str, list[str]] = {}
    for res in govcascade.collect_routes(source, fetcher=fetch):
        if not res.ok:
            tried.setdefault(res.category, []).append(res.trail() or "해당 없음")
            continue
        # 캐시에 남은 '공지사항(목록)'·'더보기READ' 같은 이름은 여기서 다듬고,
        # 이름을 모를 때만('READ'·'기타') 글 제목으로 이름을 짓는다.
        label = categories.tidy_label(res.category)
        if not label:
            titles = [n.title for n in res.notices]
            label = categories.dominant(titles) or categories.from_url(res.url)
        ok_cats.add(res.category)
        notices.extend(
            replace(n, category=categories.notice_category(label, n.title)) for n in res.notices
        )
        # korea.kr 피드는 korea_feed 에서 매번 다시 만들어지므로 적지 않는다.
        if res.stage != govcascade.KOREA:
            used.append([label, _ROUTE_KIND.get(res.stage, "board"), res.url])
    failures = [
        f"{cat} ({' / '.join(trails)})" for cat, trails in tried.items() if cat not in ok_cats
    ]
    return notices, failures, used


def collect_one(
    org_id: str,
    *,
    days: int = DEFAULT_DAYS,
    fetcher: PageFetcher | None = None,
    budget: float = DEFAULT_BUDGET,
    fresh: bool = False,
    today: date | None = None,
    clock: Callable[[], float] = time.monotonic,
    delay: float = parallel.DEFAULT_DELAY,
) -> dict:
    """기관 하나를 모아 화면용 사전으로 돌려준다(KeyError: 모르는 id).

    fresh=True 면 경로 캐시를 쓰지 않고 홈에서 다시 찾는다(점검·캐시 갱신용).
    """
    org = catalog()[org_id]
    days = max(1, min(int(days), MAX_DAYS))
    started = clock()
    deadline = _Deadline(
        _limited(fetcher or TrackingFetcher(), delay), started + budget, clock=clock
    )

    cached = None if fresh else route_cache().get(org_id)
    preset = org.source.routes  # 사람이 확인해 목록 파일에 적은 경로(예: 한국외대)
    source = org.source
    mode = "discover"
    notes: list[str] = []
    if cached and cached.get("routes"):
        source = replace(source, routes=plan_routes(preset, cached["routes"]))
        mode = "cache"
    elif source.home:
        found, notes = govdiscover.enrich(replace(source, routes=()), fetcher=deadline)
        source = replace(source, routes=plan_routes(preset, found.routes))
        mode = "discover" if not preset else "preset"

    notices, failures, used = _cascade(source, deadline)
    if mode == "cache" and not notices and deadline.left() > REDISCOVER_MIN_LEFT:
        # 캐시해 둔 게시판이 바뀌었을 수 있다 — 홈에서 다시 찾는다.
        found, notes = govdiscover.enrich(replace(org.source, routes=()), fetcher=deadline)
        source = replace(source, routes=plan_routes(preset, found.routes))
        notices, failures, used = _cascade(source, deadline)
        mode = "rediscover"

    today = today or datetime.now(KST).date()
    cutoff = today - timedelta(days=days)
    rows, seen = [], set()
    for n in sorted(notices, key=_newest_specific_first):
        if n.published is not None and n.published < cutoff:
            continue
        # 같은 글이 피드·목록·두 게시판으로 겹쳐 들어온다 — 링크로 한 번, (제목, 날짜)로
        # 한 번 더 접는다. 먼저 온 것(갈래가 분명한 게시판의 것)을 남긴다.
        keys = (n.dedup_key(), _title_key(n))
        if any(k in seen for k in keys if k):
            continue
        seen.update(k for k in keys if k)
        rows.append(_row(n))

    return {
        "id": org.id,
        "name": org.name,
        "section": org.section,
        "group": org.group,
        "home": org.home,
        "days": days,
        "generated": datetime.now(KST).replace(microsecond=0).isoformat(),
        "elapsed": round(clock() - started, 1),
        "mode": mode,
        "count": len(rows),
        "seen": len(notices),
        "timed_out": deadline.left() <= 0,
        "notices": rows,
        "routes": used,
        "failures": failures,
        "notes": notes,
    }


def _limited(fetch: PageFetcher, delay: float) -> PageFetcher:
    """같은 서버에는 간격을 두고 — CLI 와 같은 예절(robots 의 Crawl-delay 우선)."""
    return parallel.HostLimiter(delay).wrap(fetch) if delay > 0 else fetch


def _newest_specific_first(n: Notice) -> tuple:
    """최신 글이 앞 — 같은 날 같은 글이면 갈래가 분명한 쪽이 남도록."""
    group = categories.canonical(n.category) if n.category else categories.ETC
    return (-(n.published or date.min).toordinal(), group not in categories.SPECIFIC)


# 같은 글이 두 게시판에 '[공통][교외] 제목' · '[교외] 제목 새글' 처럼 머리·꼬리만 달리
# 올라온다(한국외대 장학공지 ↔ 학생지원팀 장학). 비교할 때만 떼어 낸다.
_TAG_HEAD_RE = re.compile(r"^(?:\s*(?:\[[^\]]{1,20}\]|\([^)]{1,20}\)|【[^】]{1,20}】))+\s*")
_TAG_TAIL_RE = re.compile(r"\s+(?:새글|새 글|new|n)$", re.I)


def _title_key(n: Notice) -> str:
    title = " ".join((n.title or "").split())
    title = _TAG_TAIL_RE.sub("", _TAG_HEAD_RE.sub("", title)).casefold()
    if not title or n.published is None:
        return ""
    return f"t\x1f{title}\x1f{n.published.isoformat()}"


def _row(n: Notice) -> dict:
    return {
        "title": n.title,
        "url": n.url,
        "date": n.published.isoformat() if n.published else "",
        "category": n.category,
        "group": categories.canonical(n.category) if n.category else "미분류",
        "unit": n.unit if n.unit and n.unit not in (n.org, n.agency) else "",
        "origin": n.origin or (origin_label(n.url, "board") if n.url else ""),
        "media": media_ready(n.url, n.title),
    }


# ── 글 한 건의 그림·첨부(휴대폰에서 잘리는 그림을 따로 보기) ──────────────────
_IP_RE = re.compile(r"^[0-9.]+$")


@lru_cache(maxsize=1)
def media_hosts() -> frozenset[str]:
    """그림·첨부를 찾아 줄 사이트 — 목록에 있는 기관 누리집(과 그 하위 사이트)만.

    아무 주소나 받으면 이 서버가 남의 사이트를 대신 여는 통로가 된다. 목록 기관의
    누리집·게시판 주소에서 뽑은 도메인(www. 를 뗀 것)과 그 하위 도메인만 연다.
    """
    hosts = {"korea.kr"}

    def add(url: str) -> None:
        host = (urllib.parse.urlsplit(url or "").hostname or "").lower()
        if host and "." in host and not _IP_RE.match(host):
            hosts.add(host.removeprefix("www."))

    for org in catalog().values():
        add(org.home)
        for _c, _k, u in org.source.routes:
            add(u)
    for entry in route_cache().values():
        for route in entry.get("routes") or []:
            if isinstance(route, list) and len(route) == 3:
                add(str(route[2]))
    return frozenset(hosts)


# 공공·교육 기관의 도메인 — 목록 기관의 글이 다른 기관 누리집(옛 도메인·입학처·사업단)
# 으로 이어지기도 한다(강서대 글 → entrance.kcu.ac.kr). 상업 사이트(언론사 등)는 열지 않는다.
_PUBLIC_SUFFIXES = (".ac.kr", ".go.kr", ".re.kr")


def media_allowed(url: str) -> bool:
    parts = urllib.parse.urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host or ":" in host or _IP_RE.match(host):
        return False
    if host.endswith(_PUBLIC_SUFFIXES):
        return True
    return any(host == h or host.endswith("." + h) for h in media_hosts())


def media_ready(url: str, title: str) -> bool:
    """이 글에 '그림·첨부' 단추를 달아도 되는가(화면이 단추를 그릴지 정한다).

    글 주소가 따로 없는 게시판(목록#제목)과, 글이 곧 파일인 주소(….pdf·download.do)는
    열어도 찾을 것이 없다 — 단추를 달지 않는다.
    """
    return media_allowed(url) and not _board_anchor(url, title) and not media.looks_like_file(url)


# 글 화면이 아니라 파일(HWP·PDF·ZIP …)이 바로 내려오는 주소 — 파일의 첫 바이트.
_BINARY_HEADS = (b"%PDF", b"PK\x03\x04", b"\xd0\xcf\x11\xe0", b"\x89PNG", b"\xff\xd8\xff", b"GIF8")


def _looks_binary(data: bytes) -> bool:
    head = data[:2048]
    return head.startswith(_BINARY_HEADS) or b"\x00" in head


_SPACES_RE = re.compile(r"\s+")
_HANGUL_RE = re.compile(r"[가-힣]")


def _board_anchor(url: str, title: str) -> bool:
    """글 주소가 따로 없는 게시판(목록 주소#제목)인가 — govweb._board_anchor 가 만든 것.

    조각은 목록 칸의 **날** 글자라 말머리('[답변] 면접 질문')·꼬리가 붙어 있고, 글 제목은
    그것을 다듬은 것이다 — 제목이 조각 안에 들어 있으면 그 주소다. 제목 없이도 한글이 든
    긴 조각은 페이지 안 위치표('#content')가 아니라 우리가 붙인 제목 조각으로 본다.
    """
    parts = urllib.parse.urlsplit(url)
    if not parts.fragment:
        return False
    flat = _SPACES_RE.sub("", urllib.parse.unquote(parts.fragment))
    key = _SPACES_RE.sub("", title or "")[:30]
    if len(key) >= 4 and key in flat:
        return True
    page = parts._replace(fragment="").geturl()
    return len(flat) >= 6 and bool(_HANGUL_RE.search(flat)) and not looks_like_article(page)


def media_for(
    url: str,
    title: str = "",
    *,
    fetcher: PageFetcher | None = None,
    debug: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """글 화면에서 그림·첨부 **주소**와 표 개수를 찾는다(본문 글자는 돌려주지 않는다).

    ValueError: 목록 기관의 사이트가 아닌 주소.
    """
    started = clock()
    url = (url or "").strip()
    if not media_allowed(url):
        raise ValueError("목록에 있는 기관 누리집의 글 주소만 열 수 있습니다")
    out: dict = {"url": url}
    if _board_anchor(url, title):
        out["error"] = "글마다 주소가 따로 없는 게시판입니다 — 원문 목록에서 열어 보세요"
        return out
    page = urllib.parse.urlsplit(url)._replace(fragment="").geturl()
    if not robots.allowed(page):
        out["error"] = "robots.txt 차단"
        return out
    get = fetcher or TrackingFetcher(timeout=MEDIA_TIMEOUT)
    data = get(page)
    if data is None:
        why = getattr(get, "why", None)
        out["error"] = why(page) if callable(why) else "응답 없음"
        return out
    if _looks_binary(data):
        out["error"] = "글 화면이 아니라 파일 주소입니다 — 원문 열기로 받으세요"
        return out
    # 목록 기관의 사이트 밖 그림·첨부(책 표지·기사 사진·문의 게시판의 광고)는 세기만 한다
    found = media.extract(decode_text(data), page, title=title, allow=media_allowed)
    # 본문을 iframe 으로 따로 띄우는 게시판 — 같은 사이트의 첫 iframe 을 한 번 더 본다.
    if not found.images and found.frames:
        frame = found.frames[0]
        if media_allowed(frame) and robots.allowed(frame):
            sub = get(frame)
            if sub and not _looks_binary(sub):
                inner = media.extract(decode_text(sub), frame, allow=media_allowed)
                found.images = inner.images
                found.outside_images += inner.outside_images
                if not found.files:
                    found.files = inner.files
                    found.outside_files += inner.outside_files
                found.tables += inner.tables
                found.wide_tables += inner.wide_tables
                found.inline_images += inner.inline_images
                found.kept += inner.kept
    out.update(found.as_dict(debug=debug))
    out["elapsed"] = round(clock() - started, 1)
    return out


def _no_button_reason(url: str, title: str) -> str:
    if not media_allowed(url):
        return "단추 없음 — 목록 기관 밖 사이트"
    if _board_anchor(url, title):
        return "단추 없음 — 글 주소가 따로 없는 게시판"
    return "단추 없음 — 글이 곧 파일인 주소"


def media_sample(
    org_id: str,
    *,
    per_org: int = 3,
    budget: float = DEFAULT_BUDGET,
    fetcher: PageFetcher | None = None,
    delay: float = parallel.DEFAULT_DELAY,
) -> dict:
    """점검용 — 기관의 최근 글을 게시판마다 하나씩 골라 그림·첨부를 찾아 본다."""
    got = collect_one(org_id, days=30, budget=budget / 2, fetcher=fetcher, delay=delay)
    picked: list[dict] = []
    origins: set[str] = set()
    for n in got["notices"]:
        if n.get("origin", "") in origins:
            continue
        origins.add(n.get("origin", ""))
        picked.append(n)
        if len(picked) >= per_org:
            break
    samples = []
    for n in picked:
        ready = media_ready(n["url"], n["title"])
        if not ready:
            # 화면에 단추가 없는 글 — 왜 없는지만 적는다(열어 보지 않는다)
            m = {"error": _no_button_reason(n["url"], n["title"])}
        else:
            try:
                m = media_for(n["url"], n["title"], fetcher=fetcher)
            except ValueError as e:
                m = {"error": str(e)}
        imgs = m.get("images") or []
        files = m.get("files") or []
        samples.append(
            {
                "title": n["title"][:60],
                "url": n["url"],
                "ready": ready,
                "images": len(imgs),
                "files": len(files),
                "tables": m.get("tables", 0),
                "wide": m.get("wide_tables", 0),
                "inline": m.get("inline_images", 0),
                "script_files": m.get("script_files", 0),
                "outside": [m.get("outside_images", 0), m.get("outside_files", 0)],
                "title_found": m.get("title_found", False),
                "error": m.get("error", ""),
                # 점검하는 사람이 오탐을 가려낼 수 있게 — 주소와 첨부 이름만(본문 글자 없음)
                "srcs": [i["src"] for i in imgs[:8]],
                "labels": [f"{f['kind']}|{f['label']}" for f in files[:8]],
            }
        )
    return {"id": org_id, "name": catalog()[org_id].name, "count": got["count"], "samples": samples}


# ── 일괄 점검(배포 후 실측) ──────────────────────────────────────────────────
def discover_only(
    org_id: str,
    *,
    budget: float = DEFAULT_BUDGET,
    fetcher: PageFetcher | None = None,
    delay: float = parallel.DEFAULT_DELAY,
    clock: Callable[[], float] = time.monotonic,
    skip: int = 0,
) -> dict:
    """게시판 **발견만** 한다 — 수집 없이 시간을 전부 발견에 쓴다.

    큰 부처는 후보가 수백 개라 발견만 1~2분이 걸린다. 점검을 '발견 → (캐시로) 수집'
    두 단계로 나누면 한 번의 요청 시간이 짧아도 끝까지 갈 수 있다. 시간이 모자라도
    그때까지 찾은 경로를 돌려준다(후보는 유력한 것부터 시험하므로 앞쪽이 알차다).
    """
    org = catalog()[org_id]
    started = clock()
    deadline = _Deadline(
        _limited(fetcher or TrackingFetcher(), delay), started + budget, clock=clock
    )
    found, notes = govdiscover.enrich(replace(org.source, routes=()), fetcher=deadline, skip=skip)
    return {
        "id": org.id,
        "name": org.name,
        "elapsed": round(clock() - started, 1),
        "timed_out": deadline.left() <= 0,
        "found": [list(r) for r in found.routes],
        "notes": notes[:6],
    }


def verify(
    ids: list[str],
    *,
    days: int = 30,
    fresh: bool = True,
    budget: float = DEFAULT_BUDGET,
    fetcher: PageFetcher | None = None,
    workers: int = 8,
    stage: str = "collect",
    skip: int = 0,
    delay: float = parallel.DEFAULT_DELAY,
) -> list[dict]:
    """여러 기관을 동시에 모아 요약만 돌려준다 — 경로 캐시를 굽는 재료가 된다.

    stage="discover" 면 발견만 하고 찾은 경로(found)를 돌려준다.
    """
    known = [i for i in ids if i in catalog()][:VERIFY_MAX_IDS]

    def one(org_id: str) -> dict:
        if stage == "media":
            try:
                return media_sample(org_id, budget=budget, fetcher=fetcher, delay=delay)
            except Exception as e:
                return {"id": org_id, "name": catalog()[org_id].name, "error": repr(e)[:200]}
        if stage == "discover":
            try:
                return discover_only(org_id, budget=budget, fetcher=fetcher, skip=skip, delay=delay)
            except Exception as e:
                return {"id": org_id, "name": catalog()[org_id].name, "error": repr(e)[:200]}
        try:
            got = collect_one(
                org_id, days=days, fresh=fresh, budget=budget, fetcher=fetcher, delay=delay
            )
        except Exception as e:  # 한 기관의 오류가 묶음 전체를 막지 않게
            return {"id": org_id, "name": catalog()[org_id].name, "error": repr(e)[:200]}
        groups: dict[str, int] = {}
        for n in got["notices"]:
            groups[n["group"]] = groups.get(n["group"], 0) + 1
        return {
            k: got[k]
            for k in ("id", "name", "count", "seen", "mode", "elapsed", "timed_out", "routes")
        } | {"groups": groups, "failures": got["failures"][:6], "notes": got["notes"][:4]}

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(known) or 1))) as pool:
        return list(pool.map(one, known))


def verify_tsv(results: list[dict]) -> str:
    """사람이 훑기 좋은 한 줄 요약 — id · 이름 · 건수 · 방식 · 초 · 첫 사유."""
    lines = []
    for r in results:
        why = r.get("error") or next(iter(r.get("failures") or r.get("notes") or []), "")
        lines.append(
            "\t".join(
                str(x)
                for x in (
                    r["id"],
                    r["name"],
                    r.get("count", 0),
                    r.get("mode", "-"),
                    r.get("elapsed", "-"),
                    str(why)[:160],
                )
            )
        )
    return "\n".join(lines) + "\n"


# ── HTTP ─────────────────────────────────────────────────────────────────────
def _query(path: str) -> dict[str, str]:
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
    return {k: v[0] for k, v in q.items() if v}


class NotFound(LookupError):
    """모르는 경로·기관 — 404 로 답한다."""


def respond(handler: BaseHTTPRequestHandler, route: str) -> None:
    """Vercel 함수와 로컬 서버의 공통 진입점 — 경로 이름으로 나눈다."""
    q = _query(handler.path)
    try:
        if route == "catalog":
            status, body, cache, ctype = 200, catalog_payload(), CACHE_CATALOG, "json"
        elif route == "collect":
            org_id = q.get("id", "")
            if org_id not in catalog():
                raise NotFound(org_id or "(id 없음)")
            body = collect_one(
                org_id,
                days=_int(q.get("days"), DEFAULT_DAYS),
                fresh=q.get("fresh") == "1",
            )
            status, ctype = 200, "json"
            cache = CACHE_OK if body["count"] else CACHE_EMPTY
        elif route == "verify":
            ids = [i for i in q.get("ids", "").split(",") if i]
            # budget: 점검 한 번의 시간(초). 바깥 도구가 오래 못 기다릴 때 줄여 쓴다.
            budget = max(
                10.0, min(float(_int(q.get("budget"), int(DEFAULT_BUDGET))), DEFAULT_BUDGET)
            )
            results = verify(
                ids,
                days=_int(q.get("days"), 30),
                fresh=q.get("fresh") != "0",
                budget=budget,
                workers=VERIFY_MAX_IDS,
                stage=q.get("stage") if q.get("stage") in ("discover", "media") else "collect",
                skip=max(0, _int(q.get("skip"), 0)),
            )
            status, cache = 200, CACHE_VERIFY
            if q.get("format") == "tsv":
                body, ctype = verify_tsv(results), "text"
            else:
                body, ctype = {"results": results}, "json"
        elif route == "media":
            body = media_for(
                q.get("url", ""), q.get("title", "")[:200], debug=q.get("debug") == "1"
            )
            status, ctype = 200, "json"
            cache = CACHE_EMPTY if body.get("error") else CACHE_MEDIA
        else:
            raise NotFound(route)
    except NotFound as e:
        status, body, cache, ctype = 404, {"error": f"모르는 항목: {e}"}, NO_STORE, "json"
    except ValueError as e:
        status, body, cache, ctype = 400, {"error": str(e)}, NO_STORE, "json"
    except Exception as e:  # 예상 못 한 오류도 사유를 돌려준다(조용한 실패 금지)
        status, body, cache, ctype = 500, {"error": f"처리 중 오류: {e!r}"[:300]}, NO_STORE, "json"

    if ctype == "json":
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        # pad: 응답 뒤에 공백을 붙인다(JSON 으로는 무해). 긴 응답만 파일로 저장하는
        # 점검 도구가 결과를 통째로 받게 하려는 것 — 화면은 쓰지 않는다.
        pad = min(max(_int(q.get("pad"), 0), 0), 200_000) if route == "verify" else 0
        data += b" " * pad
        content_type = "application/json; charset=utf-8"
    else:
        data = str(body).encode("utf-8")
        content_type = "text/plain; charset=utf-8"
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", cache)
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(data)


def _int(value: str | None, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError as e:
        raise ValueError(f"숫자가 아닙니다: {value}") from e


# ── 로컬 개발 서버 ───────────────────────────────────────────────────────────
_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}


class _DevHandler(BaseHTTPRequestHandler):
    """public/ 정적 파일 + /api/* — Vercel 과 같은 주소 체계를 흉내 낸다."""

    server_version = "open_site_clipper-web"

    def log_message(self, fmt: str, *args) -> None:  # 조용히(필요하면 여기서 출력)
        return

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith("/api/"):
            respond(self, path[len("/api/") :].strip("/"))
            return
        self._static(path)

    do_HEAD = do_GET

    def _static(self, path: str) -> None:
        rel = path.lstrip("/") or "index.html"
        target = (PUBLIC_DIR / rel).resolve()
        if target.is_dir():
            target = target / "index.html"
        # public/ 밖으로 나가는 경로(../)는 거절한다.
        if PUBLIC_DIR.resolve() not in target.parents or not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


def serve(port: int = 8080, *, lan: bool = False) -> None:
    """휴대폰 화면을 이 컴퓨터에서 띄운다 — lan=True 면 같은 와이파이의 폰에서 열린다."""
    host = "0.0.0.0" if lan else "127.0.0.1"
    httpd = ThreadingHTTPServer((host, port), _DevHandler)
    where = _lan_address() if lan else "127.0.0.1"
    print(f"open_site_clipper 웹 화면: http://{where}:{port}  (끝내려면 Ctrl+C)")
    if lan:
        print("같은 와이파이에 연결된 휴대폰 브라우저에서 위 주소를 여세요.")
    with httpd, contextlib.suppress(KeyboardInterrupt):
        httpd.serve_forever()


def _lan_address() -> str:
    """이 컴퓨터의 사설 IP — 바깥으로 패킷을 보내지 않고 경로만 묻는다."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"
