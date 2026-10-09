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
import time
import urllib.parse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, categories, govcascade, govdiscover, parallel
from .cascade import origin_label
from .collect import KST
from .fetch import TrackingFetcher
from .model import Notice
from .sources import Source, from_dicts

PageFetcher = Callable[[str], "bytes | None"]

# 저장소 뿌리 — Vercel 함수 묶음(/var/task)과 로컬 저장소가 같은 배치다.
ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIR = ROOT / "public"
ROUTE_CACHE_FILE = Path(__file__).with_name("data") / "route-cache.json"

# 화면의 큰 묶음 → 기관 목록 파일. 목록을 늘리려면 여기에 파일만 더하면 된다.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("정부", "examples/sources-gov.json"),
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
        "sections": [name for name, _rel in SECTIONS],
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


def _cascade(source: Source, fetch: PageFetcher) -> tuple[list[Notice], list[str], list[list[str]]]:
    """카테고리별 캐스케이드 — 공지·실패 사유·**실제로 나온 경로**를 함께 돌려준다."""
    notices: list[Notice] = []
    failures: list[str] = []
    used: list[list[str]] = []
    for category in govcascade.categories(source):
        outcome = govcascade.collect_category(source, category, fetcher=fetch)
        if outcome.notices:
            notices.extend(outcome.notices)
            hit = next((a for a in outcome.attempts if a.ok), None)
            # korea.kr 피드는 korea_feed 에서 매번 다시 만들어지므로 적지 않는다.
            if hit is not None and hit.strategy != govcascade.KOREA:
                kind = _ROUTE_KIND.get(hit.strategy, "board")  # alt 는 게시판 주소다
                used.append([category, kind, hit.url])
        else:
            failures.append(f"{category} ({outcome.trail() or '해당 없음'})")
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
    source = org.source
    mode = "discover"
    notes: list[str] = []
    if cached and cached.get("routes"):
        source = replace(source, routes=tuple(tuple(r) for r in cached["routes"]))
        mode = "cache"
    elif source.home and not source.routes:
        source, notes = govdiscover.enrich(source, fetcher=deadline)

    notices, failures, used = _cascade(source, deadline)
    if mode == "cache" and not notices and deadline.left() > REDISCOVER_MIN_LEFT:
        # 캐시해 둔 게시판이 바뀌었을 수 있다 — 홈에서 다시 찾는다.
        source, notes = govdiscover.enrich(replace(org.source, routes=()), fetcher=deadline)
        notices, failures, used = _cascade(source, deadline)
        mode = "rediscover"

    today = today or datetime.now(KST).date()
    cutoff = today - timedelta(days=days)
    rows, seen = [], set()
    for n in sorted(notices, key=lambda n: n.published or date.min, reverse=True):
        if n.published is not None and n.published < cutoff:
            continue
        key = n.dedup_key()
        if key in seen:
            continue
        seen.add(key)
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


def _row(n: Notice) -> dict:
    return {
        "title": n.title,
        "url": n.url,
        "date": n.published.isoformat() if n.published else "",
        "category": n.category,
        "group": categories.canonical(n.category) if n.category else "미분류",
        "unit": n.unit if n.unit and n.unit not in (n.org, n.agency) else "",
        "origin": n.origin or (origin_label(n.url, "board") if n.url else ""),
    }


# ── 일괄 점검(배포 후 실측) ──────────────────────────────────────────────────
def verify(
    ids: list[str],
    *,
    days: int = 30,
    fresh: bool = True,
    budget: float = DEFAULT_BUDGET,
    fetcher: PageFetcher | None = None,
    workers: int = 8,
) -> list[dict]:
    """여러 기관을 동시에 모아 요약만 돌려준다 — 경로 캐시를 굽는 재료가 된다."""
    known = [i for i in ids if i in catalog()][:VERIFY_MAX_IDS]

    def one(org_id: str) -> dict:
        try:
            got = collect_one(org_id, days=days, fresh=fresh, budget=budget, fetcher=fetcher)
        except Exception as e:  # 한 기관의 오류가 묶음 전체를 막지 않게
            return {"id": org_id, "name": catalog()[org_id].name, "error": repr(e)[:200]}
        return {
            k: got[k]
            for k in ("id", "name", "count", "seen", "mode", "elapsed", "timed_out", "routes")
        } | {"failures": got["failures"][:6], "notes": got["notes"][:4]}

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
            results = verify(ids, days=_int(q.get("days"), 30), fresh=q.get("fresh") != "0")
            status, cache = 200, NO_STORE
            if q.get("format") == "tsv":
                body, ctype = verify_tsv(results), "text"
            else:
                body, ctype = {"results": results}, "json"
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
