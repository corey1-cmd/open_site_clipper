"""병렬 수집 — 기관은 동시에, 한 서버에는 천천히.

65곳을 순차로 돌면 16분이지만, **기관별로 병렬**로 돌리면 가장 느린 기관
하나의 시간만 걸린다. 기관마다 서버가 다르므로 동시에 보내도 어느 한 서버에
부담이 몰리지 않는다.

부담이 몰리는 것을 막는 것은 **호스트별 간격**이다. 같은 호스트로 가는 요청
사이에 최소 간격을 강제한다. 간격은 이 순서로 정한다:

    ① robots.txt 의 Crawl-delay / Request-rate  ← 사이트가 직접 말한 값
    ② 그것이 없으면 기본값(--delay)

사이트가 "5초 쉬어라"라고 적어 두었으면 그것을 따른다. 숫자를 우리가 정하기
전에 상대에게 먼저 묻는 것이 옳다.

표준 라이브러리(concurrent.futures·threading)만 쓴다.
"""

from __future__ import annotations

import threading
import time
import urllib.parse
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from . import robots

DEFAULT_JOBS = 16
DEFAULT_DELAY = 1.0
MAX_JOBS = 32
# 사이트가 터무니없이 긴 지연을 적어 둔 경우의 상한 — 수집이 사실상 멈추는 것을 막는다.
MAX_HONORED_DELAY = 10.0

T = TypeVar("T")
R = TypeVar("R")


class HostLimiter:
    """호스트별 최소 요청 간격을 지키는 게이트.

    스레드가 여러 개여도 같은 호스트로는 순서대로, 간격을 두고 나간다.
    robots.txt 가 간격을 지정했으면 그 값을 쓴다(호스트당 1회 조회 후 캐시).
    """

    def __init__(self, default_delay: float = DEFAULT_DELAY, *, use_robots: bool = True):
        self.default_delay = max(0.0, default_delay)
        self._use_robots = use_robots
        self._lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._next_at: dict[str, float] = {}
        self._delays: dict[str, float] = {}

    def _host(self, url: str) -> str:
        return urllib.parse.urlsplit(url).netloc.lower()

    def delay_for(self, url: str) -> float:
        """이 호스트에 적용할 간격 — robots 지정값 우선, 없으면 기본값."""
        host = self._host(url)
        with self._lock:
            if host in self._delays:
                return self._delays[host]
        delay = self.default_delay
        if self._use_robots:
            stated = robots.stated_delay(url)
            if stated is not None:
                # 사이트가 말한 값을 따르되, 상한을 둔다.
                delay = min(max(stated, 0.0), MAX_HONORED_DELAY)
        with self._lock:
            self._delays[host] = delay
        return delay

    def _host_lock(self, host: str) -> threading.Lock:
        with self._lock:
            lock = self._locks.get(host)
            if lock is None:
                lock = self._locks[host] = threading.Lock()
            return lock

    def wait(self, url: str) -> None:
        """이 URL 을 요청해도 될 때까지 기다린다."""
        host = self._host(url)
        delay = self.delay_for(url)
        if delay <= 0:
            return
        with self._host_lock(host):
            now = time.monotonic()
            due = self._next_at.get(host, 0.0)
            if due > now:
                time.sleep(due - now)
                now = time.monotonic()  # 늦게 깨어났으면 그때부터 센다(간격이 줄지 않게)
            self._next_at[host] = now + delay

    def wrap(self, fetcher: Callable[[str], bytes | None]) -> Callable[[str], bytes | None]:
        """페처를 감싸 호출 직전에 간격을 지키게 한다.

        원본 페처가 실패 사유를 알려 주는 `why()` 를 갖고 있으면 **그대로 넘긴다.**
        감싸면서 잃어버리면 캐스케이드가 '403'·'429' 같은 진짜 원인을 못 읽고
        전부 '응답 없음' 으로 뭉뚱그리게 된다(실제로 그렇게 되고 있었다).
        """

        def limited(url: str) -> bytes | None:
            self.wait(url)
            return fetcher(url)

        why = getattr(fetcher, "why", None)
        if callable(why):
            limited.why = why  # type: ignore[attr-defined]
        return limited


def run_parallel(
    items: Sequence[T],
    work: Callable[[T], R],
    *,
    jobs: int = DEFAULT_JOBS,
    on_error: Callable[[T, Exception], R] | None = None,
) -> list[R]:
    """항목들을 병렬로 처리하고 **입력 순서 그대로** 결과를 돌려준다.

    결정론을 지키기 위해 순서를 보존한다(보고서가 실행할 때마다 달라지면 안 된다).
    한 항목이 예외를 내도 전체가 멈추지 않는다 — on_error 로 대체값을 만든다.
    """
    if not items:
        return []
    workers = max(1, min(int(jobs) or 1, MAX_JOBS, len(items)))
    if workers == 1:
        results: list[R] = []
        for item in items:
            try:
                results.append(work(item))
            except Exception as e:
                if on_error is None:
                    raise
                results.append(on_error(item, e))
        return results

    def guarded(item: T) -> R:
        try:
            return work(item)
        except Exception as e:
            if on_error is None:
                raise
            return on_error(item, e)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(guarded, items))


def iter_parallel(
    items: Sequence[T], work: Callable[[T], R], *, jobs: int = DEFAULT_JOBS
) -> Iterable[R]:
    """run_parallel 의 지연 평가판 — 큰 목록을 스트리밍할 때."""
    workers = max(1, min(int(jobs) or 1, MAX_JOBS, len(items) or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        yield from pool.map(work, items)
