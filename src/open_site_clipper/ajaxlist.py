"""스크립트로 불러오는 게시판 목록(AJAX) — 사이트 스크립트가 보내는 목록 요청을 읽어 그대로 한다.

목록 화면에 글 줄이 하나도 없고, 화면을 연 뒤 스크립트가 목록을 따로 받아 그리는 게시판이
있다(실측 2026-10-12: 중앙대 FR_CON '/ajax/FR_SVC/BBSViewList2.do' · 삼육보건대 FrCon
'/ajaxf/FrBoardSvc/bbsViewList.do' · 동원대 '/bbs/ajax/boardList.do' — 학교가 통째로 0건이거나
대표 공지가 빠졌다). 이 모듈은 그 요청을 **읽어서**(실행하지 않는다) 같은 요청을 한 번 보내고,
받은 목록을 사이트의 줄 틀(jquery.tmpl · handlebars 템플릿, tmpl 모듈)로 그려 원래 화면 뒤에
붙인다. 그러면 기존 표 파서(govweb)와 스크립트 링크 풀이(scriptlink)가 그대로 읽는다.

읽는 요청의 꼴:

    $.ajax({ url: '/bbs/ajax/boardList.do', data: { bsIdx: $('#bsIdx').val(), page: page } })
    fn_comm_ajax({ url: "/ajax/FR_SVC/BBSViewList2.do", data: $("#sendForm").serialize() })
    $.post('/board/list.do', { boardId: 'B1' }, function (json) { … })
    $('#list').load('/board/listAjax.do', $('#frm').serialize())

요청은 GET 으로 보낸다(값은 쿼리로). 사이트가 POST 로 보내는 요청도 대개 GET 으로 같은
목록을 준다 — 주지 않으면 그 게시판은 지금처럼 0건으로 남는다. robots.txt 판정은 요청
주소마다 다시 받는다.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field

from . import scriptlink, tmpl
from .fetch import POST_MARK
from .k2web_parse import coerce_date

MARK = b"\n<!--osc:ajax-->\n"  # 원래 화면과 그려 붙인 목록의 경계(다음 쪽을 다시 그릴 때 쓴다)
MAX_CALLS = 2  # 화면 하나에서 시도할 목록 요청 수
MAX_ROWS = 80

# 목록 요청이 아닌 것 — 분류·댓글·메뉴·로그인·조회수·단축 주소·원서 …
_NOISE_RE = re.compile(
    r"categor|comment|reply|repl[ey]|menu|banner|popup|popzone|login|logout|auth|chk|check|"
    r"count|cnt\b|stat|popular|keyword|shorturl|file|down|upload|zip|like|recommend|visit|"
    r"delete|insert|update|save|write|regist|pwd|passw|captcha|sms|wonseo|mypage|"
    r"calendar|schedule|weather|survey|poll|vote|chatbot|tab(?:list|content)|proc\b|proc\.|"
    r"restore|copy|move",
    re.I,
)
_PAGE_KEY_RE = re.compile(
    r"^(?:page|pageno|pageindex|pagenum|pagenumber|currentpage|curpage|cpage|pg|nowpage|"
    r"page_no|page_index|pageidx|pagecnt?)$",
    re.I,
)
_HINT_RE = re.compile(r"tmpl|template|tbody|setlist|render|\.html\(|append\(|list|handlebars", re.I)
_CALL_RE = re.compile(
    r"(?<![\w$.])((?:\$|jQuery)\s*\.\s*(?:ajax|post|get|getJSON)|"
    r"(?:\$|jQuery)\s*\(\s*['\"][^'\"]*['\"]\s*\)\s*\.\s*load|"
    r"[A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*)\s*\("
)
_NOT_HELPERS = frozenset({"if", "for", "while", "switch", "function", "return", "catch", "alert"})


@dataclass(slots=True)
class Call:
    """화면 스크립트에서 읽은 목록 요청 하나."""

    url: str  # 절대 주소(사이트가 붙인 쿼리 포함)
    pairs: list[tuple[str, str]]  # 보내는 값
    method: str = "get"
    html: bool = False  # 응답이 HTML 조각(.load · dataType: 'html')
    hints: str = ""  # 성공 처리 몸통(틀 이름·항목 경로를 찾는다)
    score: int = 0
    code: str = field(default="", repr=False)  # 요청이 든 스크립트(틀 변수를 찾는다)

    def request_url(self, page: int = 1) -> str:
        pairs = []
        for k, v in self.pairs:
            if _PAGE_KEY_RE.match(k):
                v = str(page) if page > 1 or not v.strip().isdigit() else v
            pairs.append((k, v))
        if page > 1 and not any(_PAGE_KEY_RE.match(k) for k, _ in pairs):
            return ""  # 쪽 값을 모르는 요청 — 다음 쪽을 지어내지 않는다
        parts = urllib.parse.urlsplit(self.url)
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        keys = {k for k, _ in pairs}
        merged = [(k, v) for k, v in query if k not in keys] + pairs
        return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(merged)))


# ── 요청 읽기 ─────────────────────────────────────────────────────────────────
def find_calls(ctx: scriptlink._Ctx) -> list[Call]:
    """화면(과 같은 사이트의 게시판 스크립트)에서 목록 요청들 — 유력한 것부터."""
    out: list[Call] = []
    seen: set[str] = set()
    for code in ctx.parts.scripts:
        for call in _calls_in(code, ctx):
            key = call.request_url()
            if key not in seen:
                seen.add(key)
                out.append(call)
    out.sort(key=lambda c: -c.score)
    return out


def _calls_in(code: str, ctx: scriptlink._Ctx) -> list[Call]:
    if not re.search(r"ajax|\$\.post|\$\.get|\.load\s*\(|url\s*:", code):
        return []
    code = scriptlink._strip_comments(code)
    run = scriptlink._Run(ctx, {})
    found: list[Call] = []
    for m in _CALL_RE.finditer(code):
        name = re.sub(r"\s+", "", m.group(1))
        short = name.rsplit(".", 1)[-1]
        if short in _NOT_HELPERS:
            continue
        jq = name.startswith(("$", "jQuery")) and short in (
            "ajax",
            "post",
            "get",
            "getJSON",
            "load",
        )
        if not jq and not re.match(r"\s*\{[^;]{0,600}?\burl\s*:", code[m.end() : m.end() + 700]):
            continue  # 주소를 싣지 않는 호출 — 괄호 짝을 찾지 않고 넘어간다
        open_at = m.end() - 1
        close = scriptlink._close_paren(code, open_at)
        if close < 0:
            continue
        args = scriptlink.split_top(code[open_at + 1 : close], ",")
        first = args[0].strip() if args else ""
        tail = code[close + 1 : close + 400]
        opts: dict[str, str] = {}
        url_expr = data_expr = ""
        method = "get"
        hints = ""
        is_html = False
        if name.endswith(".load"):
            url_expr = first
            if len(args) > 1 and not args[1].strip().startswith("function"):
                data_expr = args[1].strip()
            hints = ",".join(args[1:])
            is_html = True
        elif short in ("post", "get", "getJSON") and name.startswith(("$", "jQuery")):
            url_expr = first
            for a in args[1:]:
                a = a.strip()
                if a.startswith(("function", "(")) or "=>" in a[:40]:
                    hints += a
                elif not data_expr:
                    data_expr = a
            method = "post" if short == "post" else "get"
        else:
            if first.startswith("{"):
                opts = dict(scriptlink._object_pairs(first))
            elif short == "ajax" and len(args) > 1 and args[1].strip().startswith("{"):
                opts = dict(scriptlink._object_pairs(args[1].strip()))
                opts.setdefault("url", first)
            if "url" not in opts:
                continue
            url_expr = opts.get("url", "")
            data_expr = opts.get("data", "")
            method = (
                run.value(opts.get("type") or opts.get("method") or "'get'", {}, True, 0) or "get"
            ).lower()
            kind = (run.value(opts.get("dataType", "''"), {}, True, 0) or "").lower()
            is_html = kind == "html"
            hints = " ".join(v for k, v in opts.items() if k in ("success", "complete", "done"))
            if kind == "jsonp" or opts.get("contentType", "").find("json") >= 0:
                continue  # JSONP·JSON 본문 요청은 따라 하지 않는다
        hints += " " + tail
        call = _make_call(url_expr, data_expr, method, is_html, hints, code, run, ctx)
        if call is not None:
            found.append(call)
    return found


def _make_call(
    url_expr: str,
    data_expr: str,
    method: str,
    is_html: bool,
    hints: str,
    code: str,
    run: scriptlink._Run,
    ctx: scriptlink._Ctx,
) -> Call | None:
    if not url_expr:
        return None
    url = run.value(url_expr, {}, False, 0)
    if url is None:
        url = run.value(url_expr, {}, True, 0)
    url = scriptlink._absolute(url or "", ctx.page_url)
    if not url:
        return None
    page = urllib.parse.urlsplit(ctx.page_url)
    target = urllib.parse.urlsplit(url)
    if target.hostname != page.hostname:
        return None  # 다른 사이트로 가는 요청 — 그 사이트 목록은 그 사이트 몫
    tail = "/".join(target.path.split("/")[-2:])
    if _NOISE_RE.search(tail) or re.match(r"main", target.path.rsplit("/", 1)[-1], re.I):
        return None
    pairs = _pairs_of(data_expr, code, run, ctx)
    if pairs is None:
        return None
    listy = bool(re.search(r"list", tail, re.I))
    hinted = bool(_HINT_RE.search(hints))
    if not (_primary(data_expr, pairs, url, ctx.page_url) and (listy or hinted)):
        # 이 화면의 게시판 요청이라는 표시가 없다 — 다른 화면의 곁다리 목록(최신글 위젯)일 수 있다
        return None
    score = 3 * listy + hinted
    return Call(url, pairs, method, is_html, hints[:1500], score, code)


def _primary(data_expr: str, pairs: list[tuple[str, str]], url: str, page_url: str) -> bool:
    """이 화면의 게시판을 부르는 요청인가 — 화면의 폼을 통째로 싣거나(serialize), 화면 주소의
    값(메뉴·게시판 번호)이나 주소 조각('community01_01')을 싣는다."""
    if "serialize" in data_expr:
        return True
    page = urllib.parse.urlsplit(page_url)
    marks = {v for _k, v in urllib.parse.parse_qsl(page.query) if len(v) >= 2}
    marks |= {
        s.rsplit(".", 1)[0]
        for s in page.path.split("/")
        if len(s.rsplit(".", 1)[0]) >= 4 and not _GENERIC_SEG_RE.fullmatch(s.rsplit(".", 1)[0])
    }
    sent = {v for _k, v in pairs} | set(urllib.parse.urlsplit(url).path.split("/"))
    sent |= {v for _k, v in urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)}
    return bool(marks & sent)


_GENERIC_SEG_RE = re.compile(
    r"(?:index|main|list|board|bbs|boards|notice|view|cms|content|contents|page|sub|kor|eng|"
    r"ko|en|www|web|home|site|user|front|portal)\w{0,3}",
    re.I,
)


def _pairs_of(
    expr: str, code: str, run: scriptlink._Run, ctx: scriptlink._Ctx, depth: int = 0
) -> list[tuple[str, str]] | None:
    """요청 값 식 → (이름, 값) 목록. 따라 할 수 없는 꼴(JSON 본문)이면 None."""
    expr = (expr or "").strip()
    if not expr:
        return []
    if depth > 3 or "JSON.stringify" in expr or "FormData" in expr:
        return None
    if expr.startswith("{"):
        out = []
        for key, value_expr in scriptlink._object_pairs(expr):
            v = value_expr.strip()
            if not key or v.startswith(("function", "{", "[")) or "=>" in v[:30]:
                continue
            got = run.value(v, {}, False, 0)
            if got is None:
                got = run.value(v, {}, True, 0)
            out.append((key, got or ""))
        return out
    pieces = scriptlink.split_top(expr, "+")
    if any(".serialize" in p for p in pieces):
        out = []
        for piece in pieces:
            piece = piece.strip()
            sm = re.fullmatch(r"(.+?)\s*\.\s*serialize(?:Array)?\(\s*\)", piece, re.S)
            if sm:
                out += _serialize(sm.group(1), run, ctx)
                continue
            text = run.value(piece, {}, True, 0) or ""
            out += urllib.parse.parse_qsl(text.lstrip("&?"), keep_blank_values=True)
        return out
    if re.fullmatch(r"[A-Za-z_$][\w$]*", expr):
        # 값을 미리 담아 둔 변수 — var param = { … } · param = $('#frm').serialize()
        m = re.search(r"(?<![\w$.])" + re.escape(expr) + r"\s*=\s*(?!=)", code)
        if m:
            rest = code[m.end() :]
            if rest.startswith("{"):
                body = scriptlink._block(rest, 1)
                return _pairs_of("{" + body + "}", code, run, ctx, depth + 1)
            stmt, _ = scriptlink._simple(rest, 0)
            return _pairs_of(stmt, code, run, ctx, depth + 1)
        return []
    text = run.value(expr, {}, True, 0) or ""
    return urllib.parse.parse_qsl(text.lstrip("&?"), keep_blank_values=True)


def _serialize(ref: str, run: scriptlink._Run, ctx: scriptlink._Ctx) -> list[tuple[str, str]]:
    """$('#frm').serialize() — 폼의 값 전부(브라우저처럼 고르지 않은 체크·단추·사용 안 함은 뺀다)."""
    idx = run.form_of(ref, {})
    if idx is None:
        idx = run.form_of(f"$({ref})", {})
    if idx is None:
        return []
    form = ctx.parts.forms[idx]
    out = []
    for i, (name, value, _iid) in enumerate(form.inputs):
        kind = form.types[i] if i < len(form.types) else "text"
        if not name or ":disabled" in kind:
            continue
        base = kind.split(":", 1)[0]
        if base in ("submit", "button", "image", "reset", "file"):
            continue
        if base in ("checkbox", "radio") and ":checked" not in kind:
            continue
        out.append((name, value))
    return out


# ── 응답 그리기 ───────────────────────────────────────────────────────────────
def _payload(data: bytes) -> object | None:
    from .fetch import decode_text

    text = decode_text(data).lstrip("﻿ \t\r\n")
    if text.startswith(")]}'"):
        text = text.split("\n", 1)[-1]
    if text[:1] in "{[":
        try:
            return json.loads(text)
        except ValueError:
            return None
    m = re.match(r"[\w$.]+\s*\(\s*([\[{].*[\]}])\s*\)\s*;?\s*$", text, re.S)  # JSONP
    if m:
        try:
            return json.loads(m.group(1))
        except ValueError:
            return None
    return None


_TITLE_KEY_RE = re.compile(r"title|subject|sj$|ttl|nttsj|제목", re.I)
_DATE_KEY_RE = re.compile(r"date|dt$|dttm|regdt|reg_?dt|wdate|created|insert|pnttm|writ|등록", re.I)
_LINK_KEY_RE = re.compile(r"url|link|href", re.I)
_BODY_KEY_RE = re.compile(r"content|contents|cn$|body|text|summary|desc|html", re.I)


def _is_title(value: object) -> bool:
    if not isinstance(value, str):
        return False
    t = " ".join(value.split())
    return (
        4 <= len(t) <= 200
        and bool(re.search(r"[가-힣A-Za-z]", t))
        and not t.startswith(("http://", "https://", "/"))
        and coerce_date(t) is None
    )


def _date_of(value: object):
    if isinstance(value, (int, float, dict, list)) and not isinstance(value, bool):
        return coerce_date(tmpl.text_of(value))
    return coerce_date(value) if isinstance(value, str) and len(value) <= 40 else None


def item_lists(payload: object) -> list[tuple[str, list[dict]]]:
    """JSON 안의 '글 목록'다운 배열들 — 제목감과 날짜가 함께 있는 항목이 많은 것부터."""
    found: list[tuple[int, str, list[dict]]] = []

    def walk(obj: object, path: str, depth: int) -> None:
        if depth > 5:
            return
        if isinstance(obj, list):
            dicts = [x for x in obj if isinstance(x, dict)]
            if dicts and len(dicts) * 2 >= len(obj):
                score = 0
                for item in dicts[:20]:
                    titled = any(_is_title(v) for v in item.values())
                    dated = any(_date_of(v) for v in item.values())
                    score += 2 * (titled and dated) + titled
                if score:
                    found.append((score, path, dicts))
            for i, x in enumerate(obj[:2]):
                walk(x, f"{path}.{i}" if path else str(i), depth + 1)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else k, depth + 1)

    walk(payload, "", 0)
    found.sort(key=lambda t: (-t[0], -len(t[2])))
    return [(p, items) for _s, p, items in found]


def _pick_template(
    parts: scriptlink.PageParts, call: Call, keys: set[str]
) -> scriptlink.Template | None:
    """응답을 그릴 틀 — 성공 처리에서 부르는 틀(id·변수), 없으면 항목 이름을 가장 많이 쓰는 틀."""
    tmpls = [t for t in parts.templates if t.id and ("{{" in t.body or "${" in t.body)]
    if not tmpls:
        return None
    by_id = {t.id: t for t in tmpls}
    for m in re.finditer(r"""['"]#?([\w-]+)['"]""", call.hints):
        if m.group(1) in by_id:
            return by_id[m.group(1)]
    # 틀을 담은 변수 — var listTemplate = $('#list-template').html() · Handlebars.compile(…)
    for name in re.findall(r"[A-Za-z_$][\w$]*", call.hints):
        if name in by_id:
            return by_id[name]
        m = re.search(
            r"(?<![\w$.])" + re.escape(name) + r"""\s*=\s*[^;\n]*?['"]#([\w-]+)['"]""",
            "\n".join(parts.scripts),
        )
        if m and m.group(1) in by_id:
            return by_id[m.group(1)]
    best, overlap = None, 1
    for t in tmpls:
        n = len(tmpl.placeholders(t.body) & keys)
        if n > overlap:
            best, overlap = t, n
    return best


