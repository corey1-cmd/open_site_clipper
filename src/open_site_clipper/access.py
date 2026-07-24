"""접근 진단(--check-access) — 어디가 왜 막히는지 **수집 전에** 알아본다.

두 가지를 바로잡기 위한 도구다.

① **판정 주체**: 남이 다른 도구로 잰 robots 차단은 우리에게 그대로 적용되지
   않는다. robots.txt 는 User-Agent 별로 규칙이 갈리므로, 우리 UA
   (`open_site_clipper/…`)로 직접 물어야 한다.

② **차단의 종류**: "이 사이트는 차단"이라는 한 줄로는 부족하다. robots 는
   **경로 단위**라서 두 경우가 완전히 다르다.

   - **전면 차단**(`Disallow: /`) — 어떤 주소를 찾아도 소용없다. korea.kr·
     data.go.kr 같은 다른 도메인 경로만 남는다.
   - **경로별 차단** — 게시판은 막혀도 다른 진입 경로는 열려 있을 수 있다.
     한국외대에서 `/bbs/…`(차단) 대신 `/{site}/{menu}/subview.do`(허용)로 88건을
     받은 것이 이 경우다. 이런 기관에는 대체 경로 탐색이 값을 한다.

수집은 하지 않는다. robots.txt 만 읽고(호스트당 1회, 캐시됨) 표를 낸다.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field

from . import robots
from .sources import Source

# 판정 결과
FULL = "full"  # 후보 경로 전부 허용
PARTIAL = "partial"  # 일부만 허용 — 열린 경로로 수집 가능
PATHS_ONLY = "paths"  # 후보는 다 막혔지만 루트는 열림 — 다른 경로를 찾을 여지
BLOCKED = "blocked"  # 루트까지 차단 — 직접 수집 불가
KOREA_ONLY = "korea_only"  # 자체 경로가 설정되지 않음 — 외부 배포 경로만 있음

_VERDICT_LABEL = {
    FULL: "✓ 전 경로 허용",
    PARTIAL: "◐ 일부 허용 — 열린 경로로 수집",
    PATHS_ONLY: "◐ 후보 경로만 차단 — 대체 경로 탐색 여지",
    BLOCKED: "✗ 전면 차단 — korea.kr·data.go.kr 만",
    KOREA_ONLY: "— 자체 경로 미설정 — 보도자료만",
}


# 기관 자체 사이트를 두드리는 단계들(외부 배포 경로와 구분).
OWN_STAGES = ("rss", "board", "alt", "list", "page", "api")


@dataclass(frozen=True, slots=True)
class PathCheck:
    """후보 주소 하나에 대한 판정."""

    label: str  # 단계 이름(rss·board·page…)
    url: str
    allowed: bool


@dataclass(slots=True)
class OrgAccess:
    """기관 하나의 진단 결과."""

    org: str
    checks: list[PathCheck] = field(default_factory=list)
    roots: dict[str, bool] = field(default_factory=dict)  # 호스트 → 루트 허용 여부

    @property
    def allowed_count(self) -> int:
        return sum(1 for c in self.checks if c.allowed)

    @property
    def has_own_paths(self) -> bool:
        """기관 자체 사이트 경로가 후보에 있는가(외부 배포 경로만이면 False)."""
        return any(c.label.rsplit("/", 1)[-1] in OWN_STAGES for c in self.checks)

    @property
    def verdict(self) -> str:
        if self.checks and not self.has_own_paths:
            # korea.kr·datago 만 있는 상태를 '전 경로 허용'이라 하면 오해를 준다.
            return KOREA_ONLY
        if not self.checks:
            return PATHS_ONLY if any(self.roots.values()) else BLOCKED
        if self.allowed_count == len(self.checks):
            return FULL
        if self.allowed_count > 0:
            return PARTIAL
        return PATHS_ONLY if any(self.roots.values()) else BLOCKED

    @property
    def label(self) -> str:
        return _VERDICT_LABEL[self.verdict]


def candidate_urls(source: Source) -> list[tuple[str, str]]:
    """이 출처가 실제로 두드릴 (단계, 주소) 목록 — 캐스케이드와 같은 것을 쓴다."""
    if source.kind == "govorg":
        from . import govcascade

        out: list[tuple[str, str]] = []
        for category in govcascade.categories(source):
            out.extend(
                (f"{category}/{stage}", url)
                for stage, url in govcascade.stages_for(source, category)
            )
        return out
    if source.kind == "k2web":
        from . import k2web

        return k2web.candidates(source)
    return [(source.kind, source.url)] if source.url else []


def _hosts(pairs: list[tuple[str, str]]) -> list[str]:
    seen: list[str] = []
    for _label, url in pairs:
        parts = urllib.parse.urlsplit(url)
        if parts.netloc and parts.netloc not in seen:
            seen.append(parts.netloc)
    return seen


def check(
    sources: list[Source], *, allowed: Callable[[str], bool] | None = None
) -> list[OrgAccess]:
    """출처 목록을 기관 단위로 묶어 접근 가능 여부를 진단한다."""
    ask = allowed or robots.allowed
    by_org: dict[str, OrgAccess] = {}
    for source in sources:
        key = source.org or source.name
        entry = by_org.setdefault(key, OrgAccess(org=key))
        pairs = candidate_urls(source)
        for label, url in pairs:
            entry.checks.append(PathCheck(label=label, url=url, allowed=bool(ask(url))))
        for host in _hosts(pairs):
            if host not in entry.roots:
                scheme = urllib.parse.urlsplit(pairs[0][1]).scheme or "https"
                entry.roots[host] = bool(ask(f"{scheme}://{host}/"))
    return list(by_org.values())


def _width(text: str) -> int:
    """한글·전각 문자를 2칸으로 세어 표 정렬을 맞춘다."""
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: str, target: int) -> str:
    return text + " " * max(0, target - _width(text))


def render(results: list[OrgAccess]) -> str:
    """사람이 읽는 진단표."""
    if not results:
        return "진단할 출처가 없습니다."
    width = max(_width(r.org) for r in results)
    lines = [f"{_pad('기관', width)}  {'허용/전체':>9}  결론"]
    for r in sorted(results, key=lambda x: (x.verdict != BLOCKED, x.org)):
        ratio = f"{r.allowed_count}/{len(r.checks)}"
        lines.append(f"{_pad(r.org, width)}  {ratio:>9}  {r.label}")
        for c in r.checks:
            if not c.allowed:
                lines.append(f"{' ' * width}    ✗ {c.label}: {c.url}")
    tally: dict[str, int] = {}
    for r in results:
        tally[r.verdict] = tally.get(r.verdict, 0) + 1
    summary = " · ".join(
        f"{_VERDICT_LABEL[v].split(' ', 1)[1].split(' —')[0]} {n}" for v, n in sorted(tally.items())
    )
    lines.append("")
    lines.append(f"요약: 기관 {len(results)}곳 — {summary}")
    lines.append("※ robots.txt 는 User-Agent 별로 규칙이 다릅니다. 위 판정은 이 도구 기준입니다.")
    return "\n".join(lines)
