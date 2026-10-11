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

from . import categories, govpaths, govweb, korean, probe, slots
from . import discover as _discover
from .categories import CATEGORY_HINTS, classify
from .fetch import decode_text

PageFetcher = Callable[[str], "bytes | None"]

DEFAULT_BUDGET = 110  # 기관당 요청 상한(홈 + RSS 안내 + 후보 구조 테스트)

# 카테고리 판정 사전 — 앵커 텍스트에 이 말이 있으면 그 카테고리로 본다.
# 순서가 우선순위다(먼저 맞는 것을 취한다). '채용공고'가 '공고'보다 앞에 있어야
# 채용으로 잡히므로, 구체적인 말을 앞에 둔다.
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


_SCRIPT_BODY_RE = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.I | re.S)


def _script_head(data: bytes | None, limit: int = 160) -> str:
    """작은 홈(관문)의 인라인 스크립트 앞부분 — 어디로 보내려는지 진단할 수 있게.

    '응답 1KB · 링크 0개'만으로는 그 관문이 무슨 방법으로 본 화면을 부르는지 모른다.
    8KB 를 넘는 화면은 보지 않는다(관문이 아니다).
    """
    if not data or len(data) > 8192:
        return ""
    try:
        text = decode_text(data)
    except Exception:
        return ""
    code = " ".join(" ".join(m.group(1).split()) for m in _SCRIPT_BODY_RE.finditer(text))
    code = "".join(c for c in code if c.isprintable()).strip()
    return (code[:limit] + "…") if len(code) > limit else code


# 본문 속 주소 문자열 — 상대("/a/b")와 절대("https://…") 둘 다. JSON 은 "\/" 로 적기도 한다.
_LITERAL_RE = re.compile(r"""["'](/[^"'\s<>]{2,160}|https?://[^"'\s<>]{4,200})["']""")
_ASSET_TAILS = (
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".map",
    ".json",
    ".webp",
    ".mp4",
    ".pdf",
    ".hwp",
    ".zip",
)
MAX_MINED = 30


def mine_url_literals(data: bytes, base_url: str, home_host: str) -> list[str]:
    """자바스크립트로 그리는 홈에서 **게시판처럼 보이는** 주소 문자열을 캔다.

    링크(<a>)가 거의 없는 홈은 메뉴를 스크립트·JSON 으로 그린다. 그 안의 주소
    문자열 중 같은 사이트이고, 자원 파일이 아니며, 게시판 점수가 0보다 큰 것만
    점수순으로 돌려준다(최대 30개). 판정은 뒤의 구조 테스트가 한다.
    """
    text = decode_text(data).replace("\\/", "/")
    scored: dict[str, int] = {}
    for m in _LITERAL_RE.finditer(text):
        raw = m.group(1)
        if raw.startswith("//"):
            continue  # 프로토콜 상대 주소 — 대개 외부 자원
        url = urllib.parse.urljoin(base_url, raw).split("#", 1)[0]
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or probe.is_external(url, home_host):
            continue
        if parts.path.lower().endswith(_ASSET_TAILS) or parts.path in ("", "/"):
            continue
        score = board_score(url, "")
        if score > 0 and url not in scored:
            scored[url] = score
    ranked = sorted(scored, key=lambda u: (-scored[u], u))
    return ranked[:MAX_MINED]


def _raw_label(text: str) -> str:
    """앵커 원문을 분류로 쓸지 판단한다 — '더보기'·'전체' 같은 말은 쓰지 않는다."""
    return categories.tidy_label(text)[:20] or categories.ETC


def refine_label(label: str, data: bytes | None, url: str) -> str:
    """목록으로 판정된 게시판의 이름을 **내용으로** 다듬는다.

    **이름이 있으면 그 이름을 믿는다**('공지사항'·'등록금심의위원회'·'기계공학과').
    'READ'·'더보기'처럼 이름을 모를 때만 ① 글 제목들에서 우세한 갈래 ② 페이지가 밝힌
    게시판 이름(`<title>`·제목 태그) 순으로 고른다. 한국외대 홈은 공지·학사·장학·채용
    네 탭이 전부 'READ' 였고, 이름이 같아 하나만 모이고 장학은 아예 빠졌다.

    이름 있는 게시판까지 내용으로 바꿨더니(0.25.0) 실측에서 거꾸로 틀렸다 — 페이지
    머리의 메뉴 제목을 읽어 일반 공지가 '입학안내'가 되고, 회의록 제목의 '등록금'
    때문에 등록금심의위원회가 '학사'가, 장학 글이 많은 일반 공지가 '장학'이 됐다.
    그런 게시판의 글은 제목으로 하나씩 나누므로(장학 글은 장학) 잃는 것이 없다.
    """
    if categories.is_named(label) or not data:
        return label
    rows = govweb.parse_list(data, url)
    return categories.dominant([r.title for r in rows]) or govweb.page_label(data) or label


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


