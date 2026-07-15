"""핵심 도메인 모델 — 공지 하나(Notice)와 수집 결과 묶음(Report)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — 런타임 순환 임포트 회피
    from .deeplink import Link
    from .digest import Digest


@dataclass(frozen=True, slots=True)
class Notice:
    """정부·공공기관 공지 한 건 — 보고서를 이루는 최소 단위.

    수집은 제목·링크·기관·발행일·요약(발췌)·분류·라이선스 등급만 담는다.
    본문 전체를 복제하지 않는 것이 원칙이다(개방 자료라도 재이용 조건이 등급에
    따라 다르므로, 원문은 링크로 연결하고 우리는 메타데이터만 모은다).
    """

    title: str
    url: str
    agency: str  # 발행 기관명 (예: "행정안전부")
    published: date | None = None  # 발행일(파싱 실패 시 None)
    summary: str = ""  # 짧은 발췌 요약 (없으면 빈 문자열)
    category: str = ""  # 분류 라벨 (선택)
    rights: str = "unknown"  # 공공누리 등급 (rights.py 상수)
    is_new: bool = False  # 이전 실행(--state) 대비 신규 여부 — state.mark_new가 채운다
    topics: tuple[str, ...] = ()  # 출처의 정체성 태그 승계 — collect가 채운다
    # 본문에서 캔 관련 자료 링크(--deep-links). 링크만 담고 본문은 담지 않는다.
    links: tuple[Link, ...] = ()

    def dedup_key(self) -> str:
        """중복 판정 키 — 링크 우선, 없으면 (기관+제목).

        같은 공지가 여러 피드(부처 통합 RSS + 개별 부처 RSS)로 중복 유입될 때
        한 건으로 접는다.
        """
        u = self.url.strip()
        if u:
            return u.casefold()
        return f"{self.agency}\x1f{' '.join(self.title.split())}".casefold()


@dataclass(slots=True)
class Report:
    """수집 결과 묶음 — 보고서 렌더러가 받는 입력."""

    notices: list[Notice] = field(default_factory=list)
    generated_at: str = ""  # ISO 8601 생성 시각
    title: str = "정부·공공기관 공지 보고서"
    since_days: int | None = None  # 조회 기간(일) — 표지에 표기
    failed_sources: list[str] = field(default_factory=list)  # 수집 실패 출처명
    # 섹션 축 — "agency"(기본) | "topic". 렌더러가 이 값으로 그룹을 고른다.
    group_by: str = "agency"
    # 기간 요약(digest.build 결과). None이면 렌더러가 요약 섹션을 생략한다.
    # (digest 모듈이 Notice를 임포트하므로 순환을 피해 문자열 애너테이션.)
    digest: Digest | None = None

    @property
    def agencies(self) -> list[str]:
        """등장한 기관명 목록(정렬)."""
        return sorted({n.agency for n in self.notices})

    @property
    def new_count(self) -> int:
        """이전 실행 대비 신규 공지 수(--state 미사용 시 0)."""
        return sum(1 for n in self.notices if n.is_new)

    def by_topic(self) -> dict[str, list[Notice]]:
        """주제(출처 정체성)별로 묶은 공지 — 한 공지가 여러 주제에 속할 수 있다.

        기관 축(by_agency)의 대안. 여러 기관이 같은 주제를 다루는 브리핑에서
        '무엇에 관한 소식인지'로 읽히게 한다. 주제 태그가 없는 공지는 '기타'로
        모은다. 정렬은 건수 내림차순 → 주제명(결정론), 각 묶음은 발행일 내림차순.
        """
        grouped: dict[str, list[Notice]] = {}
        for n in self.notices:
            for topic in n.topics or ("기타",):
                grouped.setdefault(topic, []).append(n)
        for items in grouped.values():
            items.sort(key=_sort_key, reverse=True)
        return {
            k: grouped[k] for k in sorted(grouped, key=lambda k: (k == "기타", -len(grouped[k]), k))
        }

    def by_agency(self) -> dict[str, list[Notice]]:
        """기관별로 묶은 공지(기관명 정렬, 각 묶음은 발행일 내림차순)."""
        grouped: dict[str, list[Notice]] = {}
        for n in self.notices:
            grouped.setdefault(n.agency, []).append(n)
        for items in grouped.values():
            items.sort(key=_sort_key, reverse=True)
        return {k: grouped[k] for k in sorted(grouped)}


def _sort_key(n: Notice) -> date:
    """발행일 정렬 키 — 날짜 미상은 가장 과거로 밀어 최신이 위로 오게 한다."""
    return n.published or date.min
