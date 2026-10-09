"""배포된 웹 버전으로 전 기관을 실측 점검하고, 경로 캐시와 점검 보고서를 만든다.

점검은 배포된 서버(Vercel 서울 리전)가 한다 — 이 스크립트는 그 결과를 모을 뿐이라
어느 컴퓨터에서 돌려도 된다(국내망 불필요, 표준 라이브러리만 사용).

    # 배포 주소로 전부 점검 → route-cache.json 갱신 + docs/실측-점검-날짜.md
    python scripts/bake_routes.py https://open-site-clipper.vercel.app

    # 이미 받아 둔 /api/verify 응답(JSON 파일들)로만 굽기
    python scripts/bake_routes.py --from-files verify-*.json

/api/verify 는 한 번에 20곳까지 받는다. 421곳이면 22번 묻는다(한 번에 최대 5분).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from open_site_clipper import webapp  # noqa: E402

CACHE = ROOT / "src" / "open_site_clipper" / "data" / "route-cache.json"
BATCH = webapp.VERIFY_MAX_IDS


def fetch_batches(base: str, ids: list[str], days: int) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(ids), BATCH):
        chunk = ids[i : i + BATCH]
        url = f"{base.rstrip('/')}/api/verify?days={days}&ids=" + ",".join(
            urllib.parse.quote(x) for x in chunk
        )
        print(f"[{i + len(chunk)}/{len(ids)}] 점검 중…", flush=True)
        with urllib.request.urlopen(url, timeout=330) as resp:
            out.extend(json.loads(resp.read().decode("utf-8"))["results"])
    return out


def bake(results: list[dict], today: str) -> dict:
    try:
        doc = json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        doc = {"orgs": {}}
    orgs = doc.setdefault("orgs", {})
    for r in results:
        if r.get("count") and r.get("routes"):
            orgs[r["id"]] = {"routes": r["routes"], "count": r["count"], "checked": today}
    doc["updated"] = today
    CACHE.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return doc


def report(results: list[dict], today: str, days: int) -> str:
    cat = webapp.catalog()
    by_section: dict[str, Counter] = {}
    for r in results:
        sec = cat[r["id"]].section if r["id"] in cat else "?"
        c = by_section.setdefault(sec, Counter())
        c["점검"] += 1
        c["성공" if r.get("count") else "실패"] += 1
        c["건수"] += r.get("count") or 0
    lines = [
        f"# 실측 점검 {today}",
        "",
        f"배포 서버(서울)에서 최근 {days}일 기준으로 점검했다.",
        "",
    ]
    lines += ["| 묶음 | 점검 | 글을 모은 곳 | 못 모은 곳 | 모은 글 |", "|---|---:|---:|---:|---:|"]
    for sec, c in by_section.items():
        lines.append(f"| {sec} | {c['점검']} | {c['성공']} | {c['실패']} | {c['건수']:,} |")
    fails = [r for r in results if not r.get("count")]
    if fails:
        lines += ["", f"## 못 모은 곳 {len(fails)}곳", ""]
        for r in fails:
            why = r.get("error") or next(iter(r.get("failures") or r.get("notes") or []), "")
            lines.append(f"- {r['name']} (`{r['id']}`): {str(why)[:200]}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("base", nargs="?", help="배포 주소(https://….vercel.app)")
    ap.add_argument("--from-files", nargs="+", metavar="JSON", help="받아 둔 /api/verify 응답")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--only", help="이 문자열로 시작하는 id 만(예: gov-, u-)")
    args = ap.parse_args()

    if args.from_files:
        results = [
            r for f in args.from_files for r in json.loads(Path(f).read_text("utf-8"))["results"]
        ]
    elif args.base:
        ids = [i for i in webapp.catalog() if not args.only or i.startswith(args.only)]
        results = fetch_batches(args.base, ids, args.days)
    else:
        ap.error("배포 주소나 --from-files 가 필요합니다")

    today = date.today().isoformat()
    doc = bake(results, today)
    text = report(results, today, args.days)
    out = ROOT / "docs" / f"실측-점검-{today}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"경로 캐시 {len(doc['orgs'])}곳 → {CACHE.relative_to(ROOT)}")
    print(f"보고서 → {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
