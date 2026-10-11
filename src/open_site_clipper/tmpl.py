"""사이트의 줄 틀(템플릿)로 받은 목록을 그린다 — jquery.tmpl · handlebars 의 작은 부분집합.

스크립트로 목록을 받아 그리는 게시판은 글 한 줄의 모양을 페이지 안의 틀에 적어 둔다:

    <script type="text/x-jquery-tmpl" id="listTemplate">
      <tr><td><a href="javascript:fn_view('${BBS_SEQ}')">${SUBJECT}</a></td><td>${REG_DATE}</td></tr>
    </script>

    <script id="list-template" type="text/x-handlebars-template">
      {{#each resultList}}<tr><td><a href="#" onclick="goView({{bIdx}})">{{title}}</a></td>…{{/each}}
    </script>

그 틀에 받은 값을 채우면 브라우저가 그린 것과 같은 줄이 나온다 — 제목·날짜·글 링크(스크립트
링크면 scriptlink 가 진짜 주소를 찾는다)를 기존 표 파서가 그대로 읽는다. 스크립트를 실행하지
않는다: 값 꺼내기·비교·문자열 잇기·몇 가지 문자열 메서드만 따진다. 모르는 도우미 함수는 첫
인자를 그대로 낸다(날짜 꼴 바꾸기·글자 자르기 도우미가 대부분이다).
"""

from __future__ import annotations

import datetime as _dt
import html
import re
from dataclasses import dataclass, field

MAX_ITEMS = 80  # 한 번에 그리는 줄 수 상한(목록 한 쪽)
MAX_DEPTH = 8

_TAG_RE = re.compile(r"\$\{(.*?)\}|\{\{\{(.*?)\}\}\}|\{\{(.*?)\}\}", re.S)


@dataclass(slots=True)
class _Node:
    kind: str  # text · out · raw · block
    value: str = ""  # 글자 또는 식
    name: str = ""  # 블록 이름(if·each·unless·with·도우미)
    branches: list[tuple[str | None, list[_Node]]] = field(default_factory=list)
    names: tuple[str, ...] = ()  # {{each(i, v) list}} 의 이름들


def parse(source: str) -> list[_Node]:
    """틀 글 → 마디 나무. 짝이 안 맞는 닫기는 무시한다(깨진 틀도 읽은 데까지)."""
    root: list[_Node] = []
    stack: list[_Node] = []

    def cur() -> list[_Node]:
        return stack[-1].branches[-1][1] if stack else root

    pos = 0
    for m in _TAG_RE.finditer(source):
        if m.start() > pos:
            cur().append(_Node("text", source[pos : m.start()]))
        pos = m.end()
        dollar, triple, tag = m.groups()
        if dollar is not None:
            cur().append(_Node("out", dollar.strip()))
            continue
        if triple is not None:
            cur().append(_Node("raw", triple.strip()))
            continue
        tag = (tag or "").strip()
        if not tag or tag.startswith("!"):
            continue
        if tag.startswith("/"):
            if stack:
                stack.pop()
            continue
        if tag == "else" or tag.startswith(("else ", "else(")):
            if stack:
                cond = tag[4:].strip() or None
                if cond and cond.startswith("if "):  # handlebars '{{else if x}}'
                    cond = cond[3:].strip()
                stack[-1].branches.append((cond, []))
            continue
        if tag.startswith(("#", "^")):
            body = tag[1:].strip()
            name, _, args = body.partition(" ")
            if tag[0] == "^":
                name, args = "unless", body
            node = _Node("block", name=name.strip(), branches=[(args.strip(), [])])
            cur().append(node)
            stack.append(node)
            continue
        m2 = re.match(r"(if|each|with)\b\s*(?:\(([^)]*)\))?\s*(.*)$", tag, re.S)
        if m2:
            names = tuple(n.strip() for n in (m2.group(2) or "").split(",") if n.strip())
            node = _Node(
                "block", name=m2.group(1), branches=[(m2.group(3).strip(), [])], names=names
            )
            cur().append(node)
            stack.append(node)
            continue
        if tag.startswith("html "):
            cur().append(_Node("raw", tag[5:].strip()))
            continue
        if tag.startswith("="):
            cur().append(_Node("out", tag[1:].strip()))
            continue
        if tag.startswith((">", "tmpl", "wrap", "layout")):
            continue  # 다른 틀 끼워 넣기 — 따라가지 않는다
        cur().append(_Node("out", tag))
    if pos < len(source):
        cur().append(_Node("text", source[pos:]))
    return root


