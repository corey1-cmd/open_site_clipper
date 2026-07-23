"""피드 가져오기 — 표준 라이브러리(urllib)만으로 HTTP(S) 요청.

fail-open 원칙: 한 출처가 404·타임아웃·차단(해외 IP 등)으로 실패해도 예외를
밖으로 던지지 않고 None을 돌려준다. 호출자는 실패 출처를 보고서 표지에
"수집 실패"로 표기하고 나머지로 보고서를 완성한다.

오프라인/재현: --input 디렉터리에 저장한 피드를 읽어 네트워크 없이도 보고서를
만들 수 있다(대회 심사·CI에서 결정론적 재현에 쓰인다).
"""

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "open_site_clipper/0.9 (+https://github.com/corey1-cmd/open_site_clipper)"
_DEFAULT_TIMEOUT = 15.0
_MAX_BYTES = 8 * 1024 * 1024  # 8MB — 피드 한 건이 이보다 크면 비정상


def fetch_url(url: str, *, timeout: float = _DEFAULT_TIMEOUT) -> bytes | None:
    """URL을 GET해 본문 바이트를 돌려준다. 실패 시 None(fail-open).

    http/https만 허용한다(file:// 등 로컬 스킴 차단 — SSRF/경로 우회 방지).
    """
    # http(s)만 허용 — file://·ftp:// 등 로컬/우회 스킴을 원천 차단(SSRF 방지).
    if not (url.startswith("http://") or url.startswith("https://")):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(_MAX_BYTES)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


# ── data.go.kr 인증키 ────────────────────────────────────────────────────────
# 공공데이터포털 OpenAPI는 발급받은 serviceKey가 필요하다. 키는 코드·출처 파일에
# 적지 않고 환경변수로만 받는다(저장소에 비밀이 새지 않게).
DATAGO_KEY_ENV = "OSC_DATAGO_KEY"

# 응답 형식을 지정하는 파라미터 이름은 API마다 다르다(type/_type/dataType 등).
# URL에 이들 중 하나라도 있으면 사용자의 선택을 존중하고, 없을 때만 type=json을
# 붙인다(파서는 JSON만 읽으므로). 해당 API가 이 이름을 안 쓰면 무시될 뿐이다.
_TYPE_PARAM_NAMES = frozenset({"type", "_type", "datatype", "returntype"})


def datago_url(url: str, key: str | None = None) -> str | None:
    """datago 출처의 실효 URL — serviceKey(와 필요 시 type=json)를 주입한다.

    규칙:
      - URL에 이미 serviceKey가 있으면 그대로 둔다(사용자 명시 우선).
      - 없으면 환경변수 OSC_DATAGO_KEY를 읽어 붙인다. 키도 없으면 None
        (호출자는 "인증키 미설정"으로 처리 — 네트워크를 두드리지 않는다).
      - 포털이 주는 키는 인코딩/디코딩 두 형태가 있다. '%'가 포함돼 있으면
        이미 인코딩된 키로 보고 그대로, 아니면 URL 인코딩해 붙인다.
    """
    parts = urllib.parse.urlsplit(url)
    names = {
        name.lower() for name, _ in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    }

    out = url
    if "servicekey" not in names:
        if key is None:
            key = os.environ.get(DATAGO_KEY_ENV, "").strip()
        if not key:
            return None
        encoded = key if "%" in key else urllib.parse.quote(key, safe="")
        out += ("&" if parts.query else "?") + f"serviceKey={encoded}"

    if not (names & _TYPE_PARAM_NAMES):
        out += "&type=json" if "?" in out else "?type=json"
    return out


def decode_text(data: bytes) -> str:
    """HTML/텍스트 바이트를 한국 웹 현실에 맞게 디코딩한다.

    구형 대학·기관 사이트는 아직 EUC-KR(CP949)이 남아 있다. utf-8 로만 읽으면
    제목·부서명이 통째로 깨진(모지바케) 채 파싱돼 조용히 틀린 데이터가 된다.
    순서: utf-8 엄격 → cp949 엄격 → utf-8 관용(치환). 앞 둘이 엄격인 이유는
    '성공했지만 깨진' 디코딩을 걸러 다음 후보에 기회를 주기 위해서다.
    """
    for enc in ("utf-8", "cp949"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, AttributeError):
            continue
    return data.decode("utf-8", errors="replace")


def read_local(path: str | Path) -> bytes | None:
    """로컬 파일에서 피드를 읽는다(--input 오프라인 모드). 실패 시 None."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return data[:_MAX_BYTES]
