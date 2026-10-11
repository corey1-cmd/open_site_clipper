"""학교마다 공지·학사·장학·입학·채용 게시판을 **갈래마다 하나씩 찾아 채운다** — 외대 프리셋처럼.

홈 첫 화면의 메뉴만 보면 학교 대부분이 '공지사항' 하나만 걸린다(2026-10-11 경로 캐시:
학교 164곳 중 장학 게시판이 있는 곳 50, 다섯 갈래를 다 가진 곳 7). 장학·학사 게시판은
대개 '대학생활 > 장학 > 장학공지'처럼 한두 단계 안쪽이나 따로 떨어진 사이트(입학처·
학생지원)에 있다. 한국외대는 사람이 게시판 번호를 찾아 프리셋으로 넣었지만 356곳을
그렇게 할 수는 없다. 그래서 사람이 찾던 순서를 그대로 따른다:

  ① 후보 — 홈 메뉴와 **사이트맵 화면**(전체 메뉴가 한 장에 있다)의 링크 중 이름이 그
     갈래인 것('장학공지'·'학사공지'·'입시공지'·'채용공고'·'공지사항')
  ② 갈래별로 가장 그럴듯한 것부터 **번갈아** 구조 테스트(probe) — 날짜 달린 목록이면 채운다
  ③ 못 채운 갈래는 **갈래 화면**을 연다 — 이름이 그 갈래인 안내 화면('장학안내')이나 하위
     사이트 첫 화면('입학처'), 알림마당 같은 묶음 화면. 하위 사이트에서 처음 보이는
     '공지사항'은 그 갈래의 공지다(입학처 홈의 공지사항 = 입학 공지). 본교 화면의
     '공지사항'은 원래 이름 그대로 둔다(어느 화면에나 있는 대학 공지를 입학 공지로 오인하지 않게)

학생이 올리는 문의·상담·Q&A 게시판, 학사일정·식단 같은 화면은 공지가 아니므로 후보에서
뺀다. 요청 수는 갈래마다 상한을 둔다(테스트 5 + 갈래 화면 2곳 × 4).
"""

from __future__ import annotations

import heapq
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field

from . import categories, probe
from . import discover as _discover
from .fetch import decode_text

Route = tuple[str, str, str]
PageFetcher = Callable[[str], "bytes | None"]

TARGETS: tuple[str, ...] = ("공지", "학사", "장학", "입학", "채용")
TESTS_PER_SLOT = 5  # ①② 갈래마다 구조 테스트 상한
HUBS_PER_SLOT = 2  # ③ 갈래마다 열어 볼 갈래 화면 수
TESTS_PER_HUB = 4  # 갈래 화면 하나가 새 후보를 낼 때 늘어나는 테스트 수
MAX_REQUESTS = 70  # 이 단계 전체의 요청 상한(나머지는 일반 발견 몫)
MAX_LABEL = 20  # 메뉴 이름은 짧다 — 더 긴 링크 글자는 최근 글 상자의 글 제목이다
HUB_BONUS = 5  # 갈래 화면에서 새로 본 후보를 먼저 — 그 갈래를 말하는 자리에 있어서

