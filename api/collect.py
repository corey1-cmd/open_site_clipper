"""Vercel 함수 — /api/collect?id=<기관 id>&days=7 — 기관 하나의 최근 공지.

로직은 전부 src/open_site_clipper/webapp.py 에 있다(로컬 개발 서버와 공유).
"""

import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from open_site_clipper import webapp


# 클래스 이름은 소문자 handler 여야 한다 — Vercel 파이썬 런타임이 이 이름을 찾는다.
class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        webapp.respond(self, "collect")

    do_HEAD = do_GET
