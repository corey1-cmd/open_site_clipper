"""해석 계층 — 수집물에서 계산 가능한 통계적 해석(표·그래프의 데이터).

무LLM 원칙에서 '해석'은 논지 서술이 아니라 수치로 말하는 것이다:
발행 추이(주별)와 그 증감 정형 문장, 기관 활동 분포, 주요 사안(유사 묶음
크기) 순위, 최대 사안의 타임라인, 이전 실행(--state) 대비 새로 등장한
키워드. 전부 결정론 — 표는 각 렌더러가, 그래프는 chart.py(SVG)가 그린다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from . import cluster
from .digest import title_tokens
from .model import Notice

WEEKS = 8  # 추이 창 — 최근 8주(앵커는 오늘이 아니라 데이터의 최신 발행일)


@dataclass(frozen=True, slots=True)
class Insight:
    """해석 묶음 — 렌더러가 표/그래프로 그릴 재료."""

    weekly: tuple[tuple[str, int], ...] = ()  # (주 시작 MM/DD, 건수) 옛→새
    trend: str = ""  # 증감 정형 문장 (계산 불가 시 "")
    agencies: tuple[tuple[str, int, str], ...] = ()  # (기관, 건수, 최근 발행 ISO)
    issues: tuple[tuple[str, int, int], ...] = ()  # (대표 제목, 항목 수, 기관 수)
    timeline: tuple[tuple[str, str, str], ...] = ()  # (ISO일, 제목, 기관)
    new_keywords: tuple[str, ...] = ()  # --state 대비 이번에 새로 등장한 키워드

    def is_empty(self) -> bool:
        return not (self.weekly or self.agencies or self.issues)


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _weekly(dates: list[date], weeks: int) -> tuple[tuple[str, int], ...]:
    """발행일들을 주 단위 버킷(빈 주 포함)으로 — 앵커는 최신 발행 주."""
    if not dates:
        return ()
    anchor = _week_start(max(dates))
    starts = [anchor - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    counts = Counter(_week_start(d) for d in dates)
    return tuple((f"{s.month:02d}/{s.day:02d}", counts.get(s, 0)) for s in starts)


def _trend(weekly: tuple[tuple[str, int], ...]) -> str:
    """전반기 대비 후반기 발행량의 증감을 정형 문장으로."""
    if len(weekly) < 4:
        return ""
    half = len(weekly) // 2
    prev = sum(c for _, c in weekly[:half])
    recent = sum(c for _, c in weekly[half:])
    if prev == 0 and recent == 0:
        return ""
    if prev == 0:
        return f"최근 {half}주에 발행이 새로 시작됐습니다({recent}건)."
    pct = (recent - prev) / prev * 100
    if pct >= 15:
        word = "늘었습니다"
    elif pct <= -15:
        word = "줄었습니다"
    else:
        word = "비슷한 수준입니다"
    return f"최근 {half}주 발행량({recent}건)은 이전 {half}주({prev}건) 대비 {pct:+.0f}%로 {word}."


def _agencies(notices: list[Notice], top: int) -> tuple[tuple[str, int, str], ...]:
    counts = Counter(n.agency for n in notices)
    latest: dict[str, date] = {}
    for n in notices:
        if n.published and (n.agency not in latest or n.published > latest[n.agency]):
            latest[n.agency] = n.published
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return tuple((a, c, latest[a].isoformat() if a in latest else "") for a, c in ranked)


def _new_keywords(notices: list[Notice], top: int = 6) -> tuple[str, ...]:
    """--state가 표시한 신규 항목에만 등장하는 토큰(빈도순) — 상태 없으면 ()."""
    fresh = [n for n in notices if n.is_new]
    seen_before = [n for n in notices if not n.is_new]
    if not fresh or not seen_before:
        return ()
    old_tokens = frozenset().union(*(title_tokens(n.title) for n in seen_before))
    counts: Counter[str] = Counter()
    for n in fresh:
        for t in title_tokens(n.title) - old_tokens:
            counts[t] += 1
    return tuple(w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top])


def build(
    notices: list[Notice],
    clusters: list[list[Notice]] | None = None,
    *,
    weeks: int = WEEKS,
    top_agencies: int = 6,
    top_issues: int = 5,
) -> Insight:
    """공지 목록(+선택: 미리 묶어 둔 클러스터)에서 해석을 계산한다."""
    if not notices:
        return Insight()
    if clusters is None:
        clusters = cluster.group(notices, text_of=lambda n: n.title, date_of=lambda n: n.published)

    weekly = _weekly([n.published for n in notices if n.published], weeks)

    issues = tuple(
        (c[0].title, len(c), len({n.agency for n in c})) for c in clusters if len(c) >= 2
    )[:top_issues]

    timeline: tuple[tuple[str, str, str], ...] = ()
    multi = [c for c in clusters if len(c) >= 2]
    if multi:
        biggest = multi[0]
        ordered = sorted(biggest, key=lambda n: ((n.published or date.max).toordinal(), n.title))[
            :6
        ]
        timeline = tuple(
            (n.published.isoformat() if n.published else "미상", n.title, n.agency) for n in ordered
        )

    return Insight(
        weekly=weekly,
        trend=_trend(weekly),
        agencies=_agencies(notices, top_agencies),
        issues=issues,
        timeline=timeline,
        new_keywords=_new_keywords(notices),
    )
