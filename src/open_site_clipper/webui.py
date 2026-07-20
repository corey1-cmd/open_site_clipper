"""로컬 웹 UI(--serve) — cmd 대신 브라우저에서 조직을 골라 클릭으로 쓴다.

CLI와 같은 계층(collect·brief·discover·render)을 부르는 얇은 껍데기다.
표준 라이브러리 http.server만 쓰므로 의존성 0 원칙이 유지되고, 127.0.0.1에만
바인딩하므로 같은 컴퓨터에서만 접속된다(개인용 로컬 도구 — 인터넷 배포용 아님).

화면 구성:
  ① 조직 선택 — 정부·공공기관(내장) + 작업 폴더의 출처 JSON 들(HUFS 프리셋,
     --discover 로 추가한 대학)이 자동으로 목록에 뜬다. 여러 개 동시 선택 가능.
  ② 옵션 — 기관 묶기(org 축)·발췌 유지(quote_mode=full)·신규 🆕(--state)·최근 N일
  ③ 검색(선택) — 목적어(고용·복지·정부투자… 또는 아무 키워드)를 넣으면
     관련 자료만 골라 브리프로. 비우면 전체 보고서.
  ④ 조직 추가 — 대학 홈페이지 주소로 --discover 를 돌려 초안을 저장하면
     곧바로 ①의 목록에 나타난다.

수집은 실제 네트워크 요청이라 수십 초 걸릴 수 있고, 그동안 브라우저는
기다린다(개인용 도구로서 의도된 단순함).
"""

from __future__ import annotations

import contextlib
import json
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import (
    brief,
    brief_report,
    collect,
    digest,
    discover,
    purposes,
    report,
    sources,
    state,
)
from .report import _esc

DEFAULT_PORT = 8765
GOV_ID = "builtin:gov"
STATE_FILE = "webui-state.json"
_MAX_BODY = 64 * 1024  # 폼 본문 상한 — 로컬 도구에 이 이상은 비정상


# ── 조직 목록 ────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class OrgOption:
    """조직 선택지 하나 — 내장 프리셋이거나 작업 폴더의 출처 JSON."""

    id: str  # "builtin:gov" 또는 workspace 기준 상대 경로
    label: str
    count: int


def _label_for(srcs: list[sources.Source], fallback: str) -> str:
    orgs = sorted({s.org for s in srcs if s.org})
    return " · ".join(orgs) if orgs else fallback


def _scan_files(workspace: Path) -> list[tuple[Path, list[sources.Source]]]:
    found: list[tuple[Path, list[sources.Source]]] = []
    candidates = sorted(workspace.glob("*.json")) + sorted(workspace.glob("examples/*.json"))
    for path in candidates:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        items = raw.get("sources") if isinstance(raw, dict) else raw
        srcs = sources.from_dicts(items if isinstance(items, list) else [])
        if srcs:
            found.append((path, srcs))
    return found


def org_options(workspace: Path) -> list[OrgOption]:
    """선택 가능한 조직 목록 — 내장 정부 프리셋 + 유효한 출처 JSON 파일들."""
    out = [OrgOption(GOV_ID, "정부·공공기관 (내장 기본)", len(sources.default_sources()))]
    for path, srcs in _scan_files(workspace):
        rel = path.relative_to(workspace).as_posix()
        out.append(OrgOption(rel, _label_for(srcs, path.stem), len(srcs)))
    return out


def build_sources(ids: list[str], workspace: Path) -> list[sources.Source]:
    """선택된 조직 id 들을 출처 목록으로 — 목록에 없는 id 는 거부(경로 주입 방지)."""
    valid = {o.id for o in org_options(workspace)}
    merged: list[sources.Source] = []
    for oid in ids:
        if oid not in valid:
            raise ValueError(f"알 수 없는 조직 선택: {oid}")
        if oid == GOV_ID:
            merged.extend(sources.default_sources())
        else:
            raw = json.loads((workspace / oid).read_text(encoding="utf-8"))
            items = raw.get("sources") if isinstance(raw, dict) else raw
            merged.extend(sources.from_dicts(items if isinstance(items, list) else []))
    return merged


