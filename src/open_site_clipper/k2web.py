"""K2Web 어댑터 — 한 게시판을 여러 수단으로 시도하는 단계적 폴백(캐스케이드).

한국외대 전 사이트(본부·학생지원·대학원·법인·상담센터·학부)가 K2Web Wizard
하나로 돌아가고 URL 문법이 같다. 그래서 좌표(host·site_id·board_id)만 주면
아래 세 수단을 순서대로 시도한다. **앞 수단이 실패해도 멈추지 않는다.**

  1순위 rss   {host}/bbs/{site}/{board}/rssList.do?row=N   구조화돼 있어 가장 정확
  2순위 list  {host}/bbs/{site}/{board}/artclList.do        목록 표(부서명 포함)
  3순위 api   출처에 설정한 JSON API(api_url + api_paths)   응답 골격을 경로로 지정
  4순위 page  {host}/{site}/{menu}/subview.do               메뉴 페이지에 목록이 박혀 있음
                                                            (/bbs/ 가 막혀도 살아있는 경로)

api 단계는 api_url 이 설정된 출처에서만 시도한다. 필수 경로(items·title·
url|article_no)가 빠진 설정 오류는 요청 전에 걸러 사유로 남긴다.

각 단계는 이런 이유로 다음으로 넘어간다:
  - robots.txt가 그 경로를 막음        → 다음 수단
  - 네트워크 실패·빈 응답              → 다음 수단
  - 받았는데 글이 0건(스킨 변경 등)    → 다음 수단

시도 기록(Attempt)을 남겨 어느 수단으로 몇 건을 얻었는지 보고서에 표기할 수
있게 한다. 조용히 실패하지 않는 것이 이 도구의 방침이다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from . import jsonapi, k2web_parse, parse, robots
from .cascade import (
    FETCH_FAILED,
    NO_ITEMS,
    NOT_CONFIGURED,
    ROBOTS_BLOCKED,
    Attempt,
    Outcome,
    origin_label,
)
from .model import Notice
from .sources import Source

DEFAULT_ROW = 50

# 수단 이름 — 시도 순서이기도 하다.
RSS, LIST, API, PAGE = "rss", "list", "api", "page"


def rss_url(host: str, site_id: str, board_id: int | str, row: int = DEFAULT_ROW) -> str:
    return f"https://{host}/bbs/{site_id}/{board_id}/rssList.do?row={row}"


def list_url(host: str, site_id: str, board_id: int | str) -> str:
    return f"https://{host}/bbs/{site_id}/{board_id}/artclList.do"


def article_url(host: str, site_id: str, board_id: int | str, article_no: str) -> str:
    """글번호로 K2Web 정식 글 주소를 조립 — JSON API가 번호만 줄 때 쓴다."""
    return f"https://{host}/bbs/{site_id}/{board_id}/{article_no}/artclView.do"


def page_url(host: str, site_id: str, menu_no: int | str) -> str:
    return f"https://{host}/{site_id}/{menu_no}/subview.do"


def candidates(source: Source) -> list[tuple[str, str]]:
    """이 출처에 대해 시도할 (수단, URL) 목록을 순서대로."""
    host, site_id = source.host, source.site_id
    if not host or not site_id or source.board_id is None:
        return []
    out = [
        (RSS, rss_url(host, site_id, source.board_id, source.row)),
        (LIST, list_url(host, site_id, source.board_id)),
    ]
    if source.api_url:
        out.append((API, source.api_url))
    if source.menu_no is not None:
        out.append((PAGE, page_url(host, site_id, source.menu_no)))
    return out


def _to_notices(source: Source, rows: list[k2web_parse.Row]) -> list[Notice]:
    return [
        Notice(
            title=r.title,
            url=r.url,
            agency=source.name,
            published=r.published,
            category=source.category,
            rights=source.rights,
            org=source.org,
            site=source.site,
            unit=r.unit or source.site or source.name,
        )
        for r in rows
        if r.title and r.url
    ]


def collect_board(
    source: Source,
    *,
    fetcher: Callable[[str], bytes | None],
    check_robots: bool = True,
) -> Outcome:
    """한 게시판을 RSS → 목록 → 메뉴 순으로 시도해 첫 성공에서 멈춘다."""
    outcome = Outcome()
    cands = candidates(source)
    if not cands:
        outcome.attempts.append(Attempt(RSS, source.url, reason=NOT_CONFIGURED))
        return outcome

    for strategy, url in cands:
        if strategy == API:
            # 필수 경로 없이는 응답을 해석할 수 없다 — 요청 전에 사유를 남기고 통과.
            missing = jsonapi.required_missing(dict(source.api_paths))
            if missing:
                outcome.attempts.append(Attempt(strategy, url, reason=missing))
                continue
        if check_robots and not robots.allowed(url):
            outcome.attempts.append(Attempt(strategy, url, reason=ROBOTS_BLOCKED))
            continue
        data = fetcher(url)
        if not data:
            outcome.attempts.append(Attempt(strategy, url, reason=FETCH_FAILED))
            continue

        if strategy == RSS:
            # K2Web RSS는 표준 RSS 2.0 — 기존 파서를 그대로 쓴다.
            parsed = parse.parse_rss(
                data,
                agency=source.name,
                category=source.category,
                rights=source.rights,
            )
            # RSS에는 부서 칸이 없다 → 사이트명으로 대체(목록 수단은 부서를 준다).
            notices = [
                replace(n, org=source.org, site=source.site, unit=source.site or source.name)
                for n in parsed
            ]
        elif strategy == API:
            rows = jsonapi.parse_items(
                data,
                paths=dict(source.api_paths),
                base_url=url,
                article_url=lambda no: article_url(
                    source.host, source.site_id, source.board_id, no
                ),
            )
            notices = _to_notices(source, rows)
        else:
            notices = _to_notices(source, k2web_parse.parse_list(data, url))

        if not notices:
            outcome.attempts.append(Attempt(strategy, url, reason=NO_ITEMS))
            continue

        notices = [replace(n, origin=origin_label(url, strategy)) for n in notices]
        outcome.attempts.append(Attempt(strategy, url, count=len(notices)))
        outcome.notices = notices
        return outcome

    return outcome
