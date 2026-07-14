"""수집 오케스트레이션 — 출처 목록 → Notice 목록 → Report.

각 출처를 가져와(fetch) 파싱(parse)하고, 중복을 접고, 기간·기관으로 걸러
발행일 내림차순으로 정렬한다. 네트워크 계층은 주입 가능(fetcher)해서 테스트·
오프라인 모드가 같은 경로를 쓴다(의존성 역전).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import parse
from .model import Notice, Report
from .sources import Source

# 출처 하나를 바이트로 가져오는 함수(주입 가능). 기본은 실시간 HTTP.
Fetcher = Callable[[Source], "bytes | None"]

KST = timezone(timedelta(hours=9))


def _live_fetcher(source: Source) -> bytes | None:
    from .fetch import fetch_url

    return fetch_url(source.url)


def local_fetcher(input_dir: str | Path) -> Fetcher:
    """--input 오프라인 모드용 페처 — <input_dir>/<source.id> 파일을 읽는다.

    파일명은 소스 id(확장자 무시 매칭). 예: input_dir/mois.xml, input_dir/gg.rss.
    """
    root = Path(input_dir)

    def _read(source: Source) -> bytes | None:
        from .fetch import read_local

        for candidate in sorted(root.glob(f"{source.id}.*")):
            data = read_local(candidate)
            if data is not None:
                return data
        exact = root / source.id
        return read_local(exact) if exact.exists() else None

    return _read


def _parse_source(source: Source, data: bytes) -> list[Notice]:
    if source.kind == "datago":
        return parse.parse_datago(
            data, agency=source.name, rights=source.rights, category=source.category
        )
    return parse.parse_rss(data, agency=source.name, rights=source.rights, category=source.category)


def collect(
    sources: list[Source],
    *,
    since_days: int | None = None,
    agency: str | None = None,
    fetcher: Fetcher | None = None,
    now: date | None = None,
) -> Report:
    """출처를 수집해 Report를 만든다.

    since_days: 최근 N일 이내 공지만(발행일 미상은 보수적으로 포함).
    agency: 기관명 부분일치 필터(예: "행안" → 행정안전부).
    fetcher: 바이트 획득 함수(테스트·오프라인 주입). 기본은 실시간 HTTP.
    """
    fetch = fetcher or _live_fetcher
    today = now or datetime.now(KST).date()
    cutoff = today - timedelta(days=since_days) if since_days is not None else None

    seen: set[str] = set()
    collected: list[Notice] = []
    failed: list[str] = []

    for source in sources:
        if not source.enabled:
            continue
        data = fetch(source)
        if not data:
            failed.append(source.name)
            continue
        for notice in _parse_source(source, data):
            if cutoff is not None and notice.published is not None and notice.published < cutoff:
                continue
            if agency and agency not in notice.agency:
                continue
            key = notice.dedup_key()
            if key in seen:
                continue
            seen.add(key)
            collected.append(notice)

    collected.sort(key=lambda n: (n.published or date.min, n.agency), reverse=True)

    return Report(
        notices=collected,
        generated_at=datetime.now(KST).replace(microsecond=0).isoformat(),
        since_days=since_days,
        failed_sources=failed,
    )
