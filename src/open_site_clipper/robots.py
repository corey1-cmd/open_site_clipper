"""robots.txt 준수 — 우리 User-Agent 기준으로 접근 허용 여부를 묻는다(RFC 9309).

크롤러가 robots.txt를 무시하면 서버에 부담을 주고 IP가 막혀 도구 자체가 못 돈다.
판정은 **표준(RFC 9309)대로** 한다 — 표준 라이브러리 `urllib.robotparser` 는 규칙을 적힌
차례대로 보다가 처음 맞는 것을 쓰고(가장 긴 규칙이 이겨야 한다), 와일드카드('*'·'$')를 글자
그대로 읽는다. 그래서

    User-agent: *
    Disallow: /
    Allow: /bbs/

처럼 '모두 막고 게시판만 연' 학교를 통째로 막힌 것으로 읽었고, 'Disallow: /*.pdf$' 같은
규칙은 못 읽어 열린 것으로 읽었다. 둘 다 사이트가 적은 뜻과 다르다.

동작:
  - 호스트마다 robots.txt를 한 번만 받아 캐시한다(같은 실행 안에서 재사용).
  - robots.txt가 없거나(404 등 4xx) 받지 못하면 **허용**으로 본다(RFC 9309 '이용 불가').
  - 우리 이름(open_site_clipper)으로 된 묶음이 있으면 그것을, 없으면 '*' 묶음을 따른다.
    같은 이름의 묶음이 여럿이면 합친다. 규칙 중 **가장 길게 맞는 것**이 이기고, 길이가
    같으면 Allow 가 이긴다. 맞는 규칙이 없으면 허용. /robots.txt 자신은 늘 허용.
"""

from __future__ import annotations

import contextlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import NamedTuple

from .fetch import USER_AGENT

_TIMEOUT = 10
MAX_ROBOTS_BYTES = 512_000
RAW_KEEP = 20_000  # 점검용으로 남기는 원문 앞부분


class RequestRate(NamedTuple):
    requests: int
    seconds: int


@dataclass(slots=True)
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (허용인가, 경로 꼴)
    crawl_delay: float | None = None
    request_rate: RequestRate | None = None


def product_token(user_agent: str) -> str:
    """'open_site_clipper/0.15 (+https://…)' → 'open_site_clipper'."""
    return user_agent.split("/", 1)[0].strip().lower()


_SAFE = "/?=&;:@+$,!*'()~%-._#[]"


def _normalize(path: str) -> str:
    """비교 전에 퍼센트 인코딩을 한 꼴로 — 한글·공백은 %XX, 이미 인코딩된 것은 그대로."""
    return urllib.parse.quote(urllib.parse.unquote(path), safe=_SAFE)


