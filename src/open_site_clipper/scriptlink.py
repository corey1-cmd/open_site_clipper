"""스크립트로만 열리는 글 링크 → 진짜 글 주소(사이트 스크립트를 **읽어서**).

목록의 제목 링크가 `javascript:fn_view('1234')` · `href="#" onclick="goDetail(55)"` ·
`<a href="javascript:" data-id="554771" class="nttInfoBtn">` 뿐인 게시판이 많다(실측
2026-10-11: 학교 글 5,681건 중 1,120건, 64곳 — 동국대·경희대·고려대·한밭대 …). 예전에는
글 주소 대신 '목록 주소#제목'을 걸어, 누르면 목록이 열릴 뿐이었다.

글 주소는 사이트가 이미 알고 있다 — 그 함수의 정의가 페이지(또는 같은 사이트의 .js)에
있다. 이 모듈은 그것을 읽는다(실행하지 않는다). 읽는 꼴은 셋이다:

  location.href = '/bbs/view.do?no=' + no;                       → 문자열 잇기
  f.nttId.value = id; f.action = 'view.do'; f.submit();           → 폼 값 + action → GET 주소
  $('.nttInfoBtn').on('click', function(){ … $(this).data('id') }) → 링크의 data-* 값

만든 주소는 **그 게시판의 첫 글 하나를 실제로 열어** 그 글의 제목이 보이고 목록 화면이
아닐 때만 믿는다(지어낸 주소를 내보내지 않는다). 같은 호스트·같은 함수는 한 번 확인하면
다시 열지 않는다. 확인이 안 되면 예전처럼 '목록 주소#제목'을 둔다.
"""

from __future__ import annotations

import html
import re
import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser

# k2web_parse.anchor_href 가 data-* 만 있는 링크에 붙이는 표시('#data:data-id=5&class=btn')
DATA_MARK = "#data:"


@dataclass(slots=True)
class Form:
    name: str = ""
    id: str = ""
    action: str = ""
    method: str = ""
    inputs: list[tuple[str, str, str]] = field(default_factory=list)  # (name, value, id)
    # inputs 와 같은 순서의 종류('hidden'·'text'·'checkbox:checked'·'select' …) — serialize() 용
    types: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Anchor:
    attrs: dict[str, str]
    text: str


@dataclass(slots=True)
class Template:
    """스크립트가 아닌 <script> — 줄 틀(text/x-jquery-tmpl · handlebars)이나 자료(JSON)."""

    id: str
    type: str
    body: str


# 실행되는 스크립트의 type — 그 밖('text/x-jquery-tmpl'·'text/template'·'application/json')은 틀·자료
_JS_TYPE_RE = re.compile(
    r"^(?:|text/javascript|application/javascript|module|text/ecmascript|"
    r"application/ecmascript|text/jscript|text/babel)(?:\s*;.*)?$",
    re.I,
)


class _PartsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[Anchor] = []
        self.scripts: list[str] = []
        self.srcs: list[str] = []
        self.forms: list[Form] = []
        self.loose_inputs: list[tuple[str, str, str]] = []  # 폼 밖의 숨은 값
        self.templates: list[Template] = []
        self._a: dict[str, str] | None = None
        self._a_text: list[str] = []
        self._script: list[str] | None = None
        self._script_attrs: dict[str, str] = {}
        self._form: Form | None = None
        self._select: int | None = None  # 지금 읽는 <select> 의 자리(폼 안)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "a":
            if self._a is not None:  # 닫히지 않은 링크
                self._close_anchor()
            self._a, self._a_text = a, []
        elif tag == "script":
            if a.get("src"):
                self.srcs.append(a["src"].strip())
            self._script, self._script_attrs = [], a
        elif tag == "form":
            self._form = Form(
                name=a.get("name", ""),
                id=a.get("id", ""),
                action=a.get("action", ""),
                method=a.get("method", "").lower(),
            )
            self.forms.append(self._form)
        elif tag in ("input", "select", "textarea"):
            item = (a.get("name", ""), a.get("value", ""), a.get("id", ""))
            kind = a.get("type", "text").lower() if tag == "input" else tag
            if "checked" in a:
                kind += ":checked"
            if "disabled" in a:
                kind += ":disabled"
            if self._form is not None:
                self._form.inputs.append(item)
                self._form.types.append(kind)
                self._select = len(self._form.inputs) - 1 if tag == "select" else None
            elif a.get("type", "").lower() == "hidden":
                self.loose_inputs.append(item)
        elif tag == "option" and self._form is not None and self._select is not None:
            # 고른 값 — selected 가 붙은 것, 없으면 첫 option(브라우저와 같다)
            at = self._select
            name, _value, iid = self._form.inputs[at]
            kind = self._form.types[at]
            if "selected" in a and not kind.startswith("select:sel"):
                self._form.inputs[at] = (name, a.get("value", ""), iid)
                self._form.types[at] = "select:sel"
            elif kind == "select":
                self._form.inputs[at] = (name, a.get("value", ""), iid)
                self._form.types[at] = "select:opt"

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script.append(data)
        elif self._a is not None:
            self._a_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._a is not None:
            self._close_anchor()
        elif tag == "script" and self._script is not None:
            body = "".join(self._script)
            kind = self._script_attrs.get("type", "").strip()
            if _JS_TYPE_RE.match(kind):
                self.scripts.append(body)
            else:
                self.templates.append(
                    Template(self._script_attrs.get("id", ""), kind.lower(), body)
                )
            self._script = None
        elif tag == "select":
            self._select = None
        elif tag == "form":
            self._form = None

    def _close_anchor(self) -> None:
        assert self._a is not None
        self.anchors.append(Anchor(self._a, " ".join("".join(self._a_text).split())))
        self._a, self._a_text = None, []


@dataclass(slots=True)
class PageParts:
    anchors: list[Anchor]
    scripts: list[str]
    srcs: list[str]
    forms: list[Form]
    loose_inputs: list[tuple[str, str, str]]
    templates: list[Template] = field(default_factory=list)


def page_parts(html_text: str) -> PageParts:
    parser = _PartsParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:  # 깨진 HTML — 읽은 데까지
        pass
    return PageParts(
        parser.anchors,
        parser.scripts,
        parser.srcs,
        parser.forms,
        parser.loose_inputs,
        parser.templates,
    )


# ── 함수 호출 읽기 ────────────────────────────────────────────────────────────
_CALL_RE = re.compile(r"([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(")
_ARG_RE = re.compile(
    r"""\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|(-?[\w.$]+))\s*(,\s*\)|,|\))"""
)
_NOT_CALLS = frozenset({"void", "return", "if", "function", "alert", "confirm", "typeof"})


def call_of(js: str) -> tuple[str, list[str]] | None:
    """'javascript:fn_view('1234', 5); return false;' → ('fn_view', ['1234', '5']).

    인자가 글자·숫자가 아닌 것(this·event 같은 이름)은 이름 그대로 둔다. 못 읽으면 None.
    """
    body = strip_js_prefix(js)
    for m in _CALL_RE.finditer(body):
        name = m.group(1)
        if name.split(".")[-1] in _NOT_CALLS:
            continue
        args: list[str] = []
        pos = m.end()
        if body[pos : pos + 1] == ")":
            return name, args
        while True:
            am = _ARG_RE.match(body, pos)
            if not am:
                break
            single, double, bare, end = am.groups()
            args.append(single if single is not None else double if double is not None else bare)
            pos = am.end()
            if end.endswith(")"):
                return name, args
        # 인자를 끝까지 못 읽은 호출 — 다음 호출을 본다
    return None


_QUERY_HELPER_RE = re.compile(
    r"replace\w*(?:query|param)|(?:query|param)\w*replace|set\w*(?:query|param)|update\w*(?:query|param)",
    re.I,
)


def _replace_query(query: str, key: str, value: str) -> str:
    """'&schM=list&id=' 에서 key 의 값을 value 로(없으면 붙인다). 앞의 '?'·'&' 꼴은 그대로."""
    if not key or key == THIS:
        return query
    lead = query[:1] if query[:1] in "?&" else ""
    pairs = [p for p in query[len(lead) :].split("&") if p]
    out, done = [], False
    for p in pairs:
        k = p.split("=", 1)[0]
        if k == key:
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(p)
    if not done:
        out.append(f"{key}={value}")
    return lead + "&".join(out)


def _object_pairs(literal: str) -> list[tuple[str, str]]:
    """'{ action : x + y, method : 'get' }' → [('action', 'x + y'), ('method', "'get'")]."""
    body = literal.strip()
    if not (body.startswith("{") and body.endswith("}")):
        return []
    out = []
    for item in split_top(body[1:-1], ","):
        key, sep, value = item.partition(":")
        if sep:
            out.append((key.strip().strip("'\""), value.strip()))
    return out