# ── 실행 파이프라인 (CLI main 의 축약판 — 같은 모듈을 부른다) ────────────────
def run_report(
    ids: list[str],
    *,
    workspace: Path,
    query: str = "",
    group_org: bool = False,
    quote_full: bool = False,
    mark_new: bool = False,
    since: int | None = None,
    fetcher: collect.Fetcher | None = None,
) -> str:
    """조직 선택 + 옵션 → 완성 HTML 문자열(웹 응답으로 그대로 내보낸다)."""
    srcs = build_sources(ids, workspace)
    if not srcs:
        raise ValueError("선택된 조직에 유효한 출처가 없습니다.")
    quote = collect.QUOTE_FULL if quote_full else collect.QUOTE_CONSERVATIVE
    rep = collect.collect(srcs, since_days=since, fetcher=fetcher, quote_mode=quote)
    rep.group_by = "org" if group_org else "agency"

    if mark_new:
        state_path = workspace / STATE_FILE
        seen = state.load(state_path)
        keys = {n.dedup_key() for n in rep.notices}
        if seen is not None:
            rep.notices = state.mark_new(rep.notices, seen)
        # 상태만 못 남긴 것 — 보고서 생성은 계속한다.
        with contextlib.suppress(OSError):
            state.save(state_path, current_keys=keys, previous=seen, updated_at=rep.generated_at)

    if query.strip():
        theme = purposes.build_theme(query)
        bf = brief.build(
            rep.notices,
            theme,
            generated_at=rep.generated_at,
            since_days=rep.since_days,
            failed_sources=rep.failed_sources,
        )
        return brief_report.render_html(bf)

    if rep.notices:
        rep.digest = digest.build(rep.notices)
    return report.render_html(rep)


# ── 페이지 렌더 ──────────────────────────────────────────────────────────────
_UI_CSS = """
body { max-width: 880px; }
.card { background: #f8f9fc; border: 1px solid #eef; border-radius: 12px;
  padding: 1rem 1.2rem; margin-bottom: 1.2rem; }
.card h2 { margin: 0 0 .6rem; border: none; font-size: 1.05rem; }
.orgs label { display: block; padding: .3rem 0; }
.opts label { display: inline-block; margin-right: 1.1rem; padding: .2rem 0; }
input[type=text], input[type=url], input[type=number] { padding: .35rem .5rem;
  border: 1px solid #ccd; border-radius: 6px; font-size: .95rem; }
button { background: #191970; color: #fff; border: none; border-radius: 8px;
  padding: .5rem 1.1rem; font-size: .95rem; cursor: pointer; }
.hint { font-size: .82rem; color: #667; margin-top: .4rem; }
.note { font-size: .85rem; color: #667; }
@media (prefers-color-scheme: dark) {
  .card { background: #12151c; border-color: #262a35; }
  input[type=text], input[type=url], input[type=number] { background: #0e1116;
    color: #e6e8ee; border-color: #333a48; }
}
"""

_BUSY_JS = (
    "const b=this.querySelector('button');b.disabled=true;"
    "b.textContent='생성 중… (수십 초 걸릴 수 있어요)';"
)


def _page(title: str, body: str) -> bytes:
    html = (
        "<!DOCTYPE html>\n"
        '<html lang="ko"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_esc(title)}</title>\n"
        f"<style>{report._CSS}{_UI_CSS}</style></head><body><main>\n"
        f"{body}\n"
        '<footer><p class="note">open_site_clipper 로컬 웹 UI — 127.0.0.1 전용, '
        "이 컴퓨터에서만 접속됩니다. 인터넷 배포용이 아닙니다. 관련 자료 링크 수집은 "
        "CLI <code>--deep-links</code> 로.</p></footer></main></body></html>"
    )
    return html.encode()


