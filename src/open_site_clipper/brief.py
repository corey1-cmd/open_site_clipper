"""테마 브리프 — 정체성으로 고른 자료를 섹션 구조의 보고서로 조립한다.

신한 '글로벌 이슈'류 골격: 상단 테마 요약 박스 → 섹션별 [사안] 나열 →
해석(표·그래프) → 용어 각주 → 출처·재이용 조건. 조립만 담당하고 선별은
relevance, 묶음은 cluster, 해석은 insight/chart가 맡는다(계층 분리).

무LLM 원칙상 문단형 서술은 만들지 않는다. 대신 대표 제목 + 발췌(등급 허용
시) + 관련 항목 접기 + 채택 근거 키워드로 '왜 이게 관련 자료인지'까지
독자가 검증할 수 있게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import cluster, insight, relevance
from .digest import Digest
from .model import Notice
from .relevance import Match
from .theme import OTHER_SECTION, Theme


@dataclass(frozen=True, slots=True)
class Issue:
    """브리프의 한 사안 — 대표 항목 + 같은 사안을 다룬 관련 항목들."""

    lead: Match
    related: tuple[Match, ...] = ()

    @property
    def agencies(self) -> list[str]:
        return sorted({self.lead.notice.agency, *(m.notice.agency for m in self.related)})

    @property
    def size(self) -> int:
        return 1 + len(self.related)

    @property
    def is_new(self) -> bool:
        return self.lead.notice.is_new or any(m.notice.is_new for m in self.related)


@dataclass(frozen=True, slots=True)
class Section:
    """테마 섹션 하나 — 이름과 그 안의 사안들."""

    name: str
    issues: tuple[Issue, ...] = ()


@dataclass
class Brief:
    """테마 브리프 한 편 — 렌더러가 그대로 그릴 수 있는 완성 구조."""

    theme: Theme
    sections: list[Section] = field(default_factory=list)
    insight: insight.Insight | None = None
    digest: Digest | None = None
    generated_at: str = ""
    since_days: int | None = None
    failed_sources: list[str] = field(default_factory=list)
    considered: int = 0  # 관련성 판정 대상이 된 전체 공지 수
    min_score: int = relevance.DEFAULT_MIN_SCORE

    @property
    def title(self) -> str:
        return f"{self.theme.name} 브리프"

    @property
    def matches(self) -> list[Match]:
        """채택된 전체 항목(대표+관련) — 점수순 평탄화."""
        out: list[Match] = []
        for sec in self.sections:
            for issue in sec.issues:
                out.append(issue.lead)
                out.extend(issue.related)
        return out

    @property
    def notices(self) -> list[Notice]:
        return [m.notice for m in self.matches]

    @property
    def issue_count(self) -> int:
        return sum(len(s.issues) for s in self.sections)

    @property
    def agencies(self) -> list[str]:
        return sorted({n.agency for n in self.notices})

    @property
    def new_count(self) -> int:
        return sum(1 for n in self.notices if n.is_new)

    @property
    def top_keywords(self) -> list[str]:
        """채택 근거로 가장 많이 쓰인 정준 키워드(요약 박스용)."""
        counts: dict[str, int] = {}
        for m in self.matches:
            for k in m.matched:
                counts[k] = counts.get(k, 0) + 1
        return sorted(counts, key=lambda k: (-counts[k], k))[:6]


def _section_order(theme: Theme) -> list[str]:
    """테마 정의 순서 + 마지막에 '기타'."""
    return [s.name for s in theme.sections] + [OTHER_SECTION]


def build(
    notices: list[Notice],
    theme: Theme,
    *,
    min_score: int | None = None,
    generated_at: str = "",
    since_days: int | None = None,
    failed_sources: list[str] | None = None,
    with_insight: bool = True,
    with_digest: Digest | None = None,
) -> Brief:
    """공지 목록에서 테마 관련 자료만 골라 섹션 브리프로 조립한다."""
    floor = relevance.DEFAULT_MIN_SCORE if min_score is None else min_score
    picked = relevance.select(notices, theme, min_score=floor)

    by_section: dict[str, list[Match]] = {}
    for m in picked:
        by_section.setdefault(m.section, []).append(m)

    sections: list[Section] = []
    for name in _section_order(theme):
        members = by_section.get(name)
        if not members:
            continue
        groups = cluster.group(
            members,
            text_of=lambda m: m.notice.title,
            date_of=lambda m: m.notice.published,
        )
        issues: list[Issue] = []
        for g in groups:
            # 묶음 안 대표 선정: 점수 최고 → 발췌 보유 → 최신 → 제목.
            # 발췌 보유를 점수 다음에 두는 이유: 같은 사안을 여러 기관이 낸 경우
            # 본문 발췌가 있는 쪽이 브리프에서 더 많은 정보를 전달한다(등급이
            # 발췌를 허용한 자료 = 재이용 조건도 넉넉한 자료라는 점도 유리).
            ordered = sorted(
                g,
                key=lambda m: (
                    -m.score,
                    not m.notice.summary,
                    -(m.notice.published or date.min).toordinal(),
                    m.notice.title,
                ),
            )
            issues.append(Issue(lead=ordered[0], related=tuple(ordered[1:])))
        issues.sort(
            key=lambda i: (
                -i.lead.score,
                -i.size,
                -(i.lead.notice.published or date.min).toordinal(),
                i.lead.notice.title,
            )
        )
        sections.append(Section(name=name, issues=tuple(issues)))

    picked_notices = [m.notice for m in picked]
    ins = None
    if with_insight and picked_notices:
        ins = insight.build(picked_notices)

    return Brief(
        theme=theme,
        sections=sections,
        insight=ins,
        digest=with_digest,
        generated_at=generated_at,
        since_days=since_days,
        failed_sources=list(failed_sources or []),
        considered=len(notices),
        min_score=floor,
    )
