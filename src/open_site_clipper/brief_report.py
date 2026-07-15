"""테마 브리프 렌더러 — brief.Brief 를 MD·HTML·JSON 문서로.

기존 report.py(기관별 공지 보고서)와 형제 관계다. 공지 나열이 목적인 쪽과
달리 여기는 '테마 관련 자료 + 해석(표·그래프)'이 목적이라 레이아웃이 다르다.
공통 원칙은 그대로 승계: 출처·등급 절대 생략 없음, 무LLM, 의존성 0.
"""

from __future__ import annotations

import html
import json

from . import chart, rights
from .brief import Brief, Issue
from .report import _CSS, _fmt_date, _md_escape, _tiers_present

FORMATS = ("markdown", "html", "json")


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def _evidence(issue: Issue, limit: int = 3) -> str:
    return " · ".join(issue.lead.matched[:limit])


# ── Markdown ─────────────────────────────────────────────────────────────────
def render_markdown(brief: Brief) -> str:
    t = brief.theme
    out: list[str] = [f"# {brief.title}", ""]
    if t.description:
        out += [f"> {t.description}", ""]

    meta = f"- 생성 시각: {brief.generated_at or '미상'}"
    if brief.since_days is not None:
        meta += f" · 최근 {brief.since_days}일"
    out.append(meta)
    counts = (
        f"- 관련 자료 {len(brief.notices)}건 · 사안 {brief.issue_count}건 · "
        f"기관 {len(brief.agencies)}곳 (검토 {brief.considered}건 중)"
    )
    if brief.new_count:
        counts += f" · 🆕 신규 {brief.new_count}건"
    out.append(counts)
    if brief.top_keywords:
        out.append("- 핵심 키워드: " + " · ".join(brief.top_keywords))
    if brief.failed_sources:
        out.append(f"- ⚠ 수집 실패 출처: {', '.join(brief.failed_sources)}")
    out.append("")

    if not brief.sections:
        out += [
            f"_'{t.name}' 테마에 관련된 자료가 없습니다 "
            f"(관련성 하한 {brief.min_score}점, 검토 {brief.considered}건)._",
            "",
        ]
    for sec in brief.sections:
        out += [f"## [{sec.name}] ({len(sec.issues)}건)", ""]
        for issue in sec.issues:
            n = issue.lead.notice
            title = _md_escape(n.title)
            link = f"[{title}]({n.url})" if n.url else title
            flag = "🆕 " if issue.is_new else ""
            out.append(f"### {flag}{link}")
            out.append(
                f"- {n.agency} · {_fmt_date(n)} · {rights.badge(n.rights)} · "
                f"관련성 {issue.lead.score}점 (근거: {_evidence(issue)})"
            )
            if n.summary:
                out.append(f"- {_md_escape(n.summary)}")
            if issue.related:
                out.append(f"- 같은 사안 {len(issue.related)}건:")
                for r in issue.related:
                    rn = r.notice
                    rt = _md_escape(rn.title)
                    rl = f"[{rt}]({rn.url})" if rn.url else rt
                    out.append(f"  - {rl} — {rn.agency} · {_fmt_date(rn)}")
            out.append("")

    out.append(_insight_markdown(brief))
    if t.glossary:
        out += ["## 용어", ""]
        out += [f"- **{k}** — {v}" for k, v in t.glossary.items()]
        out.append("")

    out += ["---", "", "### 출처 및 재이용 조건", ""]
    out += [f"- **{rights.badge(x)}** — {rights.label(x)}" for x in _tiers_present(brief.notices)]
    out += [
        "",
        "> 각 기관이 공개한 자료의 제목·링크·발행일 메타데이터를 테마 기준으로 "
        "선별한 것입니다. 관련성 판정은 키워드 규칙 기반이며, 채택 근거를 항목마다 "
        "표기했습니다. 재이용 시 위 공공누리 등급과 출처 표시 조건을 따르세요.",
    ]
    return "\n".join(out) + "\n"


