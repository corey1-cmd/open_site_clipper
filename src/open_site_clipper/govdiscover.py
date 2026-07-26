"""기관 홈페이지 한 장에서 **카테고리별 수집 경로를 자동 발견**한다.

지금까지는 `routes` 를 사람이 손으로 적어야 해서 기관마다 작업이 필요했다.
이 모듈이 그 수작업을 없앤다 — 홈 주소만 주면:

  ① 앵커 텍스트로 카테고리를 판정한다(공지·인사·보도자료·채용·입찰·소식)
  ② 같은 카테고리로 가는 링크를 **여러 개 모은다** — 하나가 robots 로 막혀도
     다른 진입 경로가 열려 있을 수 있기 때문(한국외대 subview.do 사례의 일반화)
  ③ 'RSS·구독' 안내 페이지를 찾으면 한 단계 따라가 피드 목록을 파싱한다
     (korea.kr·부처 정보구독서비스가 같은 표 구조 — discover 의 S-A 재사용)

CMS 를 가리지 않는다. 링크 문법이 아니라 **앵커 텍스트와 표 구조**에 기대므로
19종 패밀리든 그 이상이든 같은 코드가 돈다. 판정이 틀릴 수 있으므로 결과는
초안이고, 실패·미발견은 사유로 남긴다.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable

from . import discover as _discover
from .fetch import decode_text

PageFetcher = Callable[[str], "bytes | None"]

DEFAULT_BUDGET = 8  # 기관당 요청 상한(홈 + RSS 안내 + 여유)

# 카테고리 판정 사전 — 앵커 텍스트에 이 말이 있으면 그 카테고리로 본다.
# 순서가 우선순위다(먼저 맞는 것을 취한다). '채용공고'가 '공고'보다 앞에 있어야
# 채용으로 잡히므로, 구체적인 말을 앞에 둔다.
CATEGORY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("채용", ("채용", "임용", "인재", "구인", "recruit")),
    ("입찰", ("입찰", "발주", "계약", "조달", "제안요청", "bid")),
    (
        "인사",
        ("인사발령", "인사"),
    ),
    ("보도자료", ("보도자료", "보도설명", "해명자료", "press")),
    ("공지", ("공지", "알립니다", "고시", "공고", "notice")),
    ("소식", ("소식", "뉴스", "새소식", "news")),
)

# RSS 안내 페이지로 가는 링크의 단서.
_RSS_HINTS = ("rss", "구독", "피드", "feed")


def classify(text: str) -> str:
    """앵커 텍스트 → 카테고리(못 정하면 "")."""
    low = " ".join(text.split()).lower()
    if not low:
        return ""
    for category, words in CATEGORY_HINTS:
        if any(w in low for w in words):
            return category
    return ""


def find_routes(
    home_url: str,
    *,
    fetcher: PageFetcher | None = None,
    check_robots: bool = True,
    budget: int = DEFAULT_BUDGET,
    max_per_category: int = 3,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """기관 홈에서 (카테고리, 종류, 주소) 목록과 메모를 만든다.

    같은 카테고리에 여러 주소를 남기는 것이 핵심이다 — 캐스케이드가 앞에서부터
    시도하다가 robots 로 막히면 다음 주소로 넘어간다.
    """
    if "://" not in home_url:
        home_url = "https://" + home_url
    routes: list[tuple[str, str, str]] = []
    notes: list[str] = []
    session = _discover._Session(fetcher, check_robots, budget)

    data = session.get(home_url)
    if not data:
        why = "robots.txt 차단" if session.blocked else "응답 없음"
        return [], [f"홈페이지를 열지 못했습니다({why}): {home_url}"]

    page = _discover._Page()
    try:
        page.feed(decode_text(data))
    except Exception:
        notes.append(f"홈페이지 HTML 파싱 실패: {home_url}")

    home_host = urllib.parse.urlsplit(home_url).netloc
    counts: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()

    # ① 표준 자동발견 피드 — 카테고리는 title 로 판정, 없으면 '소식'.
    for href, title in page.alternates:
        url = urllib.parse.urljoin(home_url, href)
        category = classify(title) or "소식"
        key = (category, url)
        if key in seen:
            continue
        seen.add(key)
        counts[category] = counts.get(category, 0) + 1
        routes.append((category, "rss", url))

    # ② 본문 앵커 — 카테고리별로 여러 후보를 모은다(다중 진입 경로).
    for href, text in page.anchors:
        category = classify(text)
        if not category:
            continue
        url = urllib.parse.urljoin(home_url, href)
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https"):
            continue  # javascript: · # 등
        # 같은 기관 도메인만(외부 기관 공고 링크가 섞이는 것을 막는다).
        if parts.netloc != home_host:
            continue
        if counts.get(category, 0) >= max_per_category:
            continue
        kind = "rss" if _discover._looks_like_feed_url(href) else "board"
        key = (category, url)
        if key in seen:
            continue
        seen.add(key)
        counts[category] = counts.get(category, 0) + 1
        routes.append((category, kind, url))

    # ③ 'RSS·구독' 안내 페이지를 한 단계 따라가 피드 목록 표를 파싱한다.
    rss_page = next(
        (
            urllib.parse.urljoin(home_url, href)
            for href, text in page.anchors
            if any(h in (text or "").lower() or h in href.lower() for h in _RSS_HINTS)
            and urllib.parse.urlsplit(urllib.parse.urljoin(home_url, href)).netloc == home_host
        ),
        "",
    )
    if rss_page and session.budget > 0:
        sub = session.get(rss_page)
        if sub:
            for name, feed_url in _discover._feed_index_rows(sub, rss_page):
                category = classify(name) or "소식"
                key = (category, feed_url)
                if key in seen:
                    continue
                seen.add(key)
                routes.append((category, "rss", feed_url))
            if not any(k == "rss" for _c, k, _u in routes):
                notes.append(f"RSS 안내 페이지에서 피드를 찾지 못했습니다: {rss_page}")
        else:
            notes.append(f"RSS 안내 페이지를 열지 못했습니다: {rss_page}")

    if not routes:
        notes.append(
            "게시판·피드 링크를 찾지 못했습니다 — 메뉴가 JavaScript 로만 그려지거나 "
            "구조가 다를 수 있습니다(보도자료는 korea.kr 경로로 대체됩니다)."
        )
    if session.blocked:
        notes.append(f"robots.txt 로 건너뛴 주소 {len(session.blocked)}건")
    return routes, notes


def enrich(
    source,  # Source — 순환 임포트를 피하려 형 주석 생략
    *,
    fetcher: PageFetcher | None = None,
    check_robots: bool = True,
    budget: int = DEFAULT_BUDGET,
):
    """govorg 출처에 routes 가 비어 있으면 홈에서 발견해 채워 준다.

    이미 routes 가 적혀 있으면 사람이 검토한 것이므로 건드리지 않고, 발견분을
    **뒤에 덧붙인다**(설정이 우선, 발견은 보강).
    """
    from dataclasses import replace

    if not source.home:
        return source, []
    found, notes = find_routes(
        source.home, fetcher=fetcher, check_robots=check_robots, budget=budget
    )
    if not found:
        return source, notes
    merged = list(source.routes) + [r for r in found if r not in source.routes]
    return replace(source, routes=tuple(merged)), notes
