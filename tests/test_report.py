"""보고서 렌더러 — markdown·html·json 계약(출처·등급 무생략)."""

from __future__ import annotations

import json
from datetime import date

from open_site_clipper import rights
from open_site_clipper.model import Notice, Report


def _report() -> Report:
    return Report(
        notices=[
            Notice(
                title="재난안전 플랫폼 개통",
                url="https://g/1",
                agency="행정안전부",
                published=date(2025, 7, 6),
                rights=rights.KOGL_TYPE1,
            ),
            Notice(
                title="등급 미상 공지",
                url="https://g/2",
                agency="어느기관",
                published=None,
                rights=rights.UNKNOWN,
            ),
        ],
        generated_at="2025-07-07T09:00:00+09:00",
        since_days=7,
        failed_sources=["죽은출처"],
    )


def test_markdown_contains_sources_and_license():
    from open_site_clipper.report import render_markdown

    md = render_markdown(_report())
    assert "# 정부·공공기관 공지 보고서" in md
    assert "행정안전부" in md and "어느기관" in md
    assert "https://g/1" in md  # 원문 링크 무생략
    assert rights.badge(rights.KOGL_TYPE1) in md
    assert "재이용 조건" in md  # 라이선스 범례
    assert "죽은출처" in md  # 실패 출처 투명 표기
    assert "날짜 미상" in md


def test_html_is_self_contained_and_escapes():
    from open_site_clipper.report import render_html

    n = Notice(title="<script>x</script>", url="https://g/x", agency="A", rights=rights.KOGL_TYPE1)
    html = render_html(Report(notices=[n], generated_at="t"))
    assert html.startswith("<!doctype html>")
    assert "<style>" in html  # 인라인 CSS(외부 의존 없음)
    assert "<script>x</script>" not in html  # 이스케이프됨
    assert "&lt;script&gt;" in html


def test_json_roundtrips_and_normalizes_rights():
    from open_site_clipper.report import render_json

    payload = json.loads(render_json(_report()))
    assert payload["count"] == 2
    assert payload["agencies"] == ["어느기관", "행정안전부"]
    assert payload["failed_sources"] == ["죽은출처"]
    first = payload["notices"][0]
    assert first["published"] == "2025-07-06"
    assert first["rights"] == rights.KOGL_TYPE1
    assert first["rights_label"]


def test_render_dispatch_and_unknown_format():
    from open_site_clipper.report import render

    assert render(_report(), "markdown").startswith("#")
    assert render(_report(), "html").startswith("<!doctype")
    try:
        render(_report(), "pdf")
    except ValueError as e:
        assert "pdf" in str(e)
    else:  # pragma: no cover
        raise AssertionError("unknown format should raise")


def test_template_substitutes_markers():
    from open_site_clipper.report import render_template

    tmpl = (
        "# $title\n"
        "공지 $count건 / $agency_count기관 / 신규 $new_count건 / 기간 $since_days일\n"
        "기관: $agencies\n실패: $failed_sources\n\n$body_md\n\n$legend_md\n"
    )
    out = render_template(_report(), tmpl)
    assert "# 정부·공공기관 공지 보고서" in out
    assert "공지 2건 / 2기관 / 신규 0건 / 기간 7일" in out
    assert "기관: 어느기관, 행정안전부" in out
    assert "실패: 죽은출처" in out
    assert "| 발행일 | 제목 | 등급 |" in out  # $body_md
    assert "https://g/1" in out  # 원문 링크 무생략
    assert "### 출처 및 재이용 조건" in out  # $legend_md


def test_template_preserves_unknown_and_escapes_dollar():
    from open_site_clipper.report import render_template

    out = render_template(_report(), "$title / $없는마커 / 예산 $$1,000")
    assert out == "정부·공공기관 공지 보고서 / $없는마커 / 예산 $1,000"


def test_template_html_fragments_and_empty_report():
    from open_site_clipper.report import render_template

    out = render_template(_report(), "$body_html|$legend_html")
    assert "<table>" in out and "재이용 조건" in out
    empty = render_template(Report(generated_at="t"), "[$body_md][$digest_md][$since_days]")
    assert empty == "[_수집된 공지가 없습니다._][][]"


def test_empty_report_renders():
    from open_site_clipper.report import render_html, render_markdown

    empty = Report(generated_at="t")
    assert "수집된 공지가 없습니다" in render_markdown(empty)
    assert "수집된 공지가 없습니다" in render_html(empty)