def find_routes(
    home_url: str,
    *,
    fetcher: PageFetcher | None = None,
    check_robots: bool = True,
    budget: int = DEFAULT_BUDGET,
    max_candidates: int = 40,
    skip: int = 0,
    targets: tuple[str, ...] = (),
    trace: list[str] | None = None,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """기관 홈에서 (카테고리, 종류, 주소) 목록과 메모를 만든다.

    같은 카테고리에 여러 주소를 남기는 것이 핵심이다 — 캐스케이드가 앞에서부터
    시도하다가 robots 로 막히면 다음 주소로 넘어간다.

    targets 를 주면(학교: 공지·학사·장학·입학·채용) 그 갈래마다 게시판을 먼저 찾아
    채운다 — 사이트맵 화면과 갈래 화면(장학안내·입학처 홈)까지 연다(slots 참고).
    trace 에는 무엇을 열고 무엇을 골랐는지 짧게 쌓인다(점검용).
    """
    if "://" not in home_url:
        home_url = "https://" + home_url
    routes: list[tuple[str, str, str]] = []
    notes: list[str] = []
    trace = trace if trace is not None else []
    session = _discover._Session(fetcher, check_robots, budget)

    data = session.get(home_url) or b""
    home_reason = session.last_reason if not data else ""
    first_home, first_data = home_url, data  # 관문을 따라가도 원래 홈의 문자열은 버리지 않는다
    failed_gateways: list[str] = []

    # 홈이 1KB 남짓이면 빈 응답이 아니라 **관문**일 수 있다(공정위·교육부·해수부 …).
    # meta refresh·location.href·frameset 이 가리키는 진짜 주소가 HTML 안에
    # 문자열로 들어 있으므로, JavaScript 를 실행하지 않고도 따라갈 수 있다.
    # 학교는 입시 홍보 **인트로**가 흔하다 — 그림이 많아 관문보다 크고 '홈페이지 바로가기'
    # 링크로 본 화면을 가리킨다. 링크가 몇 개 없는 화면이면 그 링크들도 시험해 **메뉴가
    # 실린 화면**을 고른다(로그인·오류·manifest 로 끌려가던 것을 막는다).
    for _hop in range(3):  # 관문 → 인트로 → 본 화면까지
        if session.budget <= 0 or not govpaths.needs_hop(data, home_url):
            break
        explicit = govpaths.gateway_targets(data, home_url)
        intro = [
            u
            for u in govpaths.intro_targets(data, home_url, urllib.parse.urlsplit(home_url).netloc)
            if u not in explicit
        ]
        moved, used, fallback = b"", "", None
        for cand in (explicit + intro)[:5]:
            if session.budget <= 0:
                break
            got = session.get(cand)
            if not got:
                failed_gateways.append(f"{cand}({session.last_reason})")
                continue
            if not govpaths.needs_hop(got, cand):
                moved, used = got, cand
                break
            if cand in explicit and fallback is None:
                # 명시 관문(meta refresh·location)은 메뉴가 스크립트여도 따라간다(예전 동작)
                fallback = (cand, got)
        if not moved and fallback:
            used, moved = fallback
        if not moved:
            break
        notes.append(f"관문 페이지를 따라갔습니다: {used}")
        trace.append(f"관문·인트로 → {slots.short(used)}")
        home_url, data = used, moved  # home_host 는 아래에서 이 주소로 다시 계산된다
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
        if probe.not_a_board(url):
            continue  # 다른 홈 첫 화면·글 한 건 — 게시판이 아니다(probe 참고)
        # 이름 → 주소 → 앵커 원문 순으로 분류를 정한다. 예전에는 이름이 안 잡히면
        # 곧장 앵커 원문을 썼는데, '더보기'·'바로가기' 같은 말이 그대로 분류가 되어
        # 요약에서 기타로 뭉쳤다(실측 65%). 주소에 단서가 있으면 그것이 낫다.
        label = classify(text) or categories.from_url(url, fallback="") or _raw_label(text)
        kind = "rss" if _discover._looks_like_feed_url(href) else "board"
        key = (label, url)
        if key in seen:
            continue
        seen.add(key)
        if kind == "rss":
            if "/comments/feed" in url.lower():
                continue  # 워드프레스 댓글 피드 — 공지가 아니다
            # 피드는 구조 테스트 없이 받아들인다(내용 검증은 수집 때 파서가 한다).
            routes.append((label, kind, url))
            continue
        candidates.append((label, kind, url))

    # ②-1 홈에 링크가 거의 없으면 자바스크립트로 그리는 홈이다(대학 홈에서 흔하다).
    #      메뉴 주소는 대개 본문 속 JSON·스크립트에 **문자열로** 들어 있으므로,
    #      실행하지 않고 그 문자열을 캐서 같은 구조 테스트에 넘긴다.
    if internal < govpaths.MIN_ENTRY_ANCHORS and (data or first_data):
        mined = mine_url_literals(data, home_url, home_host) if data else []
        if first_data and first_data is not data:
            # 스크립트만 있는 작은 홈은 '관문'으로 오인돼 엉뚱한 쪽으로 넘어갈 수 있다 —
            # 원래 홈에 들어 있던 메뉴 주소도 함께 본다.
            mined += [
                u for u in mine_url_literals(first_data, first_home, home_host) if u not in mined
            ]
        known = {u for _l, _k, u in candidates} | {u for _l, _k, u in routes}
        mined = [
            u for u in mined if u not in known and not probe.not_a_board(u)
        ]  # <a> 로 이미 잡은 주소는 그 이름 그대로
        for url in mined:
            label = categories.from_url(url, fallback="") or categories.ETC
            seen.add((label, url))
            candidates.append((label, "board", url))
        if mined:
            notes.append(
                f"홈에 링크가 {internal}개뿐이라 본문 속 주소 {len(mined)}개를 후보로 삼았습니다"
            )

    # ②-2 갈래 채우기(학교) — 공지·학사·장학·입학·채용마다 게시판 하나씩. 홈 메뉴에 없으면
    #      사이트맵 화면·갈래 화면(장학안내·입학처 홈)까지 연다. 시험한 주소는 아래에서 다시
    #      열지 않는다.
    tested: dict[str, str] = {}
    if targets and data and session.budget > 0 and not skip:  # 이어서 찾을 때는 이미 했다
        trace.append(f"홈 {slots.short(home_url)} 링크 {internal}")
        for route in slots.fill(
            session.get,
            home_url,
            page.anchors,
            home_host,
            board_score=board_score,
            tested=tested,
            trace=trace,
            targets=targets,
            max_requests=min(slots.MAX_REQUESTS, max(0, session.budget - 10)),
        ):
            if (route[0], route[2]) not in seen:
                seen.add((route[0], route[2]))
                routes.append(route)
    if targets:
        # 학교: 문의·Q&A·분실물·개인정보 처리방침 판과 홈 자신은 공지 게시판이 아니다
        candidates = [
            c
            for c in candidates
            if c[2] not in tested
            and not slots.not_notice(c[0])
            and not slots.same_page(c[2], home_url)
        ]

    # ③ 구조 테스트 — 후보를 열어 '날짜 붙은 목록'만 남긴다.
    # 상한(max_candidates)에 소개·정책 메뉴만 차서 정작 게시판까지 못 가던 문제가
    # 있었다(국무조정실·금융위 등 18곳이 '40건 건너뜀'). 게시판일 가능성이 높은
    # 것부터 보도록 점수순 정렬 후 상한을 적용한다.
    candidates = _fair_order(candidates)
    if skip:
        # 이어서 찾기 — 앞 회차에서 시험한 후보는 건너뛴다(순서가 결정론적이라 가능).
        notes.append(f"앞 회차에서 본 후보 {min(skip, len(candidates))}개를 건너뜁니다")
        candidates = candidates[skip:]
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
        got = session.get(url)
        result = probe.classify(got, url, home_host=home_host)
        if result.collectible:
            routes.append((refine_label(label, got, url), kind, url))
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
            budget=min(40, session.budget),
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
            f"본문머리[{_body_head(data)}]"
            + (f" · 스크립트[{_script_head(data)}]" if _script_head(data) else "")
            + (f" · 관문시도실패[{'; '.join(failed_gateways[:2])}]" if failed_gateways else "")
            + ". "
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
    skip: int = 0,
    targets: tuple[str, ...] = (),
    trace: list[str] | None = None,
):
    """govorg 출처에 routes 가 비어 있으면 홈에서 발견해 채워 준다.

    이미 routes 가 적혀 있으면 사람이 검토한 것이므로 건드리지 않고, 발견분을
    **뒤에 덧붙인다**(설정이 우선, 발견은 보강).
    """
    from dataclasses import replace

    if not source.home:
        return source, []
    found, notes = find_routes(
        source.home,
        fetcher=fetcher,
        check_robots=check_robots,
        budget=budget,
        skip=skip,
        targets=targets,
        trace=trace,
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
        cands = sorted(
            {u for u in locs if u not in seen and not probe.not_a_board(u)},
            key=lambda u: -board_score(u, ""),
        )
        for url in cands[:max_candidates]:
            if session.budget <= 0:
                break
            seen.add(url)
            got = session.get(url)
            result = probe.classify(got, url, home_host=home_host)
            if result.collectible:
                routes.append((refine_label(categories.from_url(url), got, url), "board", url))
        if routes:
            notes.append(f"사이트맵에서 목록 {len(routes)}개를 찾았습니다: {sitemap}")
            break
    if urls and not routes:
        notes.append(f"사이트맵을 읽었으나 목록을 찾지 못했습니다: {urls[0]}")
    return routes, notes
