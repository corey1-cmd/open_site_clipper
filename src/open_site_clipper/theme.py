"""테마 정의 — '무엇에 관련된 자료를 모을 것인가'를 선언하는 파일.

테마는 정준 키워드(canonical) → 동의어(alias) 사전, 브리프의 섹션 구성,
용어 각주(glossary)로 이루어진다. 신한 '글로벌 이슈'류 테마 브리프의 뼈대로,
관련성 판정(relevance)은 이 사전을 기준으로 하고 보고서에는 정준 키워드로
채택 근거를 표기한다.

JSON 형식(--theme theme.json):
{
  "name": "우주",
  "description": "발사체·위성·우주정거장 동향",
  "keywords": {"우주": ["space", "항공우주"]},
  "sections": [
    {"name": "발사체", "keywords": {"발사체": ["로켓"], "재사용": []}},
    {"name": "위성", "keywords": {"위성": ["satellite", "군집위성"]}}
  ],
  "glossary": {"LEO": "지구 저궤도 — 고도 2,000km 이하"}
}

- keywords 의 키가 정준 키워드, 값 배열이 동의어(빈 배열 가능).
- sections 는 브리프 본문의 묶음과 순서. 항목은 가장 많이 맞은 섹션에
  배치되고, 섹션과 안 맞고 최상위 keywords에만 맞으면 '기타'로 간다.
- glossary 는 보고서의 용어 각주 박스로 렌더된다(선택).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

OTHER_SECTION = "기타"


@dataclass(frozen=True, slots=True)
class ThemeSection:
    """브리프 본문 섹션 하나 — 이름과 그 섹션을 규정하는 키워드."""

    name: str
    keywords: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Theme:
    """테마 하나 — 관련성 판정과 브리프 조립의 기준."""

    name: str
    description: str = ""
    keywords: dict[str, tuple[str, ...]] = field(default_factory=dict)
    sections: tuple[ThemeSection, ...] = ()
    glossary: dict[str, str] = field(default_factory=dict)

    def all_keywords(self) -> dict[str, tuple[str, ...]]:
        """정준→동의어 전체 사전(테마명 + 최상위 + 모든 섹션 병합)."""
        merged: dict[str, tuple[str, ...]] = {self.name: ()}
        for canon, aliases in self.keywords.items():
            merged[canon] = tuple(dict.fromkeys((*merged.get(canon, ()), *aliases)))
        for sec in self.sections:
            for canon, aliases in sec.keywords.items():
                merged[canon] = tuple(dict.fromkeys((*merged.get(canon, ()), *aliases)))
        return merged


def _keyword_map(raw: object, where: str) -> dict[str, tuple[str, ...]]:
    """{"정준": ["동의어", ...]} 형태 검증·정규화."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{where}.keywords 는 객체({{정준: [동의어…]}})여야 합니다.")
    out: dict[str, tuple[str, ...]] = {}
    for canon, aliases in raw.items():
        canon = str(canon).strip()
        if not canon:
            continue
        if aliases is None:
            aliases = []
        if not isinstance(aliases, list):
            raise ValueError(f"{where}.keywords['{canon}'] 는 배열이어야 합니다.")
        out[canon] = tuple(dict.fromkeys(str(a).strip() for a in aliases if str(a).strip()))
    return out


def from_dict(payload: dict[str, object]) -> Theme:
    """dict(파싱된 JSON) → Theme. 형식 오류는 한국어 메시지의 ValueError."""
    if not isinstance(payload, dict):
        raise ValueError("테마 파일은 JSON 객체여야 합니다.")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError('테마에는 "name" 이 필요합니다.')

    sections: list[ThemeSection] = []
    raw_sections = payload.get("sections")
    if raw_sections is None:
        raw_sections = []
    if not isinstance(raw_sections, list):
        raise ValueError("sections 는 배열이어야 합니다.")
    for i, raw in enumerate(raw_sections):
        if not isinstance(raw, dict):
            raise ValueError(f"sections[{i}] 는 객체여야 합니다.")
        sec_name = str(raw.get("name") or "").strip()
        if not sec_name:
            raise ValueError(f'sections[{i}] 에는 "name" 이 필요합니다.')
        sections.append(
            ThemeSection(
                name=sec_name, keywords=_keyword_map(raw.get("keywords"), f"sections[{i}]")
            )
        )

    glossary_raw = payload.get("glossary") or {}
    if not isinstance(glossary_raw, dict):
        raise ValueError("glossary 는 객체여야 합니다.")
    glossary = {
        str(k).strip(): str(v).strip()
        for k, v in glossary_raw.items()
        if str(k).strip() and str(v).strip()
    }

    return Theme(
        name=name,
        description=str(payload.get("description") or "").strip(),
        keywords=_keyword_map(payload.get("keywords"), "theme"),
        sections=tuple(sections),
        glossary=glossary,
    )


def load(path: str | Path) -> Theme:
    """--theme 파일을 읽어 Theme 으로. 읽기/형식 오류는 ValueError 로 통일."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"테마 파일을 읽을 수 없습니다: {e}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"테마 파일이 올바른 JSON이 아닙니다: {e}") from e
    return from_dict(payload)