def _insight_markdown(brief: Brief) -> str:
    ins = brief.insight
    if not ins or ins.is_empty():
        return ""
    out: list[str] = ["## 해석", ""]
    if ins.trend:
        out += [f"- {ins.trend}", ""]
    if ins.weekly:
        out += ["**주별 발행 추이**", "", "| 주 | 건수 |", "|---|---|"]
        out += [f"| {w} | {c} |" for w, c in ins.weekly]
        out.append("")
    if ins.agencies:
        out += ["**기관별 활동**", "", "| 기관 | 건수 | 최근 발행 |", "|---|---|---|"]
        out += [f"| {a} | {c} | {d or '-'} |" for a, c, d in ins.agencies]
        out.append("")
    if ins.issues:
        out += ["**주요 사안(다기관 보도)**", "", "| 사안 | 자료 수 | 기관 수 |", "|---|---|---|"]
        out += [f"| {_md_escape(t)} | {n} | {a} |" for t, n, a in ins.issues]
        out.append("")
    if ins.timeline:
        out += ["**최대 사안 타임라인**", "", "| 일자 | 자료 | 기관 |", "|---|---|---|"]
        out += [f"| {d} | {_md_escape(t)} | {a} |" for d, t, a in ins.timeline]
        out.append("")
    if ins.new_keywords:
        out += ["- 이번에 새로 등장한 키워드: " + " · ".join(ins.new_keywords), ""]
    return "\n".join(out)


# ── HTML ─────────────────────────────────────────────────────────────────────
_BRIEF_CSS = """
.theme-box { background: #eef2ff; border-left: 4px solid #191970; border-radius: 8px;
  padding: .9rem 1.1rem; margin: 0 0 1.5rem; }
.theme-box .lead { font-weight: 600; margin: 0 0 .3rem; }
.theme-box .kw { font-size: .85rem; color: #445; }
.layout { display: grid; grid-template-columns: 1fr 210px; gap: 1.6rem; align-items: start; }
aside .card { background: #f8f9fc; border: 1px solid #eef; border-radius: 10px;
  padding: .7rem .9rem; margin-bottom: 1rem; font-size: .82rem; }
aside h3 { font-size: .8rem; margin: 0 0 .4rem; color: #667; text-transform: uppercase;
  letter-spacing: .04em; }
aside dt { font-weight: 700; color: #191970; margin-top: .5rem; }
aside dd { margin: 0; color: #445; }
.issue { border-bottom: 1px solid #eef; padding: .9rem 0; }
.issue:last-child { border-bottom: none; }
.issue h3 { font-size: 1rem; margin: 0 0 .3rem; }
.issue .line { font-size: .82rem; color: #667; margin-bottom: .35rem; }
.issue p { margin: .3rem 0; font-size: .9rem; }
.issue .related { margin: .4rem 0 0; padding-left: 1rem; font-size: .84rem; color: #556; }
.evidence { background: rgba(25,25,112,.06); border-radius: 999px; padding: .05rem .5rem;
  font-size: .74rem; color: #191970; }
.chart { margin: .6rem 0 1.2rem; overflow-x: auto; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1.2rem; }
@media print { body { background: #fff; padding: 0; } main { border: none; border-radius: 0; }
  .layout { grid-template-columns: 1fr 180px; } a { color: #000; } }
@media (max-width: 720px) { .layout, .grid2 { grid-template-columns: 1fr; } }
@media (prefers-color-scheme: dark) {
  .theme-box { background: rgba(154,168,255,.1); border-left-color: #9aa8ff; }
  .theme-box .kw, .issue .line, aside dd { color: #9aa5b4; }
  aside .card { background: #12151c; border-color: #262a35; }
  aside dt { color: #9aa8ff; }
  .evidence { background: rgba(154,168,255,.15); color: #9aa8ff; }
}
"""


