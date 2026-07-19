"""SVG 차트 — 순수 문자열 조립(의존성 0). 해석 계층의 그래프 렌더.

matplotlib류 없이 <rect>·<polyline>을 직접 조립한다. HTML 보고서에 인라인으로
들어가 파일 하나로 자체 완결되며, 같은 입력이면 같은 SVG가 나온다(좌표는
소수 1자리 고정). Markdown/JSON 형식에서는 같은 데이터를 표로 그린다.
"""

from __future__ import annotations

import html
import math

NAVY = "#191970"
GRID = "#e3e6ef"
INK = "#445"


def _esc(s: str) -> str:
    # report._esc 와 같은 1줄이지만, 저수준 chart 가 고수준 report 를 임포트하는
    # 계층 역전을 피하려고 의도적으로 남긴 유일한 중복이다.
    return html.escape(s, quote=True)


def _nice_max(v: float) -> float:
    """축 최댓값을 1·2·5×10^k 로 올림 — 눈금이 어색하지 않게."""
    if v <= 0:
        return 1.0
    exp = math.floor(math.log10(v))
    for m in (1, 2, 5, 10):
        cand = m * 10**exp
        if v <= cand:
            return float(cand)
    return float(10 ** (exp + 1))


def _empty(width: int, height: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">'
        f'<text x="{width / 2:.1f}" y="{height / 2:.1f}" text-anchor="middle" '
        f'font-size="11" fill="{INK}">데이터 없음</text></svg>'
    )


def bar(
    labels: list[str],
    values: list[int],
    *,
    title: str = "",
    unit: str = "건",
    width: int = 560,
    height: int = 200,
) -> str:
    """세로 막대 — 주별 발행 추이 등. labels/values 길이는 같아야 한다."""
    if not values or len(labels) != len(values):
        return _empty(width, height)
    left, right, top, bottom = 34, 8, 26, 22
    plot_w, plot_h = width - left - right, height - top - bottom
    vmax = _nice_max(max(values))
    slot = plot_w / len(values)
    bar_w = slot * 0.62

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" font-family="sans-serif">'
    ]
    if title:
        parts.append(
            f'<text x="{left}" y="14" font-size="11" font-weight="600" '
            f'fill="{INK}">{_esc(title)}</text>'
        )
    # 눈금(0·중간·최대)과 가로 그리드
    for frac in (0.0, 0.5, 1.0):
        y = top + plot_h * (1 - frac)
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{left - 4}" y="{y + 3.5:.1f}" text-anchor="end" font-size="9" '
            f'fill="{INK}">{vmax * frac:g}</text>'
        )
    for i, (label, v) in enumerate(zip(labels, values, strict=True)):
        x = left + slot * i + (slot - bar_w) / 2
        h = plot_h * (v / vmax)
        y = top + plot_h - h
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" '
            f'rx="2" fill="{NAVY}"/>'
        )
        if v:
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{y - 3:.1f}" text-anchor="middle" '
                f'font-size="9" fill="{INK}">{v}{_esc(unit)}</text>'
            )
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{height - 8}" text-anchor="middle" '
            f'font-size="9" fill="{INK}">{_esc(label)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def hbar(
    labels: list[str],
    values: list[int],
    *,
    title: str = "",
    unit: str = "건",
    width: int = 560,
    row_h: int = 24,
) -> str:
    """가로 막대 — 기관 분포처럼 라벨이 긴 경우."""
    if not values or len(labels) != len(values):
        return _empty(width, 80)
    left, right, top, bottom = 148, 34, 26 if title else 8, 8
    height = top + row_h * len(values) + bottom
    plot_w = width - left - right
    vmax = _nice_max(max(values))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" font-family="sans-serif">'
    ]
    if title:
        parts.append(
            f'<text x="8" y="14" font-size="11" font-weight="600" fill="{INK}">{_esc(title)}</text>'
        )
    for i, (label, v) in enumerate(zip(labels, values, strict=True)):
        y = top + row_h * i
        w = plot_w * (v / vmax)
        shown = label if len(label) <= 12 else label[:11] + "…"
        parts.append(
            f'<text x="{left - 6}" y="{y + row_h / 2 + 3.5:.1f}" text-anchor="end" '
            f'font-size="10" fill="{INK}">{_esc(shown)}</text>'
        )
        parts.append(
            f'<rect x="{left}" y="{y + 4:.1f}" width="{w:.1f}" '
            f'height="{row_h - 8}" rx="2" fill="{NAVY}"/>'
        )
        parts.append(
            f'<text x="{left + w + 4:.1f}" y="{y + row_h / 2 + 3.5:.1f}" '
            f'font-size="9" fill="{INK}">{v}{_esc(unit)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def sparkline(values: list[int], *, width: int = 140, height: int = 30) -> str:
    """요약 박스용 미니 추이선."""
    if not values:
        return _empty(width, height)
    vmax = max(max(values), 1)
    pad = 3
    span = width - pad * 2
    step = span / max(len(values) - 1, 1)
    pts = []
    for i, v in enumerate(values):
        x = pad + step * i
        y = pad + (height - pad * 2) * (1 - v / vmax)
        pts.append(f"{x:.1f},{y:.1f}")
    last_x, last_y = pts[-1].split(",")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">'
        f'<polyline points="{" ".join(pts)}" fill="none" stroke="{NAVY}" '
        f'stroke-width="1.5"/>'
        f'<circle cx="{last_x}" cy="{last_y}" r="2.2" fill="{NAVY}"/></svg>'
    )
