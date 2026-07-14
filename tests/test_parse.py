"""파싱 계약 — RSS/Atom·data.go.kr·날짜·HTML 정리."""

from __future__ import annotations

from datetime import date

from open_site_clipper import parse, rights

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>여름철 호우 대비 안내</title>
    <link>https://ex.gov/a</link>
    <description>&lt;p&gt;대피 &lt;b&gt;요령&lt;/b&gt;   안내&lt;/p&gt;</description>
    <pubDate>Fri, 04 Jul 2025 14:30:00 +0900</pubDate>
  </item>
  <item><title>제목만</title><link>https://ex.gov/b</link></item>
  <item><title>링크없음</title></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>공모 안내</title>
    <link rel="alternate" href="https://ex.gov/atom1"/>
    <updated>2025-07-02T09:00:00Z</updated>
    <summary>요약문</summary>
  </entry>
</feed>"""


def test_parse_rss_extracts_items_and_cleans_html():
    notices = parse.parse_rss(RSS, agency="행정안전부", rights=rights.KOGL_TYPE1)
    # 링크 없는 항목은 버려진다 → 2건
    assert len(notices) == 2
    n = notices[0]
    assert n.title == "여름철 호우 대비 안내"
    assert n.url == "https://ex.gov/a"
    assert n.agency == "행정안전부"
    assert n.rights == rights.KOGL_TYPE1
    assert n.published == date(2025, 7, 4)
    assert n.summary == "대피 요령 안내"  # 태그 제거 + 공백 접기


def test_parse_atom_uses_href_link():
    notices = parse.parse_rss(ATOM, agency="문체부", rights=rights.KOGL_TYPE1)
    assert len(notices) == 1
    assert notices[0].url == "https://ex.gov/atom1"
    assert notices[0].published == date(2025, 7, 2)


def test_parse_rss_rejects_xml_bomb():
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>'
        "<rss><channel><item><title>&lol;</title><link>x</link></item></channel></rss>"
    )
    assert parse.parse_rss(bomb, agency="x", rights=rights.UNKNOWN) == []


def test_parse_datago_standard_and_odcloud_fields():
    payload = """{"response":{"body":{"items":{"item":[
      {"title":"보도자료 A","detailUrl":"https://g/a","regDate":"2025-07-06"},
      {"nttSj":"공지 B","link":"https://g/b","frstRegistDt":"20250703"}
    ]}}}}"""
    notices = parse.parse_datago(payload, agency="과기정통부", rights=rights.KOGL_TYPE1)
    assert [n.title for n in notices] == ["보도자료 A", "공지 B"]
    assert notices[0].published == date(2025, 7, 6)
    assert notices[1].published == date(2025, 7, 3)
    assert notices[1].url == "https://g/b"


def test_parse_datago_odcloud_shape():
    payload = '{"data":[{"title":"C","url":"https://g/c","date":"2025.07.01"}]}'
    notices = parse.parse_datago(payload, agency="x", rights=rights.UNKNOWN)
    assert len(notices) == 1 and notices[0].published == date(2025, 7, 1)


def test_parse_date_formats():
    assert parse.parse_date("2025-07-04") == date(2025, 7, 4)
    assert parse.parse_date("20250704") == date(2025, 7, 4)
    assert parse.parse_date("2025.07.04") == date(2025, 7, 4)
    assert parse.parse_date("Fri, 04 Jul 2025 14:30:00 +0900") == date(2025, 7, 4)
    assert parse.parse_date("garbage") is None
    assert parse.parse_date("") is None


def test_bad_xml_returns_empty():
    assert parse.parse_rss("<not xml", agency="x", rights="x") == []
    assert parse.parse_datago("{bad json", agency="x", rights="x") == []
