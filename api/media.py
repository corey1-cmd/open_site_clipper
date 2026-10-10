"""Vercel 함수 — /api/media?url=<글 주소>&title=<제목> — 글 한 건의 그림·첨부 주소.

휴대폰에서 원문 그림이 잘릴 때 앱이 그림만 화면 폭에 맞춰 보여 주는 데 쓴다.
로직은 전부 src/open_site_clipper/webapp.py · media.py 에 있다.
"""

import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from open_site_clipper import webapp


# 클래스 이름은 소문자 handler 여야 한다 — Vercel 파이썬 런타임이 이 이름을 찾는다.
class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        webapp.respond(self, "media")

    do_HEAD = do_GET