def render(
    data: bytes, call: Call, parts: scriptlink.PageParts, explain: dict | None = None
) -> str:
    """받은 응답 → 목록 HTML(못 그리면 "")."""
    from .fetch import decode_text

    payload = _payload(data)
    if payload is None:
        text = decode_text(data)
        if re.search(r"<(?:tr|li)\b", text, re.I) and not re.search(r"<html\b", text[:500], re.I):
            if explain is not None:
                explain["kind"] = "html"
            return text  # HTML 조각(.load)
        if explain is not None:
            explain["kind"] = "other"
        return ""
    if explain is not None:
        explain["kind"] = "json"
        explain["skeleton"] = skeleton(payload)
    # 응답 안에 이미 그려진 HTML 이 든 경우({"html": "<tr>…</tr>"})
    if isinstance(payload, dict):
        for v in payload.values():
            if isinstance(v, str) and re.search(r"<(?:tr|li)\b", v, re.I):
                return v
    lists = item_lists(payload)
    if not lists:
        return ""
    path, items = lists[0]
    keys = set().union(*(set(i) for i in items[:5]))
    template = _pick_template(parts, call, keys)
    if explain is not None:
        explain["items"] = f"{path or '(root)'} × {len(items)}"
        explain["template"] = template.id if template else ""
    if template is not None:
        nodes = tmpl.parse(template.body)
        if re.search(r"\{\{\s*#\s*each\b", template.body) and isinstance(payload, dict):
            out = tmpl.render(nodes, payload)  # 틀이 응답 전체를 돈다(handlebars)
            if re.search(r"<(?:tr|li|div|a)\b", out, re.I):
                return _wrap(out)
        rows = [tmpl.render(nodes, item) for item in items[:MAX_ROWS]]
        return _wrap("".join(rows))
    return _wrap("".join(_auto_row(item) for item in items[:MAX_ROWS]))


