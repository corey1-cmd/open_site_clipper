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

_TIMEOUT = 10


def _load(origin: str) -> RobotFileParser | None:
    parser = RobotFileParser()
    parser.set_url(f"{origin}/robots.txt")
    req = urllib.request.Request(
        f"{origin}/robots.txt", headers={"User-Agent": USER_AGENT}, method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            raw = resp.read(512_000).decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None  # 규칙을 못 읽으면 막지 않는다(fail-open)
    parser.parse(raw.splitlines())
    return parser


def allowed(url: str, *, user_agent: str = USER_AGENT) -> bool:
    """이 URL을 우리 UA로 가져가도 되는지. 규칙이 없으면 True."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _CACHE:
        _CACHE[origin] = _load(origin)
    parser = _CACHE[origin]
    if parser is None:
        return True
    return parser.can_fetch(user_agent, url)


def reset_cache() -> None:
    """테스트·장기 실행용 캐시 비우기."""
    _CACHE.clear()
