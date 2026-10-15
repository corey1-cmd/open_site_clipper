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


# ── RFC 9309 해석(2026-10-12) — 가장 길게 맞는 규칙, 와일드카드, 우리 묶음 ─────────────
def _rules(text: str) -> robots.Rules:
    return robots.Rules(text.strip().splitlines())


UA = robots.USER_AGENT


def test_longest_match_wins_over_order():
    # '모두 막고 게시판만 연다' — 표준 라이브러리는 먼저 적힌 Disallow: / 로 다 막았다
    r = _rules("User-agent: *\nDisallow: /\nAllow: /bbs/\nAllow: /$")
    assert r.can_fetch(UA, "https://u.ac.kr/bbs/list.do?id=1") is True
    assert r.can_fetch(UA, "https://u.ac.kr/") is True
    assert r.can_fetch(UA, "https://u.ac.kr/admin/") is False
    assert r.verdict(UA, "https://u.ac.kr/admin/") == (False, "Disallow: /")


def test_wildcards_and_end_anchor():
    r = _rules("User-agent: *\nDisallow: /*.pdf$\nDisallow: /*?print=\nAllow: /*.pdf?keep")
    assert r.can_fetch(UA, "https://u.ac.kr/a/b.pdf") is False
    assert r.can_fetch(UA, "https://u.ac.kr/a/b.pdf?x=1") is True  # '$' — 끝이 .pdf 일 때만
    assert r.can_fetch(UA, "https://u.ac.kr/view.do?no=1&print=y") is True  # '?print=' 이 앞에 없다
    assert r.can_fetch(UA, "https://u.ac.kr/view.do?print=y") is False
    assert r.can_fetch(UA, "https://u.ac.kr/a/b.pdf?keep=1") is True


def test_allow_wins_a_tie_and_empty_disallow_allows_all():
    assert _rules("User-agent: *\nDisallow: /p\nAllow: /p").can_fetch(UA, "https://u.ac.kr/p/1")
    assert _rules("User-agent: *\nDisallow:").can_fetch(UA, "https://u.ac.kr/anything")


def test_our_own_group_replaces_the_star_group_and_other_bots_do_not_apply():
    text = (
        "User-agent: Googlebot\nDisallow: /\n\n"
        "User-agent: open_site_clipper\nDisallow: /private/\n\n"
        "User-agent: *\nDisallow: /"
    )
    r = _rules(text)
    assert r.can_fetch(UA, "https://u.ac.kr/bbs/1") is True  # 우리 묶음에는 /bbs 규칙이 없다
    assert r.can_fetch(UA, "https://u.ac.kr/private/x") is False
    assert _rules("User-agent: Googlebot\nDisallow: /").can_fetch(UA, "https://u.ac.kr/x") is True


def test_groups_with_several_agents_rules_before_agents_and_encoding():
    text = (
        "Disallow: /ignored\n"  # 묶음 밖 규칙
        "User-agent: a\nUser-agent: *\nDisallow: /%EA%B2%8C%EC%8B%9C/\nCrawl-delay: 3\n"
        "User-agent: b\nDisallow: /b-only\n"
        "Sitemap: https://u.ac.kr/sitemap.xml"
    )
    r = _rules(text)
    assert r.can_fetch(UA, "https://u.ac.kr/ignored") is True
    assert r.can_fetch(UA, "https://u.ac.kr/게시/1") is False  # 한글 경로도 인코딩해 비교
    assert r.can_fetch(UA, "https://u.ac.kr/b-only") is True
    assert r.crawl_delay(UA) == 3.0
    assert r.sitemaps == ["https://u.ac.kr/sitemap.xml"]
    assert r.can_fetch(UA, "https://u.ac.kr/robots.txt") is True


def test_explain_reports_the_winning_rule_and_the_old_reading(monkeypatch):
    rules = b"User-agent: *\nDisallow: /\nAllow: /bbs/\n"
    monkeypatch.setattr(robots.urllib.request, "urlopen", lambda *a, **k: _Resp(rules))
    got = robots.explain("https://u.ac.kr/bbs/list.do")
    assert got["allowed"] is True and got["rule"] == "Allow: /bbs/"
    # 비교용 예전 판정 — 표준 라이브러리의 해석은 파이썬 판마다 다르다(3.12 는 먼저 적힌 규칙)
    assert isinstance(got["stdlib"], bool)
    assert got["robots"].startswith("200")


def test_allowed_entries_are_the_plain_allow_paths(monkeypatch):
    rules = (
        b"User-agent: *\nDisallow: /\nAllow: /portal/\nAllow: /representation/\n"
        b"Allow: /board/list.jsp?*id=3&\nAllow: /favicon.ico\nAllow: /$\nAllow: /main/\n"
    )
    monkeypatch.setattr(robots.urllib.request, "urlopen", lambda *a, **k: _Resp(rules))
    assert robots.allowed_entries("https://www.jbsc.ac.kr/") == [
        "https://www.jbsc.ac.kr/main/",
        "https://www.jbsc.ac.kr/portal/",
        "https://www.jbsc.ac.kr/representation/",
    ]