def _auto_row(item: dict) -> str:
    """틀이 없을 때 — 제목·날짜·(있으면) 주소만으로 한 줄."""
    import html as _html

    title_key = next((k for k, v in item.items() if _TITLE_KEY_RE.search(k) and _is_title(v)), None)
    if title_key is None:
        cands = [
            (len(str(v)), k) for k, v in item.items() if _is_title(v) and not _BODY_KEY_RE.search(k)
        ]
        title_key = max(cands)[1] if cands else None
    if title_key is None:
        return ""
    date_text = ""
    for _k, v in sorted(item.items(), key=lambda kv: 0 if _DATE_KEY_RE.search(kv[0]) else 1):
        d = _date_of(v)
        if d:
            date_text = d.isoformat()
            break
    link = next(
        (
            v
            for k, v in item.items()
            if _LINK_KEY_RE.search(k)
            and isinstance(v, str)
            and v.startswith(("http://", "https://", "/"))
        ),
        "javascript:void(0)",
    )
    title = _html.escape(" ".join(str(item[title_key]).split()))
    return f'<tr><td><a href="{_html.escape(link)}">{title}</a></td><td>{date_text}</td></tr>'


def _wrap(rows_html: str) -> str:
    if not rows_html.strip():
        return ""
    head = rows_html.lstrip()[:20].lower()
    if head.startswith("<tr"):
        return f'<table class="osc-ajax"><tbody>{rows_html}</tbody></table>'
    if head.startswith("<li"):
        return f'<ul class="osc-ajax">{rows_html}</ul>'
    return f'<div class="osc-ajax">{rows_html}</div>'


