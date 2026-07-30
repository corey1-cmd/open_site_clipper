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
        "www.korea.kr · korea.kr 피드 · /rss/dept_mof.xml"  # 어느 피드인지까지
    )
    assert origin_label("https://www.mcst.go.kr/job/list.jsp", "board") == (
        "www.mcst.go.kr · 게시판 · /job/list.jsp"
    )
    assert "게시판(대체 경로)" in origin_label("https://h/x", "alt")


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
    assert n.origin == "www.korea.kr · RSS 피드 · /rss/dept_mcst.xml"

    html = report.render_html(rep)
    assert 'class="origin"' in html and "/rss/dept_mcst.xml" in html
    md = report.render_markdown(rep)
    assert "<sub>" in md and "www.korea.kr" in md
    import json

    data = json.loads(report.render_json(rep))
    assert data["notices"][0]["origin"].endswith("/rss/dept_mcst.xml")


# ── 실기기 65곳 수집에서 드러난 결함 ─────────────────────────────────────────
def test_digest_reports_total_not_just_top_n():
    """22곳을 모았는데 5곳만 보이면 나머지가 없는 것처럼 오해된다."""
    from datetime import date

    from open_site_clipper import digest
    from open_site_clipper.model import Notice

    notices = [
        Notice(
            title=f"t{i}",
            url=f"https://x/{i}",
            agency=f"기관{i:02d}",
            category="공지",
            published=date(2026, 7, 1),
        )
        for i in range(20)
    ]
    d = digest.build(notices)
    assert d.agency_total == 20  # 전체 수를 남긴다
    assert d.agency_more == 20 - len(d.agencies) > 0
    rep = report.Report(notices=notices, digest=d)
    md = report.render_markdown(rep)
    assert "총 20곳" in md  # 보고서에 총계가 드러난다
    html = report.render_html(rep)
    assert "총 20곳" in html


def test_limiter_wrap_preserves_failure_reason():
    """간격 제어로 감싸도 실패 사유를 잃지 않는다(korea.kr 전멸의 원인이었다)."""
    from open_site_clipper import parallel

    tf = fetch.TrackingFetcher()
    tf._reasons["https://a/"] = "요청 과다(429)"
    wrapped = parallel.HostLimiter(0, use_robots=False).wrap(tf)
    assert callable(getattr(wrapped, "why", None))
    assert wrapped.why("https://a/") == "요청 과다(429)"


def test_attachment_column_does_not_steal_title():
    """'한글 파일 PDF 파일' 이 제목 자리를 빼앗던 문제(새만금개발청)."""
    from open_site_clipper import govweb

    html = (
        "<table><tbody><tr><td>1</td>"
        '<td><a href="/v?id=1">2026년 상반기 계약현황 공고</a></td>'
        '<td><a href="/f1">한글 파일</a> <a href="/f2">PDF 파일</a></td>'
        "<td>2026.07.24</td></tr></tbody></table>"
    ).encode()
    (row,) = govweb.parse_list(html, "https://www.saemangeum.go.kr/list.do")
    assert row.title == "2026년 상반기 계약현황 공고"


def test_menu_blob_and_url_titles_rejected():
    """안내문·메뉴가 목록으로 잘못 잡힐 때 나오던 쓰레기 제목을 거른다."""
    from open_site_clipper import govweb

    blob = "가" * 200
    html = (
        "<table><tbody>"
        f'<tr><td><a href="/a">{blob}</a></td><td>2026.07.24</td></tr>'
        '<tr><td><a href="/b">http://www.mfds.go.kr/www/rss/brd.do?brdId=ntc0003</a></td>'
        "<td>2026.07.24</td></tr>"
        "</tbody></table>"
    ).encode()
    assert govweb.parse_list(html, "https://x/") == []