def form_page(workspace: Path) -> bytes:
    opts = org_options(workspace)
    org_rows = "\n".join(
        f'<label><input type="checkbox" name="org" value="{_esc(o.id)}"'
        f"{' checked' if o.id == GOV_ID else ''}> {_esc(o.label)}"
        f" <small>(출처 {o.count}곳)</small></label>"
        for o in opts
    )
    body = f"""
<h1>open_site_clipper</h1>
<p class="meta">조사할 조직을 고르고, 버튼 하나로 보고서를 만듭니다.</p>

<form method="post" action="/run" onsubmit="{_BUSY_JS}">
<div class="card"><h2>① 조직 선택</h2>
<div class="orgs">{org_rows}</div>
<p class="hint">아래 ③에서 대학을 추가하면 이 목록에 자동으로 나타납니다. 여러 조직을 함께 골라도 됩니다.</p>
</div>

<div class="card"><h2>② 옵션</h2>
<div class="opts">
<label><input type="checkbox" name="group_org"> 기관→사이트→부서로 묶기 <small>(대학용)</small></label>
<label><input type="checkbox" name="quote_full"> 발췌 유지 <small>(공공누리 표기 없는 대학 공지용)</small></label>
<label><input type="checkbox" name="mark_new"> 이전 실행 대비 신규 🆕 표시</label>
<label>최근 <input type="number" name="since" min="0" style="width:4.5rem"> 일만 <small>(비우면 전체)</small></label>
</div>
<p style="margin-top:.7rem"><label>검색어(선택): <input type="text" name="query" size="28"
 placeholder="예: 고용 · 장학 · 정부투자 · AI"></label></p>
<p class="hint">검색어를 넣으면 관련 자료만 골라 근거 키워드와 함께 브리프로 만듭니다. 비우면 전체 보고서.</p>
<p style="margin-top:.8rem"><button type="submit">보고서 만들기</button></p>
</div>
</form>

<div class="card"><h2>③ 조직 추가 — 대학·기관 자동 탐지</h2>
<form method="post" action="/discover" onsubmit="{_BUSY_JS}">
<label>홈페이지 주소: <input type="url" name="url" size="42"
 placeholder="https://www.knou.ac.kr/knou/index.do" required></label>
<button type="submit" style="margin-left:.5rem">탐지</button>
</form>
<p class="hint">RSS 자동발견과 K2Web 좌표를 찾아 출처 초안을 저장합니다. robots.txt 를 지키며, 초안은 검토 대상입니다.</p>
</div>
"""
    return _page("open_site_clipper — 로컬 웹 UI", body)


def discover_page(res: discover.Discovery, saved: str | None, workspace: Path) -> bytes:
    rows = "\n".join(
        "<tr>"
        f"<td>{_esc(e.get('kind', ''))}</td>"
        f"<td>{_esc(e.get('category') or e.get('name', ''))}</td>"
        f"<td>{_esc(str(e.get('board_id', '')) or e.get('url', ''))}</td>"
        f"<td>{'✔ 검증' if e.get('_verified') else '미검증'}</td>"
        "</tr>"
        for e in res.entries
    )
    notes = "".join(f'<p class="warn">· {_esc(n)}</p>' for n in res.notes)
    if res.entries and saved:
        action = f"""
<p>저장됨: <b>{_esc(saved)}</b> — 메인 화면의 조직 목록에 추가되었습니다.</p>
<form method="post" action="/run" onsubmit="{_BUSY_JS}">
<input type="hidden" name="org" value="{_esc(saved)}">
<input type="hidden" name="group_org" value="on">
<input type="hidden" name="quote_full" value="on">
<button type="submit">이 조직으로 바로 보고서</button></form>"""
    else:
        action = "<p>저장된 초안이 없습니다 — 주소를 게시판 페이지로 바꿔 다시 시도해 보세요.</p>"
    body = f"""
<h1>탐지 결과 — {_esc(res.org or res.start_url)}</h1>
<p class="meta">후보 {len(res.entries)}건 · 검증 {res.verified_count}건 · 요청 {res.fetched}회</p>
{notes}
<div class="card">
<table><thead><tr><th>종류</th><th>이름/분류</th><th>좌표·주소</th><th>검증</th></tr></thead>
<tbody>{rows or "<tr><td colspan=4>후보 없음</td></tr>"}</tbody></table>
{action}
</div>
<p><a href="/">← 메인으로</a></p>
"""
    return _page("탐지 결과", body)


