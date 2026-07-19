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

from .model import Notice

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

    agencies: list[tuple[str, int]] = field(default_factory=list)
    categories: list[tuple[str, int]] = field(default_factory=list)
    keywords: list[tuple[str, int]] = field(default_factory=list)

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
    top_agencies: int = 5,
    top_categories: int = 5,
    top_keywords: int = 8,
) -> Digest:
    """공지 목록에서 기간 요약을 만든다. 빈 목록이면 빈 Digest."""
    if not notices:
        return Digest()
    agency_counter = Counter(n.agency for n in notices)
    category_counter = Counter(n.category for n in notices if n.category)
    return Digest(
        agencies=_top(agency_counter, top_agencies),
        categories=_top(category_counter, top_categories),
        keywords=_keywords(notices, set(agency_counter), top_keywords),
    )
