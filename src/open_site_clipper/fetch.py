"""피드 가져오기 — 표준 라이브러리(urllib)만으로 HTTP(S) 요청.

fail-open 원칙: 한 출처가 404·타임아웃·차단(해외 IP 등)으로 실패해도 예외를
밖으로 던지지 않고 None을 돌려준다. 호출자는 실패 출처를 보고서 표지에
"수집 실패"로 표기하고 나머지로 보고서를 완성한다.

오프라인/재현: --input 디렉터리에 저장한 피드를 읽어 네트워크 없이도 보고서를
만들 수 있다(대회 심사·CI에서 결정론적 재현에 쓰인다).
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

_UA = "open_site_clipper/0.1 (+https://github.com/corey1-cmd/open_site_clipper)"
_DEFAULT_TIMEOUT = 15.0
_MAX_BYTES = 8 * 1024 * 1024  # 8MB — 피드 한 건이 이보다 크면 비정상


def fetch_url(url: str, *, timeout: float = _DEFAULT_TIMEOUT) -> bytes | None:
    """URL을 GET해 본문 바이트를 돌려준다. 실패 시 None(fail-open).

    http/https만 허용한다(file:// 등 로컬 스킴 차단 — SSRF/경로 우회 방지).
    """
    # http(s)만 허용 — file://·ftp:// 등 로컬/우회 스킴을 원천 차단(SSRF 방지).
    if not (url.startswith("http://") or url.startswith("https://")):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(_MAX_BYTES)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def read_local(path: str | Path) -> bytes | None:
    """로컬 파일에서 피드를 읽는다(--input 오프라인 모드). 실패 시 None."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return data[:_MAX_BYTES]
