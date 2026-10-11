"""스크립트로만 열리는 글 링크 — 페이지의 구조(링크·폼·스크립트)를 읽는 도구.

목록의 제목 링크가 `javascript:fn_view('1234')` · `href="#" onclick="goView(1234)"`
뿐인 게시판이 많다. 글 주소는 사이트가 이미 알고 있다 — 그 함수의 정의가 페이지
(또는 같은 사이트의 .js) 안에 있다. 이 모듈은 그것을 **읽는** 부품이다(실행하지 않는다):

  - `PageParts`  : 링크(속성 전부)·폼(숨은 값)·스크립트(본문·src)
  - `call_of`    : 'fn_view('1234', 5)' → ('fn_view', ['1234', '5'])
  - `find_function`: 스크립트 본문에서 함수 정의(매개변수, 몸통)를 찾는다

본문 글자는 다루지 않는다 — 링크의 속성과 스크립트 코드만 본다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass(slots=True)
class Form:
    name: str = ""
    id: str = ""
    action: str = ""
    method: str = ""
    inputs: list[tuple[str, str, str]] = field(default_factory=list)  # (name, value, id)


@dataclass(slots=True)
class Anchor:
    attrs: dict[str, str]
    text: str


class _PartsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[Anchor] = []
        self.scripts: list[str] = []
        self.srcs: list[str] = []
        self.forms: list[Form] = []
        self.loose_inputs: list[tuple[str, str, str]] = []  # 폼 밖의 숨은 값
        self._a: dict[str, str] | None = None
        self._a_text: list[str] = []
        self._script: list[str] | None = None
        self._form: Form | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "a":
            if self._a is not None:  # 닫히지 않은 링크
                self._close_anchor()
            self._a, self._a_text = a, []
        elif tag == "script":
            if a.get("src"):
                self.srcs.append(a["src"].strip())
            self._script = []
        elif tag == "form":
            self._form = Form(
                name=a.get("name", ""),
                id=a.get("id", ""),
                action=a.get("action", ""),
                method=a.get("method", "").lower(),
            )
            self.forms.append(self._form)
        elif tag == "input":
            item = (a.get("name", ""), a.get("value", ""), a.get("id", ""))
            if self._form is not None:
                self._form.inputs.append(item)
            elif a.get("type", "").lower() == "hidden":
                self.loose_inputs.append(item)

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script.append(data)
        elif self._a is not None:
            self._a_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._a is not None:
            self._close_anchor()
        elif tag == "script" and self._script is not None:
            self.scripts.append("".join(self._script))
            self._script = None
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


def page_parts(html_text: str) -> PageParts:
    parser = _PartsParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:  # 깨진 HTML — 읽은 데까지
        pass
    return PageParts(parser.anchors, parser.scripts, parser.srcs, parser.forms, parser.loose_inputs)


# ── 함수 호출 읽기 ────────────────────────────────────────────────────────────
_CALL_RE = re.compile(r"([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(")
_ARG_RE = re.compile(r"""\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|(-?[\w.$]+))\s*(,|\))""")
_NOT_CALLS = frozenset({"void", "return", "if", "function", "alert", "confirm"})


def call_of(js: str) -> tuple[str, list[str]] | None:
    """'javascript:fn_view('1234', 5); return false;' → ('fn_view', ['1234', '5']).

    인자가 글자·숫자가 아닌 것(this·event 같은 이름)은 이름 그대로 둔다. 못 읽으면 None.
    """
    body = (js or "").strip()
    if body.lower().startswith("javascript:"):
        body = body[len("javascript:") :]
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
            if end == ")":
                return name, args
        # 인자를 끝까지 못 읽은 호출 — 다음 호출을 본다
    return None


# ── 함수 정의 찾기 ────────────────────────────────────────────────────────────
def _def_patterns(name: str) -> list[re.Pattern[str]]:
    short = re.escape(name.split(".")[-1])
    return [
        re.compile(r"function\s+" + short + r"\s*\(([^)]*)\)\s*\{"),
        re.compile(r"\b" + short + r"\s*[:=]\s*(?:async\s+)?function\s*[\w$]*\s*\(([^)]*)\)\s*\{"),
        re.compile(r"\b" + short + r"\s*[:=]\s*\(([^)]*)\)\s*=>\s*\{"),
    ]


def _block(text: str, start: int, limit: int = 6000) -> str:
    """'{' 바로 뒤에서 짝 맞는 '}' 까지(글자·주석 속 괄호는 대충 건너뛴다)."""
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
            m = pat.search(text)
            if m:
                params = [p.strip().split("=")[0].strip() for p in m.group(1).split(",")]
                return [p for p in params if p], _block(text, m.end())
    return None
