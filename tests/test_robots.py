"""robots.txt 준수 — 허용·차단 판정, 조회 실패 시 fail-open, 호스트별 캐시."""

from __future__ import annotations

import io
import urllib.error

import pytest

from open_site_clipper import robots

RULES = b"""
User-agent: *
Disallow: /bbs/
Allow: /
"""


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


@pytest.fixture(autouse=True)
def _clear():
    robots.reset_cache()
    yield
    robots.reset_cache()


def test_disallowed_path_blocked(monkeypatch):
    monkeypatch.setattr(robots.urllib.request, "urlopen", lambda *a, **k: _Resp(RULES))
    assert robots.allowed("https://www.hufs.ac.kr/hufs/11281/subview.do") is True
    assert robots.allowed("https://www.hufs.ac.kr/bbs/hufs/2180/rssList.do") is False


def test_missing_robots_is_allowed(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError("404")

    monkeypatch.setattr(robots.urllib.request, "urlopen", boom)
    # 규칙을 못 읽으면 막지 않는다(fail-open) — 규칙 없는 사이트를 못 읽는 게 더 이상하다.
    assert robots.allowed("https://example.go.kr/bbs/x") is True


def test_cached_per_host(monkeypatch):
    calls: list[str] = []

    def fake(req, *a, **k):
        calls.append(req.full_url)
        return _Resp(RULES)

    monkeypatch.setattr(robots.urllib.request, "urlopen", fake)
    robots.allowed("https://a.kr/bbs/1")
    robots.allowed("https://a.kr/bbs/2")
    robots.allowed("https://b.kr/bbs/1")
    assert calls == ["https://a.kr/robots.txt", "https://b.kr/robots.txt"]


def test_non_http_scheme_rejected():
    assert robots.allowed("file:///etc/passwd") is False
    assert robots.allowed("notaurl") is False
