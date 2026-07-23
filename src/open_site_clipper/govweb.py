"""정부 표준홈페이지 게시판 파서 — RSS 가 없는 채용·입찰 목록을 읽는다.

부처는 공지·보도자료를 RSS 로 내주지만(정보구독서비스), **채용·입찰은 RSS 가
없는 경우가 많다**(문체부 실측: 목록에 4종뿐, 채용·입찰 제외). 그래서 목록
HTML 을 직접 읽는다.

**K2Web 파서와 다른 점**: K2Web 은 글 링크가 `/bbs/{site}/{board}/{no}/artclView.do`
라는 고정 문법이라 그걸 붙잡았다. 정부 표준홈페이지는 그렇지 않다 — 문체부
채용 게시판을 실제로 열어 보니 상세 링크가 이렇게 제각각이었다:

    https://www.museum.go.kr/MUSEUM/contents/M0701030000.do?...   (국립중앙박물관)
    https://www.karts.ac.kr/nri/bbs/NuriBbsDetail.do?...          (한국예술종합학교)
    https://www.mmca.go.kr/pr/employmentDetail.do?...             (국립현대미술관)
    javascript:void(0);                                            (링크 없음)

소속·공공기관 채용공고를 **각 기관 누리집과 연동**해 보여주기 때문이다. 따라서
링크 문법에 기대면 안 된다. 대신 K2Web 파서의 **다른** 원리 하나만 가져온다:

  **표의 칸 순서** — 번호 → 제목 → 게시일 → 마감일 → 조회.
  즉 "행에서 진짜 링크를 단 가장 긴 텍스트 칸"이 제목이고, 그 뒤 날짜꼴 칸이
  발행일이다. 스킨·CMS 가 달라도 게시판이 표인 한 버틴다.

부수적으로 제목 앞 `[기관명]` 접두를 부서(unit)로 뽑는다 — 연동 게시판에서는
이게 실제 작성 기관이다.
"""

from __future__ import annotations

import re
import urllib.parse

from .k2web_parse import Row, coerce_date, parse_rows

MIN_TITLE_LEN = 4
MAX_UNIT_LEN = 40

# 제목 앞 '[국립중앙박물관] …' 접두 — 연동 게시판에서 실제 작성 기관.
_ORG_PREFIX_RE = re.compile(r"^\[([^\]]{2,40})\]\s*")
# 목록에 섞이는 상태 표시 — 제목의 일부가 아니다.
_BADGE_RE = re.compile(r"^(새글|NEW|신규|공지)\s+", re.I)


def _clean_title(text: str) -> tuple[str, str]:
    """제목에서 '[기관명]' 접두와 '새글' 배지를 떼어 (제목, 기관명)으로."""
    unit = ""
    title = _BADGE_RE.sub("", text.strip())
    m = _ORG_PREFIX_RE.match(title)
    if m:
        unit = m.group(1).strip()[:MAX_UNIT_LEN]
        title = title[m.end() :].strip()
    title = _BADGE_RE.sub("", title)  # '[기관] 새글 제목' 순서도 있다
    return title, unit


def parse_list(html_bytes: bytes, base_url: str) -> list[Row]:
    """게시판 목록 HTML 에서 글 행을 뽑는다(링크 문법에 의존하지 않음)."""
    out: list[Row] = []
    seen: set[str] = set()

    for cells in parse_rows(html_bytes):
        # ① 제목 칸 = 진짜 http(s) 링크를 달고 텍스트가 가장 긴 칸.
        #    (첨부파일 아이콘 링크는 텍스트가 짧아 자연히 밀린다)
        best: int | None = None
        best_url = ""
        for i, (text, href) in enumerate(cells):
            if not href or not text.strip():
                continue
            url = urllib.parse.urljoin(base_url, href)
            if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
                continue  # javascript:void(0) · #none 등 제외
            if best is None or len(text) > len(cells[best][0]):
                best, best_url = i, url
        if best is None:
            continue

        title, unit = _clean_title(cells[best][0])
        if len(title) < MIN_TITLE_LEN:
            continue
        if best_url in seen:
            continue
        seen.add(best_url)

        # ② 발행일 = 제목 칸 **뒤쪽**의 첫 날짜(게시일). 마감일이 그다음에 오므로
        #    앞에서부터 찾아야 게시일을 잡는다.
        published = None
        for text, _ in cells[best + 1 :]:
            published = coerce_date(text)
            if published:
                break

        out.append(Row(title=title, url=best_url, unit=unit, published=published))
    return out
