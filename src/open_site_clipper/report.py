"""보고서 렌더러 — 수집한 공지를 하나의 문서로.

세 가지 형식을 제공한다:
  - markdown : 문서·이슈에 붙이기 좋은 표 형식(기관별 그룹)
  - html     : 자체 완결형(인라인 CSS) 보고서 — 그대로 열람·인쇄 가능
  - json     : 기계 판독용(다른 파이프라인 연동)
  - template : 사용자 템플릿($marker 치환) — 조직 서식 그대로 출력

모든 형식은 출처(기관·발행일·원문 링크)와 공공누리(KOGL) 등급을 절대 생략하지
않는다 — 개방 자료의 재이용 조건을 독자가 바로 알 수 있게 하는 것이 이 도구의
핵심 가치다.
"""

from __future__ import annotations

import html
import json
import string

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

    dg = _digest_markdown(report)
    if dg:
        lines.append(dg)
        lines.append("")

    if not report.notices:
        lines.append(_body_markdown(report))
        return "\n".join(lines) + "\n"

    lines.append(_body_markdown(report))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(_legend_markdown(report))
    lines.append("")
    lines.append(
        "> 본 보고서는 각 기관이 공개한 자료의 제목·링크·발행일 메타데이터를 모은 것입니다. "
        "재이용 시 위 공공누리 등급과 출처 표시 조건을 따르세요."
    )
    return "\n".join(lines) + "\n"


def _digest_markdown(report: Report) -> str:
    """기간 요약 마크다운 조각(없으면 "") — render_markdown과 $digest_md가 공유."""
    if not (report.digest and not report.digest.is_empty()):
        return ""
    d = report.digest
    lines = ["## 기간 요약", ""]
    if d.agencies:
        lines.append("- 기관: " + " · ".join(f"{a} {c}건" for a, c in d.agencies))
    if d.categories:
        lines.append("- 분류: " + " · ".join(f"{a} {c}건" for a, c in d.categories))
    if d.keywords:
        lines.append("- 키워드: " + " · ".join(f"{w}({c})" for w, c in d.keywords))
    return "\n".join(lines)


def _body_markdown(report: Report) -> str:
    """기관별 공지 표 조각 — render_markdown과 $body_md가 공유."""
    if not report.notices:
        return "_수집된 공지가 없습니다._"
    sections: list[str] = []
    for agency, items in report.by_agency().items():
        seg = [f"## {agency} ({len(items)}건)", "", "| 발행일 | 제목 | 등급 |", "|---|---|---|"]
        for n in items:
            title = _md_escape(n.title)
            link = f"[{title}]({n.url})" if n.url else title
            if n.is_new:
                link = f"🆕 {link}"
            seg.append(f"| {_fmt_date(n)} | {link} | {rights.badge(n.rights)} |")
        sections.append("\n".join(seg))
    return "\n\n".join(sections)


