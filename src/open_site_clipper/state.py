"""실행 간 상태 — 이전 실행에서 본 공지를 기억해 '신규'를 가려낸다.

changedetection.io의 스냅샷 비교에서 착안하되, 이 도구의 원칙에 맞게 순수
JSON 파일 하나로 최소화했다(의존성 0 · 오프라인 재현). 상태 파일이 없으면
"첫 실행"으로 보고 아무것도 신규 표기하지 않는다 — 첫 보고서 전체가 🆕로
도배되는 오탐을 막고, 기준선만 저장한다.

상태는 보고서에 실제 포함된 공지의 dedup_key 집합이다. --agency·--since로
좁혀 실행하면 그 범위만 기록되므로, 신규 판정은 "같은 조건의 이전 보고서에
없던 공지"라는 뜻이 된다.

파일 형식(버전 관리):
    {"version": 1, "updated_at": "<ISO 8601>", "seen": ["<dedup_key>", ...]}
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .model import Notice

STATE_VERSION = 1

# seen 키 상한 — 수년 치 누적으로 파일이 무한히 크지 않게. 저장 순서는
# "이번 실행 키 먼저, 그다음 과거 키"라 상한 초과 시 가장 오래된 키부터 밀려난다.
_MAX_KEYS = 20_000


def load(path: str | Path) -> list[str] | None:
    """상태 파일을 읽어 seen 키 목록을 돌려준다.

    파일이 없거나 형식이 깨졌으면 None(첫 실행 취급 — fail-open). 빈 목록과
    구분하기 위해 None을 쓴다: None이면 신규 표기 자체를 건너뛴다.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    seen = payload.get("seen")
    if not isinstance(seen, list):
        return None
    return [str(k) for k in seen]


def save(
    path: str | Path, *, current_keys: set[str], previous: list[str] | None, updated_at: str
) -> None:
    """이번 실행 키 ∪ 과거 키를 상한 내에서 저장한다(이번 실행 키 우선 보존)."""
    merged: list[str] = sorted(current_keys)
    if previous:
        merged.extend(k for k in previous if k not in current_keys)
    payload = {
        "version": STATE_VERSION,
        "updated_at": updated_at,
        "seen": merged[:_MAX_KEYS],
    }
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def mark_new(notices: list[Notice], seen: list[str]) -> list[Notice]:
    """이전 실행(seen)에 없던 공지에 is_new=True를 표시한 새 목록을 만든다."""
    known = set(seen)
    return [replace(n, is_new=True) if n.dedup_key() not in known else n for n in notices]
