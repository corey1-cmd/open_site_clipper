"""경로 사이클 — 홈에서 링크를 못 얻은 기관을 **알려진 경로 패턴**으로 뚫는다.

'응답 0KB · <a> 0개' 로 실패한 19개 부처를 조사한 결과, 홈은 못 읽어도
게시판 주소 자체는 CMS 패밀리 몇 종으로 수렴했다(고용노동부 /news/notice/,
조달청 /kor/bbs/list.do, 문체부 /kor/s_notice/, 해수부 /article/list.do,
질병관리청 /board/board.es, 교육부 /boardCnts/, 행안부 /frt/bbs/).

그래서 기관마다 코드를 쓰지 않고 **패턴을 데이터로 두고 사이클로 돌린다**:

    for 패밀리 in 데이터:
        첫 경로를 시험 → 목록이면 **그 패밀리의 나머지 경로도** 이어서 시험
                       → 아니면 다음 패밀리로

첫 경로가 통한 패밀리만 깊게 파므로, 패턴이 수십 개여도 실제 요청은 몇 회에
그친다. 새 패턴을 알게 되면 JSON 에만 추가하면 되고 코드는 그대로다.

호스트는 www 유무 두 가지를 시도한다 — 조달청은 www 없는 pps.go.kr 에서
게시판이 열린다(실측).
"""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from . import categories, probe

DATA_FILE = Path(__file__).with_name("data") / "gov-paths.json"
# 진짜 홈이라면 메뉴 링크가 이만큼은 있다. 관문 페이지는 몇 개도 안 된다.
MIN_ENTRY_ANCHORS = 10
# 패밀리 첫 경로가 실패했을 때 같은 패밀리에서 더 볼 개수.
PROBE_AFTER_MISS = 2


@lru_cache(maxsize=1)
def families() -> tuple[tuple[str, tuple[str, ...], bool], ...]:
    """(패밀리 이름, 경로들) — 데이터 파일에서 한 번만 읽는다."""
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    out: list[tuple[str, tuple[str, ...], bool]] = []
    for item in raw.get("families", []):
        paths = tuple(str(p) for p in item.get("paths", []) if str(p).strip())
        if paths:
            out.append((str(item.get("family", "?")), paths, bool(item.get("entry_point"))))
    return tuple(out)


def host_variants(home_url: str) -> list[str]:
    """www 유무 두 가지 — 어느 쪽에서 게시판이 열리는지는 기관마다 다르다."""
    parts = urllib.parse.urlsplit(home_url if "://" in home_url else "https://" + home_url)
    host = parts.netloc
    if not host:
        return []
    scheme = parts.scheme or "https"
    other = host[4:] if host.startswith("www.") else "www." + host
    return [f"{scheme}://{host}", f"{scheme}://{other}"]


