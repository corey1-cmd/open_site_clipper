"""open_site_clipper — 정부·공공기관 공지를 수집해 하나의 보고서로.

공개 RSS/OpenAPI로 흩어진 정부·지자체 공지를 모아, 출처와 공공누리(KOGL)
라이선스 등급을 명시한 단일 보고서(Markdown·HTML·JSON)로 만든다. 런타임
의존성 0 — 파이썬 표준 라이브러리만으로 동작한다.
"""

from __future__ import annotations

__version__ = "0.4.0"
__all__ = ["__version__"]
