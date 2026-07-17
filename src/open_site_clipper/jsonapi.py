"""범용 JSON 목록 파서 — 게시판형 JSON API 응답에서 공지 행을 뽑는다.

사이트마다 응답 골격이 제각각이라, 특정 API에 코드를 붙이는 대신
**설정(점 표기 경로)** 으로 위치를 가리키게 했다. 어떤 JSON이든 아래 경로만
알려 주면 된다:

    "api_url": "https://www.hufs.ac.kr/.../boardApi.do?bbsId=2180",
    "api_paths": {
      "items": "data.list",     # 항목 배열 위치 (필수)
      "title": "artclNm",       # 항목 안 제목 (필수)
      "url":   "artclUrl",      # 항목 안 링크 — 상대경로면 base_url 기준 절대화
      "article_no": "artclNo",  # url 이 없을 때: 글번호로 K2Web 정식 주소 조립
      "date": "regDt",          # 선택 — 2026.07.02 / 2026-07-02 등 인식
      "unit": "deptNm"          # 선택 — 작성 부서
    }

파싱 실패·경로 불일치·항목 0건은 전부 빈 목록으로 조용히 끝난다(fail-open) —
캐스케이드가 다음 수단으로 넘어가면 되기 때문이다. 필수 경로가 아예 빠진
설정 오류는 호출 전에 required_missing()으로 걸러 헛 요청을 막는다.
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable, Mapping

from .k2web_parse import Row, coerce_date

REQUIRED = ("items", "title")


def required_missing(paths: Mapping[str, str]) -> str:
    """필수 경로가 빠졌으면 사람이 읽을 사유를, 갖춰졌으면 ""를 돌려준다."""
    missing = [k for k in REQUIRED if not paths.get(k)]
    if not paths.get("url") and not paths.get("article_no"):
        missing.append("url|article_no")
    return f"api_paths 미설정({'·'.join(missing)})" if missing else ""


def get_path(obj: object, path: str) -> object | None:
    """점 표기 경로로 중첩 값을 꺼낸다 — dict 키와 리스트 인덱스 지원."""
    cur = obj
    for key in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and key.isdigit() and int(key) < len(cur):
            cur = cur[int(key)]
        else:
            return None
    return cur


def parse_items(
    data: bytes,
    *,
    paths: Mapping[str, str],
    base_url: str,
    article_url: Callable[[str], str] | None = None,
) -> list[Row]:
    """JSON 응답에서 공지 행을 뽑는다. 형식이 어긋나면 빈 목록(fail-open)."""
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, AttributeError):
        return []

    items = get_path(payload, paths.get("items", ""))
    if not isinstance(items, list):
        return []

    out: list[Row] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        title = _text(get_path(item, paths["title"]))
        if not title:
            continue

        url = ""
        if paths.get("url"):
            raw = _text(get_path(item, paths["url"]))
            if raw:
                url = urllib.parse.urljoin(base_url, raw)
        if not url and paths.get("article_no") and article_url is not None:
            no = _text(get_path(item, paths["article_no"]))
            if no:
                url = article_url(no)
        if not url or urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            continue
        if url in seen:
            continue
        seen.add(url)

        unit = _text(get_path(item, paths["unit"])) if paths.get("unit") else ""
        published = coerce_date(_text(get_path(item, paths["date"]))) if paths.get("date") else None
        out.append(Row(title=title, url=url, unit=unit, published=published))
    return out


def _text(v: object) -> str:
    if v is None or isinstance(v, (dict, list)):
        return ""
    return " ".join(str(v).split())
