"""수집 오케스트레이션 — dedup·기간·기관 필터·fail-open(주입 페처)."""

from __future__ import annotations

from datetime import date

from open_site_clipper import collect, rights
from open_site_clipper.sources import Source

RSS_A = """<?xml version="1.0"?><rss><channel>
  <item><title>공지1</title><link>https://g/1</link><pubDate>2025-07-06</pubDate></item>
  <item><title>공지2</title><link>https://g/2</link><pubDate>2025-06-01</pubDate></item>
</channel></rss>"""
# 다른 출처가 같은 링크(https://g/1)를 전재 → 중복
RSS_B = """<?xml version="1.0"?><rss><channel>
  <item><title>공지1 전재</title><link>https://g/1</link><pubDate>2025-07-06</pubDate></item>
  <item><title>공지3</title><link>https://g/3</link><pubDate>2025-07-05</pubDate></item>
</channel></rss>"""


def _sources() -> list[Source]:
    return [
        Source(id="a", name="행정안전부", kind="rss", url="x", rights=rights.KOGL_TYPE1),
        Source(id="b", name="문화체육관광부", kind="rss", url="x", rights=rights.KOGL_TYPE1),
        Source(id="dead", name="죽은출처", kind="rss", url="x", rights=rights.UNKNOWN),
    ]


def _fetcher(source: Source) -> bytes | None:
    return {"a": RSS_A.encode(), "b": RSS_B.encode(), "dead": None}[source.id]


def test_collect_dedups_and_records_failures():
    rep = collect.collect(_sources(), fetcher=_fetcher, now=date(2025, 7, 7))
    urls = [n.url for n in rep.notices]
    # https://g/1 은 두 출처에 있지만 한 번만
    assert urls.count("https://g/1") == 1
    assert set(urls) == {"https://g/1", "https://g/2", "https://g/3"}
    # 죽은 출처는 실패로 기록(예외 없이 fail-open)
    assert rep.failed_sources == ["죽은출처"]
    # 발행일 내림차순
    assert rep.notices[0].published == date(2025, 7, 6)


def test_since_days_filters_old():
    rep = collect.collect(_sources(), fetcher=_fetcher, since_days=7, now=date(2025, 7, 7))
    # 2025-06-01(공지2)은 7일 밖 → 제외
    assert all(n.title != "공지2" for n in rep.notices)


def test_agency_filter():
    rep = collect.collect(_sources(), fetcher=_fetcher, agency="행정안전", now=date(2025, 7, 7))
    assert {n.agency for n in rep.notices} == {"행정안전부"}


def test_by_agency_grouping():
    rep = collect.collect(_sources(), fetcher=_fetcher, now=date(2025, 7, 7))
    grouped = rep.by_agency()
    assert set(grouped) == {"행정안전부", "문화체육관광부"}
    # 각 그룹은 발행일 내림차순
    for items in grouped.values():
        dates = [n.published for n in items if n.published]
        assert dates == sorted(dates, reverse=True)