def _legend_markdown(report: Report) -> str:
    """재이용 조건 범례 조각(등장 등급만) — render_markdown과 $legend_md가 공유."""
    lines = ["### 출처 및 재이용 조건", ""]
    lines.extend(f"- **{rights.badge(t)}** — {rights.label(t)}" for t in _tiers_present(report))
    return "\n".join(lines)


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
        "digest": (
            {
                "agencies": [list(x) for x in report.digest.agencies],
                "categories": [list(x) for x in report.digest.categories],
                "keywords": [list(x) for x in report.digest.keywords],
            }
            if report.digest and not report.digest.is_empty()
            else None
        ),
        "notices": [
            {
                "title": n.title,
                "url": n.url,
                "agency": n.agency,
                "published": n.published.isoformat() if n.published else None,
                "new": n.is_new,
                "topics": list(n.topics),
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
.digest { background: #f8f9fc; border: 1px solid #eef; border-radius: 12px;
  padding: .2rem 1rem .8rem; margin: 0 0 1.5rem; }
.digest h2 { border: none; margin: .8rem 0 .4rem; font-size: 1rem; }
.digest dl { display: grid; grid-template-columns: 4rem 1fr; gap: .3rem .6rem; margin: 0; font-size: .9rem; }
.digest dt { color: #667; font-weight: 600; }
.digest dd { margin: 0; }
.chip { display: inline-block; background: rgba(25,25,112,.07); border-radius: 999px;
  padding: .05rem .55rem; margin: 0 .25rem .25rem 0; }
.chip b { color: #191970; }
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
  .digest { background: #12151c; border-color: #262a35; }
  .chip { background: rgba(154,168,255,.12); } .chip b { color: #9aa8ff; }
}
""".strip()


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def render_html(report: Report) -> str:
    esc = _esc
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

    dg = _digest_html(report)
    if dg:
        parts.append(dg)

    parts.append(_body_html(report))

    parts.append("<footer>" + _legend_html(report))
    parts.append(
        "<p>본 보고서는 각 기관이 공개한 자료의 제목·링크·발행일 메타데이터를 모은 것입니다. "
        "재이용 시 위 공공누리 등급과 출처 표시 조건을 따르세요.</p>"
    )
    parts.append(
        '<p>Generated by <a href="https://github.com/corey1-cmd/open_site_clipper">open_site_clipper</a>.</p>'
    )
    parts.append("</footer></main></body></html>")
    return "\n".join(parts) + "\n"


def _digest_html(report: Report) -> str:
    """기간 요약 HTML 조각(없으면 "") — render_html과 $digest_html이 공유."""
    if not (report.digest and not report.digest.is_empty()):
        return ""
    d = report.digest
    parts = ['<section class="digest"><h2>기간 요약</h2><dl>']
    if d.agencies:
        v = " · ".join(f"{_esc(a)} {c}건" for a, c in d.agencies)
        parts.append(f"<dt>기관</dt><dd>{v}</dd>")
    if d.categories:
        v = " · ".join(f"{_esc(a)} {c}건" for a, c in d.categories)
        parts.append(f"<dt>분류</dt><dd>{v}</dd>")
    if d.keywords:
        chips = "".join(f'<span class="chip">{_esc(w)} <b>{c}</b></span>' for w, c in d.keywords)
        parts.append(f"<dt>키워드</dt><dd>{chips}</dd>")
    parts.append("</dl></section>")
    return "\n".join(parts)


def _body_html(report: Report) -> str:
    """기관별 공지 표 HTML 조각 — render_html과 $body_html이 공유."""
    if not report.notices:
        return "<p>수집된 공지가 없습니다.</p>"
    parts: list[str] = []
    for agency, items in report.by_agency().items():
        parts.append(f"<h2>{_esc(agency)} <small>({len(items)}건)</small></h2>")
        parts.append(
            "<table><thead><tr><th>발행일</th><th>제목</th><th>등급</th></tr></thead><tbody>"
        )
        for n in items:
            cls = "badge unknown" if rights.normalize(n.rights) == rights.UNKNOWN else "badge"
            new_html = '<span class="badge new">NEW</span> ' if n.is_new else ""
            title_html = (
                f'<a href="{_esc(n.url)}" target="_blank" rel="noopener noreferrer">{_esc(n.title)}</a>'
                if n.url
                else _esc(n.title)
            )
            parts.append(
                f'<tr><td class="date">{_fmt_date(n)}</td><td>{new_html}{title_html}</td>'
                f'<td><span class="{cls}" title="{_esc(rights.label(n.rights))}">'
                f"{_esc(rights.badge(n.rights))}</span></td></tr>"
            )
        parts.append("</tbody></table>")
    return "\n".join(parts)


def _legend_html(report: Report) -> str:
    """재이용 조건 범례 HTML 조각 — render_html과 $legend_html이 공유."""
    parts = ["<strong>출처 및 재이용 조건</strong><ul>"]
    parts.extend(
        f"<li><b>{_esc(rights.badge(t))}</b> — {_esc(rights.label(t))}</li>"
        for t in _tiers_present(report)
    )
    parts.append("</ul>")
    return "\n".join(parts)


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


# ── 사용자 템플릿 (--template) ────────────────────────────────────────────────
TEMPLATE_MARKERS = (
    "title",
    "generated_at",
    "count",
    "agency_count",
    "new_count",
    "agencies",
    "since_days",
    "failed_sources",
    "body_md",
    "digest_md",
    "legend_md",
    "body_html",
    "digest_html",
    "legend_html",
)


def render_template(report: Report, template_text: str) -> str:
    """사용자 템플릿에 $마커를 치환한다 — 조직 서식(회람·공문 틀)을 그대로 살린다.

    carbone의 {d.field} 마커 발상을 표준 라이브러리 string.Template로 경량화했다.
    safe_substitute라 미지 마커($없는말)는 원문 그대로 남고, '$$'는 '$'가 된다.
    쓸 수 있는 마커는 TEMPLATE_MARKERS 참고(md·html 본문 조각을 함께 제공).
    """
    mapping = {
        "title": report.title,
        "generated_at": report.generated_at or "미상",
        "count": str(len(report.notices)),
        "agency_count": str(len(report.agencies)),
        "new_count": str(report.new_count),
        "agencies": ", ".join(report.agencies),
        "since_days": "" if report.since_days is None else str(report.since_days),
        "failed_sources": ", ".join(report.failed_sources),
        "body_md": _body_markdown(report),
        "digest_md": _digest_markdown(report),
        "legend_md": _legend_markdown(report),
        "body_html": _body_html(report),
        "digest_html": _digest_html(report),
        "legend_html": _legend_html(report),
    }
    return string.Template(template_text).safe_substitute(mapping)


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