class Rules:
    """robots.txt 한 장의 RFC 9309 해석."""

    def __init__(self, lines: list[str]):
        self.groups: list[_Group] = []
        self.sitemaps: list[str] = []
        group: _Group | None = None
        in_rules = False
        for raw in lines:
            line = raw.split("#", 1)[0].strip()
            key, sep, value = line.partition(":")
            if not sep:
                continue
            key, value = key.strip().lower(), value.strip()
            if key in ("user-agent", "useragent", "user agent"):
                if group is None or in_rules:  # 규칙 뒤의 user-agent 는 새 묶음
                    group = _Group()
                    self.groups.append(group)
                    in_rules = False
                group.agents.append(product_token(value) if value != "*" else "*")
            elif key in ("allow", "disallow"):
                if group is None:
                    continue  # user-agent 앞의 규칙은 어느 묶음에도 속하지 않는다
                in_rules = True
                if value:  # 'Disallow:' (빈 값)은 규칙이 아니다 — 모두 허용
                    if value[0] not in "/*":
                        value = "/" + value
                    group.rules.append((key == "allow", _normalize(value)))
            elif key == "crawl-delay":
                if group is not None:
                    in_rules = True
                    with contextlib.suppress(ValueError):
                        group.crawl_delay = float(value)
            elif key == "request-rate":
                if group is not None:
                    in_rules = True
                    m = re.match(r"(\d+)\s*/\s*(\d+)", value)
                    if m:
                        group.request_rate = RequestRate(int(m.group(1)), int(m.group(2)))
            elif key == "sitemap":
                url = value
                if url.startswith(("http://", "https://")) and url not in self.sitemaps:
                    self.sitemaps.append(url)

    def groups_for(self, user_agent: str) -> list[_Group]:
        """우리 이름의 묶음들(합친다), 없으면 '*' 묶음들."""
        token = product_token(user_agent)
        mine = [g for g in self.groups if token in g.agents]
        return mine or [g for g in self.groups if "*" in g.agents]

    def verdict(self, user_agent: str, url: str) -> tuple[bool, str]:
        """(허용인가, 이긴 규칙 — 'Disallow: /bbs/' · 규칙 없음은 '')."""
        parts = urllib.parse.urlsplit(url)
        path = parts.path or "/"
        if path == "/robots.txt":
            return True, ""
        target = _normalize(path + ("?" + parts.query if parts.query else ""))
        best_len, best = -1, (True, "")
        for g in self.groups_for(user_agent):
            for allow, pattern in g.rules:
                if not _pattern(pattern).match(target):
                    continue
                n = len(pattern)
                if n > best_len or (n == best_len and allow and not best[0]):
                    best_len = n
                    best = (allow, ("Allow: " if allow else "Disallow: ") + pattern)
        return best

    def can_fetch(self, user_agent: str, url: str) -> bool:
        return self.verdict(user_agent, url)[0]

    def crawl_delay(self, user_agent: str) -> float | None:
        return next((g.crawl_delay for g in self.groups_for(user_agent) if g.crawl_delay), None)

    def request_rate(self, user_agent: str) -> RequestRate | None:
        return next((g.request_rate for g in self.groups_for(user_agent) if g.request_rate), None)


_PATTERNS: dict[str, re.Pattern[str]] = {}


def _pattern(pattern: str) -> re.Pattern[str]:
    """'/bbs/*.do$' → 앞에서부터 맞추는 정규식('*' = 아무 글자 0개 이상, 끝의 '$' = 끝)."""
    got = _PATTERNS.get(pattern)
    if got is None:
        body, anchored = (pattern[:-1], True) if pattern.endswith("$") else (pattern, False)
        regex = ".*".join(re.escape(piece) for piece in body.split("*"))
        got = re.compile(regex + (r"\Z" if anchored else ""), re.S)
        if len(_PATTERNS) > 4096:
            _PATTERNS.clear()
        _PATTERNS[pattern] = got
    return got


# 호스트(scheme+netloc) → 규칙 또는 None(규칙 없음/조회 실패 = 허용)
_CACHE: dict[str, Rules | None] = {}
# robots.txt 원문의 Sitemap: 줄 — 파싱 후 버리면 공짜 정보를 잃는다.
_SITEMAPS: dict[str, list[str]] = {}
_STATUS: dict[str, str] = {}  # 점검용 — 받은 결과('200 1.2KB' · '404' · '시간 초과')
_RAW: dict[str, str] = {}  # 점검용 — 원문 앞부분


