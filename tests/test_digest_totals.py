"""기간 요약의 숫자가 총계와 맞아야 한다.

실측에서 분류 숫자를 다 더해도 1,274건뿐인데 공지는 2,241건이었다 —
967건이 어디로 갔는지 알 수 없었다. 원인은 둘이었다:
  ① 분류가 비어 있는 공지를 아예 세지 않았다
  ② 상위 10종만 보여주고 나머지 건수를 적지 않았다
"""

from __future__ import annotations

from datetime import date

from open_site_clipper import digest, report
from open_site_clipper.model import Notice, Report

# 실제 기관 메뉴명 — 대분류로 묶여야 한다(공지·채용·입찰·인사·보도자료·자료·정책).
_MENUS = (
    "공지사항",
    "채용공고",
    "입찰정보",
    "인사발령",
    "보도자료",
    "간행물",
    "국정성과",
    "사전정보공표",
    "업무추진비",
    "새소식",
    "정책자료실",
    "감사결과",
    "설명자료",
    "통계자료",
)


def _notices(n: int, *, blank_every: int = 7) -> list[Notice]:
    return [
        Notice(
            title=f"t{i}",
            url=f"https://x/{i}",
            agency=f"기관{i % 15:02d}",
            category=("" if i % blank_every == 0 else _MENUS[i % len(_MENUS)]),
            published=date(2026, 7, 1),
        )
        for i in range(n)
    ]


def test_blank_category_is_counted_as_uncategorized():
    """분류가 빈 공지도 세야 합이 맞는다."""
    d = digest.build(_notices(100))
    names = {name for name, _c in d.categories}
    assert digest.UNCATEGORIZED in names
    blank = sum(1 for n in _notices(100) if not n.category)
    assert dict(d.categories)[digest.UNCATEGORIZED] == blank


def test_shown_plus_rest_equals_total():
    """보이는 건수 + 나머지 건수 = 전체 건수. 이것이 깨지면 숫자를 못 믿는다."""
    ns = _notices(100)
    d = digest.build(ns)
    assert d.total == len(ns)
    assert sum(c for _n, c in d.categories) + d.category_rest == d.total
    assert sum(c for _n, c in d.agencies) + d.agency_rest == d.total


def test_no_hidden_items_when_everything_fits():
    """전부 보이면 '외 N' 을 붙이지 않는다."""
    ns = [
        Notice(title=f"t{i}", url=f"https://x/{i}", agency="기관", category="공지")
        for i in range(5)
    ]
    d = digest.build(ns)
    assert d.category_more == 0 and d.category_rest == 0
    assert d.agency_more == 0 and d.agency_rest == 0
    md = report.render_markdown(Report(notices=ns, digest=d))
    assert "외 " not in md.split("### ")[0]


def test_markdown_and_html_show_remaining_counts():
    ns = _notices(100)
    rep = Report(notices=ns, digest=digest.build(ns))
    md = report.render_markdown(rep)
    cat_line = next(x for x in md.splitlines() if x.startswith("- 분류:"))
    org_line = next(x for x in md.splitlines() if x.startswith("- 기관:"))
    # 분류는 대분류 9종 이하라 대개 전부 보인다 — 그때는 '외 N' 을 붙이지 않는다.
    assert "미분류" in cat_line
    # 기관은 15곳이라 상위 12곳만 보이고 나머지가 건수와 함께 표기된다.
    assert "건(총" in org_line and "곳)" in org_line
    html = report.render_html(rep)
    assert "총 15곳" in html


def test_json_carries_totals():
    import json

    ns = _notices(50)
    data = json.loads(report.render_json(Report(notices=ns, digest=digest.build(ns))))
    assert data["digest"]["category_total"] >= 1
    assert data["digest"]["agency_total"] >= 1
