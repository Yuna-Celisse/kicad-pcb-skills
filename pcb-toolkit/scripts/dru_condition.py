#!/usr/bin/env python3
"""dru_condition.py — KiCad `.kicad_dru` condition 表达式的解析与保守包含判定（M1.3）

只处理可判定的子集：`&&` / `||` / `!`、比较（`== != > >= < <=`）、
属性路径（`A.NetClass`）、方法调用（`A.intersectsArea('X')`）、布尔谓词。

关系判定返回三值：
    True  已证明成立（sub 的每个满足点都满足 sup）
    False 已证明不成立
    None  未知 —— 调用方必须按 review 处理，不得当成 False

设计原则：宁可返回 None，也不返回错误的 True。
"""

from __future__ import annotations

from dataclasses import dataclass

INF = float("inf")
CMP_OPS = {"==", "!=", ">", ">=", "<", "<="}


class ConditionError(ValueError):
    def __init__(self, message: str, offset: int):
        super().__init__(message)
        self.offset = offset


# ---------------------------------------------------------------------------
# 词法
# ---------------------------------------------------------------------------

@dataclass
class Tok:
    kind: str       # str | num | ident | op | lparen | rparen | comma | eof
    value: object
    offset: int


def tokenize(src: str) -> list[Tok]:
    toks: list[Tok] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c in "'\"":
            quote = c
            start = i
            i += 1
            buf = []
            while i < n:
                ch = src[i]
                if ch == "\\" and i + 1 < n:
                    nxt = src[i + 1]
                    buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                    i += 2
                    continue
                if ch == quote:
                    i += 1
                    break
                buf.append(ch)
                i += 1
            else:
                raise ConditionError("字符串未闭合", start)
            toks.append(Tok("str", "".join(buf), start))
            continue
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            start = i
            while i < n and (src[i].isdigit() or src[i] == "."):
                i += 1
            toks.append(Tok("num", float(src[start:i]), start))
            continue
        if c in "()":
            toks.append(Tok("lparen" if c == "(" else "rparen", c, i))
            i += 1
            continue
        if c == ",":
            toks.append(Tok("comma", ",", i))
            i += 1
            continue
        two = src[i:i + 2]
        if two in ("&&", "||", "==", "!=", ">=", "<="):
            toks.append(Tok("op", two, i))
            i += 2
            continue
        if c in "!><":
            toks.append(Tok("op", c, i))
            i += 1
            continue
        if c.isalpha() or c == "_":
            start = i
            while i < n and (src[i].isalnum() or src[i] in "._"):
                i += 1
            word = src[start:i]
            if word in ("true", "false"):
                toks.append(Tok("bool", word == "true", start))
            else:
                toks.append(Tok("ident", word, start))
            continue
        raise ConditionError(f"无法识别的字符 {c!r}", i)
    toks.append(Tok("eof", None, n))
    return toks


# ---------------------------------------------------------------------------
# 语法
# ---------------------------------------------------------------------------
# 节点：
#   {"t":"true"|"false"}
#   {"t":"and"|"or","items":[...]}
#   {"t":"not","item":...}
#   {"t":"cmp","left":operand,"op":...,"right":operand}
#   {"t":"call","name":"A.intersectsArea","args":[operand,...]}
#   {"t":"pred","name":"A.hasSoldermask"}
# operand: {"t":"prop","name":"A.NetClass"} | {"t":"str","value":..}
#          | {"t":"num","value":..}

NEGATE = {"==": "!=", "!=": "==", ">": "<=", ">=": "<", "<": ">=", "<=": ">"}


