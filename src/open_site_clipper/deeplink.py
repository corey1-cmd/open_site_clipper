"""딥링크 — 공지 본문 페이지에서 '관련 자료' 링크만 캐낸다.

브리핑에서 정작 필요한 건 원문 링크 옆의 **첨부·관련 자료**(보도자료 PDF,
설명자료 HWP, 통계 파일)인 경우가 많다. 여기서는 링크(라벨·URL·종류)만
수집하고 **본문 텍스트는 가져오지 않는다** — 원문 복제를 하지 않는다는 이
도구의 원칙과, 등급별 보수적 인용 정책(rights)을 그대로 지킨다.

기관 사이트 구조에 의존하므로 기본은 꺼짐(--deep-links로 켬). 표준 라이브러리
HTMLParser만 쓰고(의존성 0), 링크 수·요청 수에 상한을 둔다. 파일 확장자와
앵커 문구로 첨부/관련 링크를 판별하며, 판별 규칙은 아래 상수에 모아 뒀다.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser

# 첨부로 판정하는 확장자 → 표시 종류.
_EXT_KIND = {
    ".pdf": "PDF",
    ".hwp": "HWP",
    ".hwpx": "HWP",
    ".doc": "DOC",
    ".docx": "DOC",
    ".xls": "XLS",
    ".xlsx": "XLS",
    ".ppt": "PPT",
    ".pptx": "PPT",
    ".zip": "ZIP",
    ".csv": "CSV",
}
# 앵커 텍스트/URL에 이 말이 있으면 관련 자료로 본다(확장자가 없어도).
_LINK_HINTS = (
    "첨부",
    "붙임",
    "다운로드",
    "download",
    "관련자료",
    "관련 자료",
    "fileDown",
    "file_down",
)
# 무의미한 라벨(내비게이션 잡음) — 이런 앵커는 버린다.
_NOISE_LABELS = frozenset(
    {"", "바로가기", "more", "더보기", "목록", "이전", "다음", "인쇄", "공유"}
)

MAX_LINKS_PER_NOTICE = 5  # 한 공지에서 취할 링크 상한(보고서 비대화 방지)
MAX_LABEL = 60


@dataclass(frozen=True, slots=True)
class Link:
    """공지에 딸린 관련 자료 하나."""

    label: str
    url: str
    kind: str  # "PDF" | "HWP" | ... | "링크"


class _AnchorParser(HTMLParser):
    """<a href>와 그 안의 텍스트만 뽑는 최소 파서."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []  # (href, text)
        self._href: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        if href.strip():
            self._href = href.strip()
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.anchors.append((self._href, " ".join("".join(self._buf).split())))
            self._href, self._buf = None, []


def _classify(href: str, label: str) -> str | None:
    """관련 자료면 종류를, 아니면 None."""
    path = urllib.parse.urlsplit(href).path.lower()
    for ext, kind in _EXT_KIND.items():
        if path.endswith(ext):
            return kind
    haystack = f"{href} {label}".lower()
    if any(h.lower() in haystack for h in _LINK_HINTS):
        return "링크"
    return None


def extract(html_bytes: bytes, base_url: str, *, limit: int = MAX_LINKS_PER_NOTICE) -> list[Link]:
    """본문 HTML에서 관련 자료 링크만 뽑는다(본문 텍스트는 취하지 않는다).

    - 상대 경로는 base_url 기준 절대 URL로.
    - http(s)만 허용(javascript:·file: 등 차단 — fetch와 같은 방침).
    - 같은 URL 중복 제거, 라벨 없으면 파일명으로 대체, limit개까지.
    """
    try:
        text = html_bytes.decode("utf-8", errors="replace")
    except (UnicodeDecodeError, AttributeError):
        return []
    parser = _AnchorParser()
    try:
        parser.feed(text)
    except Exception:
        return []

    out: list[Link] = []
    seen: set[str] = set()
    for href, label in parser.anchors:
        if href.startswith("#") or href.lower().startswith(("javascript:", "mailto:")):
            continue
        url = urllib.parse.urljoin(base_url, href)
        if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            continue
        if url in seen:
            continue
        clean = re.sub(r"\s+", " ", label).strip()[:MAX_LABEL]
        if clean.lower() in _NOISE_LABELS:
            clean = ""
        kind = _classify(url, clean)
        if not kind:
            continue
        if not clean:
            name = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
            clean = name[:MAX_LABEL] or "첨부"
        seen.add(url)
        out.append(Link(label=clean, url=url, kind=kind))
        if len(out) >= limit:
            break
    return out
