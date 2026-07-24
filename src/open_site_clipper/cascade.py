"""단계적 폴백의 공통 뼈대 — 어느 수단으로 얻었고 무엇이 왜 막혔는지 남긴다.

대학(K2Web)과 정부, 두 캐스케이드가 이 구조를 공유한다. 핵심 규칙 하나:
**조용히 실패하지 않는다.** 성공한 수단만이 아니라 건너뛴 수단과 그 사유를
전부 기록해, 보고서 표지에 그대로 표기한다.

    rss: robots.txt 차단 → board: robots.txt 차단 → korea: 42건
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Notice

# 단계가 다음으로 넘어가는 사유 — 표기를 한곳에서 관리한다.
ROBOTS_BLOCKED = "robots.txt 차단"
FETCH_FAILED = "응답 없음"
NO_ITEMS = "글 0건"
NOT_CONFIGURED = "좌표 미설정"
NOT_AVAILABLE = "해당 없음"


@dataclass(frozen=True, slots=True)
class Attempt:
    """한 수단의 시도 결과 — 성공이든 실패든 남긴다."""

    strategy: str
    url: str
    count: int = 0
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.count > 0


@dataclass(slots=True)
class Outcome:
    """한 수집 단위의 최종 결과 + 시도 이력."""

    notices: list[Notice] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def strategy(self) -> str:
        """실제로 성공한 수단(없으면 "")."""
        return next((a.strategy for a in self.attempts if a.ok), "")

    def trail(self) -> str:
        """사람이 읽는 시도 이력 — 'rss: robots.txt 차단 → board: 12건'."""
        return " → ".join(
            f"{a.strategy}: {a.count}건" if a.ok else f"{a.strategy}: {a.reason}"
            for a in self.attempts
        )