def probe_paths(
    home_url: str,
    *,
    fetcher: Callable[[str], bytes | None],
    budget: int = 40,
    home_host: str = "",
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """알려진 경로 패턴을 돌려 게시판을 찾는다.

    패밀리별로 첫 경로만 보고 접으면, 같은 패밀리에서 번호만 다른 경로가
    살아 있어도 놓친다(교육부는 boardID=333 이 없고 294 가 있다). 반대로
    한 패밀리를 끝까지 파면 뒤쪽 패밀리에 예산이 못 간다.

    그래서 패밀리 경계를 두지 않고 **모든 경로를 한 줄로 세워** 순서대로 본다.
    줄 세우는 기준은 (패밀리 안 순번, 패밀리 순번) — 각 패밀리의 첫 경로가
    먼저 오고, 그다음 각 패밀리의 두 번째가 온다. 예산이 어디서 끊기든
    모든 패밀리가 공평하게 기회를 받는다(카테고리 라운드로빈과 같은 발상).

    호스트는 www 유무 둘 다 — 조달청은 www 없는 pps.go.kr 에서 열린다(실측).
    """
    routes: list[tuple[str, str, str]] = []
    notes: list[str] = []
    bases = host_variants(home_url)
    if not bases:
        return routes, notes
    host = home_host or urllib.parse.urlsplit(bases[0]).netloc

    # 모든 (패밀리, 경로)를 순번으로 엮어 한 줄로.
    ordered: list[tuple[int, int, str, str]] = []
    for fam_idx, (family, paths, is_entry) in enumerate(families()):
        if is_entry:
            continue  # 진입점은 find_entry 가 따로 다룬다
        for path_idx, path in enumerate(paths):
            ordered.append((path_idx, fam_idx, family, path))
    ordered.sort(key=lambda x: (x[0], x[1]))

    left = budget
    seen: set[str] = set()
    for _pi, _fi, family, path in ordered:
        for base in bases:
            if left <= 0:
                notes.append(f"경로 예산({budget}회) 소진 — 일부 패턴은 못 봤습니다.")
                return routes, notes
            url = base + path
            if url in seen:
                continue
            seen.add(url)
            left -= 1
            if _adopt(url, fetcher, host, routes):
                notes.append(f"경로 패턴 '{family}' 적중: {url}")
                return routes, notes
    if not routes:
        notes.append(f"알려진 경로 패턴 {len(ordered)}개를 시도했으나 목록이 없었습니다.")
    return routes, notes


def _adopt(url: str, fetcher: Callable[[str], bytes | None], host: str, routes: list) -> bool:
    """한 주소를 시험해 목록이면 채택한다."""
    result = probe.classify(fetcher(url), url, home_host=host)
    if not result.collectible:
        return False
    kind = "rss" if url.endswith((".xml", ".jsp")) and "/rss/" in url else "board"
    routes.append((categories.from_url(url), kind, url))
    return True


def find_entry(
    home_url: str, *, fetcher: Callable[[str], bytes | None], budget: int = 8
) -> tuple[str, bytes]:
    """'/' 가 빈 응답일 때 **진짜 홈**을 찾는다.

    홈만 0KB 이고 하위 경로는 정상인 기관이 많다(고용노동부·문체부·해수부 …).
    '/' 가 리다이렉트 관문이라 내용이 없는 것이다. 진입점 후보를 돌려 **링크가
    실제로 들어 있는 페이지**를 찾으면, 그 페이지를 홈으로 삼아 기존 발견 로직을
    그대로 다시 태울 수 있다. 기관별 게시판 경로를 일일이 아는 것보다 일반적이다.

    돌려주는 것: (찾은 주소, 본문). 못 찾으면 ("", b"").
    """
    from . import discover as _discover

    bases = host_variants(home_url)
    entries = [p for _f, paths, is_entry in families() if is_entry for p in paths]
    left = budget
    for base in bases:
        for path in entries:
            if left <= 0:
                return "", b""
            left -= 1
            url = base + path
            data = fetcher(url)
            if not data:
                continue
            page = _discover._Page()
            try:
                page.feed(_discover.strip_noise(_decode(data)))
            except Exception:
                continue
            if len(page.anchors) >= MIN_ENTRY_ANCHORS:  # 메뉴가 실린 진짜 페이지
                return url, data
    return "", b""


def _decode(data: bytes) -> str:
    from .fetch import decode_text

    return decode_text(data)


# 관문 페이지가 실제 주소를 알려 주는 방식들 — 전부 HTML 안에 문자열로 있다.
_META_REFRESH_RE = re.compile(
    r'<meta[^>]+http-equiv\s*=\s*["\']?refresh["\']?[^>]*content\s*=\s*["\']?[^"\'>;]*;\s*url\s*=\s*([^"\'>\s]+)',
    re.I,
)
_JS_LOCATION_RE = re.compile(
    r"(?:(?:top\.|self\.|window\.)?location(?:\.href)?\s*=|location\.replace\s*\()"
    r'\s*["\']([^"\']+)["\']',
    re.I,
)
_FRAME_SRC_RE = re.compile(r'<frame[^>]+src\s*=\s*["\']([^"\']+)["\']', re.I)
# 관문으로 볼 크기 상한 — 이보다 크면 내용이 있는 페이지로 본다.
GATEWAY_MAX_BYTES = 4096


# 관문 페이지 안의 주소 문자열 — 변수로 조립하는 경우까지 잡으려면 패턴이 아니라
# **문자열 전체**를 봐야 한다. 관문은 작아서(4KB 이하) 후보가 몇 개 안 된다.
_URL_LITERAL_RE = re.compile(r'["\'](/[A-Za-z0-9_\-./?=&%]{2,120})["\']')
# 주소로 보이지만 실제 페이지가 아닌 것들 — 자원 파일·앵커. manifest.json 을 홈으로
# 따라간 학교가 있었다(서울기독대 — React 앱의 관문 문자열).
_NOT_A_PAGE = (
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
    ".map",
    ".json",
    ".webmanifest",
    ".xml",
    ".txt",
    ".pdf",
    ".hwp",
    ".zip",
    ".mp4",
)
# 인트로 화면에서 본 화면으로 가는 링크의 글자 — 이것부터 시험한다.
_INTRO_TEXT_RE = re.compile(
    r"홈페이지|바로\s*가기|메인|main|home|입장|enter|skip|건너뛰기|한국어|국문|korean|/kor?\b",
    re.I,
)
# 다른 말 화면 — 인트로에서 따라가면 영문 사이트를 홈으로 삼게 된다.
_FOREIGN_RE = re.compile(
    r"english|\beng\b|/en/|/eng/|/en\b|中文|chinese|日本|japanese|/cn/|/jp/|/chn/|/jpn/|/ch/",
    re.I,
)
# 홈이 아닌 화면 — 로그인·오류·개인정보 방침
_NOT_HOME_RE = re.compile(r"login|logout|error|privacy|policy|member|join|sso|auth", re.I)
# 입시 홈페이지 — 인트로에 대학 홈과 나란히 걸리지만 홈은 아니다
_ADMISSION_RE = re.compile(r"입시|입학|ipsi|iphak|admission", re.I)


def gateway_targets(data: bytes, base_url: str) -> list[str]:
    """관문 페이지가 가리킬 수 있는 주소 후보들 — 유력한 것부터.

    `location.href = "…"` 같은 명시 패턴을 먼저 보고, 그것이 없으면(변수로
    조립하는 경우) 본문의 **주소 문자열 전체**를 후보로 삼는다. 실측한 관문들은
    쿠키 설정·모바일 판별·UA 검사 스크립트라 주소가 변수에 담기는 일이 흔하다.
    """
    if not data or len(data) > GATEWAY_MAX_BYTES:
        return []
    text = _decode(data)
    out: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        target = urllib.parse.urljoin(base_url, raw.strip())
        if target in seen or target == base_url:
            return
        parts = urllib.parse.urlsplit(target)
        if parts.scheme not in ("http", "https"):
            return
        if parts.path.lower().endswith(_NOT_A_PAGE):
            return
        seen.add(target)
        out.append(target)

    # ① 명시 패턴 — 가장 확실하다.
    for pattern in (_META_REFRESH_RE, _JS_LOCATION_RE, _FRAME_SRC_RE):
        for m in pattern.finditer(text):
            add(m.group(1))
    # ② IIS 의 'Object Moved' 안내 페이지는 <a href> 로 알려 준다.
    if "object moved" in text.lower():
        for m in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']', text, re.I):
            add(m.group(1))
    # ③ 그래도 없으면 본문의 주소 문자열 — 변수로 조립하는 관문 대응.
    #    단, **관문임이 분명할 때만** 한다. 링크가 여럿인 페이지는 정상 홈이고,
    #    거기서 아무 주소나 집으면 엉뚱한 곳으로 끌려간다(실제로 그랬다).
    if not out and _looks_like_gateway(text):
        for m in _URL_LITERAL_RE.finditer(text):
            add(m.group(1))
    return out[:3]  # 후보가 많아도 앞의 셋까지만


