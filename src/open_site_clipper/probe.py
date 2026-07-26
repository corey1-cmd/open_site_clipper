"""구조 테스트 — 이 페이지가 **수집할 만한 목록인지** 모양으로 판정한다.

메뉴 이름으로는 판정할 수 없다는 것이 실측 결론이다. 같은 `정보공개` 라도
어떤 기관에선 날짜 붙은 목록이고 어떤 기관에선 설명문 한 장이다. 키워드 사전은
22개 메뉴명 중 13개를 놓쳤고, 새 기관의 새 메뉴명은 계속 빠진다.

그래서 이름 대신 **내용의 모양**을 본다. 이 프로젝트가 이미 두 번 쓴 원리다 —
k2web_parse 는 CSS 클래스 대신 표 구조에, govweb 은 링크 문법 대신 칸 순서에
기댔다. 세 번째 적용이다.

판정(교육부 메뉴 실측에서 도출한 네 유형):

    LIST     날짜 붙은 목록          → 수집 대상
    STATIC   설명문 한 장(글 없음)    → 가져올 것이 없음
    INDEX    링크 모음(날짜 없음)     → 목록이 아님
    EXTERNAL 기관 밖 도메인          → 별도 수집 대상(법령·공공데이터·민원 등)

STATIC·INDEX·EXTERNAL 은 건너뛰되 **사유를 남긴다**(조용한 실패 금지).
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from . import govweb

# 판정 결과
LIST = "list"
STATIC = "static"
INDEX = "index"
EXTERNAL = "external"

VERDICT_REASON = {
    LIST: "",
    STATIC: "목록이 아님(글 0~1건) — 안내 페이지로 보임",
    INDEX: "날짜 없는 링크 모음 — 목록이 아님",
    EXTERNAL: "기관 밖 도메인 — 별도 출처로 등록해 수집하세요",
}

# 수집 대상으로 보려면 이만큼은 있어야 한다.
MIN_ROWS = 2
# 행 중 날짜가 붙은 비율이 이보다 낮으면 목록이 아니라 링크 모음으로 본다.
MIN_DATED_RATIO = 0.5

# 기관 사이트가 아니라 별도 시스템 — 요청대로 법령은 여기서 제외된다.
# 도메인만 보고 판정하므로 새 시스템이 생겨도 기관 밖이면 EXTERNAL 로 잡힌다.
KNOWN_EXTERNAL = (
    "law.go.kr",  # 국가법령정보센터
    "data.go.kr",  # 공공데이터포털
    "epeople.go.kr",  # 국민신문고
    "open.go.kr",  # 정보공개포털
    "g2b.go.kr",  # 나라장터
    "gov.kr",  # 정부24
    "work24.go.kr",
    "kosis.kr",
)


@dataclass(frozen=True, slots=True)
class Probe:
    """한 후보 주소에 대한 판정."""

    url: str
    verdict: str
    rows: int = 0
    dated: int = 0

    @property
    def collectible(self) -> bool:
        return self.verdict == LIST

    @property
    def reason(self) -> str:
        return VERDICT_REASON.get(self.verdict, "")


def is_external(url: str, home_host: str) -> bool:
    """기관 사이트 밖인가 — 서브도메인은 같은 기관으로 본다."""
    host = urllib.parse.urlsplit(url).netloc.lower()
    if not host:
        return True
    if any(host == d or host.endswith("." + d) for d in KNOWN_EXTERNAL):
        return True
    home = (home_host or "").lower()
    if not home:
        return False
    # www.moe.go.kr 와 moe.go.kr · sub.moe.go.kr 를 같은 기관으로 묶는다.
    base = home[4:] if home.startswith("www.") else home
    return not (host == base or host.endswith("." + base))


def classify(data: bytes | None, url: str, *, home_host: str = "") -> Probe:
    """페이지 내용으로 유형을 판정한다. 받아오지 못했으면 STATIC 취급."""
    if home_host and is_external(url, home_host):
        return Probe(url=url, verdict=EXTERNAL)
    if not data:
        return Probe(url=url, verdict=STATIC)

    rows = govweb.parse_list(data, url)
    dated = sum(1 for r in rows if r.published is not None)
    if len(rows) < MIN_ROWS:
        return Probe(url=url, verdict=STATIC, rows=len(rows), dated=dated)
    if dated / len(rows) < MIN_DATED_RATIO:
        return Probe(url=url, verdict=INDEX, rows=len(rows), dated=dated)
    return Probe(url=url, verdict=LIST, rows=len(rows), dated=dated)
