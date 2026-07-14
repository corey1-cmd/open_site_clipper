"""해석 계층 — 주별 추이·정형 문장·기관/사안 표·신규 키워드·SVG 차트."""

from __future__ import annotations

from datetime import date

from open_site_clipper import chart, insight
from open_site_clipper.model import Notice


def _n(title, published=None, agency="행정안전부", is_new=False):
    return Notice(
        title=title,
        url=f"https://g/{abs(hash((title, agency)))}",
        agency=agency,
        published=published,
        is_new=is_new,
    )


def test_weekly_buckets_zero_filled_and_anchored_on_data():
    ns = [
        _n("a", date(2026, 6, 1)),  # 월요일
        _n("b", date(2026, 6, 2)),
        _n("c", date(2026, 6, 29)),
    ]
    ins = insight.build(ns, weeks=5)
    assert [c for _, c in ins.weekly] == [2, 0, 0, 0, 1]  # 빈 주 포함, 앵커=최신 주
    assert ins.weekly[-1][0] == "06/29" and ins.weekly[0][0] == "06/01"


def test_trend_sentences():
    up = [_n(f"u{i}", date(2026, 6, 22) + (date(2026, 6, 29) - date(2026, 6, 22)) * 0) for i in range(3)]
    old = [_n("o", date(2026, 5, 4))]
    ins = insight.build(old + up, weeks=8)
    assert "대비" in ins.trend and "%" in ins.trend
    fresh_only = insight.build([_n("n", date(2026, 6, 29))], weeks=8)
    assert "새로 시작" in fresh_only.trend
    assert insight.build([_n("x")]).trend == ""  # 발행일 없음 → 문장 없음


def test_agencies_and_issue_ranking_and_timeline():
    ns = [
        _n("창정 발사체 회수 성공", date(2026, 7, 10), agency="A부"),
        _n("창정 발사체 회수 성공 브리핑", date(2026, 7, 11), agency="B청"),
        _n("위성 개방 계획", date(2026, 7, 12), agency="A부"),
    ]
    ins = insight.build(ns)
    assert ins.agencies[0] == ("A부", 2, "2026-07-12")
    # 크기 2 이상 묶음만 사안으로: (대표 제목, 항목 수, 기관 수)
    assert ins.issues == (("창정 발사체 회수 성공 브리핑", 2, 2),)
    # 타임라인은 최대 사안의 일자순 전개.
    assert [t[0] for t in ins.timeline] == ["2026-07-10", "2026-07-11"]


def test_new_keywords_require_state_mix():
    old = _n("데이터 개방 계획", date(2026, 7, 1))
    new = _n("휴머노이드 로봇 실증", date(2026, 7, 8), is_new=True)
    ins = insight.build([old, new])
    assert "휴머노이드" in ins.new_keywords and "데이터" not in ins.new_keywords
    assert insight.build([old]).new_keywords == ()  # 상태 미사용 → 계산 안 함
    assert insight.build([]).is_empty()


def test_bar_svg_deterministic_and_escaped():
    a = chart.bar(["06/01", "06/08"], [3, 5], title="추이<b>")
    b = chart.bar(["06/01", "06/08"], [3, 5], title="추이<b>")
    assert a == b and a.count("<rect") == 2 and "&lt;b&gt;" in a
    assert 'viewBox="0 0 560 200"' in a
    assert "데이터 없음" in chart.bar([], [])
    assert "데이터 없음" in chart.bar(["x"], [1, 2])  # 길이 불일치 방어


def test_hbar_and_sparkline():
    h = chart.hbar(["아주아주아주긴기관명칭연구원", "B청"], [4, 1], title="기관")
    assert h.count("<rect") == 2 and "…" in h  # 긴 라벨 말줄임
    s = chart.sparkline([0, 2, 1, 3])
    assert "<polyline" in s and "<circle" in s
    assert chart.sparkline([]).count("데이터 없음") == 1
