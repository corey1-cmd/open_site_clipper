"""관련성 판정 — 출처 정체성·테마 기준으로 '관련 자료'만 고른다.

무LLM 규칙 기반: 항목 텍스트에 테마의 정준 키워드(또는 동의어)가 등장하는지를
필드별 가중치(제목 3 · 분류 2 · 요약 1)로 점수화한다. 한국어 복합어(예:
"통신군집위성" 속의 "군집위성")를 놓치지 않도록 토큰 일치가 아니라 부분 문자열
포함으로 본다 — 그 대신 채택 항목마다 **근거 키워드를 기록**해 보고서에 표기할
수 있게 한다(왜 왔는지 검증 가능, 블랙박스 없음). 같은 입력이면 항상 같은
선별이 나온다(오프라인 재현 원칙).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .model import Notice
from .theme import OTHER_SECTION, Theme

# 필드별 가중치 — 제목에 등장하면 3점, 분류 2점, 요약 발췌 1점.
TITLE_W, CATEGORY_W, SUMMARY_W = 3, 2, 1
# 출처 정체성 가점 — 출처의 topics가 테마·섹션·정준 키워드와 겹치면 +1(1회).
TOPIC_BONUS = 1
# 기본 채택 하한 — 제목 1회 적중(3점) 수준. 테마/CLI로 조정 가능.
DEFAULT_MIN_SCORE = 3


@dataclass(frozen=True, slots=True)
class Match:
    """채택된 항목 하나 — 점수와 채택 근거, 배치될 섹션."""

    notice: Notice
    score: int
    matched: tuple[str, ...]  # 근거가 된 정준 키워드(기여도 내림차순)
    section: str  # 배치 섹션명(테마 sections 기준, 해당 없으면 '기타')


def _variants(canon: str, aliases: tuple[str, ...]) -> tuple[str, ...]:
    """정준 키워드 자신 + 동의어(2자 이상만, 소문자화)."""
    return tuple(dict.fromkeys(v.casefold() for v in (canon, *aliases) if len(v.strip()) >= 2))


def _canon_score(notice: Notice, variants: tuple[str, ...]) -> int:
    """한 정준 키워드의 기여 점수 — 등장한 필드의 가중치 합(필드당 1회)."""
    score = 0
    for text, weight in (
        (notice.title, TITLE_W),
        (notice.category, CATEGORY_W),
        (notice.summary, SUMMARY_W),
    ):
        low = text.casefold()
        if any(v in low for v in variants):
            score += weight
    return score


def score(notice: Notice, theme: Theme) -> Match | None:
    """항목 하나를 테마에 대조한다. 아무 키워드도 안 맞으면 None."""
    contributions: dict[str, int] = {}
    for canon, aliases in theme.all_keywords().items():
        variants = _variants(canon, aliases)
        if not variants:
            continue
        c = _canon_score(notice, variants)
        if c:
            contributions[canon] = c
    if not contributions:
        return None

    total = sum(contributions.values())

    # 출처 정체성 가점 — 출처 topics ∩ (테마명·섹션명·정준 키워드).
    identity = {theme.name, *(s.name for s in theme.sections), *theme.all_keywords()}
    if any(t in identity for t in notice.topics):
        total += TOPIC_BONUS

    # 섹션 배치: 그 섹션 소속 정준 키워드들의 기여 합이 최대인 곳(동점은 정의 순).
    best_section = OTHER_SECTION
    best = 0
    for sec in theme.sections:
        s = sum(contributions.get(c, 0) for c in sec.keywords)
        if s > best:
            best, best_section = s, sec.name

    matched = tuple(sorted(contributions, key=lambda c: (-contributions[c], c)))
    return Match(notice=notice, score=total, matched=matched, section=best_section)


def select(notices: list[Notice], theme: Theme, *, min_score: int | None = None) -> list[Match]:
    """테마 관련 항목만 점수순으로 고른다(하한 미달 제외)."""
    floor = DEFAULT_MIN_SCORE if min_score is None else min_score
    picked = [m for n in notices if (m := score(n, theme)) and m.score >= floor]
    picked.sort(
        key=lambda m: (
            -m.score,
            -(m.notice.published or date.min).toordinal(),
            m.notice.title,
        )
    )
    return picked
