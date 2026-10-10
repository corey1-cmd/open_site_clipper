"""정부 캐스케이드 — 메뉴 종류마다 여러 경로를 돌려가며 시도한다.

대학(K2Web)은 CMS 가 하나라 좌표로 주소 4개를 **생성**했다. 정부는 CMS 가
19종이라 생성이 안 되고, 각 단계가 주는 것도 다르다(korea.kr 은 보도자료만).
그래서 두 가지를 바꾼다:

  ① 후보 주소를 **생성이 아니라 설정·발견**으로 받는다(`routes`).
  ② 기관 단위가 아니라 **카테고리(보도자료·공지·인사·채용·입찰) 단위**로 폴백한다.
     보도자료가 korea.kr 로 됐다고 채용 게시판을 안 봐도 되는 게 아니기 때문.

카테고리마다 아래 순서로 시도하고, 앞이 막히면 다음으로 넘어간다:

    1 rss     기관 자체 피드            robots 검사
    2 board   기관 게시판 목록(HTML)     robots 검사
    3 alt     같은 목록의 다른 주소      robots 검사  ← 대학의 subview.do 에 해당
    4 datago  공공데이터포털 OpenAPI     robots 무관(키 기반 정식 API)
    5 korea   korea.kr 부처 피드         robots 무관(타 도메인) — 보도자료 안전망

`alt` 는 **우회가 아니다.** robots 가 막은 주소 대신, 같은 내용을 담은 다른
주소를 찾아 **robots 판정을 다시 받는 것**이다. 판정에서 또 막히면 그대로 건너뛴다.
어느 사이트에서 통할지는 미지수라, 되면 쓰고 안 되면 사유를 남긴다.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from . import govweb, jsonapi, parse, robots
from .cascade import (
    FETCH_FAILED,
    NO_ITEMS,
    NOT_AVAILABLE,
    NOT_CONFIGURED,
    ROBOTS_BLOCKED,
    Attempt,
    Outcome,
    origin_label,
)
from .model import Notice
from .sources import Source

# 시도 순서 — 앞일수록 풍부하고 정확하다.
RSS, BOARD, ALT, DATAGO, KOREA = "rss", "board", "alt", "datago", "korea"
STAGE_ORDER = (RSS, BOARD, ALT, DATAGO, KOREA)

# korea.kr 부처 피드 — 기관 사이트 robots 와 무관한 최후 안전망.
KOREA_FEED_FMT = "https://www.korea.kr/rss/{code}.xml"
KOREA_CATEGORY = "보도자료"


_K2_BOARD_RE = re.compile(r"/bbs/[^/]+/\d+/(rssList\.do|artclList\.do)$", re.I)


def korea_url(code: str) -> str:
    return KOREA_FEED_FMT.format(code=code)


def alt_urls(url: str) -> list[str]:
    """같은 목록의 다른 주소 후보 — robots 판정을 다시 받을 기회를 만든다.

    robots.txt 는 경로·호스트 단위라 같은 내용이라도 주소가 다르면 판정이 다르다.
    한국외대에서 `/bbs/…`(차단) 대신 `/{site}/{menu}/subview.do`(허용)로 88건을
    받은 것이 이 원리다. 정부에서 통할지는 기관마다 다르므로 **후보만 만들고
    판정은 robots 에 맡긴다.**
    """
    parts = urllib.parse.urlsplit(url)
    host, out = parts.netloc, []
    if not host:
        return []
    # ⓪ K2Web 게시판 — 같은 게시판의 피드와 목록은 서로의 대체 주소다.
    #    /bbs/{site}/{id}/rssList.do ↔ /bbs/{site}/{id}/artclList.do
    k2 = _K2_BOARD_RE.search(parts.path)
    if k2:
        other = "artclList.do" if k2.group(1).lower() == "rsslist.do" else "rssList.do"
        query = "row=50" if other == "rssList.do" else "layout=unknown"  # 사이트가 스스로 거는 꼴
        out.append(
            urllib.parse.urlunsplit(
                parts._replace(path=parts.path[: k2.start(1)] + other, query=query)
            )
        )
    # ① 모바일 도메인 — robots.txt 가 별도인 경우가 많다.
    if host.startswith("www."):
        out.append(urllib.parse.urlunsplit(parts._replace(netloc="m." + host[4:])))
    # ② www 유무 변형 — 아펙스와 www 의 규칙이 다른 사이트가 있다.
    out.append(
        urllib.parse.urlunsplit(
            parts._replace(netloc=host[4:] if host.startswith("www.") else "www." + host)
        )
    )
    # ③ 영문판 경로 — 국문이 막히고 영문만 열린 기관이 실제로 있다(국무조정실).
    for ko, en in (("/kor/", "/eng/"), ("/ko/", "/en/")):
        if ko in parts.path:
            out.append(urllib.parse.urlunsplit(parts._replace(path=parts.path.replace(ko, en, 1))))
    return [u for u in out if u != url]


def _rows_to_notices(source: Source, rows: list, category: str) -> list[Notice]:
    return [
        Notice(
            title=r.title,
            url=r.url,
            agency=source.name,
            published=r.published,
            category=category,
            rights=source.rights,
            org=source.org,
            site=source.site or source.name,
            unit=r.unit or source.site or source.name,
        )
        for r in rows
        if r.title and r.url
    ]


def _parse_stage(source: Source, stage: str, data: bytes, url: str, category: str) -> list[Notice]:
    """단계 종류에 맞는 파서로 넘긴다 — 파서는 전부 기존 것을 재사용한다."""
    if stage in (RSS, KOREA):
        parsed = parse.parse_rss(data, agency=source.name, category=category, rights=source.rights)
        return [
            replace(
                n,
                org=source.org,
                site=source.site or source.name,
                unit=source.site or source.name,
            )
            for n in parsed
        ]
    if stage == DATAGO:
        rows = jsonapi.parse_items(
            data, paths=dict(source.api_paths), base_url=url, article_url=None
        )
        return _rows_to_notices(source, rows, category)
    # BOARD·ALT — 게시판 표(칸 순서 파서). CMS 가 달라도 표면 읽힌다.
    return _rows_to_notices(source, govweb.parse_list(data, url), category)


def categories(source: Source) -> list[str]:
    """이 기관에서 시도할 카테고리 목록(설정된 경로 + korea.kr 보도자료)."""
    seen = [cat for cat, _kind, _url in source.routes]
    if source.korea_feed and KOREA_CATEGORY not in seen:
        seen.append(KOREA_CATEGORY)
    out: list[str] = []
    for c in seen:  # 순서 보존 + 중복 제거
        if c not in out:
            out.append(c)
    return out


def stages_for(source: Source, category: str) -> list[tuple[str, str]]:
    """한 카테고리에 대해 (단계, 주소)를 우선순위대로."""
    configured = [(k, u) for cat, k, u in source.routes if cat == category]
    out: list[tuple[str, str]] = []
    for kind in (RSS, BOARD):
        out.extend((kind, u) for k, u in configured if k == kind)
    # alt 는 설정된 주소에서 파생한다 — 원본이 없으면 만들 수 없다.
    for _kind, url in configured:
        out.extend((ALT, alt) for alt in alt_urls(url))
    out.extend((DATAGO, u) for k, u in configured if k == DATAGO)
    if category == KOREA_CATEGORY and source.korea_feed:
        out.append((KOREA, korea_url(source.korea_feed)))
    return out


def collect_category(
    source: Source,
    category: str,
    *,
    fetcher: Callable[[str], bytes | None],
    check_robots: bool = True,
) -> Outcome:
    """한 카테고리를 여러 경로로 돌려가며 시도해 첫 성공에서 멈춘다."""
    outcome = Outcome()
    stages = stages_for(source, category)
    if not stages:
        outcome.attempts.append(Attempt(RSS, "", reason=NOT_CONFIGURED))
        return outcome

    for stage, url in stages:
        if stage == DATAGO and not source.api_paths:
            outcome.attempts.append(Attempt(stage, url, reason=NOT_CONFIGURED))
            continue
        # korea·datago 는 기관 사이트가 아닌 정식 배포 경로라 기관 robots 와 무관하지만,
        # 그 도메인 자체의 robots 는 그대로 따른다.
        if check_robots and not robots.allowed(url):
            outcome.attempts.append(Attempt(stage, url, reason=ROBOTS_BLOCKED))
            continue
        data = fetcher(url)
        if not data:
            why = getattr(fetcher, "why", None)
            outcome.attempts.append(
                Attempt(stage, url, reason=why(url) if callable(why) else FETCH_FAILED)
            )
            continue
        notices = _parse_stage(source, stage, data, url, category)
        notices = [replace(n, origin=origin_label(url, stage)) for n in notices]
        if not notices:
            outcome.attempts.append(Attempt(stage, url, reason=NO_ITEMS))
            continue
        outcome.attempts.append(Attempt(stage, url, count=len(notices)))
        outcome.notices = notices
        return outcome
    return outcome


def collect_org(
    source: Source,
    *,
    fetcher: Callable[[str], bytes | None],
    check_robots: bool = True,
) -> tuple[list[Notice], list[str]]:
    """기관 하나를 카테고리별로 수집하고, 못 얻은 카테고리는 사유를 돌려준다."""
    notices: list[Notice] = []
    failures: list[str] = []
    cats = categories(source)
    if not cats:
        # 시도할 경로가 하나도 없는 것도 '결과'다 — 조용히 넘어가지 않는다.
        return [], [
            f"{source.org or source.name} (수집 경로 없음 — 홈에서 게시판·피드를 "
            f"찾지 못했고 korea.kr 코드도 없음)"
        ]
    for category in cats:
        outcome = collect_category(source, category, fetcher=fetcher, check_robots=check_robots)
        if outcome.notices:
            notices.extend(outcome.notices)
        else:
            trail = outcome.trail() or NOT_AVAILABLE
            failures.append(f"{source.org or source.name} {category} ({trail})")
    return notices, failures


# ── 경로마다 모으기(웹 버전) ──────────────────────────────────────────────────
@dataclass(slots=True)
class RouteResult:
    """설정·발견된 경로 하나를 (그 경로의 대체 주소까지) 시도한 결과."""

    category: str
    kind: str
    url: str  # 실제로 글이 나온 주소(대체 주소일 수 있다) — 실패면 원래 주소
    stage: str = ""  # 성공한 단계(rss·board·alt·datago·korea)
    notices: list[Notice] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.notices)

    def trail(self) -> str:
        return Outcome(attempts=self.attempts).trail()


def _try_stages(
    source: Source,
    category: str,
    kind: str,
    stages: list[tuple[str, str]],
    *,
    fetcher: Callable[[str], bytes | None],
    check_robots: bool,
) -> RouteResult:
    """(단계, 주소)를 차례로 시도해 첫 성공에서 멈춘다 — collect_category 와 같은 규칙."""
    result = RouteResult(category, kind, stages[0][1] if stages else "")
    for stage, url in stages:
        if stage == DATAGO and not source.api_paths:
            result.attempts.append(Attempt(stage, url, reason=NOT_CONFIGURED))
            continue
        if check_robots and not robots.allowed(url):
            result.attempts.append(Attempt(stage, url, reason=ROBOTS_BLOCKED))
            continue
        data = fetcher(url)
        if not data:
            why = getattr(fetcher, "why", None)
            result.attempts.append(
                Attempt(stage, url, reason=why(url) if callable(why) else FETCH_FAILED)
            )
            continue
        notices = _parse_stage(source, stage, data, url, category)
        notices = [replace(n, origin=origin_label(url, stage)) for n in notices]
        if not notices:
            result.attempts.append(Attempt(stage, url, reason=NO_ITEMS))
            continue
        result.attempts.append(Attempt(stage, url, count=len(notices)))
        result.url, result.stage, result.notices = url, stage, notices
        return result
    return result


def collect_routes(
    source: Source,
    *,
    fetcher: Callable[[str], bytes | None],
    check_robots: bool = True,
) -> list[RouteResult]:
    """**경로마다** 모은다 — 같은 이름의 게시판이 여럿이어도 전부 본다.

    collect_category 는 한 카테고리에서 첫 성공에 멈춘다. 설정한 경로들이 같은
    내용의 대체 주소일 때는 맞지만, 발견한 게시판들은 서로 다른 게시판이다. 홈의
    탭 이름이 전부 'READ' 였던 한국외대는 공지만 모이고 학사·장학·채용이 빠졌다.
    그래서 경로 하나하나를 (그 경로의 대체 주소까지) 시도하고, korea.kr 보도자료는
    보도자료가 하나도 안 나왔을 때만 안전망으로 쓴다. 같은 글은 부르는 쪽에서 접는다.
    """
    results: list[RouteResult] = []
    seen: set[str] = set()
    for category, kind, url in source.routes:
        if url in seen:
            continue
        seen.add(url)
        stage = kind if kind in (RSS, BOARD, DATAGO) else BOARD
        stages = [(stage, url)] + [(ALT, alt) for alt in alt_urls(url) if alt not in seen]
        results.append(
            _try_stages(source, category, kind, stages, fetcher=fetcher, check_robots=check_robots)
        )
    if source.korea_feed and not any(r.ok and r.category == KOREA_CATEGORY for r in results):
        url = korea_url(source.korea_feed)
        results.append(
            _try_stages(
                source,
                KOREA_CATEGORY,
                KOREA,
                [(KOREA, url)],
                fetcher=fetcher,
                check_robots=check_robots,
            )
        )
    return results