def _load(origin: str) -> Rules | None:
    req = urllib.request.Request(
        f"{origin}/robots.txt", headers={"User-Agent": USER_AGENT}, method="GET"
    )
    from . import aia
    from .fetch import _decompress, _read_capped, _SlowResponse

    url = f"{origin}/robots.txt"
    raw = ""
    for attempt in range(2):
        try:
            started = time.monotonic()
            ctx = aia.legacy_context() if aia.is_legacy(url) else aia.context()
            with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
                if resp.status != 200:
                    _STATUS[origin] = str(resp.status)
                    return None
                # 조금씩 흘리는 서버가 점검을 붙잡지 않게 전체 받기 시간도 묶는다(fetch 와 같은 규칙)
                data = _decompress(
                    _read_capped(resp, started, _TIMEOUT), getattr(resp, "headers", None)
                )
                raw = data[:MAX_ROBOTS_BYTES].decode("utf-8", errors="replace")
            break
        except _SlowResponse:
            _STATUS[origin] = "너무 느림"
            return None
        except urllib.error.HTTPError as e:
            _STATUS[origin] = str(e.code)
            return None  # 4xx·5xx — 규칙을 못 읽으면 막지 않는다(fail-open)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            text = str(getattr(e, "reason", e)).lower()
            # 중간 인증서를 안 보내는 서버·옛 TLS 서버 — 화면을 받을 때와 같이 고쳐 한 번 더
            # (robots.txt 만 못 받아 '규칙 없음'으로 넘어가면 사이트의 규칙을 놓친다)
            if attempt == 0 and "certificate" in text and aia.repair(url):
                continue
            if attempt == 0 and aia.needs_legacy(text) and aia.mark_legacy(url):
                continue
            _STATUS[origin] = f"못 받음({str(getattr(e, 'reason', e))[:40]})"
            return None
    if raw.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        _STATUS[origin] = "200 HTML(규칙 아님)"
        return None  # robots.txt 자리에 HTML 화면을 주는 서버 — 규칙이 없다
    _STATUS[origin] = f"200 {len(raw) / 1024:.1f}KB"
    _RAW[origin] = raw[:RAW_KEEP]
    rules = Rules(raw.splitlines())
    # robots.txt 는 표준적으로 `Sitemap: <절대주소>` 를 담는다. 우리는 이미 이
    # 파일을 받고 있으므로 **추가 요청 없이** 사이트맵 주소를 얻을 수 있다.
    _SITEMAPS[origin] = list(rules.sitemaps)
    return rules


def _origin(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def _parser_for(url: str) -> Rules | None:
    """이 URL 이 속한 호스트의 robots 규칙(캐시). 규칙이 없으면 None."""
    origin = _origin(url)
    if not origin:
        return None
    if origin not in _CACHE:
        _CACHE[origin] = _load(origin)
    return _CACHE[origin]


def allowed(url: str, *, user_agent: str = USER_AGENT) -> bool:
    """이 URL을 우리 UA로 가져가도 되는지. 규칙이 없으면 True."""
    if not _origin(url):
        return False
    parser = _parser_for(url)
    if parser is None:
        return True
    return parser.can_fetch(user_agent, url)


def explain(url: str, *, user_agent: str = USER_AGENT) -> dict:
    """점검용 — 이 주소의 판정과 근거(받은 결과·이긴 규칙·우리에게 걸린 규칙들)."""
    origin = _origin(url)
    parser = _parser_for(url) if origin else None
    out: dict = {"robots": _STATUS.get(origin, ""), "allowed": allowed(url, user_agent=user_agent)}
    if parser is not None:
        out["rule"] = parser.verdict(user_agent, url)[1]
        groups = parser.groups_for(user_agent)
        out["group"] = sorted({a for g in groups for a in g.agents})
        out["rules"] = [("Allow: " if a else "Disallow: ") + p for g in groups for a, p in g.rules][
            :40
        ]
        # 예전 판정(표준 라이브러리 — 먼저 적힌 규칙, 와일드카드 없음)과 비교
        from urllib.robotparser import RobotFileParser

        old = RobotFileParser()
        old.parse(_RAW.get(origin, "").splitlines())
        out["stdlib"] = old.can_fetch(user_agent, url)
    return out


def sitemap_urls(url: str) -> list[str]:
    """robots.txt 에 적힌 사이트맵 주소들(추가 요청 없음).

    사이트맵에는 그 사이트의 목록 주소가 대개 전부 들어 있어, 홈 메뉴가
    JavaScript 로만 그려지는 사이트를 우회하는 지름길이 된다.
    """
    origin = _origin(url)
    if not origin:
        return []
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
    _STATUS.clear()
    _RAW.clear()
