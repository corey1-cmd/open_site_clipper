"""중간 인증서를 빠뜨린 서버 — 인증서에 적힌 주소(AIA)에서 중간 인증서를 받아 검증을 마저 한다.

국내 학교·기관 서버는 '중간 인증서'를 보내지 않는 곳이 많다(실측 41곳 '인증서 오류').
브라우저는 인증서 안의 AIA(caIssuers) 주소에서 빠진 중간 인증서를 받아 와 문제없이
열지만, 파이썬은 그러지 않아 실패한다.

**검증을 끄는 것이 아니다.** 받아 온 중간 인증서도 운영체제의 신뢰 루트까지 서명으로
이어져야 통과한다(OpenSSL 은 저장소의 인증서로 사슬을 만들되 끝은 자체 서명 루트여야
한다). 이어지지 않으면 그대로 '인증서 오류'로 남는다.
"""

from __future__ import annotations

import os
import ssl
import tempfile
import threading
import urllib.parse
import urllib.request

_lock = threading.Lock()
_ctx = ssl.create_default_context()
_done: dict[str, bool] = {}  # 호스트 → 보강 성공 여부(같은 호스트는 한 번만 시도)
_MAX_DEPTH = 3
_TIMEOUT = 10


def context() -> ssl.SSLContext:
    """모든 요청이 쓰는 TLS 설정 — 보강한 중간 인증서가 여기에 쌓인다."""
    return _ctx


def _ca_issuers(pem: str) -> list[str]:
    """인증서의 AIA caIssuers 주소들(표준 라이브러리의 인증서 해독기를 쓴다)."""
    decode = getattr(getattr(ssl, "_ssl", None), "_test_decode_cert", None)
    if decode is None:
        return []
    fd, path = tempfile.mkstemp(suffix=".pem")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(pem)
        info = decode(path)
    except Exception:
        return []
    finally:
        os.unlink(path)
    return [u for u in info.get("caIssuers", ()) if u.startswith(("http://", "https://"))]


def repair(url: str) -> bool:
    """이 주소의 서버에 빠진 중간 인증서를 채워 넣는다. 채웠으면 True(다시 시도할 가치)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return False
    host, port = parts.hostname, parts.port or 443
    with _lock:
        if host in _done:
            return False  # 이미 해 봤다 — 같은 실패를 되풀이하지 않는다
        _done[host] = False
    try:
        pem = ssl.get_server_certificate((host, port), timeout=_TIMEOUT)
    except (OSError, ValueError):
        return False
    added = False
    issuers = _ca_issuers(pem)
    for _ in range(_MAX_DEPTH):
        if not issuers:
            break
        try:
            with urllib.request.urlopen(issuers[0], timeout=_TIMEOUT) as resp:
                raw = resp.read(200_000)
        except (OSError, ValueError):
            break
        text = raw.decode("ascii", "ignore")
        cert = text if "BEGIN CERTIFICATE" in text else ssl.DER_cert_to_PEM_cert(raw)
        try:
            with _lock:
                _ctx.load_verify_locations(cadata=cert)
        except (ssl.SSLError, ValueError):
            break
        added = True
        issuers = _ca_issuers(cert)
    with _lock:
        _done[host] = added
    return added


# 오래된 서버용 설정 — 인증서 검증은 그대로 하고, 옛 TLS 협상 방식만 허용한다.
#   · 안전하지 않은 옛 재협상(legacy renegotiation): OpenSSL 3 이 기본으로 거절한다
#   · 짧은 DH 키·옛 암호군: 보안 수준 2 에서 거절된다
# 브라우저는 이런 서버를 열어 주므로, 공지를 읽는 데 한해 같은 수준으로 맞춘다.
_LEGACY_HINTS = (
    "legacy renegotiation",
    "dh key too small",
    "handshake failure",
    "unsupported protocol",
    "wrong version number",
    "no protocols available",
    "sslv3 alert",
)
_legacy_ctx = ssl.create_default_context()
_legacy_ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
try:
    import warnings

    _legacy_ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    with warnings.catch_warnings():  # TLS 1.0 허용 경고 — 옛 서버용 설정이라 의도된 것
        warnings.simplefilter("ignore", DeprecationWarning)
        _legacy_ctx.minimum_version = ssl.TLSVersion.TLSv1
except (ssl.SSLError, ValueError, AttributeError):
    pass
_legacy_hosts: set[str] = set()


def needs_legacy(error_text: str) -> bool:
    low = error_text.lower()
    return any(h in low for h in _LEGACY_HINTS)


def legacy_context() -> ssl.SSLContext:
    return _legacy_ctx


def mark_legacy(url: str) -> bool:
    """이 호스트를 옛 TLS 설정으로 다시 시도할지 — 처음이면 True."""
    host = urllib.parse.urlsplit(url).hostname or ""
    with _lock:
        if host in _legacy_hosts:
            return False
        _legacy_hosts.add(host)
    return True


def is_legacy(url: str) -> bool:
    return (urllib.parse.urlsplit(url).hostname or "") in _legacy_hosts
