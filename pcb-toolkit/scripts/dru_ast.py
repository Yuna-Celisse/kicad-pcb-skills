#!/usr/bin/env python3
"""dru_ast.py — KiCad `.kicad_dru` 结构解析器（M1.2）

只做**语法**：tokenize → AST，保留原始顺序与源码位置。
不做规则遮蔽/优先级/约束效力（那是 lint_dru 的职责）。

设计原则：
  - 未知节点、未知 constraint **完整保留**并标记 `known: false`，绝不静默丢弃
  - 语法错误报 `line:col`，返回已解析的部分 AST，而不是抛裸异常
  - 字符串内的 `#` 不是注释；注释只在字符串外生效

用法：
    python dru_ast.py file.kicad_dru
    python dru_ast.py file.kicad_dru --json out.json
退出码：0 无语法错误；1 有错误；2 文件不可读。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

MAX_DEPTH = 256

# KiCad 8/9/10 常见 constraint 名；未知名字不报错，只标记 known=false
KNOWN_CONSTRAINTS = {
    "annular_width", "clearance", "courtyard_clearance", "diff_pair_gap",
    "diff_pair_uncoupled", "disallow", "edge_clearance", "hole_clearance",
    "hole_size", "hole_to_hole", "length", "physical_clearance",
    "silk_clearance", "skew", "thermal_relief_gap", "thermal_spoke_width",
    "track_angle", "track_width", "via_count", "via_diameter",
    "zone_connection", "text_height", "text_thickness", "text_size",
    "solder_mask_expansion", "solder_paste_expansion",
}


@dataclass
class Token:
    kind: str          # lparen | rparen | atom | string | comment | eof
    text: str          # 原始文本
    value: str | None  # 反转义后的值
    line: int
    col: int
    offset: int


@dataclass
class Node:
    kind: str                       # document | list | atom | string
    line: int
    col: int
    offset: int
    value: str | None = None
    raw: str | None = None
    items: list = field(default_factory=list)


@dataclass
class Diagnostic:
    code: str
    message: str
    line: int
    col: int


@dataclass
class ParseResult:
    root: Node | None
    comments: list[Token]
    errors: list[Diagnostic]
    token_count: int


# ---------------------------------------------------------------------------
# 词法
# ---------------------------------------------------------------------------

_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


def tokenize(src: str) -> tuple[list[Token], list[Diagnostic]]:
    tokens: list[Token] = []
    errors: list[Diagnostic] = []
    i, n = 0, len(src)
    line, col = 1, 1

    def advance(ch: str) -> None:
        nonlocal line, col
        if ch == "\n":
            line += 1
            col = 1
        else:
            col += 1

    while i < n:
        ch = src[i]
        if ch in " \t\r\n":
            advance(ch)
            i += 1
            continue

        if ch == "#":
            start_line, start_col, start = line, col, i
            j = i
            while j < n and src[j] not in "\r\n":
                j += 1
            text = src[start:j]
            tokens.append(Token("comment", text, text, start_line, start_col, start))
            for c in text:
                advance(c)
            i = j
            continue

        if ch == "(":
            tokens.append(Token("lparen", "(", None, line, col, i))
            advance(ch)
            i += 1
            continue

        if ch == ")":
            tokens.append(Token("rparen", ")", None, line, col, i))
            advance(ch)
            i += 1
            continue

        if ch == '"':
            start_line, start_col, start = line, col, i
            advance(ch)          # 起始引号本身也占一列
            j = i + 1
            buf: list[str] = []
            closed = False
            while j < n:
                c = src[j]
                if c == "\\" and j + 1 < n:
                    nxt = src[j + 1]
                    mapped = _ESCAPES.get(nxt)
                    if mapped is None:
                        buf.append(c)       # 未知转义保留原样
                        buf.append(nxt)
                    else:
                        buf.append(mapped)
                    advance(c)
                    advance(nxt)
                    j += 2
                    continue
                if c == '"':
                    closed = True
                    advance(c)
                    j += 1
                    break
                buf.append(c)
                advance(c)
                j += 1
            if not closed:
                errors.append(Diagnostic(
                    "E_UNTERMINATED_STRING", "字符串未闭合", start_line, start_col))
            tokens.append(Token("string", src[start:j], "".join(buf),
                                start_line, start_col, start))
            i = j
            continue

        start_line, start_col, start = line, col, i
        j = i
        while j < n and src[j] not in ' \t\r\n()#"':
            j += 1
        atom = src[start:j]
        for c in atom:
            advance(c)
        tokens.append(Token("atom", atom, atom, start_line, start_col, start))
        i = j

    tokens.append(Token("eof", "", None, line, col, n))
    return tokens, errors


# ---------------------------------------------------------------------------
# 语法
# ---------------------------------------------------------------------------

class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.i = 0
        self.errors: list[Diagnostic] = []
        self.comments: list[Token] = []

    def peek(self) -> Token:
        return self.tokens[self.i]

    def advance(self) -> Token:
        tok = self.tokens[self.i]
        if tok.kind != "eof":
            self.i += 1
        return tok

    def skip_comments(self) -> None:
        while self.peek().kind == "comment":
            self.comments.append(self.advance())

    def parse_document(self) -> Node:
        items: list[Node] = []
        while True:
            self.skip_comments()
            tok = self.peek()
            if tok.kind == "eof":
                break
            if tok.kind == "rparen":
                self.errors.append(Diagnostic(
                    "E_UNEXPECTED_CLOSE", "多余的 ')'", tok.line, tok.col))
                self.advance()
                continue
            node = self.parse_expr(0)
            if node is not None:
                items.append(node)
        return Node("document", 1, 1, 0, items=items)

    def parse_expr(self, depth: int) -> Node | None:
        self.skip_comments()
        tok = self.peek()
        if tok.kind == "lparen":
            return self.parse_list(depth)
        if tok.kind == "atom":
            self.advance()
            return Node("atom", tok.line, tok.col, tok.offset, value=tok.value)
        if tok.kind == "string":
            self.advance()
            return Node("string", tok.line, tok.col, tok.offset,
                        value=tok.value, raw=tok.text)
        if tok.kind == "rparen":
            self.errors.append(Diagnostic(
                "E_UNEXPECTED_CLOSE", "多余的 ')'", tok.line, tok.col))
            self.advance()
            return None
        if tok.kind == "eof":
            self.errors.append(Diagnostic(
                "E_UNEXPECTED_EOF", "输入意外结束", tok.line, tok.col))
            return None
        self.advance()
        return None

    def parse_list(self, depth: int) -> Node | None:
        open_tok = self.advance()  # '('
        node = Node("list", open_tok.line, open_tok.col, open_tok.offset)
        if depth >= MAX_DEPTH:
            self.errors.append(Diagnostic(
                "E_DEPTH", f"嵌套超过 {MAX_DEPTH} 层", open_tok.line, open_tok.col))
            # 丢弃到匹配的右括号，避免无限递归
            level = 1
            while level > 0 and self.peek().kind != "eof":
                tok = self.advance()
                if tok.kind == "lparen":
                    level += 1
                elif tok.kind == "rparen":
                    level -= 1
            return node

        while True:
            self.skip_comments()
            tok = self.peek()
            if tok.kind == "eof":
                self.errors.append(Diagnostic(
                    "E_UNCLOSED", "列表未闭合：缺少 ')'", open_tok.line, open_tok.col))
                return node
            if tok.kind == "rparen":
                self.advance()
                return node
            child = self.parse_expr(depth + 1)
            if child is not None:
                node.items.append(child)
        # 不会到这里


def parse(source: str) -> ParseResult:
    tokens, lex_errors = tokenize(source)
    parser = Parser(tokens)
    root = parser.parse_document()
    return ParseResult(root=root, comments=parser.comments,
                       errors=lex_errors + parser.errors,
                       token_count=len(tokens))


# ---------------------------------------------------------------------------
# 注解：标签 + known 标记（不丢弃任何节点）
# ---------------------------------------------------------------------------

def head_atom(node: Node) -> str | None:
    if node.kind == "list" and node.items and node.items[0].kind == "atom":
        return node.items[0].value
    return None


# 已识别的 constraint 子形式；其余保留并标未知
CONSTRAINT_VALUE_HEADS = {"min", "max", "opt"}

# 子节点继承的解释上下文
CHILD_CONTEXT = {
    "rule": "rule",
    "constraint": "constraint",
    "constraint_value": "value",
    "condition": "value",
    "layer": "value",
    "severity": "value",
    "version": "value",
    "unknown": "unparsed",
    "unparsed": "unparsed",
}


def classify(node: Node, context: str | None):
    """返回 (tag, known, name)。

    context="unparsed" 表示祖先未知：整棵子树都不按正常规则解释，
    但仍完整保留，供 lint 报 review。
    """
    head = head_atom(node)
    if context in ("unparsed", "value"):
        # 未知容器内、或落在叶子上下文里的列表，一律不解释；
        # 但保留 rule 的名字，便于 lint 指出"这条规则没有被理解"
        name = first_string(node) if head == "rule" else head
        return "unparsed", False, name
    if context is None:
        if head == "version":
            return "version", True, None
        if head == "rule":
            return "rule", True, first_string(node)
        return "unknown", False, head
    if context == "rule":
        if head == "constraint":
            name = node.items[1].value if len(node.items) > 1 and \
                node.items[1].kind == "atom" else None
            known = name in KNOWN_CONSTRAINTS
            return "constraint", known, name
        if head == "condition":
            return "condition", True, None
        if head == "layer":
            return "layer", True, None
        if head == "severity":
            return "severity", True, None
        return "unknown", False, head
    if context == "constraint":
        if head in CONSTRAINT_VALUE_HEADS:
            return "constraint_value", True, head
        return "unknown", False, head
    return "unknown", False, head


def first_string(node: Node) -> str | None:
    for item in node.items[1:]:
        if item.kind == "string":
            return item.value
    return None


def to_json(node: Node, context: str | None = None) -> dict:
    base = {"kind": node.kind, "line": node.line, "col": node.col,
            "offset": node.offset}
    if node.kind == "atom":
        base["value"] = node.value
        return base
    if node.kind == "string":
        base["value"] = node.value
        base["raw"] = node.raw
        return base
    if node.kind == "document":
        base["tag"] = "document"
        base["known"] = True
        base["items"] = [to_json(c, None) for c in node.items]
        return base
    tag, known, name = classify(node, context)
    base["tag"] = tag
    base["known"] = known
    if name is not None:
        base["name"] = name
    child_context = CHILD_CONTEXT.get(tag, "unparsed" if not known else "value")
    base["items"] = [to_json(c, child_context) for c in node.items]
    return base


def walk(node: dict):
    yield node
    for child in node.get("items", []):
        yield from walk(child)


def summarize(ast: dict) -> dict:
    rules, constraints, unknown, conditions, layers = [], [], [], [], []
    for n in walk(ast):
        tag = n.get("tag")
        if tag == "rule":
            rules.append(n.get("name"))
        elif tag == "constraint":
            constraints.append(n.get("name"))
            if not n.get("known"):
                unknown.append({"tag": "constraint", "name": n.get("name"),
                                "line": n.get("line"), "col": n.get("col")})
        elif tag in ("unknown", "unparsed"):
            unknown.append({"tag": tag, "name": n.get("name"),
                            "line": n.get("line"), "col": n.get("col")})
        elif tag == "condition":
            conditions.append(n)
        elif tag == "layer":
            layers.append(n)
    return {
        "rules": rules,
        "constraints": constraints,
        "conditions": len(conditions),
        "layers": len(layers),
        "unknown": unknown,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def analyze(path: Path) -> dict:
    src = path.read_text(encoding="utf-8")
    result = parse(src)
    ast = to_json(result.root) if result.root else None
    return {
        "file": str(path),
        "comments": [{"line": c.line, "col": c.col, "text": c.text}
                     for c in result.comments],
        "errors": [{"code": e.code, "message": e.message,
                    "line": e.line, "col": e.col} for e in result.errors],
        "summary": summarize(ast) if ast else {},
        "ast": ast,
    }


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="KiCad .kicad_dru 结构解析（M1.2）")
    ap.add_argument("path")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    path = Path(args.path)
    if not path.is_file():
        print(f"找不到文件：{path}", file=sys.stderr)
        return 2

    report = analyze(path)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.quiet:
        s = report["summary"]
        print(f"\n=== {path.name} ===")
        print(f"rules={len(s.get('rules', []))} constraints={len(s.get('constraints', []))} "
              f"conditions={s.get('conditions', 0)} layers={s.get('layers', 0)} "
              f"comments={len(report['comments'])}")
        for name in s.get("rules", []):
            print(f"  rule: {name}")
        for item in s.get("unknown", []):
            print(f"  unknown [{item['tag']}] {item['name']} @ {item['line']}:{item['col']}")
        for err in report["errors"]:
            print(f"  ERROR {err['code']} @ {err['line']}:{err['col']} — {err['message']}")

    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
