"""robots.txt 준수 — 우리 User-Agent 기준으로 접근 허용 여부를 묻는다.

크롤러가 robots.txt를 무시하면 서버에 부담을 주고 IP가 막혀 도구 자체가 못 돈다.
표준 라이브러리 `urllib.robotparser`만 쓰므로 의존성은 그대로 0이다.

동작:
  - 호스트마다 robots.txt를 한 번만 받아 캐시한다(같은 실행 안에서 재사용).
  - robots.txt가 없거나(404) 받지 못하면 **허용**으로 본다(fail-open) — 규칙이
    없는 사이트를 못 읽는 게 더 이상하다.
  - 규칙 판정은 우리 UA 문자열로 한다. 같은 경로라도 UA에 따라 허용/차단이
    갈리므로 사람이 추측하지 않고 런타임에 물어보는 것이 정확하다.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from urllib.robotparser import RobotFileParser

from .fetch import USER_AGENT

# 호스트(scheme+netloc) → 파서 또는 None(규칙 없음/조회 실패 = 허용)
_CACHE: dict[str, RobotFileParser | None] = {}
# robots.txt 원문의 Sitemap: 줄 — 파싱 후 버리면 공짜 정보를 잃는다.
_SITEMAPS: dict[str, list[str]] = {}

_TIMEOUT = 10


def _load(origin: str) -> RobotFileParser | None:
    parser = RobotFileParser()
    parser.set_url(f"{origin}/robots.txt")
    req = urllib.request.Request(
        f"{origin}/robots.txt", headers={"User-Agent": USER_AGENT}, method="GET"
    )
    try:
        from . import aia

        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=aia.context()) as resp:
            if resp.status != 200:
                return None
            raw = resp.read(512_000).decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None  # 규칙을 못 읽으면 막지 않는다(fail-open)
    lines = raw.splitlines()
    parser.parse(lines)
    # robots.txt 는 표준적으로 `Sitemap: <절대주소>` 를 담는다. 우리는 이미 이
    # 파일을 받고 있으므로 **추가 요청 없이** 사이트맵 주소를 얻을 수 있다.
    found: list[str] = []
    for line in lines:
        key, _, value = line.partition(":")
        if key.strip().lower() == "sitemap":
            url = value.strip()
            if url.startswith(("http://", "https://")) and url not in found:
                found.append(url)
    _SITEMAPS[origin] = found
    return parser


def _parser_for(url: str) -> RobotFileParser | None:
    """이 URL 이 속한 호스트의 robots 파서(캐시). 규칙이 없으면 None."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _CACHE:
        _CACHE[origin] = _load(origin)
    return _CACHE[origin]


def allowed(url: str, *, user_agent: str = USER_AGENT) -> bool:
    """이 URL을 우리 UA로 가져가도 되는지. 규칙이 없으면 True."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    parser = _parser_for(url)
    if parser is None:
        return True
    return parser.can_fetch(user_agent, url)


def sitemap_urls(url: str) -> list[str]:
    """robots.txt 에 적힌 사이트맵 주소들(추가 요청 없음).

    사이트맵에는 그 사이트의 목록 주소가 대개 전부 들어 있어, 홈 메뉴가
    JavaScript 로만 그려지는 사이트를 우회하는 지름길이 된다.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return []
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _CACHE:
        _parser_for(url)  # 캐시를 채우면서 Sitemap 도 함께 수집된다
    return list(_SITEMAPS.get(origin, ()))


def stated_delay(url: str, *, user_agent: str = USER_AGENT) -> float | None:
    """사이트가 robots.txt 에 적어 둔 요청 간격(초). 없으면 None.

    `Crawl-delay: 5` 는 5초, `Request-rate: 1/10` 은 10초에 1회라는 뜻이다.
    둘 다 있으면 더 여유 있는(긴) 쪽을 따른다 — 상대가 요구한 최소 간격을
    지키는 것이 목적이므로 짧은 쪽을 고르면 안 된다.
    """
    parser = _parser_for(url)
    if parser is None:
        return None
    candidates: list[float] = []
    try:
        delay = parser.crawl_delay(user_agent)
        if delay is not None:
            candidates.append(float(delay))
    except (AttributeError, ValueError, TypeError):
        pass
    try:
        rate = parser.request_rate(user_agent)
        if rate is not None and rate.requests > 0:
            candidates.append(float(rate.seconds) / float(rate.requests))
    except (AttributeError, ValueError, TypeError, ZeroDivisionError):
        pass
    return max(candidates) if candidates else None


def reset_cache() -> None:
    """테스트·장기 실행용 캐시 비우기."""
    _CACHE.clear()
    _SITEMAPS.clear()
