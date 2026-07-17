"""목적 동의어 사전 — '고용' 한 마디를 채용·모집·공채·인턴으로 펼친다.

pynori의 USER 사전(사용자 정의 항목이 대사전보다 먼저 매칭되는 층) 개념을
이 도구의 목적에 맞게 옮긴 것. `--query 고용`처럼 목적어 하나만 주면:

  1) 아래 사전에 있는 목적어 → 동의어로 확장한 섹션이 된다
  2) 없는 말(예: "AI", "반도체") → 그 말 자체가 키워드인 섹션이 된다
  3) 여러 개를 공백·쉼표로 나열하면 각각이 브리프의 [섹션]이 된다

확장 결과는 기존 테마 파이프라인(relevance→cluster→brief)을 그대로 타므로,
왜 이 자료가 뽑혔는지 '근거 키워드'가 항목마다 표기된다(블랙박스 없음).
동의어는 규칙 사전이라 오탐이 있을 수 있고, 그래서 근거 표기가 더 중요하다.
"""

from __future__ import annotations

import re

from .theme import Theme, ThemeSection

# 목적 → 동의어(정준 키워드 자신도 함께 매칭됨). 공지 제목의 실제 어휘 기준.
PURPOSES: dict[str, tuple[str, ...]] = {
    "고용": ("채용", "모집", "공채", "임용", "인턴", "일자리", "취업", "구인", "신입", "경력"),
    "복지": (
        "장학",
        "지원금",
        "학자금",
        "생활비",
        "기숙사",
        "상담",
        "의료",
        "건강",
        "보험",
        "돌봄",
    ),
    "정부투자": (
        "공모",
        "지원사업",
        "국고",
        "연구비",
        "R&D",
        "과제",
        "예산",
        "출연",
        "보조금",
        "투자",
    ),
    "장학": ("장학금", "학자금", "등록금", "면제", "감면", "국가장학"),
    "학사": ("수강", "성적", "졸업", "등록", "휴학", "복학", "계절학기", "시험", "학점"),
    "행사": ("세미나", "특강", "설명회", "박람회", "포럼", "축제", "경진대회", "공모전", "워크숍"),
    "안전": ("재난", "화재", "지진", "호우", "안전점검", "행동요령", "대피"),
    "입찰": ("공고", "낙찰", "계약", "조달", "발주", "제안요청", "RFP"),
}

_SPLIT_RE = re.compile(r"[\s,·/]+")


def available() -> list[str]:
    """사전에 등록된 목적어 목록(도움말·문서용)."""
    return sorted(PURPOSES)


def build_theme(query: str) -> Theme:
    """질의어로 즉석 테마를 만든다 — 파일 없이 한 줄 검색의 심장.

    질의어 순서를 보존하고(입력한 순서 = 브리프 섹션 순서) 중복은 접는다.
    빈 질의는 ValueError — 호출자가 사용법을 안내한다.
    """
    terms = [t for t in _SPLIT_RE.split(query or "") if t.strip()]
    terms = list(dict.fromkeys(terms))
    if not terms:
        raise ValueError('--query 검색어가 비었습니다. 예: --query 고용, --query "고용 복지"')

    sections = tuple(ThemeSection(name=t, keywords={t: PURPOSES.get(t, ())}) for t in terms)
    expanded = [t for t in terms if t in PURPOSES]
    desc = "질의어 즉석 검색"
    if expanded:
        desc += f" — 목적 사전 확장: {', '.join(expanded)}"
    return Theme(
        name=" · ".join(terms),
        description=desc,
        sections=sections,
    )
