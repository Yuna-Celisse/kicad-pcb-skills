#!/usr/bin/env python3
"""gen_dru.py — Design Intent → `.kicad_dru` PROPOSAL（M1.4）

流程：
    1. validate_intent 校验并重算 derived；结构错误 / stale 直接 REJECTED
    2. 只从 `adopted` 结果生成规则；conflict / unresolved / 无映射 / 等级不支持
       各自列入 unsupported，并汇总为 coverage
    3. 生成 PROPOSAL 文本 + AST + 来源映射
    4. 重新解析并逐条核对：规则数量、名称、constraint、数值、severity
    5. 跑 lint_dru：block 或未解决 conflict 时 applicable=false

不写项目文件。`--out` 只在 applicable=true 时以独占方式创建新文件。

用法：
    python gen_dru.py intent.json
    python gen_dru.py intent.json --json report.json --out proposal.kicad_dru
退出码：0 可应用；1 不可应用；2 输入无效 / 被拒绝 / 写盘被拒绝。
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

import dru_ast
import lint_dru
import validate_intent as vi

# requirement → DRU constraint 的显式映射；未列出的 requirement 不会被静默忽略
REQUIREMENT_MAP = {
    "min_clearance": "clearance",
    "min_track": "track_width",
    "track_width": "track_width",
    "min_via_diameter": "via_diameter",
    "min_via_drill": "hole_size",
    "min_hole_clearance": "hole_clearance",
    "edge_clearance": "edge_clearance",
    "max_skew": "skew",
    "diff_pair_gap": "diff_pair_gap",
}

LEVEL_RANK = {"MUST": 3, "SHOULD": 2, "HEURISTIC": 1, "INFO": 0}
VALID_SEVERITY = {"error", "warning", "ignore"}


def fmt_num(value) -> str:
    """按最短往返十进制输出，不使用指数、不截断有效数字。"""
    d = Decimal(str(float(value)))
    text = format(d, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def escape_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def comment_safe(text) -> str:
    """注释里只允许单行可打印字符，防止换行注入额外表达式。"""
    raw = str(text)
    raw = raw.replace("\r", " ").replace("\n", " ")
    return "".join(ch for ch in raw if ch >= " " and ch != "\x7f")


def render_rule(name: str, constraint: str, values: list[tuple[str, float]],
                severity: str | None = None) -> str:
    parts = " ".join(f"({k} {fmt_num(v)}mm)" for k, v in values)
    lines = [f'(rule "{escape_string(name)}"']
    if severity and severity != "error":
        lines.append(f"  (severity {severity})")
    lines.append(f"  (constraint {constraint} {parts}))")
    return "\n".join(lines)


def effective_level(req: dict, result: dict):
    """返回 (level, problem)。

    单条规则只能承载一个 severity。等级不一致时既不能取最弱（会把硬约束降级），
    也不能取最强（会把建议值升格），因此直接判为 unsupported。
    """
    levels = [req.get("level")]
    basis = set(result.get("basis", []))
    for cand in req.get("candidates", []):
        if isinstance(cand, dict) and cand.get("id") in basis:
            levels.append(cand.get("level"))
    if "level" in result:
        levels.append(result.get("level"))
    levels = [x for x in levels if x in LEVEL_RANK]
    if not levels:
        return None, "没有可识别的等级"
    distinct = sorted(set(levels), key=lambda x: -LEVEL_RANK[x])
    if len(distinct) > 1:
        return None, (f"等级混合 {distinct}，单条规则无法同时表达"
                      f"强制边界与建议边界")
    return distinct[0], None


def build_proposal(intent: dict):
    """返回 (rules, unsupported, coverage, reasons)。"""
    requirements = intent.get("requirements") or {}
    derived = vi.resolve_all(intent)
    rules, unsupported, reasons = [], [], []
    coverage = {"requirements": len(requirements), "generated": 0,
                "conflict": 0, "unresolved": 0, "unsupported": 0,
                "complete": False}

    def skip(name, kind, reason):
        unsupported.append({"requirement": name, "kind": kind, "reason": reason})
        coverage[kind if kind in ("conflict", "unresolved") else "unsupported"] += 1

    for name in sorted(requirements):
        req = requirements[name]
        if not isinstance(req, dict):
            skip(name, "unsupported", "requirement 不是对象")
            continue
        result = derived.get(name) or {}
        status = result.get("status")

        if status == "conflict":
            code = (result.get("conflict") or {}).get("code")
            skip(name, "conflict", f"resolver conflict: {code}")
            continue
        if status == "unresolved":
            skip(name, "unresolved",
                 f"resolver unresolved: {result.get('reason')}")
            continue
        if status != "adopted":
            skip(name, "unsupported", f"未知解析状态 {status!r}")
            continue

        if name not in REQUIREMENT_MAP:
            skip(name, "unsupported", "没有 requirement→DRU 映射")
            continue

        level, level_problem = effective_level(req, result)
        if level_problem:
            skip(name, "unsupported", level_problem)
            continue
        if level not in ("MUST", "SHOULD"):
            skip(name, "unsupported",
                 f"有效等级 {level} 不生成默认规则（经验值/INFO）")
            continue
        severity = None if level == "MUST" else "warning"

        constraint = REQUIREMENT_MAP[name]
        direction = req.get("direction")
        if direction == "equal":
            skip(name, "unsupported", "equal 无法用 DRU 数值约束表达")
            continue

        values: list[tuple[str, float]] = []
        if direction == "at_least":
            if "value" not in result:
                skip(name, "unsupported", "adopted 结果缺少 value")
                continue
            values = [("min", result["value"])]
        elif direction == "at_most":
            if "value" not in result:
                skip(name, "unsupported", "adopted 结果缺少 value")
                continue
            values = [("max", result["value"])]
        elif direction == "exact":
            rng = result.get("range")
            if isinstance(rng, dict):
                values = [("min", rng.get("min")), ("max", rng.get("max"))]
            elif "value" in result:
                values = [("min", result["value"]), ("max", result["value"])]
            else:
                skip(name, "unsupported", "exact 结果缺少 range/value")
                continue
        else:
            skip(name, "unsupported", f"不支持的 direction {direction!r}")
            continue

        if any(not isinstance(v, (int, float)) or isinstance(v, bool) for _, v in values):
            skip(name, "unsupported", "约束值不是数值")
            continue

        # 精度必须往返：格式化后的字符串解析回来必须与 resolver 值完全相等
        precision_ok = all(float(fmt_num(v)) == float(v) for _, v in values)
        if not precision_ok:
            skip(name, "unsupported", "无法在不损失精度的前提下格式化")
            continue

        rule_name = f"auto:{name}"
        text = render_rule(rule_name, constraint, values, severity)
        sources = []
        for cid in result.get("basis", []):
            for cand in req.get("candidates", []):
                if isinstance(cand, dict) and cand.get("id") == cid:
                    if cand.get("source") not in sources:
                        sources.append(cand.get("source"))
        rules.append({
            "requirement": name,
            "rule": rule_name,
            "constraint": constraint,
            "level": level,
            "severity": severity or "error",
            "values": {k: v for k, v in values},
            "formatted": {k: f"{fmt_num(v)}mm" for k, v in values},
            "basis": list(result.get("basis", [])),
            "sources": sources,
            "text": text,
        })

    coverage["generated"] = len(rules)
    coverage["complete"] = (coverage["conflict"] == 0
                            and coverage["unresolved"] == 0
                            and coverage["unsupported"] == 0)
    if not rules:
        reasons.append("没有可生成的规则")
    if coverage["conflict"]:
        reasons.append(f"{coverage['conflict']} 个 requirement 存在未解决 conflict")
    if coverage["unresolved"]:
        reasons.append(f"{coverage['unresolved']} 个 requirement 未解析（coverage 不完整）")
    if coverage["unsupported"]:
        reasons.append(f"{coverage['unsupported']} 个 requirement 未生成（见 unsupported）")
    return rules, unsupported, coverage, reasons


def _child(node: dict, tag: str):
    for item in node.get("items", []):
        if isinstance(item, dict) and item.get("tag") == tag:
            return item
    return None


def verify_proposal(ast: dict, rules: list[dict]) -> list[str]:
    """核对重解析结果**恰好等于**生成记录：数量、名称、constraint、取值集合、severity。"""
    problems = []
    nodes = [n for n in dru_ast.walk(ast) if n.get("tag") == "rule"]
    if len(nodes) != len(rules):
        return [f"规则数量不一致：AST {len(nodes)} vs 生成 {len(rules)}"]

    for node, rule in zip(nodes, rules):
        name = rule["rule"]
        if node.get("name") != name:
            problems.append(f"规则名不一致：{node.get('name')!r} vs {name!r}")
            continue

        items = [i for i in node.get("items", []) if isinstance(i, dict)]
        if len(items) < 2 or items[0].get("kind") != "atom" \
                or items[0].get("value") != "rule" or items[1].get("kind") != "string":
            problems.append(f"{name}: rule 头部形式异常")
            continue
        body = items[2:]
        constraints = [i for i in body if i.get("tag") == "constraint"]
        severities = [i for i in body if i.get("tag") == "severity"]
        unexpected = [i for i in body
                      if i.get("tag") not in ("constraint", "severity")]
        if unexpected:
            problems.append(f"{name}: 出现未预期内容 "
                            f"{[i.get('tag') or i.get('kind') for i in unexpected]}")
        if len(constraints) != 1:
            problems.append(f"{name}: constraint 数量 {len(constraints)} != 1")
            continue
        if len(severities) > 1:
            problems.append(f"{name}: severity 节点重复")

        cnode = constraints[0]
        citems = [i for i in cnode.get("items", []) if isinstance(i, dict)]
        if len(citems) < 2 or citems[0].get("value") != "constraint" \
                or citems[1].get("kind") != "atom":
            problems.append(f"{name}: constraint 头部形式异常")
            continue
        if citems[1].get("value") != rule["constraint"]:
            problems.append(f"{name}: constraint 名 {citems[1].get('value')!r} "
                            f"!= {rule['constraint']!r}")
            continue

        parts = citems[2:]
        value_nodes = [i for i in parts if i.get("tag") == "constraint_value"]
        stray = [i for i in parts if i.get("tag") != "constraint_value"]
        if stray:
            problems.append(f"{name}: constraint 内含未预期内容")

        heads, got = [], {}
        for child in value_nodes:
            items2 = [i for i in child.get("items", []) if isinstance(i, dict)]
            if len(items2) != 2 or items2[0].get("kind") != "atom" \
                    or items2[1].get("kind") != "atom":
                problems.append(f"{name}: 取值形式长度或类型异常")
                continue
            head = items2[0].get("value")
            raw = items2[1].get("value")
            if head not in ("min", "max", "opt"):
                problems.append(f"{name}: 未预期的取值项 {head!r}")
            heads.append(head)
            text = str(raw)
            if not text.endswith("mm"):
                problems.append(f"{name}: 值 {raw!r} 缺少单位")
                continue
            try:
                got[head] = float(text[:-2])
            except ValueError:
                problems.append(f"{name}: 值 {raw!r} 无法解析")

        if len(heads) != len(set(heads)):
            problems.append(f"{name}: 取值项重复 {heads}")
        if set(heads) != set(rule["values"]):
            problems.append(f"{name}: 取值集合 {sorted(set(heads))} "
                            f"!= 期望 {sorted(rule['values'])}")
        for head, expected in rule["values"].items():
            actual = got.get(head)
            if actual is None or actual != float(expected):
                problems.append(f"{name}: {head} 生成值 {actual!r} "
                                f"!= resolver {expected!r}")

        actual_sev = "error"
        if severities:
            sitems = [i for i in severities[0].get("items", []) if isinstance(i, dict)]
            if len(sitems) != 2 or sitems[0].get("value") != "severity" \
                    or sitems[1].get("kind") != "atom" \
                    or sitems[1].get("value") not in VALID_SEVERITY:
                problems.append(f"{name}: severity 形式异常")
            else:
                actual_sev = sitems[1].get("value")
        if actual_sev != rule["severity"]:
            problems.append(f"{name}: severity {actual_sev!r} "
                            f"!= {rule['severity']!r}")
    return problems


def describe_rejection(report) -> list[str]:
    return [f"{i.code} {i.path}: {i.message}" for i in report.errors]


def _base(intent_path: Path, validation) -> dict:
    return {
        "tool": "gen_dru",
        "version": "0.1",
        "intent": str(intent_path),
        "validation": {
            "verdict": validation.verdict,
            "issues": [i.as_dict() for i in validation.issues],
        },
    }


def analyze(intent_path: Path, intent: dict) -> dict:
    validation = vi.validate(intent)
    base = _base(intent_path, validation)

    if validation.errors:
        base.update({
            "status": "REJECTED",
            "applicable": False,
            "lint_ok": False,
            "reasons": describe_rejection(validation) or ["validation failed"],
            "rules": [], "unsupported": [],
            "coverage": {"requirements": 0, "generated": 0, "conflict": 0,
                         "unresolved": 0, "unsupported": 0, "complete": False},
            "proposal": "", "ast": None, "lint": None,
        })
        return base

    rules, unsupported, coverage, reasons = build_proposal(intent)
    if not rules:
        base.update({
            "status": "PROPOSAL", "applicable": False, "lint_ok": False,
            "reasons": reasons, "rules": [], "unsupported": unsupported,
            "coverage": coverage, "proposal": "", "ast": None, "lint": None,
        })
        return base

    header = [
        f"# generated from {comment_safe(intent.get('project_id'))} "
        f"revision {intent.get('revision')} — PROPOSAL, not applied",
        "(version 1)", "",
    ]
    proposal = "\n".join(header + [r["text"] + "\n" for r in rules])

    parsed = dru_ast.parse(proposal)
    ast = dru_ast.to_json(parsed.root) if parsed.root else None
    if parsed.errors:
        base.update({
            "status": "REJECTED", "applicable": False, "lint_ok": False,
            "reasons": ["生成的文本无法重新解析"] +
                       [f"{e.code} @ {e.line}:{e.col}" for e in parsed.errors],
            "rules": rules, "unsupported": unsupported, "coverage": coverage,
            "proposal": proposal, "ast": ast, "lint": None,
        })
        return base

    problems = verify_proposal(ast, rules)
    if problems:
        base.update({
            "status": "REJECTED", "applicable": False, "lint_ok": False,
            "reasons": problems + ["生成结果与来源映射不一致"],
            "rules": rules, "unsupported": unsupported, "coverage": coverage,
            "proposal": proposal, "ast": ast, "lint": None,
        })
        return base

    lint_rules = lint_dru.extract_rules(ast)
    findings = lint_dru.lint(lint_rules)
    blocks = [f for f in findings if f["effect"] == "block"]
    lint_ok = not blocks
    if blocks:
        reasons.append(f"lint 报 {len(blocks)} 条 block")
    applicable = lint_ok and coverage["conflict"] == 0

    base.update({
        "status": "PROPOSAL",
        "applicable": applicable,
        "lint_ok": lint_ok,
        "reasons": reasons,
        "rules": rules,
        "unsupported": unsupported,
        "coverage": coverage,
        "proposal": proposal,
        "ast": ast,
        "lint": {
            "summary": {
                "rules": len(lint_rules),
                "eligible": sum(1 for r in lint_rules if r.eligible),
                "block": len(blocks),
                "review": sum(1 for f in findings if f["effect"] == "review"),
            },
            "findings": findings,
        },
    })
    return base


def _path_conflict(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a.absolute() == b.absolute()


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Design Intent → .kicad_dru PROPOSAL（M1.4）")
    ap.add_argument("intent")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--out", dest="proposal_out")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    path = Path(args.intent)
    if not path.is_file():
        print(f"找不到文件：{path}", file=sys.stderr)
        return 2

    out_path = Path(args.proposal_out) if args.proposal_out else None
    json_path = Path(args.json_out) if args.json_out else None

    # 路径保护：不得覆盖输入、不得与其它输出互相覆盖
    if out_path and _path_conflict(out_path, path):
        print("拒绝写出：--out 与输入文件相同", file=sys.stderr)
        return 2
    if json_path and _path_conflict(json_path, path):
        print("拒绝写出：--json 与输入文件相同", file=sys.stderr)
        return 2
    if out_path and json_path and _path_conflict(out_path, json_path):
        print("拒绝写出：--out 与 --json 指向同一文件", file=sys.stderr)
        return 2
    if out_path and out_path.exists():
        print(f"拒绝写出：目标已存在 {out_path}", file=sys.stderr)
        return 2

    try:
        intent = vi.load_intent(path)
    except Exception as exc:  # noqa: BLE001
        print(f"解析失败：{exc}", file=sys.stderr)
        return 2

    report = analyze(path, intent)
    if json_path:
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.quiet:
        print(f"\n=== gen_dru: {path.name} ===")
        print(f"status={report['status']} applicable={report['applicable']} "
              f"lint_ok={report['lint_ok']} rules={len(report['rules'])} "
              f"unsupported={len(report['unsupported'])}")
        for r in report["rules"]:
            print(f"  + {r['rule']} [{r['constraint']}] level={r['level']} "
                  f"basis={r['basis']} sources={r['sources']}")
        for u in report["unsupported"]:
            print(f"  - {u['requirement']} ({u['kind']}): {u['reason']}")
        for reason in report["reasons"]:
            print(f"  ! {reason}")
        if report.get("lint"):
            s = report["lint"]["summary"]
            print(f"  lint: block={s['block']} review={s['review']}")

    if out_path:
        if not report["applicable"]:
            print("拒绝写出：proposal 不可应用（block / conflict / 没有规则）",
                  file=sys.stderr)
            return 2
        try:
            with open(out_path, "x", encoding="utf-8") as fh:
                fh.write(report["proposal"])
        except FileExistsError:
            print(f"拒绝写出：目标已存在 {out_path}", file=sys.stderr)
            return 2

    if report["status"] == "REJECTED":
        return 2
    return 0 if report["applicable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