# 공지가 아닌 게시판·화면 — 학생이 올리는 문의·후기, 일정표, 식단, 자주 묻는 질문.
_NOT_NOTICE_RE = re.compile(
    r"상담|문의|질문|q\s*&\s*a|qna|묻고|답하기|자유\s*게시|건의|칭찬|민원|faq|자주\s*묻는|"
    r"일정|캘린더|calendar|달력|시간표|식단|후기|수기",
    re.I,
)
# 게시판다운 이름 — '장학공지'·'취업게시판'·'입시소식'
_BOARDISH_RE = re.compile(r"공지|게시판|알림|소식|공고|뉴스|news|notice|board", re.I)
# 공지 갈래의 갈래 화면 — 이름에 갈래 말이 없어도 공지 게시판들이 모여 있는 묶음 화면
_NOTICE_HUB_RE = re.compile(r"알림|소식|광장|마당|커뮤니티|community", re.I)
_SITEMAP_RE = re.compile(r"사이트\s*맵|site\s*map|전체\s*메뉴", re.I)
# 공지 갈래에서 학과·기관 게시판보다 대학 공지를 먼저
_DEPT_RE = re.compile(r"학과|학부|전공|대학원|연구소|센터")
# 학과·전공 이름 — 갈래 말이 들어 있어도('공공인재학부'의 '인재') 그 갈래의 화면이 아니다.
# '학부입학'은 학부 입학이라 끝이 '학부'인 것만 학과로 본다.
_DEPARTMENT_RE = re.compile(r"(?:학과|학부|전공)$|학과\b|학과\s")
# 게시판이어도 공지가 아닌 것 — 분실물, 개인정보 처리방침 판, 약관(일반 발견에도 쓴다)
_JUNK_RE = re.compile(r"분실|습득|개인정보|처리방침|약관|저작권|사이트\s*맵|로그인", re.I)
_MAIN_NOTICE = frozenset(
    {"공지사항", "공지", "일반공지", "전체공지", "대학공지", "통합공지", "notice", "notices"}
)
# 날짜 달린 목록이어도 공지보다 자료에 가까운 것 — 뒤로 미룬다
_LOW_VALUE_RE = re.compile(r"자료|서식|양식|규정", re.I)
# 로그인해야 쓰는 시스템·신청 화면 — 게시판도 갈래 화면도 아니다('학사정보시스템'·'수강신청')
_SYSTEM_RE = re.compile(r"시스템|포털|portal|system|신청|로그인|login|e-?book|sso", re.I)
# 채용 갈래 화면은 이 말이 있어야 — '모집'만으로는 아니다('학군단 생활/모집'·'신입생 모집')
_JOB_HUB_RE = re.compile(r"채용|취업|일자리|진로|인재개발|구인|구직|job|career|recruit", re.I)
# 화면 안에 박힌 K2Web 목록 주소 — 메뉴 화면(subview.do)이 목록을 스크립트로 불러올 때
_K2_LIST_RE = re.compile(r"(?:https?://[^\"'\s<>]+)?/bbs/[A-Za-z0-9_\-]+/\d+/artclList\.do", re.I)
MINED_PER_SLOT = 2  # 안내 화면으로 판정된 게시판 이름의 화면에서 캐 볼 목록 주소 수


def slot_of(text: str, targets: tuple[str, ...] = TARGETS) -> str:
    """메뉴 이름 → 채울 갈래('' = 채울 갈래가 아니다)."""
    label = categories.tidy_label(text)
    if not label or len(label) > MAX_LABEL or not_notice(label):
        return ""
    cat = categories.classify(label)
    return cat if cat in targets else ""


def not_notice(label: str) -> bool:
    """공지 게시판이 아닌 이름 — 문의·상담·Q&A·일정·후기·분실물·개인정보 처리방침."""
    return bool(_NOT_NOTICE_RE.search(label or "") or _JUNK_RE.search(label or ""))


def same_page(url: str, home_url: str) -> bool:
    """홈과 같은 화면인가 — '…/university/' 와 '…/university/index.jsp'."""

    def norm(u: str) -> tuple[str, str, str]:
        parts = urllib.parse.urlsplit(u)
        path = re.sub(r"/(?:index|main|default)\.\w+$", "/", parts.path or "/")
        return (_bare(parts.netloc), path.rstrip("/"), parts.query)

    return bool(home_url) and norm(url) == norm(home_url)


def anchors(data: bytes) -> list[tuple[str, str]]:
    """화면의 (href, 글자) — 스크립트·스타일을 걷어 낸 뒤."""
    page = _discover._Page()
    try:
        page.feed(_discover.strip_noise(decode_text(data)))
    except Exception:
        return []
    return page.anchors


