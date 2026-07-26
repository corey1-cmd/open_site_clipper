"""피드 파싱 — RSS/Atom XML과 data.go.kr OpenAPI(JSON)를 Notice로 변환한다.

표준 라이브러리만 쓴다(xml.etree, html, json). 기관마다 골격이 조금씩 달라도
견디도록 관대하게 파싱하고, 파싱 불가한 항목은 조용히 건너뛴다(한 항목의
오류가 전체 수집을 막지 않는다).
"""

from __future__ import annotations

import html
import json
import re
from datetime import date, datetime
from xml.etree import ElementTree as ET

from .model import Notice

# Atom 네임스페이스(RSS 2.0은 네임스페이스 없음).
_ATOM = "{http://www.w3.org/2005/Atom}"
_DC = "{http://purl.org/dc/elements/1.1/}"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str | None, *, max_len: int = 280) -> str:
    """HTML 태그·엔티티 제거 + 공백 접기 + 길이 제한(요약 발췌용)."""
    if not raw:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", raw))
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


# ── 날짜 파싱 ────────────────────────────────────────────────────────────────
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        start=1,
    )
}


def parse_date(raw: str | None) -> date | None:
    """다양한 발행일 표기를 date로 — 실패 시 None(fail-soft).

    지원: RFC 822(RSS pubDate, 'Wed, 02 Oct 2024 13:00:00 +0900'),
    ISO 8601('2024-10-02T13:00:00Z' / '2024-10-02'), 'YYYY.MM.DD', 'YYYYMMDD'.
    """
    if not raw:
        return None
    s = raw.strip()
    # ISO 8601 (T 또는 공백 구분, 시간·타임존 무시)
    m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # YYYYMMDD
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # RFC 822: 'Wed, 02 Oct 2024 ...'
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", s)
    if m and m.group(2) in _MONTHS:
        return _safe_date(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
    # 한글·두 자리 연도 등 비표준 표기 — 게시판 파서와 같은 규칙을 재사용한다.
    from .k2web_parse import coerce_date

    found = coerce_date(s)
    if found is not None:
        return found
    # 마지막 시도: datetime.fromisoformat (Z 정규화)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


# ── RSS / Atom ───────────────────────────────────────────────────────────────
_DOCTYPE_RE = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


def parse_rss(
    xml_bytes: bytes | str, *, agency: str, rights: str, category: str = ""
) -> list[Notice]:
    """RSS 2.0(<item>)과 Atom(<entry>)을 모두 처리해 Notice 목록을 만든다.

    보안: 표준 라이브러리 ElementTree만 쓰되(의존성 0), 내부 엔티티 확장을
    악용하는 XML 폭탄(billion laughs)을 원천 차단하려고 DOCTYPE/ENTITY 선언이
    포함된 입력은 파싱 전에 거부한다. 정상 RSS/Atom에는 이들이 없다.
    """
    if isinstance(xml_bytes, bytes):
        text = xml_bytes.decode("utf-8", errors="replace")
    else:
        text = xml_bytes
    if _DOCTYPE_RE.search(text):
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    notices: list[Notice] = []
    # RSS: .//item, Atom: .//{ns}entry — 둘 다 시도한다.
    items = root.findall(".//item") or root.findall(f".//{_ATOM}entry")
    for it in items:
        title = clean_text(_first_text(it, ["title", f"{_ATOM}title"]), max_len=200)
        link = _rss_link(it)
        if not title or not link:
            continue
        pub = _first_text(
            it,
            [
                "pubDate",
                "date",
                f"{_DC}date",  # dc:date — 국내 기관 피드에 흔하다
                f"{_DC}issued",
                f"{_ATOM}updated",
                f"{_ATOM}published",
                "created",
                "regDate",
            ],
        )
        summary = clean_text(_first_text(it, ["description", "summary", f"{_ATOM}summary"]))
        notices.append(
            Notice(
                title=title,
                url=link,
                agency=agency,
                published=parse_date(pub),
                summary=summary,
                category=category,
                rights=rights,
            )
        )
    return notices


def _first_text(elem: ET.Element, tags: list[str]) -> str:
    for tag in tags:
        child = elem.find(tag)
        if child is not None and (child.text or "").strip():
            return child.text or ""
    return ""


def _rss_link(item: ET.Element) -> str:
    """RSS <link>텍스트 또는 Atom <link href=...>에서 URL을 뽑는다."""
    link = item.find("link")
    if link is not None and (link.text or "").strip():
        return link.text.strip()
    # Atom: <link rel="alternate" href="...">, 없으면 첫 link의 href
    atom_links = item.findall(f"{_ATOM}link")
    best = ""
    for ln in atom_links:
        href = (ln.get("href") or "").strip()
        if not href:
            continue
        if ln.get("rel", "alternate") == "alternate":
            return href
        best = best or href
    return best


# ── data.go.kr OpenAPI (JSON) ────────────────────────────────────────────────
def parse_datago(
    json_text: bytes | str, *, agency: str, rights: str, category: str = ""
) -> list[Notice]:
    """공공데이터포털 표준(response.body.items.item[])·odcloud(data[]) 응답을
    모두 처리한다. 필드명은 기관마다 다르므로 후보 목록으로 관대하게 찾는다."""
    if isinstance(json_text, bytes):
        json_text = json_text.decode("utf-8", errors="replace")
    try:
        payload = json.loads(json_text)
    except (json.JSONDecodeError, ValueError):
        return []
    rows = _datago_items(payload)
    notices: list[Notice] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = clean_text(_first_field(row, ("title", "nttSj", "bbsNm", "sj")), max_len=200)
        link = _first_field(row, ("url", "link", "detailUrl", "nttUrl")).strip()
        if not title:
            continue
        pub = _first_field(row, ("regDate", "date", "pubDate", "frstRegistDt", "creationDate"))
        summary = clean_text(_first_field(row, ("summary", "cn", "content", "nttCn")))
        notices.append(
            Notice(
                title=title,
                url=link,
                agency=agency,
                published=parse_date(pub),
                summary=summary,
                category=category,
                rights=rights,
            )
        )
    return notices


def _datago_items(payload: object) -> list[object]:
    """표준·odcloud 골격에서 항목 리스트를 찾는다(dict/list 혼용 방어)."""
    if isinstance(payload, dict):
        # 표준: response.body.items.item
        body = payload.get("response")
        if isinstance(body, dict):
            items = _dig(body, ["body", "items", "item"])
            if isinstance(items, list):
                return items
            if isinstance(items, dict):  # 단일 항목이 dict로 오는 경우
                return [items]
        # odcloud: data[]
        data = payload.get("data")
        if isinstance(data, list):
            return data
    if isinstance(payload, list):
        return payload
    return []


def _dig(d: object, path: list[str]) -> object:
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _first_field(row: dict[str, object], keys: tuple[str, ...]) -> str:
    for k in keys:
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v)
    return ""