def error_page(message: str, status: int = 400) -> tuple[int, bytes]:
    body = (
        f"<h1>문제가 생겼습니다</h1><div class='card'><p>{_esc(message)}</p></div>"
        '<p><a href="/">← 메인으로</a></p>'
    )
    return status, _page("오류", body)


# ── HTTP 핸들러 ──────────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    server_version = "open_site_clipper"

    @property
    def workspace(self) -> Path:
        return self.server.workspace  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[webui] {self.command} {self.path}", flush=True)

    def _send(self, status: int, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _form(self) -> dict[str, list[str]]:
        length = min(int(self.headers.get("Content-Length") or 0), _MAX_BODY)
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return urllib.parse.parse_qs(raw, keep_blank_values=True)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, form_page(self.workspace))
        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self._send(*error_page("없는 페이지입니다.", 404))

    def do_POST(self) -> None:
        form = self._form()
        try:
            if self.path == "/run":
                ids = form.get("org", [])
                if not ids:
                    self._send(*error_page("조직을 하나 이상 선택해 주세요."))
                    return
                since_raw = (form.get("since", [""])[0] or "").strip()
                html = run_report(
                    ids,
                    workspace=self.workspace,
                    query=form.get("query", [""])[0],
                    group_org=bool(form.get("group_org")),
                    quote_full=bool(form.get("quote_full")),
                    mark_new=bool(form.get("mark_new")),
                    since=int(since_raw) if since_raw.isdigit() else None,
                )
                self._send(200, html.encode())
            elif self.path == "/discover":
                url = (form.get("url", [""])[0] or "").strip()
                if not url:
                    self._send(*error_page("탐지할 주소를 입력해 주세요."))
                    return
                res = discover.discover(url)
                saved = None
                if res.entries:
                    name = f"조직-{_safe_name(res.org or 'site')}.json"
                    (self.workspace / name).write_text(res.to_sources_json(), encoding="utf-8")
                    saved = name
                self._send(200, discover_page(res, saved, self.workspace))
            else:
                self._send(*error_page("없는 경로입니다.", 404))
        except ValueError as e:
            self._send(*error_page(str(e)))
        except Exception as e:
            self._send(*error_page(f"실행 중 오류: {e}", 500))


def _safe_name(text: str) -> str:
    """파일명으로 안전한 조직 이름 — 한글·영숫자만 남긴다(isalnum 은 한글 포함)."""
    keep = "".join(c if c.isalnum() else "-" for c in text)
    return (keep.strip("-") or "site")[:30]


# ── 서버 기동 ────────────────────────────────────────────────────────────────
def serve(
    port: int = DEFAULT_PORT, *, workspace: Path | None = None, open_browser: bool = True
) -> None:
    """127.0.0.1 전용 서버를 띄우고(포트 점유 시 친절히 종료) 브라우저를 연다."""
    ws = (workspace or Path.cwd()).resolve()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    except OSError as e:
        raise SystemExit(
            f"포트 {port} 를 열 수 없습니다({e}). --port 로 다른 번호를 지정해 보세요."
        ) from e
    server.workspace = ws  # type: ignore[attr-defined]
    url = f"http://127.0.0.1:{port}/"
    print(f"로컬 웹 UI 시작: {url}  (끝내려면 Ctrl+C) · 작업 폴더: {ws}", flush=True)
    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n웹 UI 를 종료합니다.", flush=True)
    finally:
        server.server_close()