def _bare(host: str) -> str:
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def sitemap_links(links: list[tuple[str, str]], base_url: str, home_host: str) -> list[str]:
    """'사이트맵'·'전체메뉴' 화면 주소 — 전체 메뉴가 한 장에 실려 있다(XML 사이트맵은 아님)."""
    out: list[str] = []
    for href, text in links:
        url = urllib.parse.urljoin(base_url, href).split("#", 1)[0]
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or probe.is_external(url, home_host):
            continue
        path = parts.path.lower()
        if path.endswith((".xml", ".xml.gz")):
            continue
        if (_SITEMAP_RE.search(text or "") or "sitemap" in path or "site_map" in path) and (
            url not in out
        ):
            out.append(url)
    return out


def score(slot: str, label: str, url: str, home_host: str, board_score) -> int:
    """이 후보가 그 갈래의 게시판일 가능성 — 클수록 먼저 시험한다."""
    s = board_score(url, label)
    if _BOARDISH_RE.search(label):
        s += 6
    if _LOW_VALUE_RE.search(label):
        s -= 3
    if _DEPARTMENT_RE.search(label):
        s -= 6  # 학과 게시판보다 대학 게시판
    elif "대학원" in label:
        s -= 3
    if slot == "공지":
        if label.lower() in _MAIN_NOTICE:
            s += 4
        if _DEPT_RE.search(label):
            s -= 6
    return s


@dataclass
class _Pool:
    """갈래별 후보·갈래 화면 대기열 — 같은 주소는 처음 본 이름으로 한 번만."""

    home_host: str
    targets: tuple[str, ...]
    board_score: Callable[[str, str], int]
    home_url: str = ""
    first: dict[str, tuple[str, str]] = field(default_factory=dict)  # 주소 → (갈래, 이름)
    queue: dict[str, list] = field(default_factory=dict)
    hubs: dict[str, list] = field(default_factory=dict)
    queued: set[str] = field(default_factory=set)
    hub_seen: set[str] = field(default_factory=set)
    order: int = 0

    def _push(self, slot: str, label: str, url: str, bonus: int = 0) -> bool:
        if url in self.queued:
            return False
        self.queued.add(url)
        self.order += 1
        s = score(slot, label, url, self.home_host, self.board_score) + bonus
        heapq.heappush(self.queue.setdefault(slot, []), (-s, self.order, label, url))
        return True

    def push_first(self, slot: str, label: str, url: str) -> bool:
        """바로 다음에 시험할 후보 — 게시판 이름의 화면 속에서 캔 목록 주소."""
        if url in self.queued:
            return False
        self.queued.add(url)
        self.order += 1
        heapq.heappush(self.queue.setdefault(slot, []), (-1000, self.order, label, url))
        return True

    def push_hub(self, slot: str, label: str, url: str) -> None:
        if url in self.hub_seen or _DEPARTMENT_RE.search(label):
            return
        if slot == "채용" and not _JOB_HUB_RE.search(label):
            return
        self.hub_seen.add(url)
        self.order += 1
        # 하위 사이트 첫 화면('입학처')이 먼저, 그다음 본교 안내 화면
        own = _bare(urllib.parse.urlsplit(url).netloc) == _bare(self.home_host)
        heapq.heappush(self.hubs.setdefault(slot, []), (1 if own else 0, self.order, label, url))

    def pop(self, slot: str) -> tuple[str, str] | None:
        heap = self.queue.get(slot) or []
        if not heap:
            return None
        _s, _o, label, url = heapq.heappop(heap)
        return label, url

    def pop_hub(self, slot: str) -> tuple[str, str] | None:
        heap = self.hubs.get(slot) or []
        if not heap:
            return None
        _own, _o, label, url = heapq.heappop(heap)
        return label, url

    def add(self, page_url: str, links: list[tuple[str, str]], hub_slot: str = "") -> dict:
        """화면 하나의 링크를 후보·갈래 화면으로 나눈다 → 갈래별 새 후보 수."""
        grown: dict[str, int] = {}
        page_host = _bare(urllib.parse.urlsplit(page_url).netloc)
        sub_site = bool(hub_slot) and page_host != _bare(self.home_host)
        for href, text in links:
            url = urllib.parse.urljoin(page_url, href).split("#", 1)[0]
            if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
                continue
            if probe.is_external(url, self.home_host):
                continue
            fresh = url not in self.first
            label = categories.tidy_label(text)
            slot = slot_of(text, self.targets)
            # 하위 사이트(입학처·취업지원센터)에서 처음 보는 '공지사항'은 그 갈래의 공지다.
            if (
                sub_site
                and fresh
                and hub_slot != "공지"
                and slot in ("", "공지")
                and label
                and len(label) <= MAX_LABEL
                and _BOARDISH_RE.search(label)
                and not _NOT_NOTICE_RE.search(label)
                and _bare(urllib.parse.urlsplit(url).netloc) == page_host
            ):
                slot, label = hub_slot, f"{hub_slot} {label}"
            if fresh:
                self.first[url] = (slot, label)
            if slot and _SYSTEM_RE.search(label) and not _BOARDISH_RE.search(label):
                continue  # 로그인 시스템·신청 화면
            if slot == "공지" and _bare(urllib.parse.urlsplit(url).netloc) != _bare(self.home_host):
                # 하위 사이트(취업지원센터·학생 커뮤니티)의 '공지사항'은 대학 공지가 아니다 —
                # 공지 자리는 본교 주소만. 그 게시판은 일반 발견이 따로 줍는다.
                continue
            if slot and _DEPARTMENT_RE.search(label) and probe.looks_like_home(url):
                continue  # 학과 홈은 갈래 화면이 아니다('공공인재학부' → 채용 화면 아님)
            if not slot:
                if (
                    label
                    and len(label) <= MAX_LABEL
                    and _NOTICE_HUB_RE.search(label)
                    and not _NOT_NOTICE_RE.search(label)
                ):
                    self.push_hub("공지", label, url)
                continue
            if probe.looks_like_article(url) or probe.looks_like_search(url):
                continue
            if probe.looks_like_home(url) or same_page(url, self.home_url):
                if not _DEPARTMENT_RE.search(label) and not same_page(url, self.home_url):
                    self.push_hub(slot, label, url)  # 입학처 홈 같은 하위 사이트 첫 화면
                continue
            if self._push(slot, label, url, HUB_BONUS if hub_slot and fresh else 0):
                grown[slot] = grown.get(slot, 0) + 1
        return grown


