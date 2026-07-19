"""--query 목적 검색 — 접미 정규화(korean), 동의어 확장(purposes), 통합."""

from __future__ import annotations

from datetime import date

import pytest

from open_site_clipper import brief, korean, purposes, relevance, rights
from open_site_clipper.digest import title_tokens
from open_site_clipper.model import Notice


def test_normalize_longest_match_and_safeguards():
    # 최장일치: '에서의'(3자)가 '에서'(2자)보다 먼저 떨어진다.
    assert korean.strip_suffix("플랫폼에서의") == "플랫폼"
    assert korean.strip_suffix("지원하는") == "지원"
    assert korean.strip_suffix("모집합니다") == "모집"
    assert korean.strip_suffix("확대되었습니다") == "확대"
    # 보호 장치: 단일 문자 조사는 안 뗌, 어간이 1자가 되면 안 뗌, 접미 없으면 그대로.
    assert korean.strip_suffix("마을") == "마을"
    assert korean.strip_suffix("하는") == "하는"
    assert korean.strip_suffix("데이터") == "데이터"


def test_title_tokens_merge_inflected_forms():
    # "지원하는"과 "지원"이 같은 토큰으로 집계된다(정규화 연결 효과).
    assert title_tokens("청년 지원하는 사업") == title_tokens("청년 지원 사업")


def test_build_theme_expands_known_purpose():
    th = purposes.build_theme("고용")
    assert th.name == "고용" and len(th.sections) == 1
    kw = th.sections[0].keywords
    assert "채용" in kw["고용"] and "인턴" in kw["고용"]
    assert "목적 사전 확장" in th.description


def test_build_theme_mixed_and_dedup_and_empty():
    th = purposes.build_theme("고용, AI 고용")
    assert [s.name for s in th.sections] == ["고용", "AI"]  # 순서 보존·중복 제거
    assert th.sections[1].keywords == {"AI": ()}  # 미등록어는 그 말 자체로
    with pytest.raises(ValueError, match="검색어가 비었습니다"):
        purposes.build_theme("  , ")


def _n(title, summary=""):
    return Notice(
        title=title,
        url=f"https://g/{abs(hash(title))}",
        agency="한국외국어대학교",
        published=date(2026, 7, 1),
        summary=summary,
        rights=rights.KOGL_TYPE1,
    )


def test_query_theme_selects_via_synonyms():
    notices = [
        _n("2026학년도 직원 채용 공고"),  # '채용' = 고용의 동의어
        _n("동계 인턴십 모집 안내"),  # '인턴'+'모집'
        _n("도서관 이용시간 변경"),  # 무관 → 제외
    ]
    th = purposes.build_theme("고용")
    picked = relevance.select(notices, th)
    # 동의어가 몇 개 맞았든 정준(고용) 기준 필드당 1회 계수 → 둘 다 3점 동점,
    # 발행일도 같아 제목 오름차순으로 정렬된다(결정론).
    assert [m.notice.title for m in picked] == [
        "2026학년도 직원 채용 공고",
        "동계 인턴십 모집 안내",
    ]
    # 근거 키워드는 목적어(정준)로 찍힌다 — 왜 뽑혔는지 검증 가능.
    assert all(m.matched == ("고용",) for m in picked)
    assert all(m.section == "고용" for m in picked)


def test_query_multi_purpose_brief_sections():
    notices = [
        _n("직원 채용 공고"),
        _n("국가장학금 2차 신청 안내"),
        _n("도서관 공사 안내"),
    ]
    b = brief.build(notices, purposes.build_theme("고용 장학"), generated_at="T")
    assert [s.name for s in b.sections] == ["고용", "장학"]
    assert b.considered == 3 and len(b.notices) == 2
