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

USER_AGENT = "open_site_clipper/0.14 (+https://github.com/corey1-cmd/open_site_clipper)"
_DEFAULT_TIMEOUT = 15.0
_MAX_BYTES = 8 * 1024 * 1024  # 8MB — 피드 한 건이 이보다 크면 비정상


# 한 번 더 시도해 볼 만한 일시적 실패 — 순간적인 네트워크 끊김·서버 혼잡.
_RETRYABLE = ("timed out", "reset", "temporarily", "unreachable", "connection")


def fetch_detail(
    url: str, *, timeout: float = _DEFAULT_TIMEOUT, retry: bool = True
) -> tuple[bytes | None, str]:
    """URL을 GET해 (본문, 실패 사유)를 돌려준다.

    사유를 남기는 이유: '응답 없음' 한 줄로는 차단(403)인지, 주소가 바뀐 것(404)
    인지, 서버가 느린 것(시간 초과)인지 알 수 없어 고칠 수가 없다. 무엇이
    막혔는지 보고서에 그대로 적어 사람이 판단하게 한다.

    일시적으로 보이는 실패는 한 번만 다시 시도한다(서버 혼잡·순간 끊김 구제).
    """
    if not (url.startswith("http://") or url.startswith("https://")):
        # http(s)만 허용 — file://·ftp:// 등 로컬/우회 스킴 차단(SSRF 방지).
        return None, "지원하지 않는 주소 형식"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    attempts = 2 if retry else 1
    reason = "응답 없음"
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(_MAX_BYTES), ""
        except urllib.error.HTTPError as e:
            hint = {403: "접근 거부(403)", 404: "주소 없음(404)", 429: "요청 과다(429)"}
            return None, hint.get(e.code, f"HTTP 오류({e.code})")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            text = str(getattr(e, "reason", e)).lower()
            if "timed out" in text or isinstance(e, TimeoutError):
                reason = f"시간 초과({timeout:.0f}초)"
            elif "name or service" in text or "nodename" in text or "getaddrinfo" in text:
                return None, "도메인을 찾을 수 없음"
            elif "certificate" in text or "ssl" in text:
                return None, "인증서 오류"
            else:
                reason = f"연결 실패({str(getattr(e, 'reason', e))[:40]})"
            if i + 1 < attempts and any(k in text for k in _RETRYABLE):
                continue  # 일시적으로 보이면 한 번 더
            return None, reason
    return None, reason


def fetch_url(url: str, *, timeout: float = _DEFAULT_TIMEOUT) -> bytes | None:
    """URL을 GET해 본문 바이트를 돌려준다. 실패 시 None(fail-open)."""
    return fetch_detail(url, timeout=timeout)[0]


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


class TrackingFetcher:
    """가져오면서 실패 사유를 기억하는 페처.

    캐스케이드가 '응답 없음' 대신 '접근 거부(403)'·'시간 초과(15초)'처럼
    구체적인 사유를 보고서에 적을 수 있게 한다. 여러 스레드가 함께 쓰므로
    기록은 단순 대입만 한다(경쟁이 나도 마지막 값이 남을 뿐 문제되지 않는다).
    """

    __slots__ = ("_reasons", "timeout")

    def __init__(self, timeout: float = _DEFAULT_TIMEOUT):
        self.timeout = timeout
        self._reasons: dict[str, str] = {}

    def __call__(self, url: str) -> bytes | None:
        data, why = fetch_detail(url, timeout=self.timeout)
        if why:
            self._reasons[url] = why
        return data

    def why(self, url: str) -> str:
        return self._reasons.get(url, "응답 없음")
