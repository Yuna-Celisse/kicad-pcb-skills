#!/usr/bin/env python3
"""gate.py — 把各工具输出收敛成统一 evidence，并按 core-semantics §3 判定（M1.5）

输入可以是任意组合：
    --intent  design-intent.json      （跑 validate_intent）
    --drc     drc.json                （Konnect run_drc / kicad-cli）
    --erc     erc.json                （Konnect run_erc）
    --overlap overlap.json            （pcb_overlap --json）
    --lint    lint.json               （lint_dru --json）
    --gen     gen.json                （gen_dru --json）
    --waivers waivers.json

判据（core-semantics §3）：
    BLOCKED > INCOMPLETE > PASS_WITH_ASSUMPTIONS > PASS_WITH_WAIVERS > PASS

    0 = PASS 家族；1 = BLOCKED；2 = INCOMPLETE / 输入错误
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import validate_intent as vi

PHASES = [f"P{i}" for i in range(11)]
PASS_FAMILY = {"PASS", "PASS_WITH_WAIVERS", "PASS_WITH_ASSUMPTIONS"}
VALID_EFFECTS = {"block", "review", "incomplete", "info"}
VALID_COVERAGE = {"full", "partial", "none"}
VALID_ASSUMPTION_STATES = {"proposed", "active", "resolved", "refuted", "expired"}
WAIVER_FIELDS = ("id", "code", "reason", "approved_by", "review_by", "compensating")
POLICIES = {"prohibited", "authority_required", "project_acceptance"}
AUTHORITATIVE_TYPES = {"datasheet", "standard", "fab_profile", "project_constraint"}

REQUIRED_CHECKS = {
    "P0": [], "P1": [], "P2": [],
    "P3": ["erc"], "P4": ["erc"],
    "P5": [],
    "P6": ["drc", "overlap"],
    "P7": ["drc"],
    "P8": ["drc", "erc", "overlap", "lint"],
    "P9": ["drc", "erc", "overlap", "lint", "gen"],
    "P10": ["drc", "erc", "overlap", "lint", "gen"],
}

SEVERITY_EFFECT = {"error": "block", "warning": "review", "info": "info"}


def _finding(code, effect, message, ref=None, detail=None, policy=None):
    return {"code": code, "effect": effect, "message": message,
            "ref": ref, "detail": detail, "waiver_policy": policy}


def _counts(findings):
    out = {"block": 0, "review": 0, "incomplete": 0, "info": 0}
    for f in findings:
        out[f["effect"]] = out.get(f["effect"], 0) + 1
    return out


def _evidence(check, tool, findings, coverage="full", note=None):
    entry = {"check": check, "tool": tool, "coverage": coverage,
             "counts": _counts(findings), "findings": findings}
    if note:
        entry["note"] = note
    return entry


def _invalid(check, tool, message):
    return _evidence(check, tool,
                     [_finding(f"{check.upper()}_INVALID_REPORT", "incomplete", message)],
                     coverage="none")


def _effect(value):
    return value if value in VALID_EFFECTS else None


def _finding_policy(raw, check, findings):
    """保留并校验 finding 上的 waiver_policy，绝不静默降级。"""
    if raw is None:
        return None
    if raw in POLICIES:
        return raw
    findings.append(_finding(f"{check}_INVALID_POLICY", "incomplete",
                             f"未知 waiver_policy {raw!r}"))
    return None


# ---------------------------------------------------------------------------
# 归一化：结构/状态/覆盖都必须可验证，缺字段不得默认"已完成"
# ---------------------------------------------------------------------------

def from_overlap(report: dict) -> dict:
    if not isinstance(report, dict) or not isinstance(report.get("findings"), list):
        return _invalid("overlap", "pcb_overlap", "报告缺少 findings 列表")
    coverage = report.get("coverage", "full")
    findings = []
    if coverage not in VALID_COVERAGE:
        findings.append(_finding("OVERLAP_INVALID_COVERAGE", "incomplete",
                                 f"未知 coverage {coverage!r}"))
        coverage = "none"
    for f in report["findings"]:
        if not isinstance(f, dict):
            findings.append(_finding("OVERLAP_INVALID_FINDING", "incomplete",
                                     "finding 不是对象"))
            continue
        policy = None
        if "waiver_policy" in f:
            if f["waiver_policy"] in POLICIES:
                policy = f["waiver_policy"]
            else:
                findings.append(_finding(
                    "OVERLAP_INVALID_POLICY", "incomplete",
                    f"未知 waiver_policy {f['waiver_policy']!r}"))
        effect = _effect(f.get("gate_effect"))
        if effect is None:
            findings.append(_finding("OVERLAP_UNKNOWN_EFFECT", "incomplete",
                                     f"未知 gate_effect {f.get('gate_effect')!r}"))
            continue
        findings.append(_finding(
            f"OVERLAP_{str(f.get('kind', 'unknown')).upper()}", effect,
            f"{f.get('ref_a')} ↔ {f.get('ref_b')}: {f.get('detail', '')}",
            ref=f.get("ref_a"), policy=policy))
    if coverage != "full":
        findings.append(_finding("OVERLAP_COVERAGE", "incomplete",
                                 f"overlap 覆盖不完整：{coverage}"))
    return _evidence("overlap", "pcb_overlap", findings, coverage)


def from_lint(report: dict) -> dict:
    if not isinstance(report, dict) or not isinstance(report.get("findings"), list):
        return _invalid("lint", "lint_dru", "报告缺少 findings 列表")
    errors = report.get("errors") or []
    if not isinstance(errors, list):
        return _invalid("lint", "lint_dru", "errors 必须是列表")
    findings = []
    coverage = report.get("coverage", "full")
    if coverage not in VALID_COVERAGE:
        findings.append(_finding("LINT_INVALID_COVERAGE", "incomplete",
                                 f"未知 coverage {coverage!r}"))
        coverage = "none"
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    if summary.get("aborted") is True:
        coverage = "none"
        findings.append(_finding("LINT_ABORTED", "incomplete",
                                 "报告标记 aborted，分析未完成"))
    if errors:
        if coverage == "full":
            coverage = "partial"
        for err in errors:
            if isinstance(err, dict):
                findings.append(_finding(
                    "LINT_SYNTAX", "incomplete",
                    f"{err.get('code')} @ {err.get('line')}:{err.get('col')}"))
            else:
                findings.append(_finding("LINT_SYNTAX", "incomplete", "语法错误"))
    for f in report["findings"]:
        if not isinstance(f, dict):
            findings.append(_finding("LINT_INVALID_FINDING", "incomplete",
                                     "finding 不是对象"))
            continue
        policy = None
        if "waiver_policy" in f:
            if f["waiver_policy"] in POLICIES:
                policy = f["waiver_policy"]
            else:
                findings.append(_finding(
                    "LINT_INVALID_POLICY", "incomplete",
                    f"未知 waiver_policy {f['waiver_policy']!r}"))
        effect = _effect(f.get("effect"))
        if effect is None:
            findings.append(_finding("LINT_UNKNOWN_EFFECT", "incomplete",
                                     f"未知 effect {f.get('effect')!r}"))
            continue
        findings.append(_finding(f.get("code", "LINT"), effect,
                                 f.get("message", ""), ref=f.get("rule"),
                                 detail=f.get("constraint"), policy=policy))
    return _evidence("lint", "lint_dru", findings, coverage)


def _count(value) -> int | None:
    """计数必须是有限的非负整数；0.5、"202"、负数都视为非法。"""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or value < 0:
        return None
    if float(value) != int(value):
        return None
    return int(value)


def _violation_ref(v: dict) -> str | None:
    """按真实报告结构生成稳定、可区分的 ref。

    优先级：顶层 uuid → items[].uuid（多对象用 `+` 连接）→ 坐标。
    """
    uuid = v.get("uuid")
    if isinstance(uuid, str) and uuid:
        return uuid
    items = v.get("items")
    uuids = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                item_uuid = item.get("uuid")
                if isinstance(item_uuid, str) and item_uuid:
                    uuids.append(item_uuid)
    if uuids:
        unique = sorted(set(uuids))
        return unique[0] if len(unique) == 1 else "+".join(unique)
    x, y = v.get("x"), v.get("y")
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return f"{v.get('sheet') or '/'}@{x},{y}"
    return None


def _report_coverage(report: dict, check: str, findings: list) -> str:
    raw = report.get("coverage", "full")
    if raw not in VALID_COVERAGE:
        findings.append(_finding(f"{check.upper()}_INVALID_COVERAGE", "incomplete",
                                 f"未知 coverage {raw!r}"))
        return "none"
    return raw


def _report_failed(report: dict, check: str, findings: list) -> bool:
    status = str(report.get("status", "")).upper()
    if status in ("FAILED", "ERROR", "ABORTED"):
        findings.append(_finding(f"{check.upper()}_REPORT_FAILED", "incomplete",
                                 f"报告状态 {status}，检查未完成"))
        return True
    return False


def _report_truncated(report: dict, check: str, findings: list) -> bool:
    """截断的报告不是完整证据；字段缺失=未截断，显式 null/非 bool=非法。"""
    if "truncated" not in report:
        return False
    raw = report["truncated"]
    if not isinstance(raw, bool):
        findings.append(_finding(f"{check.upper()}_INVALID_TRUNCATED", "incomplete",
                                 f"truncated 必须是 bool，得到 {raw!r}"))
        return True
    if raw:
        findings.append(_finding(f"{check.upper()}_TRUNCATED", "incomplete",
                                 "报告被截断，证据不完整"))
    return raw


def from_drc(report: dict) -> dict:
    if not isinstance(report, dict) or not isinstance(report.get("violations"), list):
        return _invalid("drc", "kicad-cli", "报告缺少 violations 列表")
    findings = []
    coverage = _report_coverage(report, "drc", findings)
    if _report_failed(report, "drc", findings):
        coverage = "none"
    if _report_truncated(report, "drc", findings) and coverage == "full":
        coverage = "partial"
    for v in report["violations"]:
        if not isinstance(v, dict):
            findings.append(_finding("DRC_INVALID_ITEM", "incomplete",
                                     "violation 不是对象"))
            continue
        sev = str(v.get("severity", "")).lower()
        effect = SEVERITY_EFFECT.get(sev)
        if effect is None:
            findings.append(_finding("DRC_UNKNOWN_SEVERITY", "incomplete",
                                     f"未知 severity {sev!r}"))
            continue
        findings.append(_finding(f"DRC_{v.get('rule', 'unknown')}", effect,
                                 v.get("description", ""),
                                 ref=_violation_ref(v),
                                 policy=_finding_policy(v.get("waiver_policy"), "DRC", findings)))
    unconnected = _count(report.get("unconnected_items"))
    if unconnected is None:
        findings.append(_finding("DRC_INVALID_COUNT", "incomplete",
                                 "unconnected_items 不是计数或列表"))
    elif unconnected:
        findings.append(_finding("DRC_UNCONNECTED", "block",
                                 f"{unconnected} 条未布通网络"))
    parity = _count(report.get("schematic_parity"))
    if parity is None:
        findings.append(_finding("DRC_INVALID_COUNT", "incomplete",
                                 "schematic_parity 不是计数或列表"))
    elif parity:
        findings.append(_finding("DRC_SCHEMATIC_PARITY", "block",
                                 f"{parity} 条原理图/PCB 不一致"))
    if coverage != "full":
        findings.append(_finding("DRC_COVERAGE", "incomplete",
                                 f"drc 覆盖不完整：{coverage}"))
    return _evidence("drc", "kicad-cli", findings, coverage)


def from_erc(report: dict) -> dict:
    if not isinstance(report, dict) or not isinstance(report.get("violations"), list):
        return _invalid("erc", "kicad-erc", "报告缺少 violations 列表")
    findings = []
    coverage = _report_coverage(report, "erc", findings)
    if _report_failed(report, "erc", findings):
        coverage = "none"
    if _report_truncated(report, "erc", findings) and coverage == "full":
        coverage = "partial"
    for v in report["violations"]:
        if not isinstance(v, dict):
            findings.append(_finding("ERC_INVALID_ITEM", "incomplete",
                                     "violation 不是对象"))
            continue
        sev = str(v.get("severity", "")).lower()
        effect = SEVERITY_EFFECT.get(sev)
        if effect is None:
            findings.append(_finding("ERC_UNKNOWN_SEVERITY", "incomplete",
                                     f"未知 severity {sev!r}"))
            continue
        findings.append(_finding(
            f"ERC_{v.get('type', v.get('rule', 'unknown'))}", effect,
            v.get("description", ""), ref=_violation_ref(v),
            policy=_finding_policy(v.get("waiver_policy"), "ERC", findings)))
    if coverage != "full":
        findings.append(_finding("ERC_COVERAGE", "incomplete",
                                 f"erc 覆盖不完整：{coverage}"))
    return _evidence("erc", "kicad-erc", findings, coverage)


def from_gen(report: dict) -> dict:
    if not isinstance(report, dict) or report.get("status") not in ("PROPOSAL", "REJECTED"):
        return _invalid("gen", "gen_dru", "报告缺少合法的 status")
    if report.get("status") == "PROPOSAL":
        problems = []
        if not isinstance(report.get("applicable"), bool):
            problems.append("applicable 必须是 bool")
        cov = report.get("coverage")
        parsed = {}
        if not isinstance(cov, dict):
            problems.append("coverage 必须是对象")
        else:
            for key in ("conflict", "unresolved", "unsupported"):
                if key not in cov:
                    problems.append(f"coverage.{key} 缺失")
                    continue
                value = _count(cov[key])
                if value is None:
                    problems.append(f"coverage.{key} 必须是有限非负整数")
                else:
                    parsed[key] = value
            complete = cov.get("complete")
            if not isinstance(complete, bool):
                problems.append("coverage.complete 必须是 bool")
            elif len(parsed) == 3:
                expected = all(parsed[k] == 0 for k in parsed)
                if complete != expected:
                    problems.append("coverage.complete 与分类计数矛盾")
        lint = report.get("lint")
        if not isinstance(lint, dict) or not isinstance(lint.get("findings"), list):
            problems.append("lint.findings 必须是列表")
        if problems:
            return _invalid("gen", "gen_dru",
                            "PROPOSAL 报告无效：" + "; ".join(problems))

    findings = []
    if report.get("status") == "REJECTED":
        findings.append(_finding("GEN_REJECTED", "block",
                                 "; ".join(report.get("reasons", [])) or "proposal 被拒绝"))
    lint = report.get("lint") or {}
    for f in lint.get("findings", []) or []:
        if not isinstance(f, dict):
            findings.append(_finding("GEN_INVALID_FINDING", "incomplete",
                                     "lint finding 不是对象"))
            continue
        policy = None
        if "waiver_policy" in f:
            if f["waiver_policy"] in POLICIES:
                policy = f["waiver_policy"]
            else:
                findings.append(_finding("GEN_INVALID_POLICY", "incomplete",
                                         f"未知 waiver_policy {f['waiver_policy']!r}"))
        effect = _effect(f.get("effect"))
        if effect is None:
            findings.append(_finding("GEN_UNKNOWN_EFFECT", "incomplete",
                                     f"未知 effect {f.get('effect')!r}"))
            continue
        findings.append(_finding(f.get("code", "GEN_LINT"), effect,
                                 f.get("message", ""), ref=f.get("rule"),
                                 policy=policy))
    coverage = report.get("coverage") or {}
    conflict = int(coverage.get("conflict") or 0)
    conflict_reqs = [u.get("requirement") for u in (report.get("unsupported") or [])
                     if isinstance(u, dict) and u.get("kind") == "conflict"]
    if conflict_reqs:
        for name in conflict_reqs:
            findings.append(_finding(
                "GEN_CONFLICT", "block",
                f"{name}: 未解决 conflict", ref=name,
                policy="authority_required"))
    elif conflict:
        findings.append(_finding(
            "GEN_CONFLICT", "block",
            f"{conflict} 个 requirement 存在未解决 conflict",
            policy="authority_required"))
    if coverage and not coverage.get("complete", True) and not conflict:
        findings.append(_finding(
            "GEN_COVERAGE", "incomplete",
            f"coverage 不完整：unresolved={coverage.get('unresolved', 0)} "
            f"unsupported={coverage.get('unsupported', 0)}"))
    if report.get("applicable") is False and report.get("status") != "REJECTED" \
            and not conflict:
        findings.append(_finding("GEN_NOT_APPLICABLE", "incomplete",
                                 "proposal 不可应用"))
    return _evidence("gen", "gen_dru", findings,
                     "full" if report.get("status") != "REJECTED" else "none")


def from_intent(intent: dict) -> tuple[dict, list]:
    if not isinstance(intent, dict):
        return _invalid("intent", "validate_intent", "intent 不是对象"), []
    report = vi.validate(intent)
    findings = []
    for issue in report.issues:
        if issue.severity == "error":
            effect = "block"
        elif issue.severity == "incomplete":
            effect = "incomplete"
        else:
            effect = "info"
        findings.append(_finding(issue.code, effect,
                                 f"{issue.path}: {issue.message}"))

    requirements = intent.get("requirements") or {}
    derived = (intent.get("derived") or {}).get("constraints") or {}
    if isinstance(requirements, dict) and isinstance(derived, dict):
        for name, req in requirements.items():
            res = derived.get(name) or {}
            if not isinstance(res, dict):
                continue
            policy = req.get("waiver_policy") if isinstance(req, dict) else None
            if res.get("status") == "conflict":
                code = (res.get("conflict") or {}).get("code")
                findings.append(_finding(
                    "INTENT_CONFLICT", "block",
                    f"{name}: resolver conflict {code}", ref=name, policy=policy))
            elif res.get("status") == "unresolved":
                findings.append(_finding(
                    "INTENT_UNRESOLVED", "incomplete",
                    f"{name}: unresolved {res.get('reason')}", ref=name,
                    policy=policy))

    assumptions = []
    for aid, a in (intent.get("assumptions") or {}).items():
        if not isinstance(a, dict):
            continue
        assumptions.append({
            "id": aid,
            "status": a.get("status", "active"),
            "must_resolve_before": a.get("must_resolve_before"),
            "item": a.get("item"),
        })
    return _evidence("intent", "validate_intent", findings), assumptions


# ---------------------------------------------------------------------------
# Gate 判定
# ---------------------------------------------------------------------------

def _phase_index(phase: str) -> int:
    if phase not in PHASES:
        raise ValueError(f"未知阶段 {phase!r}")
    return PHASES.index(phase)


CONFLICT_CODES = {"INTENT_CONFLICT", "GEN_CONFLICT"}


def _replacement_structure_issues(replacement, req, sources, seen_ids) -> list[str]:
    issues = []
    if not isinstance(replacement, dict):
        return ["replacement 必须是对象"]
    if not isinstance(replacement.get("id"), str) or not replacement["id"]:
        issues.append("replacement.id 必须是非空字符串")
    report = vi.Report()
    vi.check_candidate("<replacement>", replacement, 0,
                       req.get("direction"), sources or {}, seen_ids, report)
    issues.extend(f"{i.code}: {i.message}" for i in report.errors)

    level = replacement.get("level")
    authority = replacement.get("authority")
    if level not in ("MUST", "SHOULD"):
        issues.append("replacement.level 必须是 MUST 或 SHOULD")
    policy = vi.DOMAIN_POLICY.get(req.get("domain"))
    if policy:
        if level == "MUST" and authority not in policy["hard"]:
            issues.append(
                f"replacement.authority {authority!r} 不是 {req.get('domain')} 的硬约束来源")
        elif level == "SHOULD" and authority not in policy["soft"]:
            issues.append(
                f"replacement.authority {authority!r} 不是 {req.get('domain')} 的可用来源")
    return issues


def _conflict_replacement_issue(waiver, finding, intent) -> str | None:
    """冲突类 finding 的 authority 必须真正替代冲突主张，并让重解析通过。"""
    if finding.get("code") not in CONFLICT_CODES:
        return None
    name = finding.get("ref")
    reqs = (intent or {}).get("requirements") or {}
    derived = ((intent or {}).get("derived") or {}).get("constraints") or {}
    req = reqs.get(name) if isinstance(reqs, dict) else None
    if not isinstance(req, dict):
        return "无法验证替代关系：requirement 不存在"
    res = derived.get(name) or {}
    conflict = res.get("conflict") or {}
    blocked = set(conflict.get("hard") or []) | set(conflict.get("project") or [])
    blocked_sources = {c.get("source") for c in req.get("candidates", [])
                       if isinstance(c, dict) and c.get("id") in blocked}
    authority = waiver.get("authority")
    if authority in blocked_sources:
        return "authority 不能是冲突原主张的来源，必须提供新的替代来源"
    replacement = waiver.get("replacement")
    if not isinstance(replacement, dict):
        return "缺少 replacement：未提供针对该 requirement 的替代主张"
    if replacement.get("source") != authority:
        return "replacement.source 必须等于 authority"
    kept = [c for c in req.get("candidates", [])
            if isinstance(c, dict) and c.get("id") not in blocked]
    kept_ids = {c.get("id") for c in kept}
    if replacement.get("id") in kept_ids:
        return f"replacement.id {replacement.get('id')!r} 与保留候选重复"
    sources = (intent or {}).get("sources") or {}
    structure = _replacement_structure_issues(replacement, req, sources, kept_ids)
    if structure:
        return "replacement 无效：" + "; ".join(structure)
    modified = dict(req)
    modified["candidates"] = [replacement] + kept
    try:
        out = vi.resolve_requirement(modified)
    except Exception as exc:  # noqa: BLE001
        return f"替代主张无法解析：{exc}"
    if out.get("status") != "adopted":
        return f"替代后仍未解析通过：{out.get('status')}"
    basis = out.get("basis") or []
    overridden = out.get("overridden") or []
    all_ids = {c.get("id") for c in modified["candidates"]}
    if not basis:
        return "替代后 basis 为空"
    if set(basis) & set(overridden):
        return "替代后 basis/overridden 交叉引用同一候选"
    if not (set(basis) | set(overridden)) <= all_ids:
        return "替代后引用了不存在的候选"
    if replacement.get("id") not in basis:
        return "替代主张未被解析采用"
    return None


def _waiver_issues(waiver: dict, finding: dict, sources, intent, today) -> list[str]:
    issues = [f"缺少 {field}" for field in WAIVER_FIELDS if not waiver.get(field)]
    review_by = waiver.get("review_by")
    if review_by:
        try:
            reviewed = date.fromisoformat(str(review_by))
        except ValueError:
            issues.append("review_by 不是 ISO 日期（YYYY-MM-DD）")
        else:
            if reviewed < today:
                issues.append(f"review_by 已过期：{review_by}")
    policy = finding.get("waiver_policy") or "project_acceptance"
    if policy == "prohibited":
        issues.append("该 finding 的 waiver_policy=prohibited")
    if policy == "authority_required":
        authority = waiver.get("authority")
        if not authority:
            issues.append("authority_required 但缺少 authority 来源")
        elif not isinstance(sources, dict):
            issues.append("无法验证 authority 来源（未提供 intent sources）")
        elif authority not in sources:
            issues.append(f"authority 来源不存在：{authority}")
        else:
            source = sources.get(authority)
            stype = source.get("type") if isinstance(source, dict) else None
            if stype not in AUTHORITATIVE_TYPES:
                issues.append(
                    f"authority 来源不具备 authoritative 资格：{authority} type={stype!r}")
    if finding.get("code") in CONFLICT_CODES:
        if policy != "authority_required":
            issues.append("冲突类 finding 必须使用 authority_required 策略")
        replacement_issue = _conflict_replacement_issue(waiver, finding, intent)
        if replacement_issue:
            issues.append(replacement_issue)
    requirement = waiver.get("requirement")
    reqs = (intent or {}).get("requirements") or {}
    if requirement is not None:
        if requirement not in reqs:
            issues.append(f"waiver.requirement 不存在：{requirement}")
        elif finding.get("ref") and requirement != finding["ref"]:
            issues.append("waiver.requirement 与 finding.ref 不一致")
    if waiver.get("policy") is not None:
        issues.append("waiver 不得自定义 policy（以 finding/requirement 为准）")
    return issues


def _find_waiver(waivers, finding, rejected, sources, intent, today):
    for w in waivers:
        if not isinstance(w, dict) or w.get("code") != finding["code"]:
            continue
        ref = w.get("ref")
        if ref is not None and ref != finding.get("ref"):
            continue
        issues = _waiver_issues(w, finding, sources, intent, today)
        if issues:
            rejected.append({"waiver": w.get("id") or w.get("code"),
                             "code": finding["code"], "reasons": issues})
            continue
        return w
    return None


def evaluate(phase: str, evidence: list[dict], waivers: list[dict],
             assumptions: list[dict], sources=None, intent=None,
             today=None) -> dict:
    phase_idx = _phase_index(phase)
    today = today or date.today()
    all_findings = [(ev["check"], f) for ev in evidence for f in ev["findings"]]

    applied, rejected, unwaived_blocks = [], [], []
    for check, finding in all_findings:
        if finding["effect"] != "block":
            continue
        match = _find_waiver(waivers, finding, rejected, sources, intent, today)
        if match:
            applied.append({"waiver": match.get("id"), "check": check,
                            "code": finding["code"], "ref": finding.get("ref")})
        else:
            unwaived_blocks.append({"check": check, **finding})

    reviews = [{"check": c, **f} for c, f in all_findings if f["effect"] == "review"]
    incompletes = [{"check": c, **f} for c, f in all_findings
                   if f["effect"] == "incomplete"]

    present = {ev["check"]: ev.get("coverage", "full") for ev in evidence}
    missing = []
    for name in REQUIRED_CHECKS.get(phase, []):
        if name not in present:
            missing.append(name)
            incompletes.append({"check": name, "code": "CHECK_MISSING",
                                "effect": "incomplete",
                                "message": f"{phase} 要求 {name} 检查，但未提供"})
        elif present[name] != "full":
            incompletes.append({"check": name, "code": "CHECK_PARTIAL",
                                "effect": "incomplete",
                                "message": f"{name} 覆盖不完整：{present[name]}"})

    open_assumptions, invalid_assumptions = [], []
    for a in assumptions:
        if a.get("status") not in VALID_ASSUMPTION_STATES \
                or a.get("must_resolve_before") not in PHASES:
            invalid_assumptions.append(a)
            incompletes.append({
                "check": "intent", "code": "ASSUMPTION_INVALID",
                "effect": "incomplete",
                "message": f"假设 {a.get('id')} 的状态或期限非法："
                           f"{a.get('status')!r}/{a.get('must_resolve_before')!r}"})
            continue
        if a["status"] in ("proposed", "active", "expired"):
            open_assumptions.append(a)

    due = [a for a in open_assumptions
           if a["status"] == "expired"
           or PHASES.index(a["must_resolve_before"]) <= phase_idx]

    counts = {
        "checks": len(evidence),
        "errors_total": sum(1 for _, f in all_findings if f["effect"] == "block"),
        "errors_waived": len(applied),
        "errors_unwaived": len(unwaived_blocks),
        "reviews_open": len(reviews),
        "incomplete_open": len(incompletes),
        "assumptions_open": len(open_assumptions),
        "assumptions_due": len(due),
        "checks_missing": len(missing),
    }

    reasons = []
    if unwaived_blocks:
        verdict = "BLOCKED"
        reasons.append(f"{len(unwaived_blocks)} 条未豁免 block")
    elif phase_idx >= PHASES.index("P8") and open_assumptions:
        verdict = "BLOCKED"
        reasons.append(f"P8 起不允许带假设通过：{len(open_assumptions)} 个假设未关闭")
    elif due:
        verdict = "BLOCKED"
        reasons.append(f"{len(due)} 个假设到期未关闭")
    elif incompletes:
        verdict = "INCOMPLETE"
        reasons.append(f"{len(incompletes)} 项未完成或覆盖不足")
    elif reviews:
        verdict = "INCOMPLETE"
        reasons.append(f"{len(reviews)} 条 finding 待复核")
    elif open_assumptions:
        verdict = "PASS_WITH_ASSUMPTIONS"
        reasons.append("存在未到期假设")
    elif applied:
        verdict = "PASS_WITH_WAIVERS"
        reasons.append(f"{len(applied)} 条 block 已豁免")
    else:
        verdict = "PASS"

    if rejected:
        reasons.append(f"{len(rejected)} 条 waiver 无效，未生效")

    return {
        "tool": "gate",
        "version": "0.1",
        "phase": phase,
        "verdict": verdict,
        "counts": counts,
        "evidence": evidence,
        "findings": {
            "unwaived_blocks": unwaived_blocks,
            "reviews": reviews,
            "incomplete": incompletes,
        },
        "waivers_applied": applied,
        "waivers_rejected": rejected,
        "assumptions_open": open_assumptions,
        "assumptions_due": due,
        "assumptions_invalid": invalid_assumptions,
        "missing_checks": missing,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load(path: Path) -> dict:
    # utf-8-sig 兼容 Windows 工具写出的 BOM
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build(phase: str, intent_path=None, drc_path=None, erc_path=None,
          overlap_path=None, lint_path=None, gen_path=None,
          waivers_path=None) -> dict:
    evidence, assumptions, sources, intent_data = [], [], None, None
    if intent_path:
        intent_data = _load(Path(intent_path))
        ev, assumptions = from_intent(intent_data)
        evidence.append(ev)
        sources = intent_data.get("sources") or {}
    if drc_path:
        evidence.append(from_drc(_load(Path(drc_path))))
    if erc_path:
        evidence.append(from_erc(_load(Path(erc_path))))
    if overlap_path:
        evidence.append(from_overlap(_load(Path(overlap_path))))
    if lint_path:
        evidence.append(from_lint(_load(Path(lint_path))))
    if gen_path:
        evidence.append(from_gen(_load(Path(gen_path))))

    waivers = _load(Path(waivers_path)) if waivers_path else []
    if not isinstance(waivers, list):
        raise ValueError("waivers 文件必须是列表")
    return evaluate(phase, evidence, waivers, assumptions,
                    sources=sources, intent=intent_data)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="PCB Gate：统一 evidence 与判定（M1.5）")
    ap.add_argument("--phase", required=True, choices=PHASES)
    ap.add_argument("--intent")
    ap.add_argument("--drc")
    ap.add_argument("--erc")
    ap.add_argument("--overlap")
    ap.add_argument("--lint")
    ap.add_argument("--gen")
    ap.add_argument("--waivers")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    try:
        report = build(args.phase, args.intent, args.drc, args.erc,
                       args.overlap, args.lint, args.gen, args.waivers)
    except Exception as exc:  # noqa: BLE001
        print(f"输入错误：{exc}", file=sys.stderr)
        return 2

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.quiet:
        c = report["counts"]
        print(f"\n=== Gate {args.phase} ===")
        print(f"verdict: {report['verdict']}")
        print(f"checks={c['checks']} total={c['errors_total']} "
              f"waived={c['errors_waived']} unwaived={c['errors_unwaived']} "
              f"reviews={c['reviews_open']} incomplete={c['incomplete_open']} "
              f"assumptions_open={c['assumptions_open']} "
              f"assumptions_due={c['assumptions_due']}")
        for reason in report["reasons"]:
            print(f"  ! {reason}")
        for f in report["findings"]["unwaived_blocks"]:
            print(f"  BLOCK {f['check']}/{f['code']}: {f.get('message', '')}")
        for f in report["findings"]["incomplete"][:10]:
            print(f"  INCOMPLETE {f['check']}/{f['code']}: {f.get('message', '')}")
        for f in report["findings"]["reviews"][:10]:
            print(f"  REVIEW {f['check']}/{f['code']}: {f.get('message', '')}")

    if report["verdict"] == "BLOCKED":
        return 1
    if report["verdict"] in PASS_FAMILY:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
