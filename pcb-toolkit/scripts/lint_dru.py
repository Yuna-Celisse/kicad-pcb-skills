#!/usr/bin/env python3
"""lint_dru.py — `.kicad_dru` 规则分析（M1.3）

在 dru_ast 的结构解析之上，做**保守**的规则求值分析：
  - 逆序求值：文件中靠后的规则先匹配
  - 完全/部分遮蔽、宽规则后写、ignore 遮蔽
  - 无法理解的规则报 L009/review，且不参与确定性推断

核心契约：
  - `known: true` 只表示节点形式已识别，不表示整条规则已被理解；
    规则只有在结构/条件/layer/severity/constraint 全部可理解时才 eligible。
  - 包含关系返回 True / False / None；None 绝不当作 False。
  - 存在 ineligible 规则时，不对其后的规则宣称"有效/不可达"。

用法：
    python lint_dru.py board.kicad_dru
    python lint_dru.py board.kicad_dru --json report.json
退出码：0 无 block；1 存在 block；2 文件不可读。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import dru_ast
import dru_condition as dc

TRUE = {"t": "true"}

PROOF = {
    "L004": "条件等价，且遮蔽者在求值顺序中更早（文件中更靠后）",
    "L006": "条件等价但约束取值不同：先求值的规则生效，另一条永不生效",
    "L007": "窄规则的条件蕴含宽规则，但宽规则在文件中更靠后、先被求值",
    "L008": "遮蔽者 severity=ignore，会让后面的规则永久沉默",
    "L009": "规则含无法理解的结构或条件，不能参与确定性推断",
    "L010": "未证明完全遮蔽、取值不同，且不能证明条件不相交（可能部分重叠）",
    "L005": "该规则的所有 constraint 都被遮蔽",
}


@dataclass
class Constraint:
    name: str
    values: dict = field(default_factory=dict)   # min/max/opt -> raw
    atoms: tuple = ()                            # disallow track via

    def signature(self):
        return (tuple(sorted(self.values.items())), tuple(sorted(self.atoms)))

    def as_text(self):
        parts = [f"{k}={v}" for k, v in sorted(self.values.items())]
        parts += list(self.atoms)
        return " ".join(parts) or "(no value)"


@dataclass
class Rule:
    name: str
    line: int
    col: int
    order: int
    constraints: dict = field(default_factory=dict)   # name -> Constraint
    condition_text: str | None = None
    condition: dict | None = None
    layer: str | None = None
    severity: str = "error"
    eligible: bool = True
    reasons: list = field(default_factory=list)

    def eff_condition(self) -> dict:
        base = self.condition or TRUE
        if not self.layer:
            return base
        layer_cmp = {"t": "cmp", "left": {"t": "prop", "name": "A.Layer"},
                     "op": "==", "right": {"t": "str", "value": self.layer}}
        return _and(base, layer_cmp)


def _and(a: dict, b: dict) -> dict:
    if a == TRUE:
        return b
    if b == TRUE:
        return a
    items: list = []
    for node in (a, b):
        items.extend(node["items"] if node.get("t") == "and" else [node])
    return {"t": "and", "items": items}


def _child(node: dict, tag: str):
    for item in node.get("items", []):
        if isinstance(item, dict) and item.get("tag") == tag:
            return item
    return None


def _children(node: dict, tag: str):
    return [i for i in node.get("items", [])
            if isinstance(i, dict) and i.get("tag") == tag]


def _has_unparsed(node) -> bool:
    """递归检查：结构可解析 ≠ 整条规则被理解。"""
    if isinstance(node, dict):
        if node.get("tag") in ("unknown", "unparsed"):
            return True
        return any(_has_unparsed(c) for c in node.get("items", []))
    if isinstance(node, list):
        return any(_has_unparsed(c) for c in node)
    return False


def build_rule(node: dict, order: int) -> Rule:
    rule = Rule(name=node.get("name") or f"<unnamed@{order}>",
                line=node["line"], col=node["col"], order=order)

    if _has_unparsed(node):
        rule.reasons.append("子树内含未理解节点")

    for cnode in _children(node, "constraint"):
        name = cnode.get("name")
        if not cnode.get("known"):
            rule.reasons.append(f"未知 constraint {name!r}")
        cons = Constraint(name=name or "<unnamed>")
        atoms = []
        for child in cnode.get("items", [])[2:]:
            if not isinstance(child, dict):
                continue
            if child.get("tag") == "constraint_value":
                items = child.get("items", [])
                head = items[0].get("value") if items else None
                if len(items) != 2 or items[1].get("kind") != "atom":
                    rule.reasons.append(
                        f"constraint {name!r} 的 {head!r} 取值形式无法识别")
                else:
                    cons.values[head] = str(items[1].get("value"))
            elif child.get("kind") == "atom":
                atoms.append(child.get("value"))
            else:
                rule.reasons.append(f"constraint {name!r} 含未理解子形式")
        cons.atoms = tuple(atoms)
        rule.constraints[cons.name] = cons

    if not rule.constraints:
        rule.reasons.append("没有可识别的 constraint")

    cond_node = _child(node, "condition")
    if cond_node is not None:
        items = cond_node.get("items", [])
        raw = items[1] if len(items) > 1 else None
        if not isinstance(raw, dict) or raw.get("kind") != "string":
            rule.reasons.append("condition 不是字符串")
        else:
            rule.condition_text = raw.get("value")
            try:
                rule.condition = dc.parse_condition(rule.condition_text)
            except dc.ConditionError as exc:
                rule.reasons.append(f"条件解析失败 @{exc.offset}: {exc}")

    layer_node = _child(node, "layer")
    if layer_node is not None:
        items = layer_node.get("items", [])
        value = items[1] if len(items) > 1 else None
        if isinstance(value, dict) and value.get("kind") == "string" and value.get("value"):
            rule.layer = value["value"]
        else:
            rule.reasons.append("layer 值无法识别")

    sev_node = _child(node, "severity")
    if sev_node is not None:
        items = sev_node.get("items", [])
        value = items[1] if len(items) > 1 else None
        if isinstance(value, dict) and value.get("kind") == "atom" \
                and value.get("value") in ("error", "warning", "ignore"):
            rule.severity = value["value"]
        else:
            rule.reasons.append("severity 值无法识别")

    rule.eligible = not rule.reasons
    return rule


def extract_rules(ast: dict) -> list[Rule]:
    rules = []
    for node in dru_ast.walk(ast):
        if node.get("tag") == "rule":
            rules.append(build_rule(node, len(rules)))
    return rules


def _finding(code, effect, rule, constraint, related, proof, message):
    return {
        "code": code,
        "effect": effect,
        "rule": rule.name,
        "line": rule.line,
        "col": rule.col,
        "constraint": constraint,
        "related_rule": related.name if related else None,
        "related_line": related.line if related else None,
        "proof": proof,
        "message": message,
    }


def lint(rules: list[Rule], top_unknown: list | None = None) -> list[dict]:
    order = list(reversed(rules))          # eval_order
    pos = {id(r): i for i, r in enumerate(order)}
    findings: list[dict] = []

    for rule in rules:
        if not rule.eligible:
            findings.append(_finding(
                "L009", "review", rule, None, None,
                "规则不可理解，未参与任何确定性推断",
                "; ".join(rule.reasons)))

    for node in (top_unknown or []):
        findings.append({
            "code": "L009", "effect": "review",
            "rule": node.get("name") or "<unknown>",
            "line": node.get("line"), "col": node.get("col"),
            "constraint": None, "related_rule": None, "related_line": None,
            "proof": "未知顶层节点的子树不参与规则解释",
            "message": "顶层存在未理解节点，其中的规则效力未知",
        })

    shadowed = {id(r): 0 for r in rules}
    indecisive: dict[int, Rule] = {}

    for rule in order:
        if not rule.eligible:
            continue
        earlier = order[:pos[id(rule)]]
        blocked = [x for x in earlier if not x.eligible]
        if blocked:
            indecisive[id(rule)] = blocked[0]
            continue
        for cname, cons in rule.constraints.items():
            shadow_found = False
            review_blocker = None
            for blocker in earlier:
                bcons = blocker.constraints.get(cname)
                if bcons is None:
                    continue
                rel = dc.implies(rule.eff_condition(), blocker.eff_condition())
                if rel is True:
                    shadow_found = True
                    shadowed[id(rule)] += 1
                    if blocker.severity == "ignore":
                        code, effect = "L008", "block"
                    elif dc.equivalent(rule.eff_condition(), blocker.eff_condition()):
                        if cons.signature() != bcons.signature():
                            code, effect = "L006", "block"
                        else:
                            code, effect = "L004", "block"
                    else:
                        code, effect = "L007", "block"
                    findings.append(_finding(
                        code, effect, rule, cname, blocker, PROOF[code],
                        f"{rule.name!r} 的 {cname} 被 {blocker.name!r} 遮蔽"))
                    break
                # 没有证明完全遮蔽、取值不同、且不能证明不相交 -> review
                # implies=False 只证明"不包含"，仍可能部分重叠
                if (rel is not True and cname != "disallow"
                        and dc.implies(blocker.eff_condition(),
                                       rule.eff_condition()) is not True
                        and cons.signature() != bcons.signature()
                        and dc.falsey(rule.eff_condition(),
                                      blocker.eff_condition()) is not True):
                    if review_blocker is None:
                        review_blocker = blocker
            if not shadow_found and review_blocker is not None:
                findings.append(_finding(
                    "L010", "review", rule, cname, review_blocker, PROOF["L010"],
                    f"{rule.name!r} 与 {review_blocker.name!r} 的 {cname} "
                    f"可能重叠且取值不同（{cons.as_text()} vs "
                    f"{review_blocker.constraints[cname].as_text()}）"))

    for rule in rules:
        if not rule.eligible or id(rule) in indecisive:
            continue
        if rule.constraints and shadowed[id(rule)] == len(rule.constraints):
            findings.append(_finding(
                "L005", "block", rule, None, None, PROOF["L005"],
                f"{rule.name!r} 的所有 constraint 都被遮蔽，规则永不生效"))

    for rule in rules:
        if id(rule) in indecisive:
            blocker = indecisive[id(rule)]
            findings.append(_finding(
                "L009", "review", rule, None, blocker,
                "存在更早求值的未理解规则，无法判定该规则是否被遮蔽",
                f"{rule.name!r} 可能被未理解的 {blocker.name!r} 遮蔽"))

    findings.sort(key=lambda f: (f["line"], f["col"], f["code"]))
    return findings


def analyze(path: Path) -> dict:
    src = path.read_text(encoding="utf-8")
    parsed = dru_ast.parse(src)
    ast = dru_ast.to_json(parsed.root)
    rules = extract_rules(ast)
    top_unknown = [n for n in ast.get("items", [])
                   if isinstance(n, dict) and n.get("tag") in ("unknown", "unparsed")]
    syntax_errors = [{"code": e.code, "message": e.message,
                      "line": e.line, "col": e.col} for e in parsed.errors]
    # 语法不完整时不做确定性推断：部分 AST 不能作为结论依据
    findings = [] if parsed.errors else lint(rules, top_unknown)
    return {
        "file": str(path),
        "comments": [{"line": c.line, "col": c.col, "text": c.text}
                     for c in parsed.comments],
        "errors": syntax_errors,
        "rules": [{
            "name": r.name, "line": r.line, "col": r.col,
            "eligible": r.eligible, "reasons": r.reasons,
            "severity": r.severity, "layer": r.layer,
            "condition": r.condition_text,
            "constraints": {k: v.as_text() for k, v in r.constraints.items()},
        } for r in rules],
        "findings": findings,
        "summary": {
            "rules": len(rules),
            "eligible": sum(1 for r in rules if r.eligible),
            "block": sum(1 for f in findings if f["effect"] == "block"),
            "review": sum(1 for f in findings if f["effect"] == "review"),
            "syntax_errors": len(syntax_errors),
            "aborted": bool(parsed.errors),
        },
    }


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description=".kicad_dru 规则分析（M1.3）")
    ap.add_argument("path")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--fail-on-review", action="store_true")
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
        print(f"rules={s['rules']} eligible={s['eligible']} "
              f"block={s['block']} review={s['review']}"
              + (f" syntax_errors={s['syntax_errors']}" if s["syntax_errors"] else ""))
        if s["aborted"]:
            print("  ! 语法不完整，已跳过规则分析")
        for err in report["errors"]:
            print(f"  ERROR {err['code']} @ {err['line']}:{err['col']} — {err['message']}")
        for f in report["findings"]:
            print(f"  {f['code']} [{f['effect']}] {f['rule']} "
                  f"@ {f['line']}:{f['col']}"
                  + (f" ({f['constraint']})" if f["constraint"] else ""))
            print(f"      {f['message']}")
            if f["proof"]:
                print(f"      依据: {f['proof']}")

    if report["summary"]["syntax_errors"]:
        return 2
    if report["summary"]["block"]:
        return 1
    if args.fail_on_review and report["summary"]["review"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
