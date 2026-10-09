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

from open_site_clipper import probe, webapp  # noqa: E402

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
        # routes = 실제로 글이 나온 경로만(verify 가 돌려준다). 기간 안 새 글이 0건이어도
        # 게시판 자체는 살아 있으므로 남긴다. 첫 화면·글 한 건 주소는 한 번 더 거른다.
        routes = [
            list(rt)
            for rt in r.get("routes") or []
            if rt[1] != "board" or not probe.not_a_board(rt[2])
        ]
        if routes:
            orgs[r["id"]] = {
                "routes": routes,
                "count": r.get("count") or 0,
                "checked": today,
            }
        elif r["id"] in orgs and r.get("mode") in ("cache", "rediscover"):
            del orgs[r["id"]]  # 캐시 경로가 더는 글을 내지 않는다
    doc["updated"] = today
    CACHE.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return doc


# 못 모은 이유 — 사유 문자열의 앞쪽부터 맞는 것 하나(화면의 PLAIN 과 같은 생각).
REASONS = (
    ("robots.txt 차단", "사이트가 자동 수집을 허용하지 않음(robots.txt) — 설계상 수집 안 함"),
    ("인증서 오류", "보안 인증서 문제(자체 서명·주소 불일치) — 검증을 끄지 않으므로 수집 안 함"),
    ("Device or resource busy", "배포 서버(해외 클라우드 망) 접속을 받지 않음"),
    ("시간 초과", "사이트 응답 없음·너무 느림"),
    ("응답 없음", "사이트 응답 없음·너무 느림"),
    ("HTTP 오류", "사이트 서버 오류"),
    ("연결 실패", "사이트 연결 실패"),
    ("형식 오류", "사이트 연결 실패"),
    ("후보 ", "홈 메뉴는 읽었으나 게시판이 자바스크립트로만 그려짐(목록 HTML 없음)"),
)


def why_failed(r: dict) -> str:
    text = " ".join([r.get("error") or ""] + (r.get("notes") or []) + (r.get("failures") or []))
    if r.get("timed_out") and "후보 " in text:
        return "후보가 많아 시간 안에 게시판을 다 보지 못함"
    for key, plain in REASONS:
        if key in text:
            if key == "후보 " and " <a> " in text:
                m = text.split(" <a> ", 1)[1].split("개", 1)[0]
                if m.isdigit() and int(m) < 20:
                    return "홈이 자바스크립트로만 그려짐(읽을 링크가 거의 없음)"
            return plain
    return "게시판을 찾지 못함"


def report(results: list[dict], today: str, days: int) -> str:
    cat = webapp.catalog()
    by_section: dict[str, Counter] = {}
    why: dict[str, Counter] = {}
    for r in results:
        sec = cat[r["id"]].section if r["id"] in cat else "?"
        c = by_section.setdefault(sec, Counter())
        c["점검"] += 1
        if r.get("count"):
            c["글 있음"] += 1
        elif r.get("routes"):
            c["연결(기간 내 새 글 없음)"] += 1
        else:
            c["못 모음"] += 1
            why.setdefault(sec, Counter())[why_failed(r)] += 1
        c["건수"] += r.get("count") or 0
    lines = [
        f"# 실측 점검 {today}",
        "",
        f"배포 서버(Vercel 서울 icn1)에서 기관마다 최대 60초, 최근 {days}일 기준으로 점검했다.",
        "'연결'은 게시판에서 글을 읽어 왔지만 기간 안 새 글이 없었던 곳이다(고장이 아니다).",
        "",
        "| 묶음 | 점검 | 글 있음 | 연결(새 글 없음) | 못 모음 | 모은 글 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for sec, c in by_section.items():
        lines.append(
            f"| {sec} | {c['점검']} | {c['글 있음']} | {c['연결(기간 내 새 글 없음)']} "
            f"| {c['못 모음']} | {c['건수']:,} |"
        )
    for sec, reasons in why.items():
        lines += ["", f"## {sec} — 못 모은 이유", "", "| 이유 | 곳 |", "|---|---:|"]
        lines += [f"| {k} | {n} |" for k, n in reasons.most_common()]
    fails = [r for r in results if not r.get("routes")]
    if fails:
        lines += ["", f"## 못 모은 곳 {len(fails)}곳", ""]
        for r in fails:
            lines.append(f"- {r['name']} (`{r['id']}`): {why_failed(r)}")
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