def list_literals(data: bytes, url: str, home_host: str, mine=None) -> list[str]:
    """화면 소스 안의 목록 주소 — 게시판 이름인데 목록이 스크립트로 그려질 때.

    K2Web 메뉴 화면(subview.do)은 목록을 `/bbs/{사이트}/{번호}/artclList.do` 로 불러오고,
    그 주소가 소스에 문자열로 들어 있다. 다른 CMS 는 mine(본문 속 게시판 주소 캐기)으로.
    """
    try:
        text = decode_text(data)
    except Exception:
        return []
    out: list[str] = []
    here = url.split("#", 1)[0]
    for m in _K2_LIST_RE.finditer(text):
        target = urllib.parse.urljoin(url, m.group(0))
        if target not in out and target != here and not probe.is_external(target, home_host):
            out.append(target)
    if mine is not None:
        for target in mine(data, url, home_host):
            if target not in out and target != here:
                out.append(target)
    return out[:MINED_PER_SLOT]


def short(url: str, limit: int = 70) -> str:
    """추적 기록용 — 호스트·경로·쿼리를 짧게."""
    parts = urllib.parse.urlsplit(url)
    text = parts.netloc + parts.path + (("?" + parts.query) if parts.query else "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def fill(
    get: PageFetcher,
    home_url: str,
    home_links: list[tuple[str, str]],
    home_host: str,
    *,
    board_score: Callable[[str, str], int],
    tested: dict[str, str],
    trace: list[str],
    targets: tuple[str, ...] = TARGETS,
    max_requests: int = MAX_REQUESTS,
    mine=None,
) -> list[Route]:
    """갈래마다 게시판 하나씩 — 찾은 (이름, "board", 주소)를 갈래 순서대로 돌려준다.

    tested 에는 시험한 주소와 판정이 쌓인다(뒤의 일반 발견이 같은 주소를 다시 열지 않게).
    """
    pool = _Pool(home_host, targets, board_score, home_url=home_url)
    pool.add(home_url, home_links)
    spent = 0
    kept: dict[str, bytes] = {}  # 안내 화면으로 판정된 것 — 갈래 화면으로 다시 쓸 때 재요청 없이

    def fetch(url: str) -> bytes | None:
        nonlocal spent
        spent += 1
        return get(url)

    for page in sitemap_links(home_links, home_url, home_host)[:2]:
        data = fetch(page)
        if not data:
            trace.append(f"사이트맵 못 엶 {short(page)}")
            continue
        links = anchors(data)
        pool.add(page, links)
        trace.append(f"사이트맵 {short(page)} 링크 {len(links)}")
        break

    filled: dict[str, Route] = {}
    tests_left = dict.fromkeys(targets, TESTS_PER_SLOT)
    hubs_left = dict.fromkeys(targets, HUBS_PER_SLOT)
    mined_left = dict.fromkeys(targets, MINED_PER_SLOT)

    def test(slot: str, label: str, url: str) -> None:
        data = fetch(url)
        result = probe.classify(data, url, home_host=home_host)
        tested[url] = result.verdict
        if result.collectible:
            filled[slot] = (label, "board", url)
            trace.append(f"{slot} ○ {label} {short(url)} ({result.dated}/{result.rows})")
            return
        trace.append(f"{slot} × {label} {short(url)} {result.verdict}")
        if data and result.verdict in (probe.STATIC, probe.INDEX):
            kept[url] = data
            pool.push_hub(slot, label, url)
            if mined_left[slot] > 0 and _BOARDISH_RE.search(label):
                # '장학공지'인데 목록이 없다 — 스크립트로 불러오는 목록 주소가 소스에 있을 수 있다
                for target in list_literals(data, url, home_host, mine):
                    if target in tested or mined_left[slot] <= 0:
                        continue
                    if pool.push_first(slot, label, target):
                        mined_left[slot] -= 1
                        tests_left[slot] += 1
                        trace.append(f"{slot} 화면 속 목록 주소 {short(target)}")

    while spent < max_requests:
        progressed = False
        moved = True
        while moved and spent < max_requests:  # ①② 갈래를 번갈아 하나씩
            moved = False
            for slot in targets:
                if slot in filled or tests_left[slot] <= 0 or spent >= max_requests:
                    continue
                cand = pool.pop(slot)
                while cand is not None and cand[1] in tested:
                    cand = pool.pop(slot)
                if cand is None:
                    continue
                tests_left[slot] -= 1
                moved = progressed = True
                test(slot, *cand)
        for slot in targets:  # ③ 못 채운 갈래마다 갈래 화면 하나
            if slot in filled or hubs_left[slot] <= 0 or spent >= max_requests:
                continue
            hub = pool.pop_hub(slot)
            if hub is None:
                continue
            hubs_left[slot] -= 1
            progressed = True
            label, url = hub
            data = kept.get(url) or fetch(url)
            if not data:
                trace.append(f"{slot} 갈래 화면 못 엶 {label} {short(url)}")
                continue
            links = anchors(data)
            grown = pool.add(url, links, hub_slot=slot)
            trace.append(
                f"{slot} 갈래 화면 {label} {short(url)} 링크 {len(links)}"
                + (" 새 후보 " + ",".join(f"{k}{v}" for k, v in grown.items()) if grown else "")
            )
            for other, n in grown.items():
                if other not in filled:
                    tests_left[other] += min(n, TESTS_PER_HUB)
        if not progressed:
            break
    missing = [s for s in targets if s not in filled]
    if missing:
        trace.append(f"못 채운 갈래 {','.join(missing)} (요청 {spent})")
    return [filled[s] for s in targets if s in filled]