def render_html(brief: Brief) -> str:
    t = brief.theme
    p: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="ko"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_esc(brief.title)}</title>",
        f"<style>{_CSS}{_BRIEF_CSS}</style></head><body><main>",
        f"<h1>{_esc(brief.title)}</h1>",
    ]
    meta = f"생성 시각: {_esc(brief.generated_at or '미상')}"
    if brief.since_days is not None:
        meta += f" · 최근 {brief.since_days}일"
    p.append(f'<p class="meta">{meta}</p>')

    p.append('<div class="theme-box">')
    if t.description:
        p.append(f'<p class="lead">{_esc(t.description)}</p>')
    p.append(
        f'<p class="kw">관련 자료 <b>{len(brief.notices)}</b>건 · 사안 '
        f"<b>{brief.issue_count}</b>건 · 기관 <b>{len(brief.agencies)}</b>곳 "
        f"(검토 {brief.considered}건 중 관련성 {brief.min_score}점 이상)</p>"
    )
    if brief.top_keywords:
        chips = "".join(f'<span class="evidence">{_esc(k)}</span> ' for k in brief.top_keywords)
        p.append(f'<p class="kw">핵심 키워드: {chips}</p>')
    if brief.insight and brief.insight.weekly:
        p.append(
            '<div class="chart">' + chart.sparkline([c for _, c in brief.insight.weekly]) + "</div>"
        )
    p.append("</div>")

    if brief.failed_sources:
        p.append(f'<p class="warn">⚠ 수집 실패 출처: {_esc(", ".join(brief.failed_sources))}</p>')

    p.append('<div class="layout"><div>')
    if not brief.sections:
        p.append(
            f"<p>'{_esc(t.name)}' 테마에 관련된 자료가 없습니다"
            f"(하한 {brief.min_score}점, 검토 {brief.considered}건).</p>"
        )
    for sec in brief.sections:
        p.append(f"<h2>[{_esc(sec.name)}] <small>({len(sec.issues)}건)</small></h2>")
        for issue in sec.issues:
            p.append(_issue_html(issue))
    p.append(_insight_html(brief))
    p.append("</div>")

    p.append("<aside>")
    if brief.agencies:
        p.append('<div class="card"><h3>관련 기관</h3>')
        p.append("<div>" + _esc(" · ".join(brief.agencies)) + "</div></div>")
    if t.glossary:
        p.append('<div class="card"><h3>용어</h3><dl>')
        for k, v in t.glossary.items():
            p.append(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>")
        p.append("</dl></div>")
    p.append("</aside></div>")

    p.append("<footer><strong>출처 및 재이용 조건</strong><ul>")
    p += [
        f"<li><b>{_esc(rights.badge(x))}</b> — {_esc(rights.label(x))}</li>"
        for x in _tiers_present(brief.notices)
    ]
    p.append("</ul>")
    p.append(
        "<p>각 기관이 공개한 자료를 테마 기준으로 선별했습니다. 관련성 판정은 "
        "키워드 규칙 기반이며 채택 근거를 항목마다 표기했습니다. 재이용 시 위 "
        "공공누리 등급과 출처 표시 조건을 따르세요.</p></footer>"
    )
    p.append("</main></body></html>")
    return "\n".join(p)


def _issue_html(issue: Issue) -> str:
    n = issue.lead.notice
    cls = "badge unknown" if rights.normalize(n.rights) == rights.UNKNOWN else "badge"
    title = (
        f'<a href="{_esc(n.url)}" target="_blank" rel="noopener noreferrer">{_esc(n.title)}</a>'
        if n.url
        else _esc(n.title)
    )
    new = '<span class="badge new">NEW</span> ' if issue.is_new else ""
    out = [
        '<article class="issue">',
        f"<h3>{new}{title}</h3>",
        f'<p class="line">{_esc(n.agency)} · {_fmt_date(n)} · '
        f'<span class="{cls}" title="{_esc(rights.label(n.rights))}">'
        f"{_esc(rights.badge(n.rights))}</span> · 관련성 {issue.lead.score}점 · "
        f'<span class="evidence">{_esc(_evidence(issue))}</span></p>',
    ]
    if n.summary:
        out.append(f"<p>{_esc(n.summary)}</p>")
    if issue.related:
        out.append(f'<ul class="related"><li>같은 사안 {len(issue.related)}건</li>')
        for r in issue.related:
            rn = r.notice
            rl = (
                f'<a href="{_esc(rn.url)}" target="_blank" rel="noopener noreferrer">'
                f"{_esc(rn.title)}</a>"
                if rn.url
                else _esc(rn.title)
            )
            out.append(f"<li>{rl} — {_esc(rn.agency)} · {_fmt_date(rn)}</li>")
        out.append("</ul>")
    out.append("</article>")
    return "\n".join(out)


def _insight_html(brief: Brief) -> str:
    ins = brief.insight
    if not ins or ins.is_empty():
        return ""
    p = ["<h2>해석</h2>"]
    if ins.trend:
        p.append(f"<p>{_esc(ins.trend)}</p>")
    if ins.weekly:
        p.append(
            '<div class="chart">'
            + chart.bar(
                [w for w, _ in ins.weekly],
                [c for _, c in ins.weekly],
                title="주별 발행 추이",
            )
            + "</div>"
        )
    if ins.agencies:
        p.append(
            '<div class="chart">'
            + chart.hbar(
                [a for a, _, _ in ins.agencies],
                [c for _, c, _ in ins.agencies],
                title="기관별 활동",
            )
            + "</div>"
        )
        p.append(
            "<table><thead><tr><th>기관</th><th>건수</th><th>최근 발행</th></tr></thead><tbody>"
        )
        p += [
            f"<tr><td>{_esc(a)}</td><td>{c}</td><td>{_esc(d or '-')}</td></tr>"
            for a, c, d in ins.agencies
        ]
        p.append("</tbody></table>")
    if ins.issues:
        p.append(
            "<h2>주요 사안</h2><table><thead><tr><th>사안</th><th>자료 수</th>"
            "<th>기관 수</th></tr></thead><tbody>"
        )
        p += [f"<tr><td>{_esc(t)}</td><td>{n}</td><td>{a}</td></tr>" for t, n, a in ins.issues]
        p.append("</tbody></table>")
    if ins.timeline:
        p.append(
            "<h2>최대 사안 타임라인</h2><table><thead><tr><th>일자</th><th>자료</th>"
            "<th>기관</th></tr></thead><tbody>"
        )
        p += [
            f'<tr><td class="date">{_esc(d)}</td><td>{_esc(t)}</td><td>{_esc(a)}</td></tr>'
            for d, t, a in ins.timeline
        ]
        p.append("</tbody></table>")
    if ins.new_keywords:
        chips = "".join(f'<span class="evidence">{_esc(k)}</span> ' for k in ins.new_keywords)
        p.append(f"<p>이번에 새로 등장한 키워드: {chips}</p>")
    return "\n".join(p)


# ── JSON ─────────────────────────────────────────────────────────────────────
def render_json(brief: Brief) -> str:
    ins = brief.insight
    payload = {
        "title": brief.title,
        "theme": brief.theme.name,
        "description": brief.theme.description,
        "generated_at": brief.generated_at,
        "since_days": brief.since_days,
        "considered": brief.considered,
        "min_score": brief.min_score,
        "count": len(brief.notices),
        "issue_count": brief.issue_count,
        "new_count": brief.new_count,
        "agencies": brief.agencies,
        "top_keywords": brief.top_keywords,
        "failed_sources": brief.failed_sources,
        "sections": [
            {
                "name": sec.name,
                "issues": [
                    {
                        "lead": _match_json(i.lead),
                        "related": [_match_json(r) for r in i.related],
                        "agencies": i.agencies,
                        "size": i.size,
                    }
                    for i in sec.issues
                ],
            }
            for sec in brief.sections
        ],
        "insight": (
            {
                "weekly": [list(x) for x in ins.weekly],
                "trend": ins.trend,
                "agencies": [list(x) for x in ins.agencies],
                "issues": [list(x) for x in ins.issues],
                "timeline": [list(x) for x in ins.timeline],
                "new_keywords": list(ins.new_keywords),
            }
            if ins and not ins.is_empty()
            else None
        ),
        "glossary": brief.theme.glossary,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _match_json(m) -> dict[str, object]:
    n = m.notice
    return {
        "title": n.title,
        "url": n.url,
        "agency": n.agency,
        "published": n.published.isoformat() if n.published else None,
        "summary": n.summary,
        "rights": rights.normalize(n.rights),
        "new": n.is_new,
        "score": m.score,
        "matched": list(m.matched),
    }


def render(brief: Brief, fmt: str) -> str:
    if fmt not in FORMATS:
        raise ValueError(f"지원하지 않는 형식: {fmt} (가능: {', '.join(FORMATS)})")
    return {
        "markdown": render_markdown,
        "html": render_html,
        "json": render_json,
    }[fmt](brief)