class Parser:
    def __init__(self, src: str):
        self.toks = tokenize(src)
        self.i = 0

    def peek(self) -> Tok:
        return self.toks[self.i]

    def advance(self) -> Tok:
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def expect(self, kind: str) -> Tok:
        tok = self.peek()
        if tok.kind != kind:
            raise ConditionError(f"期望 {kind}，得到 {tok.kind}", tok.offset)
        return self.advance()

    def parse(self) -> dict:
        node = self.parse_or()
        if self.peek().kind != "eof":
            raise ConditionError("表达式后有多余内容", self.peek().offset)
        return node

    def parse_or(self) -> dict:
        items = [self.parse_and()]
        while self.peek().kind == "op" and self.peek().value == "||":
            self.advance()
            items.append(self.parse_and())
        return items[0] if len(items) == 1 else {"t": "or", "items": items}

    def parse_and(self) -> dict:
        items = [self.parse_unary()]
        while self.peek().kind == "op" and self.peek().value == "&&":
            self.advance()
            items.append(self.parse_unary())
        return items[0] if len(items) == 1 else {"t": "and", "items": items}

    def parse_unary(self) -> dict:
        tok = self.peek()
        if tok.kind == "op" and tok.value == "!":
            self.advance()
            inner = self.parse_unary()
            if inner["t"] == "cmp":
                return {**inner, "op": NEGATE[inner["op"]]}
            if inner["t"] == "true":
                return {"t": "false"}
            if inner["t"] == "false":
                return {"t": "true"}
            return {"t": "not", "item": inner}
        return self.parse_primary()

    def parse_primary(self) -> dict:
        tok = self.peek()
        if tok.kind == "bool":
            self.advance()
            return {"t": "true" if tok.value else "false"}
        if tok.kind == "lparen":
            self.advance()
            node = self.parse_or()
            self.expect("rparen")
            return node
        left = self.parse_operand()
        nxt = self.peek()
        if nxt.kind == "op" and nxt.value in CMP_OPS:
            op = self.advance().value
            right = self.parse_operand()
            return {"t": "cmp", "left": left, "op": op, "right": right}
        if left["t"] == "prop":
            return {"t": "pred", "name": left["name"]}
        if left["t"] == "call":
            return left          # 独立的方法调用本身就是布尔谓词
        raise ConditionError("独立的值不是布尔表达式", tok.offset)

    def parse_operand(self) -> dict:
        tok = self.peek()
        if tok.kind == "str":
            self.advance()
            return {"t": "str", "value": tok.value}
        if tok.kind == "num":
            self.advance()
            return {"t": "num", "value": tok.value}
        if tok.kind == "ident":
            self.advance()
            name = tok.value
            if self.peek().kind == "lparen":
                self.advance()
                args = []
                if self.peek().kind != "rparen":
                    args.append(self.parse_operand())
                    while self.peek().kind == "comma":
                        self.advance()
                        args.append(self.parse_operand())
                self.expect("rparen")
                return {"t": "call", "name": name, "args": args}
            return {"t": "prop", "name": name}
        raise ConditionError(f"期望操作数，得到 {tok.kind}", tok.offset)


def parse_condition(src: str | None) -> dict:
    """空条件表示"匹配所有"。"""
    if src is None or not src.strip():
        return {"t": "true"}
    return Parser(src).parse()


# ---------------------------------------------------------------------------
# 保守包含判定
# ---------------------------------------------------------------------------

def _is_true(n: dict) -> bool:
    return n.get("t") == "true"


def _is_false(n: dict) -> bool:
    return n.get("t") == "false"


def _interval(cmp: dict):
    if cmp["left"].get("t") != "prop" or cmp["right"].get("t") != "num":
        return None
    op = cmp["op"]
    v = float(cmp["right"]["value"])
    if op == "==":
        return (v, v, True, True)
    if op == ">":
        return (v, INF, False, False)
    if op == ">=":
        return (v, INF, True, False)
    if op == "<":
        return (-INF, v, False, False)
    if op == "<=":
        return (-INF, v, False, True)
    return None


def _subset(ia, ib) -> bool:
    la, ha, lai, hai = ia
    lb, hb, lbi, hbi = ib
    if la < lb:
        return False
    if la == lb and lai and not lbi:
        return False
    if ha > hb:
        return False
    if ha == hb and hai and not hbi:
        return False
    return True


def _const_operand(op: dict):
    if op.get("t") == "str":
        return ("str", op["value"])
    if op.get("t") == "num":
        return ("num", op["value"])
    return None


# KiCad 允许一个网络属于多个 netclass；`A.NetClass == 'X'` 是成员判断，
# 不能据此证明与另一个类互斥。
MULTI_VALUED_PROPS = {"NetClass"}


def _multi_valued(op: dict) -> bool:
    if op.get("t") != "prop":
        return False
    name = op.get("name", "")
    return name.rsplit(".", 1)[-1] in MULTI_VALUED_PROPS


