"""수집 오케스트레이션 — 출처 목록 → Notice 목록 → Report.

각 출처를 가져와(fetch) 파싱(parse)하고, 중복을 접고, 기간·기관으로 걸러
발행일 내림차순으로 정렬한다. 네트워크 계층은 주입 가능(fetcher)해서 테스트·
오프라인 모드가 같은 경로를 쓴다(의존성 역전).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import parse, rights
from .model import Notice, Report
from .sources import Source

# 출처 하나를 바이트로 가져오는 함수(주입 가능). 기본은 실시간 HTTP.
Fetcher = Callable[[Source], "bytes | None"]

KST = timezone(timedelta(hours=9))


def _live_fetcher(source: Source) -> bytes | None:
    from .fetch import datago_url, fetch_url

    url = source.url
    if source.kind == "datago":
        # 인증키(OSC_DATAGO_KEY) 주입. 키가 없으면 네트워크를 두드리지 않고
        # 바로 실패시킨다 — collect()가 "인증키 미설정"으로 구분 표기한다.
        url = datago_url(url)
        if url is None:
            return None
    return fetch_url(url)


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


def _collect_k2web(source: Source, *, fetcher: Fetcher | None, failed: list[str]) -> list[Notice]:
    """K2Web 출처를 캐스케이드로 수집하고, 실패 시 시도 이력을 실패 목록에 남긴다."""
    from . import k2web

    if fetcher is not None:
        # 오프라인(--input/--demo): 주입된 페처는 Source 단위라 캐스케이드를 쓰지 않는다.
        data = fetcher(source)
        if not data:
            failed.append(source.name)
            return []
        return _parse_source(source, data)

    from .fetch import fetch_url

    outcome = k2web.collect_board(source, fetcher=fetch_url)
    if not outcome.notices:
        # 어느 수단이 왜 실패했는지 그대로 보고서에 남긴다(조용한 실패 금지).
        failed.append(f"{source.name} ({outcome.trail()})")
    return outcome.notices


def _failure_label(source: Source, *, live: bool) -> str:
    """실패 출처 표기 — datago 인증키 미설정은 네트워크 실패와 구분해 알린다."""
    if live and source.kind == "datago":
        from .fetch import DATAGO_KEY_ENV, datago_url

        if datago_url(source.url) is None:
            return f"{source.name} (인증키 미설정: {DATAGO_KEY_ENV})"
    return source.name


def _parse_source(source: Source, data: bytes) -> list[Notice]:
    if source.kind == "datago":
        return parse.parse_datago(
            data, agency=source.name, rights=source.rights, category=source.category
        )
    return parse.parse_rss(data, agency=source.name, rights=source.rights, category=source.category)


QUOTE_CONSERVATIVE = "conservative"  # 등급이 변형을 허락할 때만 발췌(기본)
QUOTE_FULL = "full"  # 등급 미상이어도 발췌 유지 — 교내 공지처럼 표기 관행이 없는 곳용
QUOTE_MODES = (QUOTE_CONSERVATIVE, QUOTE_FULL)


def collect(
    sources: list[Source],
    *,
    since_days: int | None = None,
    agency: str | None = None,
    fetcher: Fetcher | None = None,
    now: date | None = None,
    quote_mode: str = QUOTE_CONSERVATIVE,
) -> Report:
    """출처를 수집해 Report를 만든다.

    since_days: 최근 N일 이내 공지만(발행일 미상은 보수적으로 포함).
    agency: 기관명 부분일치 필터(예: "행안" → 행정안전부).
    fetcher: 바이트 획득 함수(테스트·오프라인 주입). 기본은 실시간 HTTP.
    """
    live = fetcher is None
    fetch = fetcher or _live_fetcher
    today = now or datetime.now(KST).date()
    cutoff = today - timedelta(days=since_days) if since_days is not None else None

    seen: set[str] = set()
    collected: list[Notice] = []
    failed: list[str] = []

    for source in sources:
        if not source.enabled:
            continue

        if source.kind == "k2web":
            # 단계적 폴백(RSS → 목록 → 메뉴). 오프라인 모드에서는 기존 페처를 쓴다.
            parsed = _collect_k2web(source, fetcher=fetcher, failed=failed)
        else:
            data = fetch(source)
            if not data:
                failed.append(_failure_label(source, live=live))
                continue
            parsed = _parse_source(source, data)

        for notice in parsed:
            if cutoff is not None and notice.published is not None and notice.published < cutoff:
                continue
            if agency and agency not in notice.agency:
                continue
            key = notice.dedup_key()
            if key in seen:
                continue
            seen.add(key)
            # 인용 정책 — 기본(conservative)은 변형이 금지된 등급(3·4유형·미상)의
            # 요약 발췌를 비운다(rights.py 정책의 강제). 대학·교내 공지처럼 공공누리
            # 표기 관행 자체가 없는 곳은 전부 '미상'이라 발췌가 항상 빈칸이 되므로,
            # 그런 맥락에서는 quote_mode="full" 로 발췌를 유지한다(사용자 선택).
            if (
                quote_mode != QUOTE_FULL
                and notice.summary
                and not rights.allows_derivative(notice.rights)
            ):
                notice = replace(notice, summary="")
            if source.topics:
                # 출처의 정체성을 항목에 승계 — 관련성 가점·주제 섹션화의 축.
                notice = replace(notice, topics=source.topics)
            if source.org and not notice.org:
                # 기관 계층 승계(k2web 은 이미 채워 온다).
                notice = replace(
                    notice,
                    org=source.org,
                    site=source.site or source.name,
                    unit=notice.unit or source.site or source.name,
                )
            collected.append(notice)

    collected.sort(key=lambda n: (n.published or date.min, n.agency), reverse=True)

    return Report(
        notices=collected,
        generated_at=datetime.now(KST).replace(microsecond=0).isoformat(),
        since_days=since_days,
        failed_sources=failed,
    )


def enrich_links(
    notices: list[Notice],
    *,
    fetcher: Callable[[str], bytes | None] | None = None,
    limit: int = 20,
    quote_mode: str = QUOTE_CONSERVATIVE,
) -> list[Notice]:
    """공지 본문에서 관련 자료 링크만 캐 Notice.links에 채운다(--deep-links).

    본문 페이지를 공지마다 한 번씩 받아오므로 비용이 크다. 그래서:
      - 앞에서부터 limit개까지만(기본 20) — 보고서 상단에 올 항목만 보강
      - 변형 금지 등급(3·4유형·미상)은 건너뛴다. 첨부는 원문 자체이므로
        보수적 인용 정책(제목·링크·출처만)의 취지를 링크 수집에도 적용한다
      - 실패한 페이지는 조용히 건너뛴다(fail-open) — 링크가 없을 뿐이다
    """
    from . import deeplink

    fetch = fetcher or _live_page_fetcher
    out: list[Notice] = []
    budget = limit
    for n in notices:
        gated = quote_mode != QUOTE_FULL and not rights.allows_derivative(n.rights)
        if budget <= 0 or not n.url or gated:
            out.append(n)
            continue
        budget -= 1
        data = fetch(n.url)
        if not data:
            out.append(n)
            continue
        links = deeplink.extract(data, n.url)
        out.append(replace(n, links=tuple(links)) if links else n)
    return out


def _live_page_fetcher(url: str) -> bytes | None:
    from .fetch import fetch_url

    return fetch_url(url)