def placeholders(source: str) -> set[str]:
    """틀이 꺼내 쓰는 값 이름들(맨 앞 조각) — 어느 틀이 이 목록의 것인지 고를 때 쓴다."""
    out: set[str] = set()
    for m in _TAG_RE.finditer(source):
        expr = next((g for g in m.groups() if g is not None), "")
        for name in re.findall(r"(?<![\w$.@'\"])([A-Za-z_][\w]*)", expr):
            if name not in _WORDS:
                out.add(name)
    return out


_WORDS = frozenset(
    {
        "if",
        "else",
        "each",
        "with",
        "unless",
        "html",
        "this",
        "true",
        "false",
        "null",
        "undefined",
        "tmpl",
        "wrap",
        "typeof",
        "length",
    }
)


# ── 그리기 ────────────────────────────────────────────────────────────────────
class _Scope:
    __slots__ = ("data", "parent", "vars")

    def __init__(self, data: object, parent: _Scope | None = None, vars: dict | None = None):
        self.data = data
        self.parent = parent
        self.vars = vars or {}


def render(source: str | list[_Node], data: object) -> str:
    """틀 하나를 값 하나(항목 또는 응답 전체)로 그린다."""
    nodes = parse(source) if isinstance(source, str) else source
    out: list[str] = []
    _render(nodes, _Scope(data), out, 0)
    return "".join(out)


def _render(nodes: list[_Node], scope: _Scope, out: list[str], depth: int) -> None:
    if depth > MAX_DEPTH:
        return
    for node in nodes:
        if node.kind == "text":
            out.append(node.value)
        elif node.kind in ("out", "raw"):
            value = _output(node.value, scope)
            out.append(value if node.kind == "raw" else html.escape(value, quote=True))
        elif node.kind == "block":
            _block(node, scope, out, depth)


def _block(node: _Node, scope: _Scope, out: list[str], depth: int) -> None:
    name = node.name
    if name == "each":
        args, body = node.branches[0]
        items = evaluate(args, scope) if args else scope.data
        seq = list(items.items()) if isinstance(items, dict) else items
        if not isinstance(seq, list) or not seq:
            if len(node.branches) > 1:  # {{#each}}…{{else}}(빈 목록)…{{/each}}
                _render(node.branches[1][1], scope, out, depth + 1)
            return
        for i, item in enumerate(seq[:MAX_ITEMS]):
            key = None
            if isinstance(items, dict):
                key, item = item
            v = {"@index": i, "$index": i, "@first": i == 0, "@last": i == len(seq) - 1}
            v["@key"] = key if key is not None else i
            v["$value"] = item
            if node.names:
                v[node.names[0]] = key if key is not None else i
                if len(node.names) > 1:
                    v[node.names[1]] = item
            _render(body, _Scope(item, scope, v), out, depth + 1)
        return
    if name == "with":
        args, body = node.branches[0]
        value = evaluate(args, scope)
        if truthy(value):
            _render(body, _Scope(value, scope), out, depth + 1)
        return
    for cond, body in node.branches:
        if cond is None or _test(name, cond, scope):
            _render(body, scope, out, depth + 1)
            return


def _test(name: str, cond: str, scope: _Scope) -> bool:
    if name == "unless":
        return not truthy(evaluate(cond, scope))
    if name == "if":
        return truthy(evaluate(cond, scope))
    # 사이트 도우미 블록 — {{#ifCond a '==' b}} · {{#xif "a > b"}} · {{#eq a b}} · {{#compare a b operator="=="}}
    words = _hbs_args(cond)
    lowered = name.lower()
    if len(words) == 1 and words[0][:1] in "'\"" and re.search(r"[=<>!&|]", words[0]):
        return truthy(evaluate(words[0][1:-1], scope))
    vals = [evaluate(w, scope) for w in words]
    if len(words) == 3 and words[1][:1] in "'\"":
        return _compare(vals[0], words[1].strip("'\""), vals[2])
    if len(vals) >= 2 and re.search(r"eq|equal|same|compare|is", lowered):
        op = "!=" if re.search(r"ne|not", lowered) else "=="
        return _compare(vals[0], op, vals[1])
    return truthy(vals[0]) if vals else False


