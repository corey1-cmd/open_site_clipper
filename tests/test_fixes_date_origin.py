"""실사용에서 드러난 결함 세 가지 — 날짜 미상·실패 사유 은폐·출처 미표시."""

from __future__ import annotations

from datetime import date

from open_site_clipper import collect, fetch, parse, report, rights, sources
from open_site_clipper.cascade import origin_label
from open_site_clipper.k2web_parse import coerce_date


# ── ① 날짜를 못 가져오던 문제 ────────────────────────────────────────────────
def test_korean_and_short_year_dates():
    """국내 기관 게시판 실측 표기를 모두 읽는다."""
    assert coerce_date("2026.07.20.") == date(2026, 7, 20)
    assert coerce_date("2026년 7월 20일") == date(2026, 7, 20)  # 한글 표기
    assert coerce_date("26.07.20") == date(2026, 7, 20)  # 두 자리 연도
    assert coerce_date("20260720") == date(2026, 7, 20)  # 붙임 표기
    assert coerce_date("2026-07-20 15:30") == date(2026, 7, 20)


def test_date_parser_does_not_invent_dates():
    """없는 날짜를 지어내지 않는다 — 전화번호·연도만 있는 문자열은 None."""
    assert coerce_date("전화 02-123-4567") is None
    assert coerce_date("2026") is None
    assert coerce_date("") is None
    assert coerce_date("공지사항") is None


def test_rss_reads_dc_date_and_korean_pubdate():
    feed = (
        '<?xml version="1.0"?>'
        '<rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0"><channel>'
        "<item><title>A</title><link>https://x/1</link>"
        "<pubDate>Mon, 20 Jul 2026 05:18:00 GMT</pubDate></item>"
        "<item><title>B</title><link>https://x/2</link><dc:date>2026-07-19</dc:date></item>"
        "<item><title>C</title><link>https://x/3</link><pubDate>2026년 7월 18일</pubDate></item>"
        "<item><title>D</title><link>https://x/4</link></item>"
        "</channel></rss>"
    ).encode()
    got = {
        n.title: n.published
        for n in parse.parse_rss(feed, agency="t", category="", rights=rights.UNKNOWN)
    }
    assert got["A"] == date(2026, 7, 20)
    assert got["B"] == date(2026, 7, 19)  # dc:date — 예전에 놓치던 것
    assert got["C"] == date(2026, 7, 18)  # 한글 표기
    assert got["D"] is None  # 없으면 없는 대로


# ── ② 실패 사유가 '응답 없음' 으로 뭉뚱그려지던 문제 ────────────────────────
def test_fetch_detail_reports_real_reason():
    _data, why = fetch.fetch_detail("ftp://x/", retry=False)
    assert "지원하지 않는" in why


def test_tracking_fetcher_remembers_reason():
    tf = fetch.TrackingFetcher()
    assert tf.why("https://아직없음.example/") == "응답 없음"  # 기본값
    tf._reasons["https://a/"] = "접근 거부(403)"
    assert tf.why("https://a/") == "접근 거부(403)"


def test_cascade_records_specific_reason():
    """캐스케이드가 페처에게 사유를 물어 이력에 남긴다."""
    from open_site_clipper import govcascade

    class Blocked:
        def __call__(self, url):
            return None

        def why(self, url):
            return "접근 거부(403)"

    src = sources.Source(
        id="x",
        name="테스트부",
        kind="govorg",
        url="",
        org="테스트부",
        routes=(("공지", "board", "https://t.go.kr/list.do"),),
    )
    out = govcascade.collect_category(src, "공지", fetcher=Blocked(), check_robots=False)
    assert "접근 거부(403)" in out.trail()
    assert "응답 없음" not in out.trail()


# ── ③ 항목마다 출처를 보여주지 않던 문제 ────────────────────────────────────
def test_origin_label_is_host_and_stage():
    assert origin_label("https://www.korea.kr/rss/dept_mof.xml", "korea") == (
        "www.korea.kr · korea.kr 피드"
    )
    assert origin_label("https://www.mcst.go.kr/job/list.jsp", "board") == (
        "www.mcst.go.kr · 게시판"
    )
    assert origin_label("https://h/x", "alt").endswith("게시판(대체 경로)")


def test_report_shows_origin_box():
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
        "<item><title>보도자료 하나</title><link>https://www.korea.kr/n/1</link>"
        "<pubDate>Mon, 20 Jul 2026 05:18:00 GMT</pubDate></item></channel></rss>"
    ).encode()
    src = sources.Source(
        id="m",
        name="문화체육관광부",
        kind="govorg",
        url="",
        org="문화체육관광부",
        routes=(("보도자료", "rss", "https://www.korea.kr/rss/dept_mcst.xml"),),
    )
    rep = collect.collect([src], fetcher=lambda _s: feed, delay=0)
    (n,) = rep.notices
    assert n.published == date(2026, 7, 20)
    assert n.origin == "www.korea.kr · RSS 피드"

    html = report.render_html(rep)
    assert 'class="origin"' in html and "www.korea.kr · RSS 피드" in html
    md = report.render_markdown(rep)
    assert "<sub>" in md and "www.korea.kr" in md
    import json

    data = json.loads(report.render_json(rep))
    assert data["notices"][0]["origin"] == "www.korea.kr · RSS 피드"
