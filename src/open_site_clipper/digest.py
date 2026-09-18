"""규칙 기반 다이제스트 — LLM 없이 수집 결과를 한눈에(기간 요약).

모델·외부 API 없이 순수 규칙(빈도 집계)만으로 보고서 상단에 붙일 요약을
만든다: 기관별 건수, 분류 분포, 제목 키워드 상위 N. 결정론적이라 같은
입력이면 항상 같은 요약이 나온다(오프라인 재현 원칙과 합치).

키워드 추출은 형태소 분석 없는 휴리스틱이다. 정부·공공기관 공지 제목은
"○○ 지원사업 공고"처럼 명사 나열형이 대부분이라 조사 제거 없이도 빈도
집계가 잘 동작한다(섣부른 조사 절단은 '합동평가→합동평' 같은 훼손을 낳아
하지 않는다). 상투어(안내·공고 등)·숫자·기관명 자체는 제외한다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from . import categories
from .model import Notice

# 분류가 비어 있는 공지를 세는 이름 — 합이 총계와 맞으려면 이것도 세야 한다.
UNCATEGORIZED = "미분류"

# 제목에서 뽑는 토큰 — 한글·영문·숫자 연속체.
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")

# 공지 상투어 — 주제가 아니라 문서 형식을 가리키는 말들이라 키워드에서 뺀다.
_STOPWORDS = frozenset(
    {
        "안내",
        "알림",
        "공고",
        "공지",
        "관련",
        "대한",
        "위한",
        "통한",
        "위해",
        "통해",
        "및",
        "등",
        "개최",
        "실시",
        "발표",
        "보도자료",
        "브리핑",
        "안내문",
        "재공고",
        "변경",
        "the",
        "of",
        "and",
        "for",
        "in",
        "on",
    }
)

# 제N차·제N회 같은 회차 표기.
_ORDINAL_RE = re.compile(r"^제?\d+(차|회|호|기|분기)?$")


@dataclass(frozen=True, slots=True)
class Digest:
    """기간 요약 — (이름, 건수) 쌍의 내림차순 목록들."""

    # 분류가 비어 있는 공지의 이름.

    agencies: list[tuple[str, int]] = field(default_factory=list)
    categories: list[tuple[str, int]] = field(default_factory=list)
    keywords: list[tuple[str, int]] = field(default_factory=list)
    # 목록에 보이는 것은 상위 몇 개뿐이므로 **전체 수**를 함께 남긴다.
    agency_total: int = 0
    category_total: int = 0
    # 목록에 보이는 것들의 **건수 합**과 전체 건수 — 둘이 다르면 그 차이를 적는다.
    total: int = 0
    agency_shown: int = 0
    category_shown: int = 0
    # '기타' 로 묶인 원래 이름들(상위 몇 개) — 사전 보강의 단서.
    etc_samples: list[tuple[str, int]] = field(default_factory=list)
    # '기타' 안의 서로 다른 이름 수 — 상위 몇 개가 전체의 일부뿐이면
    # 사전으로는 못 잡는 롱테일이라는 뜻이다(실측: 상위 8개가 14%).
    etc_names: int = 0

    @property
    def agency_more(self) -> int:
        """목록에 안 보이는 기관 수(0이면 전부 보인다)."""
        return max(0, self.agency_total - len(self.agencies))

    @property
    def category_more(self) -> int:
        return max(0, self.category_total - len(self.categories))

    @property
    def agency_rest(self) -> int:
        """목록에 안 보이는 기관들의 **건수 합**."""
        return max(0, self.total - self.agency_shown)

    @property
    def category_rest(self) -> int:
        return max(0, self.total - self.category_shown)

    def is_empty(self) -> bool:
        return not (self.agencies or self.categories or self.keywords)


def _top(counter: Counter[str], n: int) -> list[tuple[str, int]]:
    """건수 내림차순 · 동수는 이름 오름차순(결정론)."""
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def title_tokens(text: str) -> frozenset[str]:
    """제목류 텍스트의 내용 토큰 집합(소문자화) — 2자 이상·숫자/상투어 제외.

    digest 키워드 집계와 cluster(유사 사안 묶음), insight(신규 키워드)가
    같은 기준으로 토큰을 보게 하는 공용 함수.
    """
    from .korean import strip_suffix

    out: set[str] = set()
    for tok in _TOKEN_RE.findall(text):
        # 닫힌 접미(조사·어미) 최장일치 정규화 — "지원하는/지원하며"를 "지원"으로.
        tok = strip_suffix(tok)
        low = tok.casefold()
        if len(tok) < 2 or tok.isdigit() or low in _STOPWORDS or _ORDINAL_RE.match(tok):
            continue
        out.add(low)
    return frozenset(out)


def _keywords(notices: list[Notice], agencies: set[str], n: int) -> list[tuple[str, int]]:
    # 기관명(과 그 구성 토큰)은 주제가 아니라 발신자라 키워드에서 뺀다.
    skip = set(_STOPWORDS) | {a.casefold() for a in agencies}
    for a in agencies:
        skip.update(t.casefold() for t in _TOKEN_RE.findall(a))

    counts: Counter[str] = Counter()
    for notice in notices:
        # 같은 제목 안의 중복 토큰은 1회만(한 공지가 키워드를 부풀리지 않게).
        for tok in {t for t in _TOKEN_RE.findall(notice.title)}:
            low = tok.casefold()
            if len(tok) < 2 or low in skip or tok.isdigit() or _ORDINAL_RE.match(tok):
                continue
            counts[tok] += 1
    # 1건짜리 키워드는 요약 가치가 없어 제외한다(공지가 1건뿐일 때는 예외).
    floor = 1 if len(notices) == 1 else 2
    return [(w, c) for w, c in _top(counts, n) if c >= floor]


def build(
    notices: list[Notice],
    *,
    top_agencies: int = 12,
    top_categories: int = 10,
    top_keywords: int = 8,
) -> Digest:
    """공지 목록에서 기간 요약을 만든다. 빈 목록이면 빈 Digest.

    상위 몇 개만 보여주되 **전체 수를 함께 남긴다**. 22곳을 모았는데 5곳만
    보이면 나머지가 없는 것처럼 오해되기 때문이다(agency_total·category_total).
    """
    if not notices:
        return Digest()
    agency_counter = Counter(n.agency for n in notices)
    # 분류가 비어 있는 공지도 '미분류'로 세어 **합이 총계와 맞게** 한다.
    # 예전에는 아예 빼서, 분류 숫자를 다 더해도 공지 수에 한참 못 미쳤다.
    # 요약은 **대분류**로 센다. 세부 이름을 그대로 세면 기관마다 메뉴명이 달라
    # 실측에서 400종까지 늘었다(외 390종 4,189건). 표에는 세부가 그대로 남는다.
    category_counter = Counter(
        categories.canonical(n.category) if n.category else UNCATEGORIZED for n in notices
    )
    shown_categories = _top(category_counter, top_categories)
    # '기타' 가 크면 그 안에 무엇이 들었는지 보여 준다 — 사전에 무엇을 더할지는
    # 이 목록이 알려 준다. 추측으로 사전을 늘리다 두 번 헛짚었다.
    etc_raw = Counter(
        n.category
        for n in notices
        if n.category and categories.canonical(n.category) == categories.ETC
    )
    return Digest(
        etc_samples=_top(etc_raw, 10),
        etc_names=len(etc_raw),
        agencies=_top(agency_counter, top_agencies),
        categories=shown_categories,
        keywords=_keywords(notices, set(agency_counter), top_keywords),
        agency_total=len(agency_counter),
        category_total=len(category_counter),
        total=len(notices),
        agency_shown=sum(c for _n, c in _top(agency_counter, top_agencies)),
        category_shown=sum(c for _n, c in shown_categories),
    )