def intro_targets(data: bytes, base_url: str, home_host: str) -> list[str]:
    """인트로 화면에서 **본 화면일 만한 주소** — 크기와 상관없이 본다.

    입시 홍보 인트로('intro.jsp'·'intro_260902.html')는 그림이 많아 관문 크기(4KB)를
    넘고, '홈페이지 바로가기' 링크나 onclick 의 location.href 로 본 화면을 가리킨다.
    이것을 따라가지 않으면 링크 두세 개짜리 인트로를 홈으로 알고 끝난다(광운대·
    한신대·강원도립대 … 실측). 고르는 것은 부르는 쪽이 한다(메뉴가 실린 화면만).
    """
    if not data:
        return []
    text = _decode(data)
    out: list[str] = []
    seen = {base_url.split("#", 1)[0]}

    def add(raw: str) -> None:
        target = urllib.parse.urljoin(base_url, raw.strip()).split("#", 1)[0]
        parts = urllib.parse.urlsplit(target)
        if target in seen or parts.scheme not in ("http", "https"):
            return
        if parts.path.lower().endswith(_NOT_A_PAGE) or probe.is_external(target, home_host):
            return
        if _FOREIGN_RE.search(target) or _NOT_HOME_RE.search(parts.path):
            return
        seen.add(target)
        out.append(target)

    for pattern in (_META_REFRESH_RE, _JS_LOCATION_RE, _FRAME_SRC_RE):
        for m in pattern.finditer(text):
            add(m.group(1))
    from . import discover as _discover

    page = _discover._Page()
    try:
        page.feed(_discover.strip_noise(text))
    except Exception:
        return out[:5]
    links = [(h, t) for h, t in page.anchors if not _FOREIGN_RE.search(t or "")]
    base_host = urllib.parse.urlsplit(base_url).netloc.lower().removeprefix("www.")

    def rank(link: tuple[str, str]) -> tuple[int, int, int]:
        # 대학 본 화면이 먼저 — 입시 홈페이지(하위 사이트)는 홈이 아니라 갈래 화면이다
        href, text = link
        host = urllib.parse.urlsplit(urllib.parse.urljoin(base_url, href)).netloc.lower()
        return (
            1 if _ADMISSION_RE.search(text or "") or _ADMISSION_RE.search(host) else 0,
            0 if host.removeprefix("www.") == base_host else 1,
            0 if _INTRO_TEXT_RE.search(text or "") else 1,
        )

    links.sort(key=rank)
    for href, _text in links:
        add(href)
    return out[:5]


