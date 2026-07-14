"""공공누리(KOGL) 라이선스 등급 — 수집한 공지의 재이용 조건을 명시한다.

정부·공공기관 저작물의 재이용은 공공누리(KOGL, Korea Open Government License)
유형과 저작권법 제7조(보호받지 못하는 저작물)를 따른다. 이 모듈은 각 출처의
등급을 담고, 보고서가 "이 자료를 어떻게 재이용해도 되는가"를 독자에게 정확히
알리도록 한다(무단 전재가 아니라 조건부 개방 자료임을 드러내는 것이 목적).

  - PUBLIC_DOMAIN  저작권법 제7조: 고시·공고·법령 등. 자유 이용.
  - KOGL_TYPE1     출처표시. 상업적 이용·변형(2차 저작물) 허용.
  - KOGL_TYPE2     출처표시 + 비상업적 이용만.
  - KOGL_TYPE3     출처표시 + 변경 금지(상업적 이용 가능).
  - KOGL_TYPE4     출처표시 + 비상업 + 변경 금지.
  - UNKNOWN        등급 미상 — 보수적으로 제목·링크·출처만 인용한다.
"""

from __future__ import annotations

PUBLIC_DOMAIN = "public_domain"
KOGL_TYPE1 = "kogl_type1"
KOGL_TYPE2 = "kogl_type2"
KOGL_TYPE3 = "kogl_type3"
KOGL_TYPE4 = "kogl_type4"
UNKNOWN = "unknown"

# 등급 → 사람이 읽는 재이용 조건(보고서 각주·범례에 그대로 인쇄된다).
LABELS: dict[str, str] = {
    PUBLIC_DOMAIN: "저작권법 제7조 — 자유 이용(고시·공고·법령 등)",
    KOGL_TYPE1: "공공누리 제1유형 — 출처표시(상업적 이용·변형 허용)",
    KOGL_TYPE2: "공공누리 제2유형 — 출처표시 + 비상업적 이용",
    KOGL_TYPE3: "공공누리 제3유형 — 출처표시 + 변경 금지",
    KOGL_TYPE4: "공공누리 제4유형 — 출처표시 + 비상업 + 변경 금지",
    UNKNOWN: "등급 미상 — 제목·링크·출처만 인용(보수적 이용)",
}

# 짧은 배지 표기(카드·표에서 쓰는 한 칸짜리 라벨).
BADGES: dict[str, str] = {
    PUBLIC_DOMAIN: "제7조",
    KOGL_TYPE1: "KOGL-1",
    KOGL_TYPE2: "KOGL-2",
    KOGL_TYPE3: "KOGL-3",
    KOGL_TYPE4: "KOGL-4",
    UNKNOWN: "미상",
}

_ALL = frozenset(LABELS)

# 출처표시만 하면 상업적 이용·변형까지 가능한 개방 등급(가장 자유로운 두 등급).
_OPEN = frozenset({PUBLIC_DOMAIN, KOGL_TYPE1})

# 변경(요약·번역·재구성)이 금지되는 등급 — 원문 그대로 인용만 허용된다.
_NO_DERIV = frozenset({KOGL_TYPE3, KOGL_TYPE4, UNKNOWN})


def normalize(tier: str | None) -> str:
    """알 수 없는 값은 UNKNOWN으로 접는다(등급은 항상 유효한 상수 하나)."""
    t = (tier or "").strip().lower()
    return t if t in _ALL else UNKNOWN


def label(tier: str | None) -> str:
    """등급의 사람이 읽는 재이용 조건 문장."""
    return LABELS[normalize(tier)]


def badge(tier: str | None) -> str:
    """등급의 짧은 배지 표기."""
    return BADGES[normalize(tier)]


def is_open(tier: str | None) -> bool:
    """출처표시만으로 상업적 이용·변형까지 되는 개방 등급인가."""
    return normalize(tier) in _OPEN


def allows_derivative(tier: str | None) -> bool:
    """요약·번역 등 '변형'이 허용되는 등급인가(3·4유형·미상은 금지)."""
    return normalize(tier) not in _NO_DERIV
