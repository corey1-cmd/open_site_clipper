"""수집 오케스트레이션 — dedup·기간·기관 필터·fail-open(주입 페처)."""

from __future__ import annotations

from datetime import date

from open_site_clipper import collect, rights
from open_site_clipper.model import Notice, Report
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


RSS_WITH_SUMMARY = """<?xml version="1.0"?><rss><channel>
  <item><title>요약있는 공지</title><link>https://g/s</link>
    <description>본문 발췌입니다</description></item>
</channel></rss>"""


def test_no_derivative_tiers_drop_summary():
    """3·4유형·미상은 '제목·링크·출처만 보수적 인용' — 요약 발췌를 비운다."""

    def fx(_s: Source) -> bytes:
        return RSS_WITH_SUMMARY.encode()

    for tier, kept in [
        (rights.KOGL_TYPE1, True),
        (rights.KOGL_TYPE2, True),
        (rights.KOGL_TYPE3, False),
        (rights.KOGL_TYPE4, False),
        (rights.UNKNOWN, False),
    ]:
        src = Source(id="s", name="기관", kind="rss", url="x", rights=tier)
        (n,) = collect.collect([src], fetcher=fx).notices
        assert bool(n.summary) is kept, tier


def test_datago_without_key_labeled_distinctly(monkeypatch):
    """인증키 미설정 datago 출처는 네트워크를 두드리지 않고 사유를 구분 표기한다."""
    from open_site_clipper.fetch import DATAGO_KEY_ENV

    monkeypatch.delenv(DATAGO_KEY_ENV, raising=False)
    src = Source(
        id="d", name="공공데이터포털", kind="datago", url="https://apis.data.go.kr/x/getList"
    )
    rep = collect.collect([src])  # fetcher=None → 실시간 경로(키 검사에서 즉시 실패)
    assert rep.notices == []
    assert rep.failed_sources == [f"공공데이터포털 (인증키 미설정: {DATAGO_KEY_ENV})"]


def test_by_topic_grouping():
    """주제 축 — 한 공지가 여러 주제에 중복 등장하고, 태그 없으면 '기타'."""
    tagged = Notice(title="a", url="https://g/1", agency="A부", topics=("우주", "산업"))
    plain = Notice(title="b", url="https://g/2", agency="B청")
    rep = Report(notices=[tagged, plain])
    groups = rep.by_topic()
    # 건수 내림차순 → 이름순, '기타'는 항상 마지막.
    assert list(groups) == ["산업", "우주", "기타"]
    assert groups["우주"] == [tagged] and groups["기타"] == [plain]


def test_group_by_switches_render_axis():
    from open_site_clipper.report import render_markdown

    n = Notice(title="a", url="https://g/1", agency="A부", topics=("우주",))
    rep = Report(notices=[n], generated_at="t")
    assert "## A부 (1건)" in render_markdown(rep)
    rep.group_by = "topic"
    md = render_markdown(rep)
    assert "## 우주 (1건)" in md and "## A부" not in md


def test_by_agency_grouping():
    rep = collect.collect(_sources(), fetcher=_fetcher, now=date(2025, 7, 7))
    grouped = rep.by_agency()
    assert set(grouped) == {"행정안전부", "문화체육관광부"}
    # 각 그룹은 발행일 내림차순
    for items in grouped.values():
        dates = [n.published for n in items if n.published]
        assert dates == sorted(dates, reverse=True)
