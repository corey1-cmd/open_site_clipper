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

from . import probe

DATA_FILE = Path(__file__).with_name("data") / "gov-paths.json"
# 진짜 홈이라면 메뉴 링크가 이만큼은 있다. 관문 페이지는 몇 개도 안 된다.
MIN_ENTRY_ANCHORS = 10


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
    budget: int = 12,
    home_host: str = "",
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """경로 사이클을 돌려 (카테고리, 종류, 주소) 목록과 메모를 만든다.

    budget 은 이 함수가 쓸 요청 수 상한이다. 패밀리 첫 경로가 통하지 않으면
    그 패밀리는 바로 접고 다음으로 가므로, 상한 안에서 여러 패밀리를 훑는다.
    """
    routes: list[tuple[str, str, str]] = []
    notes: list[str] = []
    bases = host_variants(home_url)
    if not bases:
        return routes, notes
    host = home_host or urllib.parse.urlsplit(bases[0]).netloc
    left = budget
    seen: set[str] = set()

    for base in bases:
        for family, paths, is_entry in families():
            if is_entry:
                continue  # 진입점은 find_entry 가 따로 다룬다
            if left <= 0:
                break
            head, *rest = paths
            url = base + head
            if url in seen:
                continue
            seen.add(url)
            left -= 1
            if not _adopt(url, fetcher, host, routes):
                continue  # 첫 경로가 아니면 이 패밀리는 접는다
            # 통했다 — 같은 패밀리의 나머지도 이어서 시험한다(짝일 확률이 높다).
            for path in rest:
                if left <= 0:
                    break
                nxt = base + path
                if nxt in seen:
                    continue
                seen.add(nxt)
                left -= 1
                _adopt(nxt, fetcher, host, routes)
            notes.append(f"경로 패턴 '{family}' 적중 — 목록 {len(routes)}개({base})")
            return routes, notes  # 한 패밀리를 찾았으면 충분하다
        if routes:
            break
    if not routes:
        notes.append(f"알려진 경로 패턴 {len(families())}종을 시도했으나 목록이 없었습니다.")
    return routes, notes


def _adopt(url: str, fetcher: Callable[[str], bytes | None], host: str, routes: list) -> bool:
    """한 주소를 시험해 목록이면 채택한다."""
    result = probe.classify(fetcher(url), url, home_host=host)
    if not result.collectible:
        return False
    kind = "rss" if url.endswith((".xml", ".jsp")) and "/rss/" in url else "board"
    routes.append(("기타", kind, url))
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


def gateway_target(data: bytes, base_url: str) -> str:
    """관문 페이지가 가리키는 **진짜 주소**를 뽑는다.

    홈이 1KB 남짓한 기관이 많다(공정위·교육부·해수부·조달청 …). 빈 응답이 아니라
    `<meta http-equiv="refresh">` · `location.href=` · `<frameset>` 으로 실제
    페이지를 가리키는 **관문**이다. 그 주소가 HTML 안에 문자열로 들어 있으므로
    JavaScript 를 실행하지 않고도 읽어낼 수 있다.

    못 찾으면 "". 관문 크기를 넘는 페이지는 애초에 보지 않는다(오탐 방지).
    """
    if not data or len(data) > GATEWAY_MAX_BYTES:
        return ""
    text = _decode(data)
    for pattern in (_META_REFRESH_RE, _JS_LOCATION_RE, _FRAME_SRC_RE):
        m = pattern.search(text)
        if m:
            target = urllib.parse.urljoin(base_url, m.group(1).strip())
            if target != base_url and urllib.parse.urlsplit(target).scheme in ("http", "https"):
                return target
    return ""
