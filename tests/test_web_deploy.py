"""Vercel 배포 묶음이 깨지지 않았는지 — 배포해 보기 전에 잡을 수 있는 것들.

배포는 사용자가 '가져오기' 한 번으로 끝나야 한다. 그러려면 설정 파일·함수 파일·
화면 파일이 서로 맞물려 있어야 하고, 이 테스트가 그 맞물림을 지킨다.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import re
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"


def _vercel() -> dict:
    return json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))


def test_vercel_config_runs_functions_in_seoul():
    cfg = _vercel()
    assert cfg["regions"] == ["icn1"]  # 해외 IP 를 막는 정부 서버가 있다 — 서울에서 돈다
    assert cfg["framework"] is None and cfg["outputDirectory"] == "public"
    fn = cfg["functions"]["api/*.py"]
    assert 60 < fn["maxDuration"] <= 300
    # 웹 함수의 시간 예산이 함수 제한보다 넉넉히 짧아야 사유를 남기고 끝난다
    from open_site_clipper import webapp

    assert fn["maxDuration"] > webapp.DEFAULT_BUDGET + 30


def test_every_api_file_exposes_a_handler_for_its_route():
    files = sorted((ROOT / "api").glob("*.py"))
    assert {f.stem for f in files} == {"catalog", "collect", "verify"}
    for f in files:
        assert fnmatch.fnmatch(f"api/{f.name}", "api/*.py")
        spec = importlib.util.spec_from_file_location(f"api_{f.stem}", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert issubclass(mod.handler, BaseHTTPRequestHandler)
        assert callable(mod.handler.do_GET)
        assert f'respond(self, "{f.stem}")' in f.read_text(encoding="utf-8")


def test_vercelignore_keeps_what_functions_need():
    rules = [
        line.strip()
        for line in (ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert "pyproject.toml" in rules  # 있으면 패키지 설치를 시도한다
    needed = [
        "api/collect.py",
        "src/open_site_clipper/webapp.py",
        "src/open_site_clipper/data/route-cache.json",
        "examples/sources-gov.json",
        "examples/sources-schools.json",
        "public/index.html",
        "vercel.json",
    ]
    for path in needed:
        for rule in rules:
            pattern = rule.rstrip("/")
            assert not fnmatch.fnmatch(path, pattern), (path, rule)
            assert not path.startswith(pattern + "/"), (path, rule)


def test_page_references_existing_files():
    html = (PUBLIC / "index.html").read_text(encoding="utf-8")
    local = [u for u in re.findall(r'(?:href|src)="(/[^"#?]*)"', html) if u != "/"]
    assert local, "화면이 자기 파일을 하나도 부르지 않는다"
    for url in local:
        assert (PUBLIC / url.lstrip("/")).is_file(), url
    manifest = json.loads((PUBLIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    for icon in manifest["icons"]:
        assert (PUBLIC / icon["src"].lstrip("/")).is_file(), icon["src"]


def test_page_never_links_scraped_urls_raw():
    """긁어 온 주소는 http(s) 만 링크로 — javascript: 주소가 섞여도 실행되지 않게."""
    js = (PUBLIC / "app.js").read_text(encoding="utf-8")
    assert "safeUrl(n.url)" in js
    assert 'href="${esc(n.url)}"' not in js


SCHOOL_TYPES = {
    "4년제",
    "교육대",
    "과학기술원",
    "특수대",
    "방송통신대",
    "사이버대",
    "전문대",
    "전공대학",
}
REGIONS = {
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
    "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주", "전국",
}  # fmt: skip


def test_school_list_is_clean():
    raw = json.loads((ROOT / "examples" / "sources-schools.json").read_text(encoding="utf-8"))
    schools = raw["sources"]
    ids = [s["id"] for s in schools]
    assert len(ids) == len(set(ids)) and all(i.startswith("u-") for i in ids)
    for s in schools:
        assert s["kind"] == "govorg" and s["org"] == s["name"]
        assert s["group"] in SCHOOL_TYPES, s
        assert s["region"] in REGIONS, s
        assert re.fullmatch(r"https://[a-z0-9.-]+\.[a-z]{2,}", s["home"]), s["home"]
    # 2026 통합·폐교된 학교가 다시 들어오지 않게
    names = {s["name"] for s in schools}
    assert not names & {"강릉원주대학교", "원광보건대학교", "광양보건대학교", "동주대학교"}
