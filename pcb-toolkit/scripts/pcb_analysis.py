#!/usr/bin/env python3
"""pcb_analysis.py — 对现有报告做只读汇总/分诊（不重新判定 DRC/ERC）。

ops:
    triage_drc   DRC 报告 → 按规则/严重度分组
    audit_bom    BOM 行 → 本地格式与一致性检查（不含供应链结论）
    rule_audit   lint_dru 报告 → 按规则/约束汇总

CLI:
    python pcb_analysis.py --op triage_drc --input drc.json --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def _clean(value) -> str:
    """None/缺失 → 空串；其他类型转字符串但不伪装成有效值。"""
    if value is None:
        return ""
    return str(value).strip()


def _count(value):
    if isinstance(value, list):
        return len(value)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def triage_drc(report: dict) -> dict:
    if not isinstance(report, dict) or not isinstance(report.get("violations"), list):
        raise ValueError("DRC 报告缺少 violations 列表")
    groups = {}
    for v in report["violations"]:
        if not isinstance(v, dict):
            continue
        rule = str(v.get("rule", "unknown"))
        severity = str(v.get("severity", "error")).lower()
        key = (severity, rule)
        g = groups.setdefault(key, {"severity": severity, "rule": rule,
                                    "count": 0, "samples": []})
        g["count"] += 1
        desc = v.get("description")
        if desc and len(g["samples"]) < 3:
            g["samples"].append(desc)

    ordered = sorted(groups.values(),
                     key=lambda g: (SEVERITY_RANK.get(g["severity"], 9),
                                    -g["count"], g["rule"]))
    unconnected = _count(report.get("unconnected_items"))
    parity = _count(report.get("schematic_parity"))
    notes = []
    if unconnected is None:
        notes.append("unconnected_items 缺失或非法")
    if parity is None:
        notes.append("schematic_parity 缺失或非法")
    return {
        "tool": "pcb_analysis",
        "op": "triage_drc",
        "total": len(report["violations"]),
        "by_severity": {s: sum(1 for v in report["violations"]
                               if isinstance(v, dict)
                               and str(v.get("severity", "error")).lower() == s)
                        for s in ("error", "warning", "info")},
        "unconnected_items": unconnected,
        "schematic_parity": parity,
        "groups": ordered,
        "notes": notes,
    }


def audit_bom(rows: list[dict]) -> dict:
    if not isinstance(rows, list):
        raise ValueError("BOM 必须是对象列表")
    issues = []
    seen_refs = {}
    seen_mpn = {}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            issues.append({"code": "BOM_INVALID_ROW", "severity": "error",
                           "ref": f"row{i + 1}", "message": "行不是对象"})
            continue
        ref = _clean(row.get("Reference"))
        if not ref:
            issues.append({"code": "BOM_NO_REFERENCE", "severity": "error",
                           "ref": f"row{i + 1}", "message": "缺少 Reference"})
            continue
        if ref in seen_refs:
            issues.append({"code": "BOM_DUPLICATE_REFERENCE", "severity": "error",
                           "ref": ref, "message": f"位号重复（行 {i + 1}）"})
        seen_refs[ref] = i
        for field in ("Value", "Package"):
            if not _clean(row.get(field)):
                issues.append({"code": f"BOM_MISSING_{field.upper()}",
                               "severity": "error", "ref": ref,
                               "message": f"缺少 {field}"})
        mpn = _clean(row.get("MPN"))
        lcsc = _clean(row.get("LCSC"))
        if not mpn:
            issues.append({"code": "BOM_MISSING_MPN", "severity": "error",
                           "ref": ref, "message": "缺少 MPN"})
        if not lcsc:
            issues.append({"code": "BOM_MISSING_LCSC", "severity": "warning",
                           "ref": ref, "message": "缺少 LCSC"})
        value = _clean(row.get("Value"))
        if mpn:
            if mpn in seen_mpn and value != seen_mpn[mpn][1]:
                issues.append({"code": "BOM_MPN_VALUE_MISMATCH",
                               "severity": "warning", "ref": ref,
                               "message": f"同一 MPN 出现不同 Value（{seen_mpn[mpn][0]}）"})
            else:
                seen_mpn.setdefault(mpn, (ref, value))
        dnp = _clean(row.get("DNP")).lower()
        if dnp not in ("", "no", "yes", "false", "true", "0", "1"):
            issues.append({"code": "BOM_BAD_DNP", "severity": "warning",
                           "ref": ref, "message": f"DNP 值无法识别：{row.get('DNP')!r}"})
    counts = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        counts[issue["severity"]] += 1
    return {
        "tool": "pcb_analysis",
        "op": "audit_bom",
        "rows": len(rows),
        "issues": issues,
        "counts": counts,
        "checked": ["Reference 唯一", "Value/Package 必填", "MPN/LCSC 存在",
                    "DNP 取值"],
        "not_checked": ["EOL/生命周期", "库存/交期", "价格/单一来源"],
        "requires": ["external_datasource: 供应链风险需要 LCSC/厂商数据"],
    }


def rule_audit(report: dict) -> dict:
    if not isinstance(report, dict) or not isinstance(report.get("rules"), list):
        raise ValueError("lint 报告缺少 rules 列表")
    rules = []
    for r in report["rules"]:
        if not isinstance(r, dict):
            continue
        rules.append({
            "name": r.get("name"),
            "line": r.get("line"),
            "eligible": r.get("eligible"),
            "severity": r.get("severity"),
            "constraints": r.get("constraints"),
            "has_condition": bool(r.get("condition")),
            "reasons": r.get("reasons", []),
        })
    findings = [f for f in report.get("findings", []) if isinstance(f, dict)]
    by_code = {}
    for f in findings:
        code = f.get("code", "?")
        by_code[code] = by_code.get(code, 0) + 1
    return {
        "tool": "pcb_analysis",
        "op": "rule_audit",
        "rules": rules,
        "rule_count": len(rules),
        "eligible": sum(1 for r in rules if r["eligible"]),
        "findings": {"total": len(findings), "by_code": by_code},
        "block": sum(1 for f in findings if f.get("effect") == "block"),
        "review": sum(1 for f in findings if f.get("effect") == "review"),
        "errors": len(report.get("errors") or []),
    }


OPS = {
    "triage_drc": triage_drc,
    "audit_bom": audit_bom,
    "rule_audit": rule_audit,
}


def compute(op: str, payload) -> dict:
    fn = OPS.get(op)
    if fn is None:
        raise ValueError(f"未知 op: {op}")
    return fn(payload)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="PCB 报告分诊（只读）")
    ap.add_argument("--op", required=True, choices=sorted(OPS))
    ap.add_argument("--input", required=True)
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)
    try:
        source = Path(args.input).resolve()
        if args.json_out and Path(args.json_out).resolve() == source:
            raise ValueError("--json 不能与 --input 指向同一文件")
        with open(args.input, encoding="utf-8-sig") as fh:
            payload = json.load(fh)
        report = compute(args.op, payload)
    except Exception as exc:  # noqa: BLE001
        print(f"输入错误：{exc}", file=sys.stderr)
        return 2
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