def _hbs_args(text: str) -> list[str]:
    return [
        w
        for w in re.findall(r"""'[^']*'|"[^"]*"|[^\s]+""", text or "")
        if "=" not in w[:-1] or w[:1] in "'\""
    ]


def _output(expr: str, scope: _Scope) -> str:
    words = _hbs_args(expr)
    if (
        len(words) > 1
        and re.fullmatch(r"[A-Za-z_$][\w$.]*", words[0])
        and not re.search(r"[=<>!?+(]", expr)
    ):
        # handlebars 도우미 '{{formatDate regDate "YYYY.MM.DD"}}' — 첫 인자를 그대로
        return text_of(evaluate(words[1], scope))
    return text_of(evaluate(expr, scope))


# ── 값 ────────────────────────────────────────────────────────────────────────
_KST = _dt.timezone(_dt.timedelta(hours=9))


def text_of(value: object) -> str:
    """그릴 글자 — 날짜 숫자(밀리초)·자바 Date 꼴은 날짜 글자로."""
    if value is None or value is False:
        return ""
    if value is True:
        return "true"
    if isinstance(value, dict):
        stamp = value.get("time")
        if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
            return text_of(stamp)
        year, month, day = (value.get(k) for k in ("year", "monthValue", "dayOfMonth"))
        if all(isinstance(x, int) for x in (year, month, day)):
            return f"{year:04d}-{month:02d}-{day:02d}"  # 자바 LocalDateTime 꼴
        return ""
    if isinstance(value, list):
        if (
            len(value) >= 3
            and all(isinstance(x, int) for x in value[:3])
            and 1900 < value[0] < 2200
        ):
            return f"{value[0]:04d}-{value[1]:02d}-{value[2]:02d}"  # [2026, 10, 12, …]
        return ""
    if isinstance(value, (int, float)):
        if 10**11 <= value <= 4 * 10**12:  # 1973~2096 년의 밀리초
            return _dt.datetime.fromtimestamp(value / 1000, _KST).strftime("%Y-%m-%d")
        return str(int(value)) if float(value).is_integer() else str(value)
    return str(value)


def truthy(value: object) -> bool:
    if isinstance(value, str):
        return value != ""
    if isinstance(value, (list, dict)):
        return bool(value)
    return bool(value) and value is not None


def _compare(a: object, op: str, b: object) -> bool:
    if op in ("==", "===", "eq"):
        return _loose(a) == _loose(b)
    if op in ("!=", "!==", "ne"):
        return _loose(a) != _loose(b)
    try:
        x, y = float(text_of(a) or 0), float(text_of(b) or 0)
    except ValueError:
        x, y = text_of(a), text_of(b)  # type: ignore[assignment]
    return {">": x > y, "<": x < y, ">=": x >= y, "<=": x <= y}.get(op, False)


