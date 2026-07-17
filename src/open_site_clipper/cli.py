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

from . import (
    __version__,
    brief,
    brief_report,
    collect,
    digest,
    relevance,
    report,
    sources,
    state,
    theme,
)
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
    p.add_argument(
        "--state",
        metavar="FILE",
        help="실행 간 상태 파일(JSON) — 이전 실행에 없던 공지를 🆕로 표기하고, "
        "이번 실행 결과를 저장한다. 파일이 없으면 첫 실행(기준선)으로 취급",
    )
    p.add_argument(
        "--only-new",
        action="store_true",
        help="--state 기준 신규 공지만으로 보고서를 만든다",
    )
    p.add_argument(
        "--digest",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="보고서 상단 기간 요약(기관·분류·키워드) — 규칙 기반, LLM 없음 (기본: 포함)",
    )
    p.add_argument(
        "--template",
        metavar="FILE",
        help="사용자 템플릿 파일 — $title·$body_md 등 마커를 치환해 조직 서식 그대로 "
        "출력한다(지정 시 --format 무시). 마커 목록은 README 참고",
    )
    p.add_argument(
        "--theme",
        metavar="FILE",
        help="테마 정의(JSON) — 이 테마에 관련된 자료만 골라 섹션 브리프로 만든다"
        "(신한 '글로벌 이슈'류). 해석 표·그래프 포함",
    )
    p.add_argument(
        "--min-score",
        type=int,
        metavar="N",
        help=f"테마 관련성 채택 하한 (기본 {relevance.DEFAULT_MIN_SCORE}점 = 제목 1회 적중)",
    )
    p.add_argument(
        "--group-by",
        choices=("agency", "topic", "org"),
        default="agency",
        help="보고서 섹션 축 — agency(기본) | topic(주제별) | org(기관→사이트→부서)",
    )
    p.add_argument(
        "--deep-links",
        action="store_true",
        help="공지 본문 페이지에서 관련 자료·첨부 링크만 추가 수집(본문은 가져오지 않음). "
        "공지마다 요청이 늘어 느려지며, 변형 금지 등급은 건너뛴다",
    )
    p.add_argument(
        "--deep-links-limit",
        type=int,
        default=20,
        metavar="N",
        help="--deep-links로 본문을 열어볼 공지 수 상한 (기본 20)",
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
        if s.kind == "k2web":
            from . import k2web

            trail = " → ".join(f"{name}" for name, _ in k2web.candidates(s))
            first = next((u for _, u in k2web.candidates(s)), "")
            print(f"        {first}  (폴백: {trail})")
        else:
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
        # 목록 조회는 꺼진 출처도 [off]로 보여준다 — datago 예시와 인증키 상태를
        # 사용자가 발견할 수 있게(수집 자체는 여전히 enabled만 돈다).
        if not args.demo and not args.sources:
            srcs = sources.default_sources(include_disabled=True)
        _print_sources(srcs)
        return 0

    if args.only_new and not args.state:
        raise SystemExit("--only-new 은 --state FILE 과 함께 써야 합니다.")

    rep = collect.collect(srcs, since_days=args.since, agency=args.agency, fetcher=fetcher)
    rep.group_by = args.group_by
    if args.title:
        rep.title = args.title

    seen: list[str] | None = None
    all_keys: set[str] = set()
    if args.state:
        seen = state.load(args.state)
        all_keys = {n.dedup_key() for n in rep.notices}
        if seen is None:
            print(
                f"상태 파일이 없어 첫 실행(기준선)으로 저장합니다: {args.state}",
                file=sys.stderr,
            )
        else:
            rep.notices = state.mark_new(rep.notices, seen)
        if args.only_new:
            rep.notices = [n for n in rep.notices if n.is_new]

    if args.deep_links and rep.notices:
        if args.demo or args.input:
            print(
                "--deep-links 는 실시간 수집에서만 동작합니다(오프라인 모드에서는 건너뜁니다).",
                file=sys.stderr,
            )
        else:
            rep.notices = collect.enrich_links(rep.notices, limit=args.deep_links_limit)

    if args.digest and rep.notices:
        rep.digest = digest.build(rep.notices)

    if args.theme:
        if args.template:
            raise SystemExit("--theme 과 --template 은 함께 쓸 수 없습니다.")
        try:
            th = theme.load(args.theme)
        except ValueError as e:
            raise SystemExit(str(e)) from e
        bf = brief.build(
            rep.notices,
            th,
            min_score=args.min_score,
            generated_at=rep.generated_at,
            since_days=rep.since_days,
            failed_sources=rep.failed_sources,
            with_digest=rep.digest,
        )
        text = brief_report.render(bf, _FMT_ALIASES[args.format])
        summary = (
            f"브리프 저장: {args.output} (테마 '{th.name}' · 관련 자료 "
            f"{len(bf.notices)}건 · 사안 {bf.issue_count}건 / 검토 {bf.considered}건)"
        )
    elif args.template:
        try:
            tmpl = Path(args.template).read_text(encoding="utf-8")
        except OSError as e:
            raise SystemExit(f"템플릿 파일을 읽을 수 없습니다: {e}") from e
        text = report.render_template(rep, tmpl)
        summary = ""
    else:
        text = report.render(rep, _FMT_ALIASES[args.format])
        summary = ""

    if not summary:
        summary = (
            f"보고서 저장: {args.output} "
            f"(공지 {len(rep.notices)}건 · 기관 {len(rep.agencies)}곳"
            + (f" · 수집 실패 {len(rep.failed_sources)}곳" if rep.failed_sources else "")
            + ")"
        )

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(summary, file=sys.stderr)
    else:
        sys.stdout.write(text)

    if args.state:
        state.save(args.state, current_keys=all_keys, previous=seen, updated_at=rep.generated_at)
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
