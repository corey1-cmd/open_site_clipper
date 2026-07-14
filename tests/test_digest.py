"""규칙 기반 다이제스트 — 상투어·숫자·기관명 제외, 결정론, 렌더러 통합."""

from __future__ import annotations

import json
from datetime import date

from open_site_clipper import digest, rights
from open_site_clipper.model import Notice, Report


def _n(title: str, agency: str = "행정안전부", category: str = "보도자료") -> Notice:
    return Notice(title=title, url=f"https://g/{hash(title)}", agency=agency, category=category)


def test_keywords_filter_boilerplate_digits_and_agency():
    notices = [
        _n("2025년 데이터 안전 지원사업 공고"),
        _n("데이터 안전 교육 안내"),
        _n("행정안전부 데이터 개방 확대 발표"),
        _n("제3차 지원 위원회 개최"),
    ]
    d = digest.build(notices)
    words = dict(d.keywords)
    assert words.get("데이터") == 3
    assert words.get("안전") == 2
    # '지원사업'은 한 토큰 — '지원' 단독은 1회뿐이라 빈도 하한(2)에 걸러진다.
    assert "지원" not in words
    # 상투어(공고·안내·발표·개최), 연도, 회차, 기관명 토큰은 키워드가 아니다.
    for banned in ("공고", "안내", "발표", "개최", "2025년", "제3차", "행정안전부", "행정안전부의"):
        assert banned not in words
    # 1건짜리(교육·개방·확대·위원회)는 요약 가치가 없어 제외된다.
    assert "교육" not in words


def test_counts_are_deterministic_with_name_tiebreak():
    notices = [
        _n("a", agency="나기관"),
        _n("b", agency="가기관"),
        _n("c", agency="가기관"),
        _n("d", agency="다기관"),
        _n("e", agency="다기관"),
    ]
    d = digest.build(notices)
    # 동수(가기관 2 = 다기관 2)는 이름 오름차순.
    assert d.agencies == [("가기관", 2), ("다기관", 2), ("나기관", 1)]


def test_empty_and_single_notice():
    assert digest.build([]).is_empty()
    # 공지 1건이면 빈도 하한을 낮춰 그 제목의 키워드라도 보여준다.
    d = digest.build([_n("청년 창업 지원")])
    assert ("청년", 1) in d.keywords


def test_renderers_include_digest_only_when_set():
    from open_site_clipper.report import render_html, render_json, render_markdown

    notices = [
        Notice(
            title="데이터 지원 계획",
            url="https://g/1",
            agency="행정안전부",
            published=date(2025, 7, 6),
            category="보도자료",
            rights=rights.KOGL_TYPE1,
        ),
        Notice(
            title="데이터 개방 계획",
            url="https://g/2",
            agency="행정안전부",
            category="보도자료",
            rights=rights.KOGL_TYPE1,
        ),
    ]
    plain = Report(notices=notices, generated_at="t")
    assert "기간 요약" not in render_markdown(plain)
    assert json.loads(render_json(plain))["digest"] is None

    plain.digest = digest.build(notices)
    md = render_markdown(plain)
    assert "## 기간 요약" in md and "데이터(2)" in md
    html = render_html(plain)
    assert "기간 요약" in html and 'class="chip"' in html
    payload = json.loads(render_json(plain))
    assert ["데이터", 2] in payload["digest"]["keywords"]
    assert payload["digest"]["agencies"] == [["행정안전부", 2]]
