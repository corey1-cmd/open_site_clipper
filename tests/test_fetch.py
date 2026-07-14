"""fetch 계층 — datago 인증키 주입 규칙과 로컬 스킴 차단."""

from __future__ import annotations

from open_site_clipper.fetch import DATAGO_KEY_ENV, datago_url, fetch_url

URL = "https://apis.data.go.kr/x/getList"


def test_key_injected_from_env(monkeypatch):
    monkeypatch.setenv(DATAGO_KEY_ENV, "abc+def")
    out = datago_url(URL)
    # 디코딩 키('%' 없음)는 URL 인코딩되어 주입된다.
    assert out == f"{URL}?serviceKey=abc%2Bdef&type=json"


def test_encoded_key_passes_through(monkeypatch):
    # '%'가 포함된 키는 이미 인코딩된 것으로 보고 그대로 붙인다.
    monkeypatch.setenv(DATAGO_KEY_ENV, "abc%2Bdef")
    assert "serviceKey=abc%2Bdef" in (datago_url(URL) or "")


def test_existing_servicekey_respected(monkeypatch):
    monkeypatch.setenv(DATAGO_KEY_ENV, "SHOULD-NOT-APPEAR")
    out = datago_url(f"{URL}?serviceKey=user-key&numOfRows=5")
    assert out is not None
    assert "user-key" in out and "SHOULD-NOT-APPEAR" not in out
    assert out.count("serviceKey") == 1


def test_missing_key_returns_none(monkeypatch):
    monkeypatch.delenv(DATAGO_KEY_ENV, raising=False)
    assert datago_url(URL) is None


def test_type_param_added_only_when_absent(monkeypatch):
    monkeypatch.setenv(DATAGO_KEY_ENV, "k")
    assert (datago_url(URL) or "").endswith("&type=json")
    # 사용자가 형식 파라미터를 이미 지정했으면 존중한다(_type/dataType 포함).
    kept = datago_url(f"{URL}?_type=xml")
    assert kept is not None and "type=json" not in kept


def test_fetch_url_blocks_local_schemes():
    # SSRF 방지 — http(s) 외 스킴은 네트워크 없이 즉시 None.
    assert fetch_url("file:///etc/passwd") is None
    assert fetch_url("ftp://example.com/a") is None
