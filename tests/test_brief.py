"""테마 브리프 — 조립(섹션·사안 접기)과 3형식 렌더."""

from __future__ import annotations

import json
from datetime import date

import pytest

from open_site_clipper import brief, brief_report, rights, theme
from open_site_clipper.model import Notice

SPACE = theme.from_dict(
    {
        "name": "우주",
        "description": "발사체·위성 동향",
        "keywords": {"우주": []},
        "sections": [
            {"name": "발사체", "keywords": {"발사체": ["로켓"]}},
            {"name": "위성", "keywords": {"위성": []}},
        ],
        "glossary": {"LEO": "지구 저궤도"},
    }
)


def _n(title, agency="A부", published=None, summary="", is_new=False, url=""):
    return Notice(
        title=title,
        url=url or f"https://g/{abs(hash((title, agency)))}",
        agency=agency,
        published=published,
        summary=summary,
        rights=rights.KOGL_TYPE1,
        is_new=is_new,
    )


NOTICES = [
    _n("누리호 발사체 시험 성공", published=date(2026, 7, 10), summary="3단 엔진 연소"),
    _n("누리호 발사체 시험 성공 브리핑", "B청", date(2026, 7, 11)),
    _n("위성 관측 자료 공개", published=date(2026, 7, 9)),
    _n("우주 정책 로드맵", published=date(2026, 7, 8)),  # 최상위 키워드만 → 기타
    _n("지방세 납부 안내", published=date(2026, 7, 7)),  # 무관 → 제외
]


def test_build_sections_issues_and_folding():
    b = brief.build(NOTICES, SPACE, generated_at="T", since_days=7)
    assert [s.name for s in b.sections] == ["발사체", "위성", "기타"]  # 테마 정의 순
    launch = b.sections[0].issues
    # 같은 사안 2건이 하나로 접힘 — 동점이면 발췌 있는 쪽이 대표(정보량 우선).
    assert len(launch) == 1 and launch[0].size == 2
    assert launch[0].lead.notice.title == "누리호 발사체 시험 성공"
    assert launch[0].related[0].notice.agency == "B청"
    assert launch[0].agencies == ["A부", "B청"]
    # 무관 자료는 애초에 채택되지 않는다.
    assert "지방세 납부 안내" not in [n.title for n in b.notices]
    assert b.considered == 5 and len(b.notices) == 4 and b.issue_count == 3
    assert b.title == "우주 브리프" and b.insight is not None


def test_empty_when_nothing_relevant():
    b = brief.build([_n("지방세 납부")], SPACE)
    assert b.sections == [] and b.notices == [] and b.new_count == 0
    md = brief_report.render_markdown(b)
    assert "관련된 자료가 없습니다" in md
    assert json.loads(brief_report.render_json(b))["sections"] == []
    assert "관련된 자료가 없습니다" in brief_report.render_html(b)


def test_markdown_has_evidence_related_insight_and_legend():
    b = brief.build(NOTICES, SPACE, generated_at="T")
    md = brief_report.render_markdown(b)
    assert "## [발사체] (1건)" in md
    assert "근거: 발사체" in md  # 채택 근거 표기
    assert "같은 사안 1건:" in md and "B청" in md  # 접힌 관련 항목
    assert "3단 엔진 연소" in md  # 등급 허용 시 발췌
    assert "## 해석" in md and "**주별 발행 추이**" in md and "| 기관 | 건수 |" in md
    assert "**KOGL-1**" in md and "## 용어" in md and "LEO" in md


def test_html_is_self_contained_with_svg_and_aside():
    b = brief.build(NOTICES, SPACE, generated_at="T")
    h = brief_report.render_html(b)
    assert h.startswith("<!DOCTYPE html>") and h.rstrip().endswith("</html>")
    assert "<svg" in h and 'class="chart"' in h  # 해석 그래프 인라인
    assert 'class="theme-box"' in h and "<aside>" in h and "LEO" in h
    assert 'class="evidence"' in h  # 근거 칩
    assert "@media print" in h  # 인쇄 레이아웃


def test_json_shape_and_scores():
    b = brief.build(NOTICES, SPACE, generated_at="T")
    d = json.loads(brief_report.render_json(b))
    assert d["theme"] == "우주" and d["considered"] == 5 and d["count"] == 4
    launch = d["sections"][0]["issues"][0]
    assert launch["lead"]["matched"] == ["발사체"]
    assert launch["lead"]["score"] >= 3 and launch["size"] == 2
    assert d["insight"]["weekly"] and d["glossary"]["LEO"] == "지구 저궤도"


def test_new_flag_propagates_to_issue():
    b = brief.build([_n("위성 신규 공개", is_new=True, published=date(2026, 7, 1))], SPACE)
    issue = b.sections[0].issues[0]
    assert issue.is_new and b.new_count == 1
    assert "🆕" in brief_report.render_markdown(b)
    assert "NEW" in brief_report.render_html(b)


def test_render_rejects_unknown_format():
    b = brief.build(NOTICES, SPACE)
    with pytest.raises(ValueError, match="지원하지 않는 형식"):
        brief_report.render(b, "pdf")
