"""수집 진행 상황 추적 — 무엇을 하고 있고 얼마나 남았는지.

수집은 기관 수십 곳을 병렬로 도느라 몇 분씩 걸린다. 그동안 화면이 멈춘 것처럼
보이면 사람은 실패한 줄 안다. 그래서 **지금 어느 기관의 어느 주소를 두드리는지**,
**몇 곳 중 몇 곳을 끝냈는지**, **얼마나 더 걸릴지**를 모아 둔다.

수집 스레드 여러 개가 동시에 기록하므로 잠금으로 보호한다. 읽는 쪽(웹 UI 폴링)은
snapshot() 으로 한 시점의 사본을 받아 간다 — 읽는 도중에 값이 바뀌지 않는다.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Snapshot:
    """한 시점의 진행 상황 사본."""

    total: int
    done: int
    elapsed: float
    eta: float  # 남은 예상 시간(초). 아직 모르면 -1
    collected: int
    active: tuple[tuple[str, str], ...] = ()  # (기관, 지금 두드리는 주소)
    finished: tuple[tuple[str, int], ...] = ()  # (기관, 건수) — 최근 것부터

    @property
    def percent(self) -> int:
        return int(self.done * 100 / self.total) if self.total else 0


@dataclass
class Tracker:
    """진행 상황을 모으는 그릇. 수집 코드가 여기에 알려 준다."""

    total: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _started: float = field(default_factory=time.monotonic)
    _done: int = 0
    _collected: int = 0
    _active: dict[str, str] = field(default_factory=dict)
    _finished: list[tuple[str, int]] = field(default_factory=list)

    def start(self, org: str) -> None:
        with self._lock:
            self._active[org] = "시작"

    def fetching(self, org: str, url: str) -> None:
        """지금 두드리는 주소 — 사람이 읽기 좋게 짧게 줄여 둔다."""
        with self._lock:
            if org in self._active:
                self._active[org] = url

    def finish(self, org: str, count: int) -> None:
        with self._lock:
            self._active.pop(org, None)
            self._done += 1
            self._collected += count
            self._finished.append((org, count))

    def wrap(self, org: str, fetcher):
        """페처를 감싸 요청 직전에 주소를 알린다(수집 동작은 그대로)."""

        def reporting(url: str):
            self.fetching(org, url)
            return fetcher(url)

        why = getattr(fetcher, "why", None)
        if callable(why):
            reporting.why = why  # 실패 사유 전달 경로를 잃지 않는다
        return reporting

    def snapshot(self) -> Snapshot:
        with self._lock:
            elapsed = time.monotonic() - self._started
            # 끝난 기관들의 평균 시간으로 남은 시간을 어림한다.
            eta = (elapsed / self._done) * (self.total - self._done) if self._done else -1.0
            return Snapshot(
                total=self.total,
                done=self._done,
                elapsed=elapsed,
                eta=eta,
                collected=self._collected,
                active=tuple(sorted(self._active.items())),
                finished=tuple(reversed(self._finished[-8:])),
            )
