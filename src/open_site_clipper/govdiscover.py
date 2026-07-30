"""기관 홈페이지 한 장에서 **카테고리별 수집 경로를 자동 발견**한다.

지금까지는 `routes` 를 사람이 손으로 적어야 해서 기관마다 작업이 필요했다.
이 모듈이 그 수작업을 없앤다 — 홈 주소만 주면:

  ① 메뉴 링크를 **전부** 후보로 모은다(이름으로 거르지 않는다)
  ② 각 후보를 열어 **구조 테스트**(probe)로 선별한다 — 날짜 붙은 목록이면
     수집 대상, 아니면 사유를 남기고 버린다. 이름 사전은 '분류 라벨'로만 쓴다.
     같은 이름이 어떤 기관에선 목록이고 어떤 기관에선 안내문이기 때문이다
  ③ 'RSS·구독' 안내 페이지를 찾으면 한 단계 따라가 피드 목록을 파싱한다
     (korea.kr·부처 정보구독서비스가 같은 표 구조 — discover 의 S-A 재사용)

CMS 를 가리지 않는다. 링크 문법이 아니라 **앵커 텍스트와 표 구조**에 기대므로
19종 패밀리든 그 이상이든 같은 코드가 돈다. 판정이 틀릴 수 있으므로 결과는
초안이고, 실패·미발견은 사유로 남긴다.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Callable
from functools import lru_cache

from . import discover as _discover
from . import govpaths, korean, probe
from .fetch import decode_text

PageFetcher = Callable[[str], "bytes | None"]

DEFAULT_BUDGET = 70  # 기관당 요청 상한(홈 + RSS 안내 + 후보 구조 테스트)

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
    ("공지", ("공지", "공지사항", "알림", "알립니다", "고시", "공고", "notice")),
    ("소식", ("소식", "뉴스", "새소식", "동향", "news")),
)

# RSS 안내 페이지로 가는 링크의 단서.
_RSS_HINTS = ("rss", "구독", "피드", "feed")


# 게시판일 가능성 점수 — 주소와 이름의 신호를 더한다.
_BOARD_URL_HINTS = ("list", "board", "bbs", "article", "notice", "brd", "news")
_INTRO_URL_HINTS = ("intro", "about", "greeting", "org", "history", "vision", "location", "map")


# 게시판 주소에 흔한 쿼리 파라미터 — eGovFrame 원본에서 뽑았다.
# (bbsId 342회 · nttId 174 · menuNo 91 · bid/mid) `/menu.es?mid=…&bid=0015` 같은
# 코드형 주소는 경로에 단서가 없어 이 신호가 없으면 음수로 밀린다.
_BOARD_QUERY_HINTS = ("bbsid", "nttid", "menuno", "boardid", "bid=", "mid=", "key=")
# 목록 주소로 흔한 꼬리 — 상세 페이지와 구분한다.
_LIST_TAIL_HINTS = ("list", "List")
OPTIMAL_DEPTH = 3  # 실측상 게시판 목록은 대개 이 깊이다(관문은 더 얕고 상세는 더 깊다)


@lru_cache(maxsize=1)
def _romanized_hints() -> tuple[str, ...]:
    """카테고리 사전의 한글 단어를 로마자로 옮긴 별칭들.

    주소에 `/gongji/`·`/alrim/` 처럼 음역이 쓰이는 경우를 잡는다. 사전을 고치면
    별칭도 자동으로 따라오므로 따로 관리할 것이 없다.
    """
    out: set[str] = set()
    for _cat, words in CATEGORY_HINTS:
        for w in words:
            out.update(korean.romanized_aliases(w))
    return tuple(sorted(out))


def _fair_order(
    candidates: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """카테고리별로 **번갈아** 뽑아 배열한다.

    점수만으로 줄을 세우면 같은 '채용' 후보라도 주소 모양에 따라 어떤 것은
    상한 안에 들고 어떤 것은 잘린다. 카테고리가 통째로 빠지는 것도, 한
    카테고리가 자리를 독식하는 것도 원치 않는다.

    그래서 카테고리 안에서는 점수순으로 정렬하되, 밖에서는 **라운드로빈**으로
    한 개씩 돌아가며 뽑는다. 상한이 어디서 잘리든 각 카테고리의 가장 유력한
    후보는 이미 앞쪽에 들어와 있다.
    """
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for item in candidates:
        groups.setdefault(item[0], []).append(item)
    for items in groups.values():
        # 동점이면 주소순 — 입력 순서에 기대면 실행마다 결과가 달라진다.
        items.sort(key=lambda c: (-board_score(c[2], c[0]), c[2]))
    # 카테고리 순서도 결정론적으로 — 최고점이 높은 카테고리부터.
    order = sorted(groups, key=lambda cat: (-board_score(groups[cat][0][2], cat), cat))
    out: list[tuple[str, str, str]] = []
    rounds = max(len(v) for v in groups.values()) if groups else 0
    for i in range(rounds):
        for cat in order:
            if i < len(groups[cat]):
                out.append(groups[cat][i])
    return out


def _body_head(data: bytes, limit: int = 90) -> str:
    """응답의 앞부분을 진단용으로 요약한다.

    '응답 0KB'·'앵커 0개'만으로는 그 1KB 미만 응답이 무엇인지 알 수 없다.
    빈 문서인지·오류 안내인지·프레임인지·자바스크립트 관문인지는 **내용을 보면**
    바로 갈린다. 제어문자를 지우고 공백을 접어 한 줄로 만든다.
    """
    if not data:
        return "(빈 응답)"
    try:
        text = decode_text(data[: limit * 4])
    except Exception:
        return f"(해독 실패, {len(data)}바이트)"
    flat = " ".join(text.split())
    flat = "".join(c for c in flat if c.isprintable())
    return (flat[:limit] + "…") if len(flat) > limit else (flat or "(내용 없음)")


def board_score(url: str, label: str) -> int:
    """이 링크가 게시판 목록일 가능성 — 클수록 먼저 시험한다.

    신호를 **가중합**한다(crawl4ai CompositeScorer 와 같은 구조). 키워드는
    하나만 맞아도 되는 이진값이 아니라 **맞은 개수**를 본다 —
    `/frt/bbs/type010/commonSelectBoardList.do` 는 bbs·board·list 가 모두
    걸리므로 `/list.do` 보다 위로 간다(KeywordRelevanceScorer 원리).
    """
    low = (url or "").lower()
    score = 0
    # ① 주소 키워드 — 맞은 개수만큼(최대 3까지)
    hits = sum(1 for h in _BOARD_URL_HINTS if h in low)
    score += min(hits, 3) * 2
    # ② 음역 표기 — /gongji/·/alrim/ 처럼 한글을 로마자로 적은 주소
    if any(h in low for h in _romanized_hints()):
        score += 3
    # ③ 쿼리 파라미터 — 코드형 주소(?mid=&bid=)의 유일한 단서
    if any(h in low for h in _BOARD_QUERY_HINTS):
        score += 2
    # ④ 소개·연혁 계열은 감점
    if any(h in low for h in _INTRO_URL_HINTS):
        score -= 3
    # ⑤ 이름이 카테고리로 판정되면 가점
    if classify(label):
        score += 3
    # ⑥ 깊이 — 최적값에서 멀수록 감점(PathDepthScorer 의 거리 개념)
    depth = low.split("?", 1)[0].rstrip("/").count("/") - 2
    score -= min(abs(depth - OPTIMAL_DEPTH), 3)
    return score


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
    max_candidates: int = 40,
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

    data = session.get(home_url) or b""
    home_reason = session.last_reason if not data else ""

    # 홈이 1KB 남짓이면 빈 응답이 아니라 **관문**일 수 있다(공정위·교육부·해수부 …).
    # meta refresh·location.href·frameset 이 가리키는 진짜 주소가 HTML 안에
    # 문자열로 들어 있으므로, JavaScript 를 실행하지 않고도 따라갈 수 있다.
    for _hop in range(2):  # 관문이 관문을 가리키는 경우까지만
        target = govpaths.gateway_target(data, home_url)
        if not target or session.budget <= 0:
            break
        moved = session.get(target)
        if not moved:
            break
        notes.append(f"관문 페이지를 따라갔습니다: {target}")
        home_url, data = target, moved  # home_host 는 아래에서 이 주소로 다시 계산된다
    if not data:
        # 홈을 못 읽어도 여기서 끝내지 않는다. 실패한 19개 부처가 정확히 이
        # 경로였다 — 홈이 빈 응답이라고 게시판까지 없는 것은 아니다. 아래의
        # 사이트맵·경로 사이클이 여전히 유효하므로 사유만 적고 계속 간다.
        why = "robots.txt 차단" if session.blocked else "응답 없음"
        # '/' 가 리다이렉트 관문이라 빈 응답인 기관이 많다(고용노동부·문체부·해수부).
        # 진짜 홈을 찾으면 아래 로직이 **그대로** 돌아간다 — 기관별 게시판 경로를
        # 일일이 아는 것보다 일반적이다.
        entry_url, entry_data = govpaths.find_entry(
            home_url, fetcher=session.get, budget=min(8, session.budget)
        )
        if entry_data:
            notes.append(f"홈이 비어 진입점을 찾았습니다: {entry_url}")
            home_url, data = entry_url, entry_data
        else:
            notes.append(f"홈페이지를 열지 못했습니다({why}) — 다른 경로로 계속합니다: {home_url}")

    page = _discover._Page()
    try:
        page.feed(_discover.strip_noise(decode_text(data)))
    except Exception:
        notes.append(f"홈페이지 HTML 파싱 실패: {home_url}")

    home_host = urllib.parse.urlsplit(home_url).netloc
    seen: set[tuple[str, str]] = set()

    # ① 표준 자동발견 피드 — 카테고리는 title 로 판정, 없으면 '소식'.
    for href, title in page.alternates:
        url = urllib.parse.urljoin(home_url, href)
        category = classify(title) or "소식"
        key = (category, url)
        if key in seen:
            continue
        seen.add(key)
        routes.append((category, "rss", url))

    # ② 본문 앵커 — 이름으로 거르지 않고 **전부** 후보로 둔다. 선별은 구조
    #    테스트(probe)가 한다. 이름은 분류 라벨로만 쓴다(모르면 "기타").
    candidates: list[tuple[str, str, str]] = []
    internal = external = tried = 0
    for href, text in page.anchors:
        url = urllib.parse.urljoin(home_url, href)
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https"):
            continue  # javascript: · # 등
        if probe.is_external(url, home_host):
            external += 1
            continue  # 법령·공공데이터·국민신문고 등 — 별도 출처로 등록할 것
        internal += 1
        label = classify(text) or (" ".join((text or "").split())[:20] or "기타")
        kind = "rss" if _discover._looks_like_feed_url(href) else "board"
        key = (label, url)
        if key in seen:
            continue
        seen.add(key)
        if kind == "rss":
            # 피드는 구조 테스트 없이 받아들인다(내용 검증은 수집 때 파서가 한다).
            routes.append((label, kind, url))
            continue
        candidates.append((label, kind, url))

    # ③ 구조 테스트 — 후보를 열어 '날짜 붙은 목록'만 남긴다.
    # 상한(max_candidates)에 소개·정책 메뉴만 차서 정작 게시판까지 못 가던 문제가
    # 있었다(국무조정실·금융위 등 18곳이 '40건 건너뜀'). 게시판일 가능성이 높은
    # 것부터 보도록 점수순 정렬 후 상한을 적용한다.
    candidates = _fair_order(candidates)
    # 상한은 고정값이 아니라 **남은 예산**을 따른다. 국세청은 후보 614개 중
    # 40개(6%)만 보고 끝나 게시판을 놓쳤다. 정렬이 있으므로 위쪽부터 보는 한
    # 예산을 다 쓰는 편이 낫다(사이트맵·경로 사이클 몫으로 여유를 남긴다).
    limit = max(max_candidates, min(len(candidates), max(0, session.budget - 8)))
    skipped: dict[str, int] = {}
    for label, kind, url in candidates[:limit]:
        tried += 1
        if session.budget <= 0:
            notes.append(f"요청 예산 소진 — 후보 {len(candidates)}개 중 일부만 확인했습니다.")
            break
        result = probe.classify(session.get(url), url, home_host=home_host)
        if result.collectible:
            routes.append((label, kind, url))
        else:
            skipped[result.verdict] = skipped.get(result.verdict, 0) + 1
    for verdict, n in sorted(skipped.items()):
        notes.append(f"{probe.VERDICT_REASON.get(verdict, verdict)} — {n}건 건너뜀")

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

    # ④ 홈에서 아무것도 못 찾았으면 **사이트맵**으로 우회한다.
    #    robots.txt 의 Sitemap: 은 이미 받아 둔 것이라 추가 요청이 들지 않고,
    #    거기 담긴 목록 주소는 홈 메뉴가 JS 로만 그려져도 그대로 쓸 수 있다.
    if not routes and session.budget > 0:
        found, why = _from_sitemap(session, home_url, home_host, max_candidates)
        routes.extend(found)
        notes.extend(why)

    # ⑤ 그래도 없으면 **알려진 경로 패턴**을 사이클로 돌린다. 홈을 못 읽어도
    #    게시판 주소 자체는 CMS 패밀리 몇 종으로 수렴한다(19곳 조사 결과).
    if not routes and session.budget > 0:
        found, why = govpaths.probe_paths(
            home_url,
            fetcher=session.get,
            budget=min(12, session.budget),
            home_host=home_host,
        )
        routes.extend(found)
        notes.extend(why)

    if not routes:
        notes.append(
            f"게시판·피드 링크를 찾지 못했습니다 — 진단: 응답 {len(data) // 1024}KB"
            f"{'(' + home_reason + ')' if home_reason else ''} · "
            f"<a> {page.anchor_tags}개(주소없음 {page.dead_links}·data속성 {page.data_links}) · "
            f"내부 {internal}·외부제외 {external} · 후보 {len(candidates)}개(시험 {tried}건) · "
            f"본문머리[{_body_head(data)}]. "
            "메뉴가 JavaScript 로만 그려지거나 구조가 다를 수 있습니다"
            "(보도자료는 korea.kr 경로로 대체됩니다)."
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


# 사이트맵에서 목록 주소를 캘 때 쓰는 최소 XML 추출 — 표준 <loc> 만 본다.
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def _from_sitemap(
    session, home_url: str, home_host: str, max_candidates: int
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """사이트맵(XML)에서 게시판 후보를 캐 구조 테스트로 거른다.

    robots.txt 의 `Sitemap:` 은 이미 받아 둔 파일에서 읽으므로 **추가 요청이
    들지 않는다**. 사이트맵에는 그 사이트의 목록 주소가 대개 전부 들어 있어,
    홈 메뉴가 JavaScript 로만 그려지는 사이트를 우회하는 지름길이 된다.
    """
    from . import robots as _robots

    routes: list[tuple[str, str, str]] = []
    notes: list[str] = []
    urls = _robots.sitemap_urls(home_url)
    if not urls:
        return routes, notes

    seen: set[str] = set()
    for sitemap in urls[:2]:  # 사이트맵이 여러 개면 앞의 둘만
        if session.budget <= 0:
            break
        data = session.get(sitemap)
        if not data:
            continue
        locs = [
            u
            for u in _LOC_RE.findall(decode_text(data))
            if u.startswith(("http://", "https://")) and not probe.is_external(u, home_host)
        ]
        # 중첩 사이트맵(sitemapindex)이면 첫 자식 하나만 더 따라간다.
        if locs and all(u.endswith((".xml", ".xml.gz")) for u in locs[:3]):
            child = session.get(locs[0])
            if child:
                locs = [
                    u
                    for u in _LOC_RE.findall(decode_text(child))
                    if not probe.is_external(u, home_host)
                ]
        cands = sorted({u for u in locs if u not in seen}, key=lambda u: -board_score(u, ""))
        for url in cands[:max_candidates]:
            if session.budget <= 0:
                break
            seen.add(url)
            result = probe.classify(session.get(url), url, home_host=home_host)
            if result.collectible:
                routes.append(("기타", "board", url))
        if routes:
            notes.append(f"사이트맵에서 목록 {len(routes)}개를 찾았습니다: {sitemap}")
            break
    if urls and not routes:
        notes.append(f"사이트맵을 읽었으나 목록을 찾지 못했습니다: {urls[0]}")
    return routes, notes