def _loose(v: object) -> object:
    """'1' == 1 · null == undefined 처럼 느슨한 같음."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v) if v.strip() else v
        except ValueError:
            return v
    return v


def lookup(path: str, scope: _Scope) -> object:
    """'BBS_SEQ' · 'board.title' · '../menuId' · '@index' · 'this' · '$item.x' · 'list[0].t'."""
    path = path.strip()
    while path.startswith("../"):
        path = path[3:]
        scope = scope.parent or scope
    if path in ("this", ".", "$data"):
        return scope.data
    if path.startswith(("this.", "$data.", "$item.data.")):
        path = path.split(".", 1)[1] if not path.startswith("$item.data.") else path[11:]
        return _walk(scope.data, path)
    if path.startswith("$item."):
        return None  # 틀 항목 객체의 다른 값은 알 수 없다
    head = re.match(r"[@$]?[A-Za-z_][\w$]*", path)
    if not head:
        return None
    name, rest = head.group(0), path[head.end() :]
    s: _Scope | None = scope
    while s is not None:  # 지금 항목 → each 이름 → 바깥 항목(jquery.tmpl 은 바깥도 본다)
        if isinstance(s.data, dict) and name in s.data:
            return _walk(s.data[name], rest)
        if name in s.vars:
            return _walk(s.vars[name], rest)
        s = s.parent
    return None


def _walk(value: object, rest: str) -> object:
    for m in re.finditer(
        r"\.([A-Za-z_$][\w$]*)|\[\s*(\d+)\s*\]|\[\s*['\"]([^'\"]+)['\"]\s*\]|\.(\d+)", rest
    ):
        key = m.group(1) or m.group(3)
        idx = m.group(2) or m.group(4)
        if key == "length" and isinstance(value, (list, str)):
            value = len(value)
        elif key is not None:
            value = value.get(key) if isinstance(value, dict) else None
        elif idx is not None:
            i = int(idx)
            value = value[i] if isinstance(value, list) and i < len(value) else None
        if value is None:
            return None
    return value


# ── 식(자바스크립트의 작은 부분) ───────────────────────────────────────────────
def _top(expr: str, ops: tuple[str, ...], start: int = 0) -> tuple[int, str]:
    """괄호·따옴표 밖에서 처음 나오는 연산자 자리. 없으면 (-1, '')."""
    depth, quote, i, n = 0, "", start, len(expr)
    while i < n:
        ch = expr[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0:
            for op in ops:
                if expr.startswith(op, i):
                    return i, op
        i += 1
    return -1, ""


def _close(expr: str, open_at: int) -> int:
    """expr[open_at] 가 '(' 일 때 짝 ')' 의 자리(없으면 -1) — 따옴표 속 괄호는 건너뛴다."""
    depth, quote, i = 0, "", open_at
    while i < len(expr):
        ch = expr[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split(expr: str, op: str) -> list[str]:
    parts, last = [], 0
    while True:
        at, _ = _top(expr, (op,), last)
        if at < 0:
            parts.append(expr[last:])
            return parts
        parts.append(expr[last:at])
        last = at + len(op)


def evaluate(expr: str, scope: _Scope) -> object:
    expr = (expr or "").strip()
    if not expr:
        return None
    q, _ = _top(expr, ("?",))
    if q > 0 and expr[q + 1 : q + 2] not in (".", "?"):
        c, _ = _top(expr, (":",), q + 1)
        if c > 0:
            cond = evaluate(expr[:q], scope)
            return evaluate(expr[q + 1 : c] if truthy(cond) else expr[c + 1 :], scope)
    for op in ("||", "&&"):
        parts = _split(expr, op)
        if len(parts) > 1:
            if op == "||":
                for p in parts:
                    v = evaluate(p, scope)
                    if truthy(v):
                        return v
                return v
            v = None
            for p in parts:
                v = evaluate(p, scope)
                if not truthy(v):
                    return v
            return v
    at, op = _top(expr, ("===", "!==", "==", "!=", ">=", "<=", ">", "<"))
    if at > 0:
        return _compare(evaluate(expr[:at], scope), op, evaluate(expr[at + len(op) :], scope))
    parts = _split(expr, "+")
    if len(parts) > 1 and all(p.strip() for p in parts):
        vals = [evaluate(p, scope) for p in parts]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            return sum(vals)  # type: ignore[arg-type]
        return "".join(text_of(v) for v in vals)
    if expr.startswith("!"):
        return not truthy(evaluate(expr[1:], scope))
    return _atom(expr, scope)


_STR_RE = re.compile(r"""^(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""")
_NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def _atom(expr: str, scope: _Scope) -> object:
    if expr.startswith("(") and _close(expr, 0) == len(expr) - 1:
        return evaluate(expr[1:-1], scope)
    m = _STR_RE.match(expr)
    if m and m.end() == len(expr):
        return re.sub(r"\\(.)", r"\1", m.group(1) if m.group(1) is not None else m.group(2))
    if _NUM_RE.match(expr):
        return float(expr) if "." in expr else int(expr)
    if expr in ("null", "undefined"):
        return None
    if expr in ("true", "false"):
        return expr == "true"
    if expr.startswith("typeof "):
        v = evaluate(expr[7:], scope)
        return "undefined" if v is None else "string" if isinstance(v, str) else "object"
    m = re.match(r"(?:\.\./)*[@$]?[A-Za-z_][\w$]*", expr)
    if not m:
        return None
    pos = m.end()
    name = m.group(0)
    if expr[pos : pos + 1] == "(":
        # 모르는 함수 — 날짜 꼴·글자 자르기 도우미가 대부분이라 첫 인자를 그대로
        close = _close(expr, pos)
        args = _args(expr[pos + 1 : close], scope) if close > 0 else []
        value: object = args[0] if args else None
        pos = close + 1 if close > 0 else len(expr)
    else:
        # 경로 끝까지(.이름 · [수] · ['키'])
        pm = re.match(
            r"(?:\.[A-Za-z_$][\w$]*(?![\w$])(?!\s*\()|\[\s*\d+\s*\]|\[\s*['\"][^'\"]+['\"]\s*\])*",
            expr[pos:],
        )
        rest = pm.group(0) if pm else ""
        value = lookup(name + rest, scope)
        pos += len(rest)
    # 메서드 잇기 — .substring(0, 10) · .replace(/-/g, '.') · .trim()
    while pos < len(expr):
        mm = re.match(r"\s*\.\s*([A-Za-z_$][\w$]*)\s*", expr[pos:])
        if not mm:
            break
        meth = mm.group(1)
        pos += mm.end()
        if expr[pos : pos + 1] != "(":
            value = _walk(value, "." + meth)
            continue
        close = _close(expr, pos)
        if close < 0:
            break
        raw = expr[pos + 1 : close]
        pos = close + 1
        value = _method(value, meth, raw, scope)
        im = re.match(r"\s*\[\s*(\d+)\s*\]", expr[pos:])
        if im:  # .split('-')[0]
            value = _walk(value, f"[{im.group(1)}]")
            pos += im.end()
    return value


def _args(raw: str, scope: _Scope) -> list[object]:
    if not raw.strip():
        return []
    return [evaluate(a, scope) for a in _split(raw, ",")]


def _method(value: object, meth: str, raw: str, scope: _Scope) -> object:
    text = text_of(value) if value is not None else ""
    if meth in ("trim", "toString", "valueOf", "toLowerCase", "toUpperCase"):
        return {"trim": text.strip(), "toLowerCase": text.lower(), "toUpperCase": text.upper()}.get(
            meth, text if value is not None else None
        )
    if meth == "replace":
        parts = _split(raw, ",")
        if len(parts) == 2:
            pat, repl = parts[0].strip(), text_of(evaluate(parts[1], scope))
            rm = re.fullmatch(r"/(.+)/([gimsuy]*)", pat)
            if rm:
                try:
                    return re.sub(rm.group(1), repl, text, count=0 if "g" in rm.group(2) else 1)
                except re.error:
                    return text
            return text.replace(text_of(evaluate(pat, scope)), repl, 1)
        return text
    args = _args(raw, scope)
    nums = [int(a) for a in args if isinstance(a, (int, float)) and not isinstance(a, bool)]
    if meth in ("substring", "slice") and nums:
        return text[nums[0] : nums[1]] if len(nums) > 1 else text[nums[0] :]
    if meth == "substr" and nums:
        return text[nums[0] : nums[0] + nums[1]] if len(nums) > 1 else text[nums[0] :]
    if meth == "split":
        sep = text_of(args[0]) if args else ","
        return text.split(sep) if sep else list(text)
    if meth == "indexOf":
        if isinstance(value, list):
            return value.index(args[0]) if args and args[0] in value else -1
        return text.find(text_of(args[0])) if args else -1
    if meth == "join" and isinstance(value, list):
        return (text_of(args[0]) if args else ",").join(text_of(v) for v in value)
    if meth == "charAt" and nums:
        return text[nums[0] : nums[0] + 1]
    return value
