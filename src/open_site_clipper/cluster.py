"""연관 묶음 — 같은 사안을 다룬 항목들을 규칙으로 묶는다.

meridian은 임베딩+HDBSCAN으로 기사를 군집화하지만, 이 도구의 원칙(무LLM·
의존성 0·결정론)에 맞게 **제목 토큰 자카드 유사도** 기반의 탐욕 그룹핑으로
대체한다. 같은 발표를 여러 기관이 낸 경우(예: 발사 성공 보도 3건)를 한
묶음으로 접어 브리프의 잡음을 줄이는 것이 목적이다.

- 토큰 기준은 digest.title_tokens와 동일(상투어·숫자 제외) — 계층 간 일관성.
- dedup(동일 링크 제거)과는 별개의 층: 링크가 달라도 '유사 사안'이면 묶는다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import TypeVar

from .digest import title_tokens

T = TypeVar("T")

# 자카드 임계 — 공지 제목은 짧아 0.5면 '사실상 같은 사안'만 묶인다.
# 낮추면 과묶음(다른 사안 합쳐짐), 높이면 묶임이 드물어진다.
JACCARD_THRESHOLD = 0.5


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """자카드 유사도 |A∩B|/|A∪B| — 둘 다 비면 0."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def group(
    items: list[T],
    *,
    text_of: Callable[[T], str],
    date_of: Callable[[T], date | None] = lambda _x: None,
    threshold: float = JACCARD_THRESHOLD,
) -> list[list[T]]:
    """항목들을 유사 사안 묶음으로 나눈다. 각 묶음의 첫 항목이 대표.

    탐욕 방식: (발행일 내림차순, 텍스트) 순으로 훑으며 기존 묶음 대표와
    비교해 임계 이상이면 가장 비슷한 묶음에 합류, 아니면 새 묶음을 연다.
    출력은 (크기 내림차순, 대표 발행일 내림차순, 대표 텍스트) — 결정론.
    """
    ordered = sorted(
        items,
        key=lambda x: (-(date_of(x) or date.min).toordinal(), text_of(x)),
    )
    clusters: list[list[T]] = []
    rep_tokens: list[frozenset[str]] = []
    for item in ordered:
        toks = title_tokens(text_of(item))
        best_i, best_sim = -1, 0.0
        for i, rt in enumerate(rep_tokens):
            sim = jaccard(toks, rt)
            if sim >= threshold and sim > best_sim:
                best_i, best_sim = i, sim
        if best_i >= 0:
            clusters[best_i].append(item)
        else:
            clusters.append([item])
            rep_tokens.append(toks)

    clusters.sort(
        key=lambda c: (
            -len(c),
            -(date_of(c[0]) or date.min).toordinal(),
            text_of(c[0]),
        )
    )
    return clusters