def skeleton(obj: object, depth: int = 0) -> object:
    """점검용 — JSON 의 모양(열쇠·배열 길이·값 앞 몇 자)."""
    if depth > 4:
        return "…"
    if isinstance(obj, dict):
        return {k: skeleton(v, depth + 1) for k, v in list(obj.items())[:30]}
    if isinstance(obj, list):
        return [f"×{len(obj)}", skeleton(obj[0], depth + 1)] if obj else []
    if isinstance(obj, str):
        return obj[:24]
    return obj


# ── 한 화면 → 목록을 붙인 화면 ───────────────────────────────────────────────
def maybe_ajax(data: bytes) -> bool:
    """값싼 사전 판정 — 스크립트로 목록을 부를 만한 화면인가."""
    return bool(re.search(rb"\$\.ajax|jQuery\.ajax|\$\.post|\$\.get|\.load\(|url\s*:", data))


def original(data: bytes) -> bytes:
    """붙여 그린 목록을 뗀 원래 화면."""
    return data.split(MARK, 1)[0]


def expand(
    data: bytes,
    page_url: str,
    fetch: Callable[[str], bytes | None] | None,
    allowed: Callable[[str], bool] | None = None,
    *,
    page: int = 1,
    explain: dict | None = None,
) -> bytes | None:
    """목록이 비어 있는 화면에서 스크립트의 목록 요청을 따라 해 그린 목록을 붙인다.

    목록 요청을 못 찾았거나, 받은 것이 목록이 아니면 None — 부르는 쪽은 원래 화면을 쓴다.
    page > 1 이면 같은 요청의 쪽 값만 바꾼다(쪽 값이 없는 요청이면 None).
    """
    from .fetch import decode_text

    if fetch is None or not data:
        return None
    data = original(data)
    if not maybe_ajax(data):
        return None
    text = decode_text(data)
    parts = scriptlink.page_parts(text)
    # 값 읽기에는 화면 안의 것만 쓴다(같은 사이트 스크립트 파일을 더 받지 않는다)
    calls = find_calls(scriptlink._Ctx(parts, page_url, None))
    if explain is not None:
        explain["calls"] = [
            {"url": c.request_url(page)[:300], "method": c.method, "score": c.score}
            for c in calls[:4]
        ]
        explain["templates"] = [f"{t.id}:{t.type}" for t in parts.templates][:10]
    for call in calls[:MAX_CALLS]:
        url = call.request_url(page)
        if not url:
            continue
        if allowed is not None and not allowed(url):
            if explain is not None:
                explain.setdefault("tried", []).append(
                    {"url": url[:300], "error": "robots.txt 차단"}
                )
            continue
        key = (urllib.parse.urlsplit(url).netloc, urllib.parse.urlsplit(url).path)
        # GET 이 먼저 — 사이트가 POST 로 보내고 GET 으로는 목록을 안 주면(405·빈 응답) 같은 POST 로
        tries = [url]
        if call.method == "post":
            tries = [url + POST_MARK] if _METHOD.get(key) == "post" else [url, url + POST_MARK]
        for target in tries:
            step: dict = {"url": target[:300]}
            if explain is not None:
                explain.setdefault("tried", []).append(step)
            got = fetch(target)
            step["bytes"] = len(got or b"")
            if not got:
                why = getattr(fetch, "why", None)
                step["error"] = why(target) if callable(why) else "응답 없음"
                continue
            rows = render(got, call, parts, step)
            step["rendered"] = len(re.findall(r"<(?:tr|li)\b", rows, re.I))
            if rows:
                _METHOD[key] = "post" if target.endswith(POST_MARK) else "get"
                # 원래 화면이 EUC-KR 이어도 한 글자 체계로 — 이어 붙인 뒤 깨지지 않게 다시 UTF-8 로
                return text.encode("utf-8") + MARK + rows.encode("utf-8")
    return None


_METHOD: dict[tuple[str, str], str] = {}  # (호스트, 경로) → 목록을 준 방식(get·post)
