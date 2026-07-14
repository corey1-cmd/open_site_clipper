"""보고서 렌더러 — 수집한 공지를 하나의 문서로.

세 가지 형식을 제공한다:
  - markdown : 문서·이슈에 붙이기 좋은 표 형식(기관별 그룹)
  - html     : 자체 완결형(인라인 CSS) 보고서 — 그대로 열람·인쇄 가능
  - json     : 기계 판독용(다른 파이프라인 연동)

모든 형식은 출처(기관·발행일·원문 링크)와 공공누리(KOGL) 등급을 절대 생략하지
않는다 — 개방 자료의 재이용 조건을 독자가 바로 알 수 있게 하는 것이 이 도구의
핵심 가치다.
"""

from __future__ import annotations

import html
import json

from . import rights
from .model import Notice, Report


def _fmt_date(n: Notice) -> str:
    return n.published.isoformat() if n.published else "날짜 미상"


# ── Markdown ─────────────────────────────────────────────────────────────────
def render_markdown(report: Report) -> str:
    lines: list[str] = []
    lines.append(f"# {report.title}")
    lines.append("")
    lines.append(
        f"- 생성 시각: {report.generated_at or '미상'}"
        + (f" · 최근 {report.since_days}일" if report.since_days is not None else "")
    )
    counts = f"- 공지 {len(report.notices)}건 · 기관 {len(report.agencies)}곳"
    if report.new_count:
        counts += f" · 🆕 신규 {report.new_count}건"
    lines.append(counts)
    if report.failed_sources:
        lines.append(f"- ⚠ 수집 실패 출처: {', '.join(report.failed_sources)}")
    lines.append("")

    if not report.notices:
        lines.append("_수집된 공지가 없습니다._")
        return "\n".join(lines) + "\n"

    for agency, items in report.by_agency().items():
        lines.append(f"## {agency} ({len(items)}건)")
        lines.append("")
        lines.append("| 발행일 | 제목 | 등급 |")
        lines.append("|---|---|---|")
        for n in items:
            title = _md_escape(n.title)
            link = f"[{title}]({n.url})" if n.url else title
            if n.is_new:
                link = f"🆕 {link}"
            lines.append(f"| {_fmt_date(n)} | {link} | {rights.badge(n.rights)} |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("### 출처 및 재이용 조건")
    lines.append("")
    for tier in _tiers_present(report):
        lines.append(f"- **{rights.badge(tier)}** — {rights.label(tier)}")
    lines.append("")
    lines.append(
        "> 본 보고서는 각 기관이 공개한 자료의 제목·링크·발행일 메타데이터를 모은 것입니다. "
        "재이용 시 위 공공누리 등급과 출처 표시 조건을 따르세요."
    )
    return "\n".join(lines) + "\n"


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")


# ── JSON ─────────────────────────────────────────────────────────────────────
def render_json(report: Report) -> str:
    payload = {
        "title": report.title,
        "generated_at": report.generated_at,
        "since_days": report.since_days,
        "count": len(report.notices),
        "new_count": report.new_count,
        "agencies": report.agencies,
        "failed_sources": report.failed_sources,
        "notices": [
            {
                "title": n.title,
                "url": n.url,
                "agency": n.agency,
                "published": n.published.isoformat() if n.published else None,
                "new": n.is_new,
                "summary": n.summary,
                "category": n.category,
                "rights": rights.normalize(n.rights),
                "rights_label": rights.label(n.rights),
            }
            for n in report.notices
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ── HTML (자체 완결형) ────────────────────────────────────────────────────────
_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
  line-height: 1.6; margin: 0; padding: 2rem 1rem; background: #f6f7f9; color: #1a1a2e; }
main { max-width: 900px; margin: 0 auto; background: #fff; border: 1px solid #e5e7eb;
  border-radius: 16px; padding: 2rem; }
h1 { font-size: 1.6rem; margin: 0 0 .5rem; }
.meta { color: #556; font-size: .9rem; margin-bottom: 1.5rem; }
.warn { color: #b00020; }
.stats { display: flex; gap: 1rem; flex-wrap: wrap; margin: 1rem 0 2rem; }
.stat { background: #eef2ff; border-radius: 12px; padding: .6rem 1rem; }
.stat b { display: block; font-size: 1.4rem; }
h2 { font-size: 1.15rem; margin: 1.8rem 0 .6rem; padding-bottom: .3rem;
  border-bottom: 2px solid #191970; }
table { width: 100%; border-collapse: collapse; font-size: .92rem; }
th, td { text-align: left; padding: .5rem .4rem; border-bottom: 1px solid #eef; vertical-align: top; }
th { color: #667; font-weight: 600; }
td.date { white-space: nowrap; color: #556; width: 6.5rem; }
a { color: #191970; text-decoration: none; }
a:hover { text-decoration: underline; }
.badge { display: inline-block; font-size: .72rem; font-weight: 700; white-space: nowrap;
  padding: .1rem .5rem; border-radius: 999px; background: rgba(25,25,112,.1); color: #191970; }
.badge.unknown { background: #eee; color: #667; }
.badge.new { background: #e8f7ee; color: #0b7a3b; }
.stat.new { background: #e8f7ee; }
footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #eef; font-size: .85rem; color: #556; }
footer ul { padding-left: 1.1rem; }
@media (prefers-color-scheme: dark) {
  body { background: #0f1117; color: #e6e8ef; }
  main { background: #171a21; border-color: #262a35; }
  .stat { background: #1e2330; } th, td { border-color: #262a35; }
  a, h2 { color: #9aa8ff; } h2 { border-color: #9aa8ff; }
  .badge { background: rgba(154,168,255,.15); color: #9aa8ff; }
  .badge.new { background: rgba(52,199,123,.15); color: #57d78f; }
  .stat.new { background: rgba(52,199,123,.12); }
}
""".strip()


def render_html(report: Report) -> str:
    def esc(s: str) -> str:
        return html.escape(s, quote=True)

    parts: list[str] = []
    parts.append("<!doctype html>")
    parts.append('<html lang="ko"><head><meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append(f"<title>{esc(report.title)}</title>")
    parts.append(f"<style>{_CSS}</style></head><body><main>")
    parts.append(f"<h1>{esc(report.title)}</h1>")
    meta = f"생성 시각 {esc(report.generated_at or '미상')}"
    if report.since_days is not None:
        meta += f" · 최근 {report.since_days}일"
    parts.append(f'<div class="meta">{meta}</div>')

    parts.append('<div class="stats">')
    parts.append(f'<div class="stat"><b>{len(report.notices)}</b>공지</div>')
    parts.append(f'<div class="stat"><b>{len(report.agencies)}</b>기관</div>')
    if report.new_count:
        parts.append(f'<div class="stat new"><b>{report.new_count}</b>신규</div>')
    if report.failed_sources:
        parts.append(f'<div class="stat warn"><b>{len(report.failed_sources)}</b>수집 실패</div>')
    parts.append("</div>")

    if report.failed_sources:
        parts.append(
            f'<p class="warn">⚠ 수집 실패 출처: {esc(", ".join(report.failed_sources))} '
            "(해외 IP 차단·URL 변경 등 — 나머지 출처로 보고서를 완성했습니다)</p>"
        )

    if not report.notices:
        parts.append("<p>수집된 공지가 없습니다.</p>")
    else:
        for agency, items in report.by_agency().items():
            parts.append(f"<h2>{esc(agency)} <small>({len(items)}건)</small></h2>")
            parts.append(
                "<table><thead><tr><th>발행일</th><th>제목</th><th>등급</th></tr></thead><tbody>"
            )
            for n in items:
                cls = "badge unknown" if rights.normalize(n.rights) == rights.UNKNOWN else "badge"
                new_html = '<span class="badge new">NEW</span> ' if n.is_new else ""
                title_html = (
                    f'<a href="{esc(n.url)}" target="_blank" rel="noopener noreferrer">{esc(n.title)}</a>'
                    if n.url
                    else esc(n.title)
                )
                parts.append(
                    f'<tr><td class="date">{_fmt_date(n)}</td><td>{new_html}{title_html}</td>'
                    f'<td><span class="{cls}" title="{esc(rights.label(n.rights))}">'
                    f"{esc(rights.badge(n.rights))}</span></td></tr>"
                )
            parts.append("</tbody></table>")

    parts.append("<footer><strong>출처 및 재이용 조건</strong><ul>")
    for tier in _tiers_present(report):
        parts.append(f"<li><b>{esc(rights.badge(tier))}</b> — {esc(rights.label(tier))}</li>")
    parts.append("</ul>")
    parts.append(
        "<p>본 보고서는 각 기관이 공개한 자료의 제목·링크·발행일 메타데이터를 모은 것입니다. "
        "재이용 시 위 공공누리 등급과 출처 표시 조건을 따르세요.</p>"
    )
    parts.append(
        '<p>Generated by <a href="https://github.com/corey1-cmd/open_site_clipper">open_site_clipper</a>.</p>'
    )
    parts.append("</footer></main></body></html>")
    return "\n".join(parts) + "\n"


def _tiers_present(report: Report) -> list[str]:
    """보고서에 실제 등장한 등급만(범례가 불필요하게 길어지지 않게)."""
    present = {rights.normalize(n.rights) for n in report.notices}
    order = [
        rights.PUBLIC_DOMAIN,
        rights.KOGL_TYPE1,
        rights.KOGL_TYPE2,
        rights.KOGL_TYPE3,
        rights.KOGL_TYPE4,
        rights.UNKNOWN,
    ]
    return [t for t in order if t in present]


FORMATS = ("markdown", "html", "json")


def render(report: Report, fmt: str) -> str:
    """형식 이름으로 렌더러를 고른다."""
    if fmt == "markdown":
        return render_markdown(report)
    if fmt == "html":
        return render_html(report)
    if fmt == "json":
        return render_json(report)
    raise ValueError(f"unknown format: {fmt!r} (expected one of {FORMATS})")