def strip_js_prefix(js: str) -> str:
    """'javascript:' 머리(겹쳐 붙은 것까지)를 뗀다 — onclick 안의 'javascript:' 는 JS 라벨일 뿐이다."""
    body = (js or "").strip()
    while body.lower().startswith("javascript:"):
        body = body[len("javascript:") :].strip()
    return body


# ── 함수 정의 찾기 ────────────────────────────────────────────────────────────
def _def_patterns(name: str) -> list[re.Pattern[str]]:
    short = re.escape(name.split(".")[-1])
    return [
        re.compile(r"function\s+" + short + r"\s*\(([^)]*)\)\s*\{"),
        re.compile(
            r"(?<![\w$])" + short + r"\s*[:=]\s*(?:async\s+)?function\s*[\w$]*\s*\(([^)]*)\)\s*\{"
        ),
        re.compile(r"(?<![\w$])" + short + r"\s*[:=]\s*\(([^)]*)\)\s*=>\s*\{"),
        # 객체·클래스의 줄임 메서드 — `view(seq) { … }` (호출 뒤에 '{' 가 오는 일은 거의 없다)
        re.compile(r"(?<![\w$.])" + short + r"\s*\(([\w$\s,]*)\)\s*\{"),
    ]


def _block(text: str, start: int, limit: int = 8000) -> str:
    """'{' 바로 뒤에서 짝 맞는 '}' 까지(글자·주석 속 괄호는 건너뛴다)."""
    depth, i, end = 1, start, min(len(text), start + limit)
    quote = ""
    while i < end:
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif ch == "/" and text[i : i + 2] == "//":
            nl = text.find("\n", i)
            i = end if nl < 0 else nl
            continue
        elif ch == "/" and text[i : i + 2] == "/*":
            close = text.find("*/", i + 2)
            i = end if close < 0 else close + 2
            continue
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return text[start:end]


def find_function(sources: list[str], name: str) -> tuple[list[str], str] | None:
    """스크립트 본문들에서 함수 정의 → (매개변수 이름들, 몸통). 없으면 None."""
    for text in sources:
        for pat in _def_patterns(name):
            for m in pat.finditer(text):
                if pat is not _def_patterns(name)[0] and _is_keyword_before(text, m.start()):
                    continue
                params = [p.strip().split("=")[0].strip() for p in m.group(1).split(",")]
                return [p for p in params if p], _block(text, m.end())
    return None


def _is_keyword_before(text: str, at: int) -> bool:
    """`if (view(x)) {` 같은 호출을 메서드 정의로 읽지 않게 — 앞 낱말이 제어문이면 거른다."""
    before = text[max(0, at - 12) : at].rstrip()
    return bool(re.search(r"(?:if|while|for|switch|return|&&|\|\||\(|!|=)$", before))


# ── 식 읽기(문자열 잇기만) ─────────────────────────────────────────────────────
THIS = "\x00this"  # 매개변수로 넘어온 링크 자신(this)
_IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_DATA_KEY_RE = re.compile(
    r"""(?:\$\(\s*[\w$.]+\s*\)|[\w$]+)\s*\.\s*(?:data\(\s*['"]([\w-]+)['"]\s*\)|"""
    r"""attr\(\s*['"]data-([\w-]+)['"]\s*\)|getAttribute\(\s*['"]data-([\w-]+)['"]\s*\)|"""
    r"""dataset\.([\w$]+)|dataset\[\s*['"]([\w-]+)['"]\s*\])"""
)
_CSRF_RE = re.compile(r"csrf|token|_ga|recaptcha|password|passwd|pwd$", re.I)


def _norm_key(key: str) -> str:
    return key.replace("-", "").replace("_", "").lower()


