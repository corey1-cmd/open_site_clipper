"""명령줄 인터페이스 — `open_site_clipper` 또는 `python -m open_site_clipper`.

예시:
  open_site_clipper --demo                         # 번들 샘플로 오프라인 보고서(HTML)
  open_site_clipper --format markdown -o report.md # 실시간 수집 → 마크다운 파일
  open_site_clipper --since 7 --agency 행정안전부   # 최근 7일 · 특정 기관만
  open_site_clipper --input ./feeds --format html  # 저장해 둔 피드로 오프라인 생성
  open_site_clipper --sources my_sources.json      # 사용자 정의 출처
  open_site_clipper --list-sources                 # 설정된 출처 확인
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib import resources
from pathlib import Path

from . import __version__, collect, report, sources
from .collect import local_fetcher

_FMT_ALIASES = {"md": "markdown", "markdown": "markdown", "html": "html", "json": "json"}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="open_site_clipper",
        description="정부·공공기관 공지를 수집해 하나의 보고서로 만든다(공공누리 등급 표기).",
    )
    p.add_argument("--version", action="version", version=f"open_site_clipper {__version__}")
    p.add_argument(
        "-f",
        "--format",
        default="html",
        choices=sorted(set(_FMT_ALIASES)),
        help="보고서 형식 (기본: html)",
    )
    p.add_argument("-o", "--output", metavar="FILE", help="출력 파일 경로 (기본: 표준 출력)")
    p.add_argument("--since", type=int, metavar="DAYS", help="최근 N일 이내 공지만")
    p.add_argument("--agency", metavar="NAME", help="기관명 부분일치 필터")
    p.add_argument(
        "--sources", metavar="FILE", help="사용자 정의 출처 JSON(목록). 없으면 기본 출처"
    )
    p.add_argument(
        "--input",
        metavar="DIR",
        help="오프라인 모드 — 네트워크 대신 이 디렉터리의 저장된 피드(<source-id>.*)를 읽는다",
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="번들된 샘플 피드로 오프라인 보고서를 만든다(네트워크·설치 검증용)",
    )
    p.add_argument("--list-sources", action="store_true", help="설정된 출처를 출력하고 종료")
    p.add_argument("--title", metavar="TEXT", help="보고서 제목 재정의")
    return p


def _load_sources(args: argparse.Namespace) -> list[sources.Source]:
    if args.sources:
        try:
            raw = json.loads(Path(args.sources).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise SystemExit(f"출처 파일을 읽을 수 없습니다: {e}") from e
        items = raw.get("sources") if isinstance(raw, dict) else raw
        parsed = sources.from_dicts(items if isinstance(items, list) else [])
        if not parsed:
            raise SystemExit("출처 파일에 유효한 출처가 없습니다(name·url·kind 확인).")
        return parsed
    return sources.default_sources()


def _print_sources(srcs: list[sources.Source]) -> None:
    from . import rights
    from .fetch import DATAGO_KEY_ENV, datago_url

    for s in srcs:
        state = "on " if s.enabled else "off"
        key = ""
        if s.kind == "datago":
            key = " · 인증키 OK" if datago_url(s.url) else f" · 인증키 미설정({DATAGO_KEY_ENV})"
        print(f"[{state}] {s.id:<16} {s.kind:<6} {rights.badge(s.rights):<7} {s.name}{key}")
        print(f"        {s.url}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.demo:
        srcs = sources.demo_sources()
        fetcher = _demo_fetcher()
    else:
        srcs = _load_sources(args)
        fetcher = local_fetcher(args.input) if args.input else None

    if args.list_sources:
        _print_sources(srcs)
        return 0

    rep = collect.collect(srcs, since_days=args.since, agency=args.agency, fetcher=fetcher)
    if args.title:
        rep.title = args.title

    text = report.render(rep, _FMT_ALIASES[args.format])

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(
            f"보고서 저장: {args.output} "
            f"(공지 {len(rep.notices)}건 · 기관 {len(rep.agencies)}곳"
            + (f" · 수집 실패 {len(rep.failed_sources)}곳" if rep.failed_sources else "")
            + ")",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(text)
    return 0


def _demo_fetcher() -> collect.Fetcher:
    """번들 샘플(samples/)을 소스 id로 매핑해 돌려주는 오프라인 페처."""
    mapping = {"mois": "mois_press.xml", "datago-example": "datago_sample.json"}

    def _read(source: sources.Source) -> bytes | None:
        name = mapping.get(source.id)
        if not name:
            return None
        try:
            res = resources.files("open_site_clipper").joinpath(f"samples/{name}")
            return res.read_bytes()
        except (FileNotFoundError, OSError, ModuleNotFoundError):
            return None

    return _read


if __name__ == "__main__":
    raise SystemExit(main())