def _cmp_implies(a: dict, b: dict) -> bool | None:
    if a["left"] != b["left"]:
        return None
    if a["op"] in ("==", "!=") and b["op"] in ("==", "!="):
        ka, kb = _const_operand(a["right"]), _const_operand(b["right"])
        if ka is not None and kb is not None:
            same = ka == kb
        elif a["right"] == b["right"]:
            # 同一个操作数表达式：==X 与 !=X 互补
            if a["op"] == b["op"]:
                return True
            if {a["op"], b["op"]} == {"==", "!="}:
                return False
            return None
        else:
            # 属性/调用之间：AST 不等不等于运行时不等，不能推断
            return None
        if _multi_valued(a["left"]) and not same:
            return None
        if a["op"] == "==" and b["op"] == "==":
            return same
        if a["op"] == "==" and b["op"] == "!=":
            return not same
        if a["op"] == "!=" and b["op"] == "!=":
            return same
        return False
    ia, ib = _interval(a), _interval(b)
    if ia is None or ib is None:
        return None
    return _subset(ia, ib)


def implies(sub: dict, sup: dict) -> bool | None:
    """sub ⇒ sup。True 已证成立；False 已证不成立；None 未知。"""
    if _is_true(sup):
        return True
    if _is_false(sub):
        return True
    if sub == sup:
        return True
    ts, tp = sub.get("t"), sup.get("t")

    if ts == "and":
        if any(implies(x, sup) is True for x in sub["items"]):
            return True
        return None
    if tp == "and":
        results = [implies(sub, y) for y in sup["items"]]
        if any(r is False for r in results):
            return False
        if all(r is True for r in results):
            return True
        return None
    if tp == "or":
        if any(implies(sub, y) is True for y in sup["items"]):
            return True
        if ts == "or" and all(implies(x, sup) is True for x in sub["items"]):
            return True
        return None
    if ts == "or":
        if all(implies(x, sup) is True for x in sub["items"]):
            return True
        return None
    if ts == "not" or tp == "not":
        return None
    if ts == "cmp" and tp == "cmp":
        return _cmp_implies(sub, sup)
    if ts in ("call", "pred") and ts == tp:
        return True if sub == sup else None
    return None


def equivalent(a: dict, b: dict) -> bool:
    return implies(a, b) is True and implies(b, a) is True


def falsey(a: dict, b: dict) -> bool | None:
    """两条件是否**可证明**不相交（无共同满足点）。"""
    if a.get("t") == "cmp" and b.get("t") == "cmp":
        if a["left"] != b["left"]:
            return None
        if a["op"] in ("==", "!=") and b["op"] in ("==", "!="):
            ka, kb = _const_operand(a["right"]), _const_operand(b["right"])
            if ka is not None and kb is not None:
                same = ka == kb
                if _multi_valued(a["left"]) and not same:
                    return None
                if a["op"] == "==" and b["op"] == "==":
                    return ka != kb
                if {a["op"], b["op"]} == {"==", "!="}:
                    return ka == kb
                return False            # 两个 != 总能取到共同点
            if a["right"] == b["right"] and {a["op"], b["op"]} == {"==", "!="}:
                return True             # x==E 与 x!=E 互补
            if a["right"] == b["right"] and a["op"] == "==" and b["op"] == "==":
                return False
            return None                 # 属性/调用之间不能据 AST 差异断定不相交
        ia, ib = _interval(a), _interval(b)
        if ia is None or ib is None:
            return None
        la, ha, lai, hai = ia
        lb, hb, lbi, hbi = ib
        if ha < lb or hb < la:
            return True
        if ha == lb and not (hai and lbi):
            return True
        if hb == la and not (hbi and lai):
            return True
        return False
    if a.get("t") == "and":
        for x in a["items"]:
            rel = falsey(x, b)
            if rel is True:
                return True
        return None
    if b.get("t") == "and":
        for y in b["items"]:
            rel = falsey(a, y)
            if rel is True:
                return True
        return None
    return None


def describe(node: dict) -> str:
    t = node.get("t")
    if t in ("true", "false"):
        return t
    if t == "and":
        return "(" + " && ".join(describe(x) for x in node["items"]) + ")"
    if t == "or":
        return "(" + " || ".join(describe(x) for x in node["items"]) + ")"
    if t == "not":
        return "!" + describe(node["item"])
    if t == "cmp":
        return f"{_operand(node['left'])} {node['op']} {_operand(node['right'])}"
    if t == "call":
        return f"{node['name']}(" + ", ".join(_operand(a) for a in node["args"]) + ")"
    if t == "pred":
        return node["name"]
    return "?"


def _operand(op: dict) -> str:
    if op.get("t") == "str":
        return repr(op["value"])
    if op.get("t") == "num":
        return str(op["value"])
    if op.get("t") == "prop":
        return op["name"]
    if op.get("t") == "call":
        return describe(op)
    return "?"