def split_top(expr: str, sep: str) -> list[str]:
    """괄호·따옴표 밖의 sep 으로 나눈다."""
    parts, buf, depth, quote = [], [], 0, ""
    i, n = 0, len(expr)
    while i < n:
        ch = expr[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                buf.append(expr[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth -= 1
            buf.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def _close_paren(text: str, start: int) -> int:
    """text[start] 가 '(' 일 때 짝 ')' 의 자리(없으면 -1)."""
    depth, quote, i = 0, "", start
    while i < len(text):
        ch = text[i]
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


def _unescape_js(text: str) -> str:
    return re.sub(r"\\(.)", lambda m: m.group(1), text)


@dataclass(slots=True)
class _Chain:
    """`$("#frm").attr("action", url).submit()` → base='$("#frm")', calls=[(attr, '"action", url'), …]."""

    base: str
    calls: list[tuple[str, str]]


def _chain(stmt: str) -> _Chain | None:
    s = stmt.strip()
    m = re.match(r"(?:\$|jQuery)\s*\(", s)
    if m:
        close = _close_paren(s, m.end() - 1)
        if close < 0:
            return None
        base, rest = s[: close + 1], s[close + 1 :]
    else:
        m = re.match(
            r"[A-Za-z_$][\w$]*(?:\s*(?:\.\s*[A-Za-z_$][\w$]*|\[\s*(?:'[^']*'|\"[^\"]*\"|\d+)\s*\]))*",
            s,
        )
        if not m:
            return None
        base, rest = m.group(0), s[m.end() :]
        # 'f.submit' 처럼 마지막 이름이 메서드면 떼어 호출로 본다
        if rest.lstrip().startswith("("):
            head, _, last = base.rpartition(".")
            if not head:
                return None
            base, rest = head, "." + last + rest
    calls: list[tuple[str, str]] = []
    while True:
        rest = rest.lstrip()
        if rest.startswith("[0]"):
            rest = rest[3:]
            continue
        m = re.match(r"\.\s*([A-Za-z_$][\w$]*)\s*\(", rest)
        if not m:
            break
        close = _close_paren(rest, m.end() - 1)
        if close < 0:
            return None
        calls.append((m.group(1), rest[m.end() : close]))
        rest = rest[close + 1 :]
    if rest.strip(" ;"):
        return None
    return _Chain(base, calls)


# ── 실행 없이 따라가기 ────────────────────────────────────────────────────────
@dataclass(slots=True)
class _FormState:
    index: int  # parts.forms 의 자리(-1 = 폼 없이 값만)
    sets: dict[str, str] = field(default_factory=dict)
    action: str | None = None
    submitted: bool = False


@dataclass(slots=True)
class Candidate:
    """만든 글 주소 하나와 그 꼴(확인할 때 같은 꼴을 게시판 전체에 쓴다)."""

    kind: str  # loc · form_all · form_set · form_bare
    url: str


_KEYWORD_RE = re.compile(r"(if|for|while|switch|try|do|function|else|catch|finally|with)\b")
_LOC_LHS_RE = re.compile(
    r"^(?:(?:window|document|self|top|parent)\s*\.\s*)?location(?:\s*\.\s*href)?$"
)
_LOC_CALL_RE = re.compile(
    r"^(?:(?:window|document|self|top|parent)\s*\.\s*)?location\s*\.\s*(?:replace|assign)\s*\("
)
_OPEN_RE = re.compile(r"^(?:window\s*\.\s*)?open\s*\(")
# 조건을 알 수 없을 때 '주소를 만드는' 블록인지 — 아니면 경고·되돌아가기뿐인 관문으로 본다
_EFFECT_RE = re.compile(r"location|submit|\.action|window\.open|\.val\(|\.value|setHidden|attr\(")
_CALLBACK_RE = re.compile(r"function\s*[\w$]*\s*\([^)]*\)\s*\{|\([^()]*\)\s*=>\s*\{")
MAX_STEPS = 600
MAX_DEPTH = 4


def _strip_comments(code: str) -> str:
    out, i, n, quote = [], 0, len(code), ""
    while i < n:
        ch = code[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(code[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
            out.append(ch)
        elif code.startswith("//", i) and (i == 0 or code[i - 1] != ":"):
            nl = code.find("\n", i)
            i = n if nl < 0 else nl
            continue
        elif code.startswith("/*", i):
            close = code.find("*/", i + 2)
            i = n if close < 0 else close + 2
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _simple(code: str, i: int) -> tuple[str, int]:
    """i 에서 시작하는 단순 문장 하나(';' 또는 끝난 줄까지) → (문장, 다음 자리)."""
    buf, depth, quote, n = [], 0, "", len(code)
    while i < n:
        ch = code[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                buf.append(code[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break  # 감싼 블록의 끝
            depth -= 1
        elif depth == 0 and ch == ";":
            return " ".join("".join(buf).split()), i + 1
        elif depth == 0 and ch == "\n":
            prev = "".join(buf).rstrip()
            nxt = code[i + 1 :].lstrip()[:1]
            if (
                prev
                and prev[-1] not in "+=,(&|?:."
                and nxt not in ("+", ".", "?", ":", "&", "|", ")", "]", ",")
            ):
                return " ".join(prev.split()), i + 1
        buf.append(ch)
        i += 1
    return " ".join("".join(buf).split()), i


def _body(code: str, i: int) -> tuple[str, int]:
    """조건·else 뒤의 몸통 — '{ … }' 이면 그 안, 아니면 문장 하나."""
    n = len(code)
    while i < n and code[i] in " \t\r\n":
        i += 1
    if i < n and code[i] == "{":
        inner = _block(code, i + 1)
        return inner, min(n, i + 1 + len(inner) + 1)
    m = re.compile(r"if\s*\(").match(code, i)
    if m:  # if (…) if (…) x(); 처럼 몸통이 또 조건문
        close = _close_paren(code, m.end() - 1)
        if close < 0:
            return "", n
        _then, j = _body(code, close + 1)
        k = j
        while k < n and code[k] in " \t\r\n;":
            k += 1
        if code.startswith("else", k):
            _else, j = _body(code, k + 4)
        return code[i:j], j
    stmt, j = _simple(code, i)
    return stmt, j


def split_ops(expr: str, op: str) -> list[str]:
    """괄호·따옴표 밖의 두 글자 연산자(&&, ||)로 나눈다."""
    parts, buf, depth, quote = [], [], 0, ""
    i, n = 0, len(expr)
    while i < n:
        ch = expr[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                buf.append(expr[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth -= 1
            buf.append(ch)
        elif depth == 0 and expr.startswith(op, i):
            parts.append("".join(buf))
            buf = []
            i += len(op)
            continue
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


_FORM_KEEP = frozenset({"closest", "parents", "parent", "get", "eq", "first"})


def _assignment(s: str) -> tuple[str, str, str] | None:
    """'a.b = c' → ('a.b', '=', 'c'). 괄호·따옴표 밖의 첫 대입 기호만(==·!=·<=·>=·=> 는 아니다)."""
    depth, quote, i, n = 0, "", 0, len(s)
    while i < n:
        ch = s[i]
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
        elif ch == "=" and depth == 0:
            nxt = s[i + 1 : i + 2]
            prev = s[i - 1 : i] if i else ""
            if nxt in ("=", ">") or prev in ("=", "!", "<", ">"):
                return None
            lhs = s[:i]
            op = "="
            if prev in ("+", "-", "*", "/", "%", "&", "|", "^"):
                op = prev + "="
                lhs = s[: i - 1]
            lhs = lhs.strip()
            if not lhs or not re.fullmatch(
                r"[\w$.\s]+|.+?(?:\.\s*value|\.\s*action|\.\s*href)", lhs, re.S
            ):
                return None
            return lhs, op, s[i + 1 :].strip()
        i += 1
    return None


class _Run:
    """한 링크의 스크립트를 따라가며 위치 이동·폼 제출을 모은다(실행하지 않는다).

    조건문은 값을 알 수 있으면(`reqSecYN == 'Y'`) 그대로 따지고, 모르면 주소를 만드는
    쪽(위치 이동·폼 값·제출이 든 블록)을 따라간다 — 경고만 띄우고 끝나는 관문
    (`if (!권한()) { alert(…); return; }`)에 걸려 멈추지 않게.
    """

    def __init__(self, ctx: _Ctx, data: dict[str, str]):
        self.ctx = ctx
        self.data = data
        self.forms: dict[int, _FormState] = {}
        self.locations: list[str] = []
        self.steps = 0
        self._evaluating: set[str] = set()
        self._form_calls = 0
        self._uncertain = False

    def done(self) -> bool:
        return bool(self.locations) or any(f.submitted for f in self.forms.values())

    # ── 폼 찾기 ──
    def _form_state(self, index: int) -> _FormState:
        if index not in self.forms:
            self.forms[index] = _FormState(index)
        return self.forms[index]

    def form_of(self, ref: str, env: dict[str, str]) -> int | None:
        """폼을 가리키는 식 → parts.forms 의 자리."""
        ref = ref.strip()
        for _ in range(3):  # $(f) · $(f)[0] · $(document.frm) 껍질 벗기기
            m = re.match(r"(?:\$|jQuery)\s*\(", ref)
            if not m:
                break
            close = _close_paren(ref, m.end() - 1)
            tail = ref[close + 1 :].strip() if close > 0 else "x"
            if close < 0 or tail not in ("", "[0]", ".get(0)"):
                break
            ref = ref[m.end() : close].strip()
        if ref == "this" or env.get(ref) == THIS:
            return None  # 링크 자신 — 링크의 폼은 closest('form') 일 때만
        if _IDENT_RE.fullmatch(ref) and ref not in env:
            # 옛 스킨은 폼 이름을 그대로 전역 이름으로 쓴다(frmBbs.action = url)
            return self.ctx.form_by(ref)
        if env.get(ref, "").startswith("\x00form:"):
            return int(env[ref].split(":", 1)[1])
        m = re.fullmatch(r"""['"](.+)['"]""", ref)
        if m:
            sel = m.group(1).strip()
            for pat in (
                r"#([\w-]+)",
                r"""form\s*\[\s*(?:name|id)\s*=\s*['"]?([\w-]+)['"]?\s*\]""",
                r"form\s*#([\w-]+)",
            ):
                sm = re.fullmatch(pat, sel)
                if sm:
                    return self.ctx.form_by(sm.group(1))
            return None
        m = re.fullmatch(
            r"""document\s*\.\s*(?:forms\s*\[\s*['"]([\w-]+)['"]\s*\]|forms\s*\.\s*([\w$]+)|"""
            r"""getElementById\(\s*['"]([\w-]+)['"]\s*\)|([\w$]+))""",
            ref,
        )
        if m:
            return self.ctx.form_by(next(g for g in m.groups() if g))
        m = re.fullmatch(r"document\s*\.\s*forms\s*\[\s*(\d+)\s*\]", ref)
        if m:
            idx = int(m.group(1))
            return idx if idx < len(self.ctx.parts.forms) else None
        m = re.fullmatch(r"([A-Za-z_$][\w$.]*)\s*\(\s*\)", ref)
        if m and m.group(1) not in ("$", "jQuery") and self._form_calls < 3:
            # 폼을 돌려주는 함수 — getForm().schIdx.value = idx(가야대)
            found = self.ctx.function(m.group(1))
            ret = re.search(r"\breturn\s+([^;}]+)", found[1]) if found else None
            if ret:
                self._form_calls += 1
                try:
                    return self.form_of(ret.group(1), {})
                finally:
                    self._form_calls -= 1
        m = re.fullmatch(
            r"[A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*\s*\.\s*([A-Za-z_$][\w$]*)", ref
        )
        if m and not ref.startswith(("window.", "location.")):
            # 객체에 담아 둔 폼 — article.searchForm(배재대 Article.js)
            return self.ctx.form_by(m.group(1))
        return None

    def form_from_chain(self, chain: _Chain, env: dict[str, str]) -> int | None:
        idx = self.form_of(chain.base, env)
        for method, args in chain.calls:
            if method in ("closest", "parents", "parent") and "form" in args and idx is None:
                inner = re.sub(r"^(?:\$|jQuery)\s*\(|\)$", "", chain.base).strip()
                if inner == "this" or env.get(inner) == THIS:
                    idx = self.ctx.anchor_form()
        return idx

    # ── 값 읽기 ──
    def value(self, expr: str, env: dict[str, str], lenient: bool, depth: int) -> str | None:
        expr = expr.strip()
        if not expr:
            return None
        if "?" in expr and ":" in expr and re.search(r"(?<![=!<>?])\?(?![?.:])", expr):
            return None  # 삼항식 — 조건을 따지지 않는다
        out = []
        for piece in split_top(expr, "+"):
            v = self.atom(piece.strip(), env, lenient, depth)
            if v is None:
                return None
            out.append(v)
        return "".join(out)

    def either(self, expr: str, env: dict[str, str], depth: int) -> str | None:
        got = self.value(expr, env, False, depth)
        return got if got is not None else self.value(expr, env, True, depth)

    def atom(self, p: str, env: dict[str, str], lenient: bool, depth: int) -> str | None:
        if not p:
            return None
        if p[0] == "(" and _close_paren(p, 0) == len(p) - 1:
            return self.value(p[1:-1], env, lenient, depth)
        if len(p) >= 2 and p[0] in "'\"" and p[-1] == p[0]:
            return _unescape_js(p[1:-1])
        if len(p) >= 2 and p[0] == "`" and p[-1] == "`":
            parts = []
            for i, chunk in enumerate(re.split(r"\$\{([^}]*)\}", p[1:-1])):
                v = chunk if i % 2 == 0 else self.value(chunk, env, lenient, depth)
                if v is None:
                    return None
                parts.append(v)
            return "".join(parts)
        if _NUMBER_RE.fullmatch(p):
            return p
        if p in ("null", "undefined", "true", "false"):
            return None if p in ("null", "undefined") else p
        m = re.fullmatch(r"(.+?)\s*\.\s*(?:trim|toString)\(\s*\)", p, re.S)
        if m:
            return self.atom(m.group(1), env, lenient, depth)
        m = re.fullmatch(r"(encodeURIComponent|encodeURI|escape)\s*\((.*)\)", p, re.S)
        if m:
            inner = self.value(m.group(2), env, lenient, depth)
            if inner is None:
                return None
            safe = "" if m.group(1) == "encodeURIComponent" else "/:?&=#"
            return urllib.parse.quote(inner, safe=safe)
        m = re.fullmatch(r"(.+?)\s*\.\s*serialize\(\s*\)", p, re.S)
        if m:
            # $('#frm').serialize() — 폼의 값(바꾼 값 반영)을 쿼리 글로(jQuery 와 같은 인코딩)
            idx = self.form_of(m.group(1), env)
            if idx is not None:
                return self.serialize(idx)
            return "" if lenient else None
        m = re.fullmatch(
            r"(?:String|Number|parseInt|parseFloat|\$\.trim|jQuery\.trim)\s*\((.*)\)", p, re.S
        )
        if m:
            return self.value(split_top(m.group(1), ",")[0], env, lenient, depth)
        m = _DATA_KEY_RE.fullmatch(p)
        if m:
            # 링크에 없는 data-* 는 빈 값 — 브라우저에서도 null(거짓)이라 조건을 따질 수 있다
            return self.data.get(_norm_key(next(g for g in m.groups() if g)), "")
        got = self.read_input(p, env)
        if got is not None:
            return got
        if _IDENT_RE.fullmatch(p):
            if p in env:
                v = env[p]
                return None if v.startswith("\x00") else v
            got = self.ctx.globals.get(p)
            if got is None and p in self.ctx.global_exprs and p not in self._evaluating:
                self._evaluating.add(p)
                try:
                    got = self.value(self.ctx.global_exprs[p], {}, False, depth + 1)
                finally:
                    self._evaluating.discard(p)
                if got is not None:
                    self.ctx.globals[p] = got
            return got if got is not None else ("" if lenient else None)
        m = re.fullmatch(
            r"(?:window\s*\.\s*|document\s*\.\s*)?location\s*\.\s*(pathname|search|href|host|origin)",
            p,
        )
        if m:
            parts = urllib.parse.urlsplit(self.ctx.page_url)
            return {
                "pathname": parts.path,
                "search": ("?" + parts.query) if parts.query else "",
                "href": self.ctx.page_url,
                "host": parts.netloc,
                "origin": f"{parts.scheme}://{parts.netloc}",
            }[m.group(1)]
        m = re.fullmatch(r"([A-Za-z_][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\((.*)\)", p, re.S)
        if (
            m
            and depth < MAX_DEPTH
            and _close_paren(p, m.end(1) + p[m.end(1) :].index("(")) == len(p) - 1
        ):
            args = self.args(m.group(2), env, depth)
            got = self.call_return(m.group(1), args, depth + 1)
            if got is not None:
                return got
            if _QUERY_HELPER_RE.search(m.group(1).split(".")[-1]) and len(args) >= 3:
                # 쿼리 값을 바꾸는 도우미 — fn_replaceQueryString(q, 'schM', 'view')(동덕여대·화성의과학대)
                return _replace_query(args[0], args[1], args[2])
            if lenient:
                # 정의를 못 읽는 도우미는 첫 인자를 그대로 — 주소를 감싸는 kurl(url)·쿼리를 다듬는
                # removeQueryParam(qs, 'nttNo') 꼴이 대부분이다. 틀리면 확인 단계가 걸러 낸다.
                return args[0] if args and args[0] != THIS else ""
            return None
        return "" if lenient else None

    def serialize(self, idx: int) -> str:
        """폼 값들(바꾼 값 반영) → 'a=1&b=%EA%B0%80' — 고르지 않은 체크·단추·사용 안 함은 뺀다."""
        form = self.ctx.parts.forms[idx]
        sets = dict(self.forms[idx].sets) if idx in self.forms else {}
        pairs = []
        for i, (name, value, _iid) in enumerate(form.inputs):
            kind = form.types[i] if i < len(form.types) else "text"
            base = kind.split(":", 1)[0]
            if (
                not name
                or ":disabled" in kind
                or base in ("submit", "button", "image", "reset", "file")
            ):
                continue
            if base in ("checkbox", "radio") and ":checked" not in kind:
                continue
            pairs.append((name, sets.pop(name, value)))
        pairs += list(sets.items())
        return urllib.parse.urlencode(pairs)

    def args(self, src: str, env: dict[str, str], depth: int) -> list[str]:
        if not src.strip():
            return []
        out = []
        for a in split_top(src, ","):
            a = a.strip()
            if a == "this" or env.get(a) == THIS:
                out.append(THIS)
                continue
            got = self.either(a, env, depth)
            out.append(got if got is not None else "")
        return out

    def read_input(self, p: str, env: dict[str, str]) -> str | None:
        """$('#id').val() · document.getElementById('id').value · f.name.value → 그 값."""
        m = re.fullmatch(r"""(?:\$|jQuery)\s*\(\s*['"]#([\w-]+)['"]\s*\)\s*\.\s*val\(\s*\)""", p)
        if m:
            # 없는 입력칸의 값은 빈 값(undefined) — '$("#masterSecretYn").val() === "Y"' 를 따질 수 있게
            got = self.ctx.input_value(self, by_id=m.group(1))
            return "" if got is None else got
        m = re.fullmatch(
            r"""(?:\$|jQuery)\s*\(\s*['"][^'"]*\[\s*name\s*=\s*['"]?([\w-]+)['"]?\s*\][^'"]*['"]\s*\)"""
            r"""\s*\.\s*val\(\s*\)""",
            p,
        )
        if m:
            return self.ctx.input_value(self, by_name=m.group(1))
        m = re.fullmatch(
            r"""document\s*\.\s*getElementById\(\s*['"]([\w-]+)['"]\s*\)\s*\.\s*value""", p
        )
        if m:
            return self.ctx.input_value(self, by_id=m.group(1))
        m = re.fullmatch(r"([\w$.]+?)\s*\.\s*([\w$]+)\s*\.\s*value", p)
        if m:
            idx = self.form_of(m.group(1), env)
            if idx is not None:
                return self.ctx.input_value(self, by_name=m.group(2), form=idx)
        return None

    # ── 조건 ──
    def truth(self, cond: str, env: dict[str, str], depth: int) -> bool | None:
        cond = cond.strip()
        if not cond:
            return None
        parts = split_ops(cond, "||")
        if len(parts) > 1:
            vals = [self.truth(c, env, depth) for c in parts]
            if any(v is True for v in vals):
                return True
            return False if all(v is False for v in vals) else None
        parts = split_ops(cond, "&&")
        if len(parts) > 1:
            vals = [self.truth(c, env, depth) for c in parts]
            if any(v is False for v in vals):
                return False
            return True if all(v is True for v in vals) else None
        if cond[0] == "(" and _close_paren(cond, 0) == len(cond) - 1:
            return self.truth(cond[1:-1], env, depth)
        if cond.startswith("!") and not cond.startswith("!="):
            v = self.truth(cond[1:], env, depth)
            return None if v is None else not v
        m = re.fullmatch(r"(.+?)\s*(===|!==|==|!=)\s*(.+)", cond, re.S)
        if m:
            a = self.value(m.group(1), env, False, depth)
            b = self.value(m.group(3), env, False, depth)
            if a is None or b is None:
                return None
            return (a == b) if m.group(2) in ("==", "===") else (a != b)
        if re.search(r"[<>]", cond):
            return None
        v = self.value(cond, env, False, depth)
        if v is None:
            return None
        return v not in ("", "0", "false")

    def effectful(self, block: str) -> bool:
        """주소를 만드는 블록인가 — 위치 이동·폼 값·제출, 또는 정의를 아는 사용자 함수 부르기."""
        if _EFFECT_RE.search(block):
            return True
        for m in re.finditer(r"(?<![\w$.])([A-Za-z_][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\(", block):
            name = m.group(1)
            if (
                name.split(".")[-1] not in _NOT_CALLS
                and name not in ("$", "jQuery")
                and self.ctx.function(name)
            ):
                return True
        return False

    # ── 함수 부르기 ──
    def call_return(self, name: str, args: list[str], depth: int) -> str | None:
        """사용자 함수의 return 값(문자열 잇기만)."""
        found = self.ctx.function(name)
        if not found or depth > MAX_DEPTH:
            return None
        params, body = found
        env = {p: (args[i] if i < len(args) else "") for i, p in enumerate(params)}
        result: list[str] = []
        outer, self._uncertain = self._uncertain, False
        try:
            self.execute(body, env, depth, returns=result)
            # 값을 모르는 조건으로 건너뛴 블록에 return 이 있었다 — 돌려준 값을 믿을 수 없다
            # (checkBoardAuth: 권한 함수를 못 읽어 'false' 를 돌려주면 글 보기를 통째로 막는다)
            return None if self._uncertain else (result[0] if result else None)
        finally:
            self._uncertain = outer

    def call(self, name: str, args: list[str], depth: int) -> bool:
        found = self.ctx.function(name)
        if not found or depth > MAX_DEPTH:
            return False
        params, body = found
        env = {p: (args[i] if i < len(args) else "") for i, p in enumerate(params)}
        self.execute(body, env, depth)
        return True

    # ── 코드 따라가기 ──
    def execute(
        self, code: str, env: dict[str, str], depth: int, returns: list[str] | None = None
    ) -> bool:
        """앞에서부터 따라간다 — return 을 만나면 True(그 함수는 거기서 끝)."""
        code = _strip_comments(code)
        i, n = 0, len(code)
        while i < n:
            self.steps += 1
            if self.steps > MAX_STEPS:
                return True
            while i < n and code[i] in " \t\r\n;":
                i += 1
            if i >= n:
                break
            if code[i] == "{":
                inner = _block(code, i + 1)
                if self.execute(inner, env, depth, returns):
                    return True
                i += len(inner) + 2
                continue
            m = _KEYWORD_RE.match(code, i)
            if m and (m.end() >= n or not (code[m.end()].isalnum() or code[m.end()] in "_$")):
                kw = m.group(1)
                j = m.end()
                if kw == "if":
                    paren = code.find("(", j)
                    close = _close_paren(code, paren) if paren >= 0 else -1
                    if close < 0:
                        return False
                    cond = code[paren + 1 : close]
                    then, i = _body(code, close + 1)
                    k = i
                    while k < n and code[k] in " \t\r\n;":
                        k += 1
                    other = None
                    if code.startswith("else", k) and (k + 4 >= n or not code[k + 4].isalnum()):
                        other, i = _body(code, k + 4)
                    verdict = self.truth(cond, env, depth)
                    if verdict is None:
                        effect = self.effectful(then)
                        verdict = effect or not other
                        if not effect and other is None:
                            verdict = False  # 경고·return 뿐인 관문
                        skipped = other if verdict else then
                        if skipped and re.search(r"\breturn\b", skipped):
                            self._uncertain = True
                    branch = then if verdict else other
                    if branch and self.execute(branch, env, depth, returns):
                        return True
                    continue
                if kw in ("for", "while", "switch", "catch", "with"):
                    paren = code.find("(", j)
                    close = _close_paren(code, paren) if paren >= 0 else -1
                    if close < 0:
                        return False
                    _skip, i = _body(code, close + 1)
                    continue
                if kw in ("try", "finally"):
                    inner, i = _body(code, j)
                    if self.execute(inner, env, depth, returns):
                        return True
                    continue
                if kw in ("do", "else"):
                    _skip, i = _body(code, j)
                    if kw == "do":
                        wm = re.compile(r"\s*while\s*\(").match(code, i)
                        if wm:
                            close = _close_paren(code, wm.end() - 1)
                            i = n if close < 0 else close + 1
                    continue
                if kw == "function":
                    brace = code.find("{", j)
                    if brace < 0:
                        return False
                    inner = _block(code, brace + 1)
                    i = brace + len(inner) + 2
                    continue
            start = i
            stmt, i = _simple(code, i)
            if i == start:  # 짝 없는 닫는 괄호 — 건너뛴다(제자리걸음 방지)
                i += 1
                continue
            if stmt and self.statement(stmt, env, depth, returns):
                return True
        return False

    def statement(self, s: str, env: dict[str, str], depth: int, returns: list[str] | None) -> bool:
        """단순 문장 하나 — return 이면 True. 문장 속 콜백(성공 처리 함수)도 따라간다."""
        if self._statement(s, env, depth, returns):
            return True
        if not self.done() and depth < MAX_DEPTH and ("function" in s or "=>" in s):
            # '$.ajax({ …, success: function(data){ location.href = … } })' — 확인 요청의 답을 받은
            # 뒤에 글로 가는 게시판(삼육보건대 bbsChecking). 답은 모르니 주소를 만드는 쪽을 따른다.
            for m in _CALLBACK_RE.finditer(s):
                body = _block(s, m.end())
                if _EFFECT_RE.search(body):
                    self.execute(body, dict(env), depth + 1)
                    if self.done():
                        break
        return False

    def _statement(
        self, s: str, env: dict[str, str], depth: int, returns: list[str] | None
    ) -> bool:
        if s == "return" or s.startswith(("return ", "return(", "return!")):
            rest = s[len("return") :].strip()
            if rest:
                got = self.either(rest, env, depth)
                if got is not None and returns is not None and not returns:
                    returns.append(got)
            return True
        if s.startswith(("var ", "let ", "const ")):
            for decl in split_top(s.split(" ", 1)[1], ","):
                name, eq, rhs = decl.partition("=")
                if eq:
                    self.assign(name.strip(), rhs.strip(), env, depth)
            return False
        split = _assignment(s)
        if split:
            lhs, op, rhs = split
            if op == "+=":
                if _IDENT_RE.fullmatch(lhs) and lhs in env and not env[lhs].startswith("\x00"):
                    extra = self.value(rhs, env, False, depth)
                    if extra is not None:
                        env[lhs] += extra
                return False
            self.assign(lhs, rhs, env, depth)
            return False
        m = _LOC_CALL_RE.match(s) or _OPEN_RE.match(s)
        if m:
            close = _close_paren(s, m.end() - 1)
            if close > 0:
                url = self.either(split_top(s[m.end() : close], ",")[0], env, depth)
                if url:
                    self.locations.append(url)
            return False
        m = re.fullmatch(r"([A-Za-z_][\w$]*)\s*\((.*)\)", s, re.S)
        if m and m.group(1) not in _NOT_CALLS and _close_paren(s, s.index("(")) == len(s) - 1:
            self.call(m.group(1), self.args(m.group(2), env, depth), depth + 1)
            return False
        chain = _chain(s)
        if chain is None:
            return False
        if (
            len(chain.calls) == 1
            and _IDENT_RE.fullmatch(chain.base)
            and chain.base not in env
            and chain.base not in ("document", "window", "location", "this", "$", "jQuery")
            and self.form_of(chain.base, env) is None
        ):
            name = f"{chain.base}.{chain.calls[0][0]}"
            if self.call(name, self.args(chain.calls[0][1], env, depth), depth + 1):
                return False
        self.chain_effects(chain, env, depth)
        return False

    def chain_effects(self, chain: _Chain, env: dict[str, str], depth: int) -> None:
        form = self.form_from_chain(chain, env)
        sel_name = sel_id = None
        m = re.fullmatch(
            r"""(?:\$|jQuery)\s*\(\s*['"]([^'"]+)['"]\s*(?:,\s*[^)]*)?\)""", chain.base
        )
        if m:
            sel = m.group(1).strip()
            im = re.fullmatch(r"#([\w-]+)", sel)
            # 'form[name=searchFrm]' 은 폼 자신이다 — 그 안의 입력칸('#frm [name=x]')이 아니다(부산교대)
            whole = re.fullmatch(r"""form\s*\[\s*(?:name|id)\s*=\s*['"]?[\w-]+['"]?\s*\]""", sel)
            nm = None if whole else re.search(r"""\[\s*name\s*=\s*['"]?([\w-]+)['"]?\s*\]$""", sel)
            if im and form is None:
                sel_id = im.group(1)
            elif nm:
                sel_name = nm.group(1)
                fm = re.match(r"(?:form)?#([\w-]+)\s", sel) or re.match(
                    r"""form\s*\[\s*name\s*=\s*['"]?([\w-]+)['"]?\s*\]\s""", sel
                )
                form = self.ctx.form_by(fm.group(1)) if fm else None
        for method, args in chain.calls:
            parts = split_top(args, ",") if args.strip() else []
            if method == "find" and parts:
                nm = re.search(r"""\[\s*name\s*=\s*['"]?([\w-]+)['"]?\s*\]""", parts[0])
                im = re.fullmatch(r"""\s*['"]#([\w-]+)['"]\s*""", parts[0])
                if nm:
                    sel_name = nm.group(1)
                elif im:
                    sel_id = im.group(1)
                continue
            if method in ("attr", "prop") and len(parts) == 1 and parts[0].strip().startswith("{"):
                # .attr({ action: …, method: 'get' }) — 객체로 한꺼번에(남부대 board_view)
                for key, expr in _object_pairs(parts[0]):
                    if key.lower() == "action" and form is not None:
                        url = self.either(expr, env, depth)
                        if url is not None:
                            self._form_state(form).action = url
                continue
            if method in ("attr", "prop", "setAttribute") and len(parts) >= 2:
                key = (self.value(parts[0], env, False, depth) or "").lower()
                if key == "action" and form is not None:
                    url = self.either(parts[1], env, depth)
                    if url is not None:
                        self._form_state(form).action = url
                elif key == "href" and "location" in chain.base:
                    url = self.either(parts[1], env, depth)
                    if url:
                        self.locations.append(url)
                elif key == "value" and (sel_id or sel_name):
                    v = self.value(parts[1], env, False, depth)
                    if v is not None:
                        self.set_input(v, by_id=sel_id or "", by_name=sel_name or "", form=form)
                continue
            if method == "val" and parts:
                v = self.value(parts[0], env, False, depth)
                if v is not None and (sel_id or sel_name):
                    self.set_input(v, by_id=sel_id or "", by_name=sel_name or "", form=form)
                continue
            if method == "setHidden" and len(parts) >= 2 and form is not None:
                key = self.value(parts[0], env, False, depth)
                v = self.value(parts[1], env, False, depth)
                if key and v is not None:
                    self._form_state(form).sets[key] = v
                continue
            if method in ("submit", "ajaxSubmit") or (method == "trigger" and "submit" in args):
                if form is None and sel_id:
                    form = self.ctx.form_by(sel_id)
                if form is not None:
                    self._form_state(form).submitted = True

    def assign(self, lhs: str, rhs: str, env: dict[str, str], depth: int) -> None:
        if _LOC_LHS_RE.fullmatch(lhs.replace(" ", "")):
            url = self.either(rhs, env, depth)
            if url:
                self.locations.append(url)
            return
        m = re.fullmatch(r"(.+?)\s*\.\s*action", lhs)
        if m:
            idx = self.form_of(m.group(1), env)
            url = self.either(rhs, env, depth)
            if idx is not None and url is not None:
                self._form_state(idx).action = url
            return
        if lhs.endswith(".value"):
            v = self.value(rhs, env, False, depth)
            if v is None:
                return
            target = lhs[: -len(".value")].strip()
            gm = re.fullmatch(
                r"""document\s*\.\s*getElementById\(\s*['"]([\w-]+)['"]\s*\)""", target
            )
            if gm:
                self.set_input(v, by_id=gm.group(1))
                return
            fm = re.fullmatch(
                r"""(.+?)\s*(?:\.\s*elements\s*\[\s*['"]([\w-]+)['"]\s*\]|\[\s*['"]([\w-]+)['"]\s*\]|\.\s*([\w$]+))""",
                target,
            )
            if fm:
                idx = self.form_of(fm.group(1), env)
                name = fm.group(2) or fm.group(3) or fm.group(4)
                if idx is not None:
                    self._form_state(idx).sets[name] = v
                else:
                    self.set_input(v, by_name=name)
            return
        if _IDENT_RE.fullmatch(lhs):
            if rhs == "this" or env.get(rhs) == THIS:
                env[lhs] = THIS
                return
            idx = None if rhs[:1] in "'\"`" else self.form_of(rhs, env)
            if idx is None and rhs[:1] not in "'\"`":
                chain = _chain(rhs)
                if (
                    chain is not None
                    and chain.calls
                    and all(m in _FORM_KEEP for m, _a in chain.calls)
                ):
                    idx = self.form_from_chain(chain, env)
            if idx is not None:
                env[lhs] = f"\x00form:{idx}"
                return
            v = self.either(rhs, env, depth)
            if v is not None:
                env[lhs] = v

    def set_input(
        self, value: str, *, by_id: str = "", by_name: str = "", form: int | None = None
    ) -> None:
        idx, name = self.ctx.locate_input(by_id=by_id, by_name=by_name, form=form)
        if name:
            self._form_state(idx).sets[name] = value


class _Ctx:
    """한 목록 화면의 구조와 (필요할 때만 받는) 같은 사이트 스크립트."""

    def __init__(
        self,
        parts: PageParts,
        page_url: str,
        fetch: Callable[[str], bytes | None] | None,
        allowed: Callable[[str], bool] | None = None,
    ):
        self.parts = parts
        self.page_url = page_url
        self.fetch = fetch
        self.allowed = allowed
        self._external: list[str] | None = None
        self.globals = _globals(parts.scripts)
        self.global_exprs = _global_exprs(parts.scripts)

    def external(self) -> list[str]:
        """같은 사이트의 스크립트 파일(라이브러리 빼고) — 함수를 페이지에서 못 찾을 때만 받는다."""
        if self._external is None:
            self._external = []
            if self.fetch is not None:
                host = urllib.parse.urlsplit(self.page_url).hostname
                srcs = sorted(self.parts.srcs, key=lambda s: 0 if _BOARD_JS_RE.search(s) else 1)
                for src in srcs:
                    if len(self._external) >= MAX_EXTERNAL:
                        break
                    full = urllib.parse.urljoin(self.page_url, src)
                    if urllib.parse.urlsplit(full).hostname != host or _LIB_RE.search(src):
                        continue
                    if self.allowed is not None and not self.allowed(full):
                        continue  # robots.txt 가 막은 스크립트는 받지 않는다
                    code = _script_text(full, self.fetch)
                    if code:
                        self._external.append(code)
                for code in self._external:
                    for k, v in _globals([code]).items():
                        self.globals.setdefault(k, v)
                    for k, v in _global_exprs([code]).items():
                        self.global_exprs.setdefault(k, v)
        return self._external

    def function(self, name: str) -> tuple[list[str], str] | None:
        return find_function(self.parts.scripts, name) or find_function(self.external(), name)

    def handlers(self, classes: list[str], attrs: list[str] = ()) -> list[tuple[list[str], str]]:
        """'.cls'·'[data-x]' 에 걸린 클릭 처리기들의 몸통 — 감싼 함수, 없으면 바로 뒤의 함수."""
        out: list[tuple[list[str], str]] = []
        fn_re = re.compile(r"function\s*[\w$]*\s*\(([^)]*)\)\s*\{|\(([^)]*)\)\s*=>\s*\{")
        marks = [r"\." + re.escape(c) + r"(?![\w-])" for c in classes]
        # 'tbody tr[data-wr-id]' 처럼 data-* 이름으로 고르는 처리기(부산교대)
        marks += [r"\[\s*" + re.escape(a) + r"(?![\w-])" for a in attrs]
        for code in [*self.parts.scripts, *self.external()]:
            for mark in marks:
                for m in re.finditer(mark, code):
                    picked = None
                    # $('.cls').click(function(){…}) · .on('click', '.cls', function(e){…}) — 바로 뒤
                    fm = fn_re.search(code, m.end(), m.end() + 300)
                    if fm and not re.search(r"[;{}]", code[m.end() : fm.start()]):
                        picked = (fm, _block(code, fm.end()))
                    else:
                        # addEventListener('click', function(e){ … closest('.cls') … }) — 감싼 함수
                        for fm in fn_re.finditer(code, max(0, m.start() - 600), m.start()):
                            body = _block(code, fm.end())
                            if fm.end() + len(body) > m.end():
                                picked = (fm, body)
                    if picked:
                        fm, body = picked
                        params = [
                            p.strip()
                            for p in (fm.group(1) or fm.group(2) or "").split(",")
                            if p.strip()
                        ]
                        if (params, body) not in out:
                            out.append((params, body))
                    if len(out) >= 4:
                        return out
        return out

    def form_by(self, key: str) -> int | None:
        for i, f in enumerate(self.parts.forms):
            if key and key in (f.name, f.id):
                return i
        return None

    def anchor_form(self) -> int | None:
        """링크가 든 폼 — 목록 화면 자신으로 가는 폼 중 숨은 값이 가장 많은 것.

        '?menuno=4005' 화면의 폼 action 이 '/index.html?menuno=4005' 인 사이트가 있어(을지대),
        경로가 '' · '/' · '/index.*' 이면 같은 화면으로 본다. 그래도 없으면 같은 사이트로 가는
        폼 중 검색창이 아닌 것.
        """
        page = urllib.parse.urlsplit(self.page_url)

        def same(path: str) -> bool:
            return _index_path(path) == _index_path(page.path)

        best, size = None, -1
        fallback, fsize = None, -1
        for i, f in enumerate(self.parts.forms):
            target = urllib.parse.urlsplit(
                urllib.parse.urljoin(self.page_url, f.action or self.page_url)
            )
            if target.netloc != page.netloc or re.search(
                r"search|srch|total|login", f.name + f.id, re.I
            ):
                continue
            if same(target.path) and len(f.inputs) > size:
                best, size = i, len(f.inputs)
            elif len(f.inputs) > fsize:
                fallback, fsize = i, len(f.inputs)
        return best if best is not None else fallback

    def locate_input(
        self, *, by_id: str = "", by_name: str = "", form: int | None = None
    ) -> tuple[int, str]:
        forms = self.parts.forms
        order = [form] if form is not None else []
        order += [i for i in range(len(forms)) if i != form]
        for i in order:
            for name, _value, iid in forms[i].inputs:
                if (by_id and iid == by_id) or (by_name and name == by_name):
                    return i, name
        if by_id:
            for name, _value, iid in self.parts.loose_inputs:
                if iid == by_id:
                    return -1, name
            return -1, ""
        return (form if form is not None else -1), by_name

    def input_value(
        self, run: _Run, *, by_id: str = "", by_name: str = "", form: int | None = None
    ) -> str | None:
        idx, name = self.locate_input(by_id=by_id, by_name=by_name, form=form)
        if not name:
            return None
        state = run.forms.get(idx)
        if state and name in state.sets:
            return state.sets[name]
        pool = self.parts.forms[idx].inputs if idx >= 0 else self.parts.loose_inputs
        for n, v, _i in pool:
            if n == name:
                return v
        return None


MAX_EXTERNAL = 8


def _index_path(path: str) -> str:
    """'' · '/' · '/index.html' · '/main/index.do' 의 디렉터리 첫 화면을 같은 것으로."""
    path = path or "/"
    return re.sub(r"/(?:index|default|main)\.(?:html?|do|jsp|php|aspx?)$", "/", path)


# 게시판 스크립트다운 이름 — 이것부터 받는다(고려대 portalBoardList.js 는 스무 번째였다)
_BOARD_JS_RE = re.compile(r"board|bbs|list|article|notice|view|ntt|common", re.I)
_LIB_RE = re.compile(
    r"jquery|bootstrap|swiper|slick|aos\.|gsap|lodash|moment|polyfill|analytics|gtag|kakao|naver|"
    r"google|facebook|chart|datepicker|select2|owl|fancybox|lightbox|tweenmax|scrollmagic|"
    r"scrolltrigger|vue|react|babel|bluebird|html5shiv|respond|modernizr",
    re.I,
)
_GLOBAL_RE = re.compile(
    r"""(?:^|[;\n])\s*(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*(['"])((?:(?!\2)[^\\\n]|\\.)*)\2"""
)
_JS_CACHE: dict[str, str] = {}
_JS_LOCK = threading.Lock()
MAX_JS_BYTES = 800_000


_GLOBAL_EXPR_RE = re.compile(
    r"(?:^|[;\n])\s*(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*([^;\n]{1,300})"
)


def _global_exprs(codes: list[str]) -> dict[str, str]:
    """'const ARTICLE_BASE_URL = `/${SITE}/article`' 처럼 식으로 둔 전역 상수 — 쓸 때 계산한다."""
    out: dict[str, str] = {}
    for code in codes:
        for m in _GLOBAL_EXPR_RE.finditer(code):
            out.setdefault(m.group(1), m.group(2).strip())
    return out


def _globals(codes: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for code in codes:
        for m in _GLOBAL_RE.finditer(code):
            out.setdefault(m.group(1), _unescape_js(m.group(3)))
    return out


def _script_text(url: str, fetch: Callable[[str], bytes | None]) -> str:
    from .fetch import decode_text

    with _JS_LOCK:
        if url in _JS_CACHE:
            return _JS_CACHE[url]
    data = fetch(url)
    text = decode_text(data[:MAX_JS_BYTES]) if data else ""
    with _JS_LOCK:
        if len(_JS_CACHE) > 32:
            _JS_CACHE.clear()
        _JS_CACHE[url] = text
    return text


# ── 한 링크 → 후보 주소들 ────────────────────────────────────────────────────
def _data_of(script: str) -> tuple[dict[str, str], list[str]]:
    """'#data:data-id=5&class=btn+view' → ({'id': '5'}, ['btn', 'view'])."""
    data, classes, _names = _data_parts(script)
    return data, classes


def _data_parts(script: str) -> tuple[dict[str, str], list[str], list[str]]:
    """_data_of 에 data-* 속성 이름들('data-wr-id')까지 — 이름으로 고르는 처리기를 찾는다."""
    pairs = urllib.parse.parse_qsl(script[len(DATA_MARK) :], keep_blank_values=True)
    data = {_norm_key(k[len("data-") :]): v for k, v in pairs if k.startswith("data-")}
    classes = next((v.split() for k, v in pairs if k == "class"), [])
    names = [k for k, _v in pairs if k.startswith("data-")]
    return data, classes, names


def candidates(script: str, ctx: _Ctx) -> list[Candidate]:
    """제목 링크의 스크립트(또는 data-* 표시) → 글 주소 후보들(꼴마다 하나)."""
    run = _Run(ctx, {})
    if script.startswith(DATA_MARK):
        data, classes, names = _data_parts(script)
        if not any(data.values()) or not (classes or names):
            return []
        run.data = data
        for _params, body in ctx.handlers(classes, names):
            run.execute(body, {"this": THIS}, 1)
            if run.done():
                break
    else:
        code = strip_js_prefix(script)
        run.execute(code, {"this": THIS}, 0)
        call = call_of(code)
        if not run.done() and not run.forms and call:
            run.call(call[0], [THIS if a == "this" else a for a in call[1]], 1)
    return _to_candidates(run, ctx)


def _to_candidates(run: _Run, ctx: _Ctx) -> list[Candidate]:
    """깔끔한 꼴부터 — 위치 이동 주소, (폼) 바꾼 값만, action 만, 폼의 값 전부."""
    out: list[Candidate] = []
    page = ctx.page_url
    for loc in run.locations:
        url = _absolute(loc, page)
        if url:
            out.append(Candidate("loc", url))
            break
    states = [s for s in run.forms.values() if s.submitted]
    if not states and not out:
        # 제출하는 함수를 못 읽었어도 action 을 바꿨다면 그 주소 — 확인 단계가 거른다
        states = [s for s in run.forms.values() if s.action]
    for state in states:
        form = ctx.parts.forms[state.index] if state.index >= 0 else Form()
        action = state.action if state.action is not None else form.action
        base = _absolute(action or page, page)
        if not base:
            continue
        static = [(n, v) for n, v, _i in form.inputs if n and v and not _CSRF_RE.search(n)]
        sets = [(n, v) for n, v in state.sets.items() if v and not _CSRF_RE.search(n)]
        if sets:
            out.append(Candidate("form_set", _with_query(base, sets)))
        elif base != _absolute(page, page):
            out.append(Candidate("form_bare", base))
        merged = dict(static)
        merged.update(sets)
        if merged and (static or not sets):
            out.append(Candidate("form_all", _with_query(base, list(merged.items()))))
        break
    out += _variants(out, page)
    seen: set[str] = set()
    uniq = []
    for c in out:
        if c.url not in seen:
            seen.add(c.url)
            uniq.append(c)
    return uniq


def _variants(cands: list[Candidate], page: str) -> list[Candidate]:
    """확인에 쓸 덜 확실한 꼴 — 맨 뒤에 둔다.

    - 'X.do' 목록의 사이트에서 확장자 없는 '/…/view' 주소(K2Web kurl() 이 '.do' 를 붙인다 —
      협성대 '/portalBbs/uhs/4/99241/view' 는 404, '.do' 는 글)
    - 값이 빈 쿼리를 단 action('…/detailView.do?pageIndex=&menu=2379' — 전북대 400)의 경로만
    """
    out: list[Candidate] = []
    page_do = urllib.parse.urlsplit(page).path.endswith(".do")
    for c in cands:
        parts = urllib.parse.urlsplit(c.url)
        last = parts.path.rsplit("/", 1)[-1]
        if page_do and last and "." not in last:
            out.append(
                Candidate(
                    c.kind + "_do", urllib.parse.urlunsplit(parts._replace(path=parts.path + ".do"))
                )
            )
        if parts.query and c.kind in ("form_bare", "loc"):
            out.append(
                Candidate(c.kind + "_path", urllib.parse.urlunsplit(parts._replace(query="")))
            )
    return out


_SESSION_RE = re.compile(r";jsessionid=[^?#]*", re.I)


def _absolute(url: str, page: str) -> str:
    url = (url or "").strip()
    if not url or url.lower().startswith(("javascript", "#", "mailto:")):
        return ""
    full = urllib.parse.urljoin(page, _SESSION_RE.sub("", url))
    parts = urllib.parse.urlsplit(full)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    query = re.sub(r"&{2,}", "&", parts.query).strip("&")  # '?&schM=view' → '?schM=view'
    return urllib.parse.urlunsplit(parts._replace(query=query, fragment=""))


def _with_query(base: str, pairs: list[tuple[str, str]]) -> str:
    parts = urllib.parse.urlsplit(base)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    keys = {k for k, _ in pairs}
    query = [(k, v) for k, v in query if k not in keys] + pairs
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


# ── 확인: 첫 글 하나를 열어 그 글인지 본다 ───────────────────────────────────
_FAILED: dict[tuple, float] = {}  # 연결 실패·시간 제한으로 확인 못 한 꼴 → 그때(잠시 쉬었다 다시)
FAILED_TTL = 600.0
_VERIFIED: dict[tuple, str] = {}  # (호스트, 함수 이름, 후보 꼴들) → 통한 꼴('' = 안 통함)
_VERIFIED_LOCK = threading.Lock()
_SPACE_RE = re.compile(r"\s+")
_ELLIPSIS_RE = re.compile(r"(?:\.\.\.|…)+$")


def _flat(text: str) -> str:
    return _SPACE_RE.sub("", html.unescape(text or ""))


_HEAD_TAG_RE = re.compile(r"^(?:\[[^\]]{1,20}\]|\([^)]{1,20}\)|【[^】]{1,20}】|<[^>]{1,20}>)\s*")


def _title_keys(title: str) -> list[str]:
    """글 화면에서 찾을 제목 조각들(18자) — 그대로, 앞의 짧은 낱말('국제'·'공 지')을 뗀 것,
    앞 머리말('[심리상담센터]')을 뗀 것. 목록 칸에만 붙는 말이 글 화면에는 없을 수 있다."""
    base = _ELLIPSIS_RE.sub("", " ".join((title or "").split())).strip()
    forms = [base]
    words = base.split(" ")
    for n in (1, 2):
        head = words[:n]
        if len(words) > n and all(len(w) <= 4 and w[:1] not in "[(【<" for w in head):
            forms.append(" ".join(words[n:]))
    for form in list(forms):
        s = form
        while True:
            t = _HEAD_TAG_RE.sub("", s, count=1)
            if t == s:
                break
            s = t
        forms.append(s)
    keys: list[str] = []
    for form in forms:
        k = _flat(form)[:18]
        if len(k) >= 6 and k not in keys:
            keys.append(k)
    # 짧은 제목 뒤에 칸 글자가 붙은 경우('… 원장 채용 공고 일반' — 분류 칸이 링크 안에 있다)
    short = _flat(base)[:12]
    if len(short) >= 8 and short not in keys:
        keys.append(short)
    return keys


def looks_like_post(
    data: bytes | None, title: str, others: list[str], listing: bytes | None = None
) -> bool:
    """받은 화면이 그 글인가 — 제목이 보이고, 목록 화면이 아니다.

    목록이 아니라는 것: 목록의 다른 제목들이 거의 없다(이전·다음 글 두셋은 괜찮다), 그
    화면을 목록으로 읽어도 다른 제목들이 줄지어 나오지 않는다, 목록 화면과 똑같지 않다
    (주소의 값을 무시하고 목록을 다시 주는 서버).
    """
    from . import govweb
    from .fetch import decode_text

    if not data:
        return False
    head = data[:2048]
    if head.startswith((b"%PDF", b"PK\x03\x04", b"\xd0\xcf\x11\xe0")) or b"\x00" in head:
        return False
    text = decode_text(data)
    page = _flat(text)
    keys_of_title = _title_keys(title)
    flat_others = [_flat(o) for o in others]
    # 머리말을 뗀 조각은 다른 글 제목에도 들어 있으면 쓰지 않는다('1차 …'·'2차 …' 같은 연재 글)
    usable = [
        k for i, k in enumerate(keys_of_title) if i == 0 or not any(k in o for o in flat_others)
    ]
    if not usable or not any(k in page for k in usable):
        return False
    key = keys_of_title[0]
    if listing is not None and page == _flat(decode_text(listing)):
        return False
    keys = [
        k
        for k in (_flat(_ELLIPSIS_RE.sub("", t.strip()))[:18] for t in others)
        if len(k) >= 6 and k != key
    ]
    if len(keys) >= 3 and sum(1 for k in keys if k in page) > max(2, len(keys) // 3):
        return False
    listed = {_flat(r.title)[:18] for r in govweb.parse_list(data, "https://x.invalid/")}
    return sum(1 for k in keys if k in listed) < 3


def _signature(script: str) -> str:
    if script.startswith(DATA_MARK):
        _data, classes, names = _data_parts(script)
        return "data:" + ".".join(sorted(classes)) + "|" + ".".join(sorted(names))
    call = call_of(script)
    return call[0] if call else "inline"


def resolve_rows(
    rows: list,
    data: bytes,
    list_url: str,
    fetch: Callable[[str], bytes | None] | None,
    *,
    allowed: Callable[[str], bool] | None = None,
) -> list:
    """`script` 가 있는 행(제목이 스크립트 링크)의 주소를 진짜 글 주소로 바꾼다.

    rows: k2web_parse.Row 목록. 확인(첫 글 열기)이 안 되면 그대로 돌려준다.
    """
    from .fetch import decode_text

    targets = [i for i, r in enumerate(rows) if getattr(r, "script", "")]
    if not targets or fetch is None:
        return rows
    ctx = _Ctx(page_parts(decode_text(data)), list_url, fetch, allowed)
    host = urllib.parse.urlsplit(list_url).netloc.lower()
    titles = [r.title for r in rows]
    built: dict[int, dict[str, str]] = {}
    for i in targets:
        cands = candidates(rows[i].script, ctx)
        if cands:
            built[i] = {c.kind: c.url for c in cands}
    if not built:
        return rows
    out = list(rows)
    by_sig: dict[str, list[int]] = {}
    for i in built:
        by_sig.setdefault(_signature(rows[i].script), []).append(i)
    for sig, idxs in by_sig.items():
        kind = _verified_kind(host, sig, rows, idxs, built, titles, fetch, allowed, data)
        if not kind:
            continue
        for i in idxs:
            url = built[i].get(kind)
            if url:
                out[i] = replace(rows[i], url=url)
    return out


KIND_ORDER = (
    "loc",
    "form_set",
    "form_bare",
    "form_all",
    "loc_do",
    "form_set_do",
    "form_bare_do",
    "form_all_do",
    "loc_path",
    "form_bare_path",
)
MAX_CHECKS = 4


def _verified_kind(
    host: str,
    sig: str,
    rows: list,
    idxs: list[int],
    built: dict[int, dict[str, str]],
    titles: list[str],
    fetch: Callable[[str], bytes | None],
    allowed: Callable[[str], bool] | None,
    listing: bytes | None = None,
) -> str:
    memo = (host, sig, tuple(k for k in KIND_ORDER if k in built[idxs[0]]))
    with _VERIFIED_LOCK:
        if memo in _VERIFIED:
            return _VERIFIED[memo]
        failed_at = _FAILED.get(memo)
        if failed_at is not None and time.monotonic() - failed_at < FAILED_TTL:
            return ""  # 방금 열지 못한 꼴 — 잠시 다시 열지 않는다
    first = idxs[0]
    checks = 0
    judged = False  # 화면을 받아 보고 판단했는가(연결 실패·시간 제한이면 기억하지 않는다)
    found = ""
    for kind in KIND_ORDER:
        url = built[first].get(kind)
        if not url or checks >= MAX_CHECKS:
            continue
        if allowed is not None and not allowed(url):
            continue
        checks += 1
        others = [t for j, t in enumerate(titles) if j != first]
        page = fetch(url)
        judged = judged or bool(page)
        if looks_like_post(page, rows[first].title, others, listing):
            found = kind
            break
    if found or judged:
        with _VERIFIED_LOCK:
            _VERIFIED[memo] = found
    elif checks:
        with _VERIFIED_LOCK:
            _FAILED[memo] = time.monotonic()
    return found


def reset_cache() -> None:
    with _VERIFIED_LOCK:
        _VERIFIED.clear()
        _FAILED.clear()
    with _JS_LOCK:
        _JS_CACHE.clear()