# 인트로 화면 주소 — 링크가 꽤 있어도(팝업·배너 10여 개) 메뉴가 실린 본 화면이 아니다.
_INTRO_PATH_RE = re.compile(r"intro", re.I)
INTRO_MIN_LINKS = 40


def needs_hop(data: bytes | None, url: str) -> bool:
    """이 화면을 홈으로 삼기 전에 한 번 더 따라가 봐야 하나 — 링크가 몇 개 없거나,
    주소가 인트로('…/intro/intro.asp')인데 링크가 메뉴만큼 많지 않을 때."""
    n = menu_links(data, url)
    if n < MIN_ENTRY_ANCHORS:
        return True
    path = urllib.parse.urlsplit(url).path
    return bool(_INTRO_PATH_RE.search(path)) and n < INTRO_MIN_LINKS


def menu_links(data: bytes | None, url: str) -> int:
    """화면에 실린 같은 사이트 링크 수 — 메뉴가 실린 진짜 화면인지 가늠한다."""
    if not data:
        return 0
    from . import discover as _discover

    page = _discover._Page()
    try:
        page.feed(_discover.strip_noise(_decode(data)))
    except Exception:
        return 0
    host = urllib.parse.urlsplit(url).netloc
    n = 0
    for href, _text in page.anchors:
        target = urllib.parse.urljoin(url, href)
        if urllib.parse.urlsplit(target).scheme in ("http", "https") and not probe.is_external(
            target, host
        ):
            n += 1
    return n


def _looks_like_gateway(text: str) -> bool:
    """관문 페이지인가 — 링크는 거의 없고 스크립트가 본문의 대부분인 문서."""
    low = text.lower()
    if low.count("<a ") > 2:
        return False  # 메뉴가 있으면 정상 페이지다
    return "<script" in low or "<frameset" in low or "object moved" in low


def gateway_target(data: bytes, base_url: str) -> str:
    """관문 페이지가 가리키는 **진짜 주소**를 뽑는다.

    홈이 1KB 남짓한 기관이 많다(공정위·교육부·해수부·조달청 …). 빈 응답이 아니라
    `<meta http-equiv="refresh">` · `location.href=` · `<frameset>` 으로 실제
    페이지를 가리키는 **관문**이다. 그 주소가 HTML 안에 문자열로 들어 있으므로
    JavaScript 를 실행하지 않고도 읽어낼 수 있다.

    못 찾으면 "". 관문 크기를 넘는 페이지는 애초에 보지 않는다(오탐 방지).
    """
    found = gateway_targets(data, base_url)
    return found[0] if found else ""
