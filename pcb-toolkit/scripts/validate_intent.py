#!/usr/bin/env python3
"""validate_intent.py — Design Intent 语义校验器（M1.1）

只依赖 Python 标准库；`.yaml` 需要 PyYAML，缺失时会明确提示改用 `.json`。

职责边界：
  1. 结构校验（必填、类型、枚举）
  2. 跨字段语义校验（source 回指、candidate id、assumption 期限、derived provenance）
  3. 用内置 resolver 重算 derived，发现 stale 结果

不做的事：几何、DRC、单位换算、板厂数据。那些属于其他工具。

用法：
    python validate_intent.py intent.json
    python validate_intent.py intent.json --json report.json
    python validate_intent.py intent.json --print-derived
退出码：0 PASS / 1 FAIL|INCOMPLETE / 2 解析错误
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1

CANONICAL_UNITS = {
    "length": "mm",
    "voltage": "V",
    "current": "A",
    "impedance": "ohm",
    "frequency": "Hz",
    "temperature": "C",
    "power": "W",
    "time": "s",
    "capacitance": "F",
    "inductance": "H",
    "angle": "deg",
    "ratio": "pct",
}
CORE_UNITS = ("length", "voltage", "current", "impedance", "frequency", "temperature")

DOMAINS = {"safety", "manufacturing", "component", "signal_integrity", "project", "practice"}
AUTHORITIES = {"PROJECT", "DATASHEET", "STANDARD", "FAB", "DOMAIN", "GENERIC"}
LEVELS = {"MUST", "SHOULD", "HEURISTIC", "INFO"}
DIRECTIONS = {"at_least", "at_most", "exact", "equal"}
WAIVER_POLICIES = {"prohibited", "authority_required", "project_acceptance"}
SOURCE_TYPES = {
    "calculation", "datasheet", "standard", "fab_profile", "project_constraint", "heuristic",
}
ASSUMPTION_STATES = {"proposed", "active", "resolved", "refuted", "expired"}
RESULT_STATES = {"adopted", "conflict", "unresolved"}
PHASES = [f"P{i}" for i in range(11)]

UNIT_SUFFIXES = ("_mm", "_mv", "_v", "_ma", "_a", "_mhz", "_hz", "_ms", "_ns", "_s", "_c", "_w", "_ohm")
TOP_LEVEL = {
    "schema_version", "project_id", "revision", "units", "sources",
    "requirements", "assumptions", "derived",
}

DOMAIN_POLICY = {
    "safety": {"hard": ["STANDARD"], "soft": ["STANDARD", "PROJECT", "DOMAIN", "GENERIC"]},
    "manufacturing": {"hard": ["FAB"], "soft": ["FAB", "PROJECT", "DOMAIN", "GENERIC"]},
    "component": {"hard": ["DATASHEET", "STANDARD"],
                  "soft": ["DATASHEET", "STANDARD", "PROJECT", "DOMAIN", "GENERIC"]},
    "signal_integrity": {"hard": ["STANDARD", "DATASHEET"],
                         "soft": ["STANDARD", "DATASHEET", "PROJECT", "DOMAIN", "GENERIC"]},
    "project": {"hard": ["PROJECT"], "soft": ["PROJECT", "DOMAIN", "GENERIC"]},
    "practice": {"hard": [], "soft": ["DOMAIN", "GENERIC"]},
}


def is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_finite(v) -> bool:
    """数值且有限；inf/nan 与超出 float 表示范围的整数都不是有效工程值。"""
    if not is_number(v):
        return False
    try:
        return math.isfinite(float(v))
    except (OverflowError, ValueError):
        return False


def as_dict(value) -> dict:
    """结构不合法时返回空字典，让各分支安全退化为诊断而不是异常。"""
    return value if isinstance(value, dict) else {}


BINDING_LEVELS = ("MUST", "SHOULD")


@dataclass
class Issue:
    code: str
    severity: str          # error | incomplete | warning
    path: str
    message: str

    def as_dict(self):
        return {"code": self.code, "severity": self.severity,
                "path": self.path, "message": self.message}


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    derived_calc: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)

    def add(self, code, severity, path, message):
        self.issues.append(Issue(code, severity, path, message))

    @property
    def errors(self):
        return [i for i in self.issues if i.severity == "error"]

    @property
    def incompletes(self):
        return [i for i in self.issues if i.severity == "incomplete"]

    @property
    def verdict(self):
        if self.errors:
            return "FAIL"
        if self.incompletes:
            return "INCOMPLETE"
        return "PASS"


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------

def load_intent(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "PyYAML 未安装：请把 intent 存为 .json，或 pip install pyyaml") from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("顶层必须是对象")
    return data


# ---------------------------------------------------------------------------
# 结构校验
# ---------------------------------------------------------------------------

def walk_keys(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, path + (k,)
            yield from walk_keys(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_keys(v, path + (str(i),))


def check_top_level(intent: dict, r: Report):
    for key in sorted(set(intent) - TOP_LEVEL):
        r.add("W001", "warning", key, f"未知顶层字段 `{key}`（已忽略）")
    for key in sorted(TOP_LEVEL - set(intent)):
        r.add("E002", "error", key, f"缺少必填顶层字段 `{key}`")

    version = intent.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version != SCHEMA_VERSION:
        r.add("E001", "error", "schema_version",
              f"不支持的 schema_version：{version!r}（期望整数 {SCHEMA_VERSION}）")
    if not isinstance(intent.get("project_id"), str) or not intent.get("project_id"):
        r.add("E002", "error", "project_id", "project_id 必须是非空字符串")
    rev = intent.get("revision")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 1:
        r.add("E002", "error", "revision", "revision 必须是 ≥1 的整数")
    for key in ("units", "sources", "requirements", "assumptions", "derived"):
        if key in intent and not isinstance(intent[key], dict):
            r.add("E002", "error", key, f"{key} 必须是对象")


def check_units(intent: dict, r: Report):
    units = intent.get("units")
    if not isinstance(units, dict):
        return
    for key in CORE_UNITS:
        if key not in units:
            r.add("E003", "error", f"units.{key}", f"缺少核心单位 `{key}`（应为 {CANONICAL_UNITS[key]}）")
        elif units[key] != CANONICAL_UNITS[key]:
            r.add("E003", "error", f"units.{key}",
                  f"`{key}` 必须是 {CANONICAL_UNITS[key]}，得到 {units[key]!r}")
    for key, value in units.items():
        if key not in CANONICAL_UNITS:
            r.add("E003", "error", f"units.{key}", f"未知单位类别 `{key}`")
        elif value != CANONICAL_UNITS[key]:
            r.add("E003", "error", f"units.{key}",
                  f"`{key}` 必须是 {CANONICAL_UNITS[key]}，得到 {value!r}")


def check_field_names(intent: dict, r: Report):
    for key, path in walk_keys(intent):
        if path and path[0] == "units":
            continue
        low = key.lower()
        if low.endswith(UNIT_SUFFIXES):
            r.add("E004", "error", ".".join(path),
                  f"字段名 `{key}` 带单位后缀；改为无后缀 + units 块")


def check_sources(intent: dict, r: Report):
    sources = as_dict(intent.get("sources"))
    for sid, src in sources.items():
        base = f"sources.{sid}"
        if not isinstance(src, dict):
            r.add("E005", "error", base, "source 必须是对象")
            continue
        stype = src.get("type")
        if stype not in SOURCE_TYPES:
            r.add("E005", "error", f"{base}.type", f"未知来源类型 {stype!r}")
        if not isinstance(src.get("ref"), str) or not src.get("ref"):
            r.add("E005", "error", f"{base}.ref", "缺少 ref")
        if stype == "fab_profile" and not src.get("retrieved"):
            r.add("E005", "warning", f"{base}.retrieved",
                  "板厂能力值建议带 retrieved 日期，便于判断是否过期")


def check_candidate(req_key, cand, idx, direction, sources, seen_ids, r: Report):
    base = f"requirements.{req_key}.candidates[{idx}]"
    if not isinstance(cand, dict):
        r.add("E008", "error", base, "candidate 必须是对象")
        return
    cid = cand.get("id")
    if not isinstance(cid, str) or not cid:
        r.add("E008", "error", f"{base}.id", "candidate 必须有局部 id")
    elif cid in seen_ids:
        r.add("E008", "error", f"{base}.id", f"candidate id `{cid}` 在 requirement 内重复")
    else:
        seen_ids.add(cid)

    # 表示由 direction 决定：resolver 只会读取与之匹配的字段
    has_value = "value" in cand
    has_range = "range" in cand
    has_tol = "tolerance_pct" in cand
    if direction in ("at_least", "at_most"):
        if not has_value:
            r.add("E019", "error", f"{base}.value", f"`{direction}` 需要数值 value")
        elif not is_finite(cand["value"]):
            r.add("E019", "error", f"{base}.value", f"`{direction}` 的 value 必须是有限数值")
        if has_range:
            r.add("E019", "error", f"{base}.range", f"`{direction}` 不接受 range")
        if has_tol:
            r.add("E019", "error", f"{base}.tolerance_pct", "tolerance_pct 只用于 `exact`")
    elif direction == "exact":
        if has_value and has_range:
            r.add("E019", "error", base, "不能同时提供 value 与 range")
        if has_tol and has_range:
            r.add("E019", "error", base, "range 不能与 tolerance_pct 混用")
        if has_tol:
            tol = cand["tolerance_pct"]
            if not is_finite(tol) or tol < 0:
                r.add("E019", "error", f"{base}.tolerance_pct",
                      "tolerance_pct 必须是有限非负数")
        if has_range:
            rng = cand["range"]
            if not isinstance(rng, dict) or not all(is_finite(rng.get(k)) for k in ("min", "max")):
                r.add("E008", "error", f"{base}.range", "range 必须是 {min, max} 有限数值对象")
            elif rng["min"] > rng["max"]:
                r.add("E008", "error", f"{base}.range", "range.min 不得大于 max")
        elif not has_value:
            r.add("E019", "error", base, "`exact` 需要 value(+tolerance_pct) 或 range")
        elif not is_finite(cand["value"]):
            r.add("E019", "error", f"{base}.value", "`exact` 的 value 必须是有限数值")
    elif direction == "equal":
        if not has_value:
            r.add("E019", "error", f"{base}.value", "`equal` 需要 value")
        elif isinstance(cand["value"], str):
            pass
        elif not is_finite(cand["value"]):
            r.add("E019", "error", f"{base}.value",
                  "`equal` 的 value 必须是字符串或有限数值")
        if has_range:
            r.add("E019", "error", f"{base}.range", "`equal` 不接受 range")
        if has_tol:
            r.add("E019", "error", f"{base}.tolerance_pct", "tolerance_pct 只用于 `exact`")
    elif not has_value and not has_range:
        r.add("E008", "error", f"{base}.value", "candidate 必须有 value 或 range")

    if cand.get("authority") not in AUTHORITIES:
        r.add("E008", "error", f"{base}.authority", f"未知 authority {cand.get('authority')!r}")
    if cand.get("level") not in LEVELS:
        r.add("E008", "error", f"{base}.level", f"未知 level {cand.get('level')!r}")
    src = cand.get("source")
    if src not in sources:
        r.add("E009", "error", f"{base}.source", f"引用了不存在的 source `{src}`")


def check_requirements(intent: dict, r: Report):
    requirements = as_dict(intent.get("requirements"))
    sources = as_dict(intent.get("sources"))
    assumptions = as_dict(intent.get("assumptions"))
    r.stats["requirements"] = len(requirements)

    for key, req in requirements.items():
        base = f"requirements.{key}"
        if not isinstance(req, dict):
            r.add("E006", "error", base, "requirement 必须是对象")
            continue
        domain = req.get("domain")
        if domain not in DOMAINS:
            r.add("E006", "error", f"{base}.domain", f"未知 domain {domain!r}")
        direction = req.get("direction")
        if direction not in DIRECTIONS:
            r.add("E007", "error", f"{base}.direction", f"未知 direction {direction!r}")
        if req.get("level") not in LEVELS:
            r.add("E007", "error", f"{base}.level", f"未知 level {req.get('level')!r}")
        if req.get("waiver_policy") not in WAIVER_POLICIES:
            r.add("E007", "error", f"{base}.waiver_policy",
                  f"未知 waiver_policy {req.get('waiver_policy')!r}")

        refs = req.get("assumptions", [])
        if not isinstance(refs, list):
            r.add("E017", "error", f"{base}.assumptions", "assumptions 必须是 id 列表")
            refs = []
        for aid in refs:
            if not isinstance(aid, str) or aid not in assumptions:
                r.add("E017", "error", f"{base}.assumptions",
                      f"引用了不存在的 assumption `{aid}`")

        cands = req.get("candidates", [])
        if not isinstance(cands, list):
            r.add("E008", "error", f"{base}.candidates", "candidates 必须是列表")
            continue
        if not cands and not refs:
            r.add("I001", "incomplete", f"{base}.candidates",
                  "既无 candidate 也无 assumption：该要求无法解析，也无法解释")
        seen: set[str] = set()
        for i, cand in enumerate(cands):
            check_candidate(key, cand, i, direction, sources, seen, r)


def check_assumptions(intent: dict, r: Report):
    assumptions = as_dict(intent.get("assumptions"))
    for aid, a in assumptions.items():
        base = f"assumptions.{aid}"
        if not re.fullmatch(r"A-\d{3}", aid):
            r.add("E016", "error", base, "assumption id 必须形如 A-017")
        if not isinstance(a, dict):
            r.add("E016", "error", base, "assumption 必须是对象")
            continue
        if not isinstance(a.get("item"), str) or not a.get("item"):
            r.add("E016", "error", f"{base}.item", "缺少 item")
        av = a.get("assumed_value")
        if not isinstance(av, dict) or "value" not in av or \
                not isinstance(av.get("unit"), str) or not av.get("unit"):
            r.add("E016", "error", f"{base}.assumed_value",
                  "assumed_value 必须是 {value, unit} 对象（单位不可省略）")
        else:
            val = av.get("value")
            if not (isinstance(val, str) or is_finite(val)):
                r.add("E016", "error", f"{base}.assumed_value.value",
                      "assumed_value.value 必须是字符串或有限数值")
        if a.get("must_resolve_before") not in PHASES:
            r.add("E016", "error", f"{base}.must_resolve_before",
                  f"必须是 P0–P10，得到 {a.get('must_resolve_before')!r}")
        impact = a.get("impact")
        if not isinstance(impact, list) or not impact:
            r.add("E016", "error", f"{base}.impact", "impact 必须是非空列表")
        elif not all(isinstance(x, str) and x for x in impact):
            r.add("E016", "error", f"{base}.impact", "impact 元素必须是非空字符串")
        if a.get("status") not in ASSUMPTION_STATES:
            r.add("E016", "error", f"{base}.status", f"未知 status {a.get('status')!r}")


def check_derived(intent: dict, r: Report):
    derived = as_dict(intent.get("derived"))
    constraints = derived.get("constraints")
    requirements = as_dict(intent.get("requirements"))
    if constraints is None:
        r.add("I002", "incomplete", "derived.constraints", "缺少 derived.constraints")
        return
    if not isinstance(constraints, dict):
        r.add("E010", "error", "derived.constraints", "必须是对象")
        return

    for key in requirements:
        if key not in constraints:
            r.add("I002", "incomplete", f"derived.constraints.{key}",
                  "requirement 没有对应的解析结果（resolver 未运行或未输出）")

    for key, res in constraints.items():
        base = f"derived.constraints.{key}"
        if key not in requirements:
            r.add("E010", "error", base, f"指向不存在的 requirement `{key}`")
            continue
        req = requirements[key]
        if not isinstance(req, dict):
            continue  # 已在 check_requirements 报 E006
        if not isinstance(res, dict):
            r.add("E011", "error", base, "必须是对象")
            continue
        status = res.get("status")
        if status not in RESULT_STATES:
            r.add("E011", "error", f"{base}.status", f"未知 status {status!r}")
            continue

        cand_ids = [c.get("id") for c in req.get("candidates", []) if isinstance(c, dict)]
        basis_raw = res.get("basis")
        over_raw = res.get("overridden")
        if "basis" in res and not isinstance(basis_raw, list):
            r.add("E013", "error", f"{base}.basis", "basis 必须是 candidate id 列表")
        if "overridden" in res and not isinstance(over_raw, list):
            r.add("E013", "error", f"{base}.overridden", "overridden 必须是 candidate id 列表")
        basis = basis_raw if isinstance(basis_raw, list) else []
        overridden = over_raw if isinstance(over_raw, list) else []

        for label, lst in (("basis", basis), ("overridden", overridden)):
            hashable = [x for x in lst if isinstance(x, (str, int, float))]
            dups = sorted({x for x in hashable if hashable.count(x) > 1})
            if dups:
                r.add("E020", "error", f"{base}.{label}",
                      f"重复的 candidate id: {dups}")

        if status == "adopted":
            if "value" not in res and "range" not in res:
                r.add("E012", "error", base, "adopted 必须有 value 或 range")
            if direction_of(req) != "equal" and "value" in res and not is_finite(res["value"]):
                r.add("E021", "error", f"{base}.value",
                      "adopted.value 必须是有限数值（`equal` 方向除外）")
            if "range" in res:
                rng = res["range"]
                if not isinstance(rng, dict) or not all(is_finite(rng.get(k)) for k in ("min", "max")):
                    r.add("E022", "error", f"{base}.range", "range 端点必须是有限数值")
                elif rng["min"] > rng["max"]:
                    r.add("E022", "error", f"{base}.range", "range.min 不得大于 max")
            if not isinstance(basis_raw, list) or not basis_raw:
                r.add("E012", "error", f"{base}.basis", "adopted 必须有非空 basis")
            if "conflict" in res:
                r.add("E014", "error", f"{base}.conflict", "adopted 不得出现 conflict 字段（含 null）")
        elif status == "conflict":
            if "value" in res or "range" in res:
                r.add("E014", "error", base, "conflict 不得带 value/range")
            conf = res.get("conflict")
            if not isinstance(conf, dict) or not conf.get("code"):
                r.add("E014", "error", f"{base}.conflict", "conflict 必须带 code")
            elif isinstance(conf, dict):
                for label in ("hard", "project"):
                    for cid in conf.get(label) or []:
                        if cid not in cand_ids:
                            r.add("E013", "error", f"{base}.conflict.{label}",
                                  f"引用了不属于该 requirement 的 candidate `{cid}`")
        elif status == "unresolved":
            if "value" in res or "range" in res or "conflict" in res:
                r.add("E015", "error", base, "unresolved 不得带 value/range/conflict（含 null）")
            if not res.get("reason"):
                r.add("E015", "error", f"{base}.reason", "unresolved 必须带 reason")

        for cid in basis + overridden:
            if cid not in cand_ids:
                r.add("E013", "error", base,
                      f"引用了不属于该 requirement 的 candidate `{cid}`")
        dup = set(x for x in basis if isinstance(x, (str, int, float))) & \
              set(x for x in overridden if isinstance(x, (str, int, float)))
        if dup:
            r.add("E013", "error", base, f"candidate 同时出现在 basis/overridden: {sorted(dup)}")


def direction_of(req: dict) -> str | None:
    d = req.get("direction")
    return d if d in DIRECTIONS else None


# ---------------------------------------------------------------------------
# Resolver（core-semantics §2）
# ---------------------------------------------------------------------------

def _range_of(cand: dict) -> tuple[float, float] | None:
    if "range" in cand and isinstance(cand["range"], dict):
        rng = cand["range"]
        lo, hi = rng.get("min"), rng.get("max")
        if is_finite(lo) and is_finite(hi):
            return float(lo), float(hi)
        return None
    value = cand.get("value")
    if not is_finite(value):
        return None
    tol = cand.get("tolerance_pct")
    if tol is not None:
        if not is_finite(tol) or tol < 0:
            return None
        lo = value * (1 - tol / 100.0)
        hi = value * (1 + tol / 100.0)
        if not (is_finite(lo) and is_finite(hi)):
            return None
        return lo, hi
    return float(value), float(value)


def combine(cands: list[dict], direction: str) -> dict:
    """返回 {"ok": True, ...} 或 {"ok": False, "code": ...}。"""
    if not cands:
        return {"ok": False, "code": "no_candidate"}
    if direction == "at_least":
        if not all(is_finite(c.get("value")) for c in cands):
            return {"ok": False, "code": "invalid_value"}
        return {"ok": True, "value": max(float(c["value"]) for c in cands)}
    if direction == "at_most":
        if not all(is_finite(c.get("value")) for c in cands):
            return {"ok": False, "code": "invalid_value"}
        return {"ok": True, "value": min(float(c["value"]) for c in cands)}
    if direction == "equal":
        if not all(isinstance(c.get("value"), str) or is_finite(c.get("value")) for c in cands):
            return {"ok": False, "code": "invalid_value"}
        values = {c["value"] for c in cands}
        if len(values) > 1:
            return {"ok": False, "code": "value_mismatch"}
        return {"ok": True, "value": cands[0]["value"]}
    if direction == "exact":
        ranges = [_range_of(c) for c in cands]
        if any(r is None for r in ranges):
            return {"ok": False, "code": "non_finite_result"}
        lo = max(r[0] for r in ranges)
        hi = min(r[1] for r in ranges)
        if lo > hi:
            return {"ok": False, "code": "empty_intersection"}
        return {"ok": True, "range": {"min": lo, "max": hi}}
    return {"ok": False, "code": "unknown_direction"}


def _loosens(project: dict, bound: dict, direction: str) -> bool:
    if direction == "at_least":
        return project["value"] < bound["value"]
    if direction == "at_most":
        return project["value"] > bound["value"]
    if direction == "equal":
        return project["value"] != bound["value"]
    if direction == "exact":
        return project["range"]["min"] < bound["range"]["min"] or \
               project["range"]["max"] > bound["range"]["max"]
    return True


def _tighten(bound: dict, project: dict | None, direction: str) -> dict:
    if not project:
        return copy.deepcopy(bound)
    if direction == "at_least":
        return {"value": max(bound["value"], project["value"])}
    if direction == "at_most":
        return {"value": min(bound["value"], project["value"])}
    if direction == "equal":
        return {"value": bound["value"]}
    if direction == "exact":
        return {"range": {
            "min": max(bound["range"]["min"], project["range"]["min"]),
            "max": min(bound["range"]["max"], project["range"]["max"]),
        }}
    return copy.deepcopy(bound)


def _ids(cands):
    return [c.get("id") for c in cands]


def _clean_result(res: dict) -> dict:
    """去掉内部字段；不做数值舍入（F/H/s 等小量级会被 round 吃掉）。"""
    return {k: v for k, v in res.items() if k != "ok"}


def resolve_requirement(req: dict) -> dict:
    return _clean_result(_resolve_requirement(req))


def _resolve_requirement(req: dict) -> dict:
    # 入口契约：不抛异常；结构不合法一律返回 unresolved，由 validator 负责诊断
    if not isinstance(req, dict):
        return {"status": "unresolved", "reason": "invalid_requirement"}
    domain = req.get("domain")
    policy = DOMAIN_POLICY.get(domain) if isinstance(domain, str) else None
    if policy is None:
        return {"status": "unresolved", "reason": "unknown_domain"}
    direction = req.get("direction")
    if not isinstance(direction, str) or direction not in DIRECTIONS:
        return {"status": "unresolved", "reason": "unknown_direction"}
    raw = req.get("candidates")
    cands = [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []
    if not cands:
        return {"status": "unresolved", "reason": "no_candidate"}

    def conflict(code, hard, project):
        return {"status": "conflict",
                "conflict": {"code": code, "hard": hard, "project": project,
                             "waiver_policy": req.get("waiver_policy")}}

    hard = [c for c in cands
            if c.get("level") == "MUST" and c.get("authority") in policy["hard"]]
    if hard:
        bound = combine(hard, direction)
        if not bound["ok"]:
            if bound["code"] == "non_finite_result":
                return {"status": "unresolved", "reason": "non_finite_result"}
            return conflict(bound["code"], _ids(hard), [])
        # 只有 MISS/SHOULD 级项目主张参与收紧；HEURISTIC/INFO 不得改判
        proj_cands = [c for c in cands
                      if c.get("authority") == "PROJECT" and c.get("level") in BINDING_LEVELS]
        project = combine(proj_cands, direction) if proj_cands else None
        if project and not project["ok"]:
            return conflict(project["code"], _ids(hard), _ids(proj_cands))
        if project and _loosens(project, bound, direction):
            return conflict("project_loosen_hard_bound", _ids(hard), _ids(proj_cands))
        result = _tighten(bound, project, direction)
        result.update({"status": "adopted",
                       "basis": _ids(hard) + (_ids(proj_cands) if project else []),
                       "overridden": _ids([c for c in cands
                                           if c not in hard and c not in proj_cands])})
        return result

    for auth in policy["soft"]:
        group = [c for c in cands
                 if c.get("authority") == auth and c.get("level") in BINDING_LEVELS]
        if group:
            bound = combine(group, direction)
            if not bound["ok"]:
                if bound["code"] == "non_finite_result":
                    return {"status": "unresolved", "reason": "non_finite_result"}
                return conflict(bound["code"], _ids(group), [])
            bound.update({"status": "adopted", "basis": _ids(group),
                          "overridden": _ids([c for c in cands if c not in group])})
            return bound

    heur = [c for c in cands if c.get("level") == "HEURISTIC"]
    if not heur:
        return {"status": "unresolved", "reason": "no_applicable_candidate"}
    bound = combine(heur, direction)
    if not bound["ok"]:
        # 经验值之间不一致不构成工程冲突，只是"无法据此定值"
        return {"status": "unresolved", "reason": "heuristic_disagreement"}
    bound.update({"status": "adopted", "basis": _ids(heur),
                  "overridden": _ids([c for c in cands if c not in heur]),
                  "level": "HEURISTIC"})
    return bound


def resolve_all(intent: dict) -> dict:
    return {key: resolve_requirement(req)
            for key, req in (intent.get("requirements") or {}).items()
            if isinstance(req, dict)}


def _sorted_ids(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(x) for x in value})


def _norm(res: dict) -> dict:
    """归一化为可比较结构：集合语义、保留原始数值精度。"""
    status = res.get("status")
    out: dict = {"status": status}
    if status == "adopted":
        if "value" in res:
            out["value"] = res["value"]
        rng = res.get("range")
        if isinstance(rng, dict):
            out["range"] = [rng.get("min"), rng.get("max")]
        out["basis"] = _sorted_ids(res.get("basis"))
        out["overridden"] = _sorted_ids(res.get("overridden"))
    elif status == "conflict":
        conf = res.get("conflict") if isinstance(res.get("conflict"), dict) else {}
        out["code"] = conf.get("code")
        out["hard"] = _sorted_ids(conf.get("hard"))
        out["project"] = _sorted_ids(conf.get("project"))
        out["waiver_policy"] = conf.get("waiver_policy")
    elif status == "unresolved":
        out["reason"] = res.get("reason")
    if "level" in res:
        out["level"] = res.get("level")
    return out


def _num_eq(a, b, exact: bool = False) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if exact:
            return a == b          # 不转 float：>2^53 的整数会被合并
        try:
            # 只用相对误差：加上 abs_tol 会让 1e-13 与 0 被判为相等
            return math.isclose(float(a), float(b), rel_tol=1e-12)
        except (OverflowError, ValueError):
            return a == b
    return a == b


def _same_result(a: dict, b: dict, direction: str | None = None) -> bool:
    if a.get("status") != b.get("status"):
        return False
    if a.get("level") != b.get("level"):
        return False
    status = a["status"]
    exact = direction == "equal"
    if status == "adopted":
        if ("value" in a) != ("value" in b):
            return False
        if "value" in a and not _num_eq(a["value"], b["value"], exact=exact):
            return False
        if ("range" in a) != ("range" in b):
            return False
        if "range" in a:
            ra, rb = a.get("range"), b.get("range")
            if not (isinstance(ra, list) and isinstance(rb, list) and len(ra) == len(rb)):
                return False
            if not all(_num_eq(x, y) for x, y in zip(ra, rb)):
                return False
        return a.get("basis") == b.get("basis") and a.get("overridden") == b.get("overridden")
    if status == "conflict":
        return (a.get("code") == b.get("code")
                and a.get("hard") == b.get("hard")
                and a.get("project") == b.get("project")
                and a.get("waiver_policy") == b.get("waiver_policy"))
    return a.get("reason") == b.get("reason")


def check_stale(intent: dict, r: Report):
    derived = as_dict(as_dict(intent.get("derived")).get("constraints"))
    if not derived:
        return
    calc = resolve_all(intent)
    r.derived_calc = calc
    requirements = as_dict(intent.get("requirements"))
    for key, got in calc.items():
        if key not in derived or not isinstance(derived[key], dict):
            continue
        want = _norm(derived[key])
        computed = _norm(got)
        req = requirements.get(key)
        direction = req.get("direction") if isinstance(req, dict) else None
        if not _same_result(want, computed, direction):
            r.add("E018", "error", f"derived.constraints.{key}",
                  f"与 resolver 重算结果不一致：derived={want} / computed={computed}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def validate(intent: dict) -> Report:
    r = Report()
    checks = (check_top_level, check_units, check_field_names, check_sources,
              check_requirements, check_assumptions, check_derived)
    for fn in checks:
        try:
            fn(intent, r)
        except Exception as exc:  # noqa: BLE001 - 结构异常必须变成诊断，不能中断
            r.add("E099", "error", "",
                  f"内部校验异常 @{fn.__name__}: {type(exc).__name__}: {exc}")
    if not r.errors:
        try:
            check_stale(intent, r)
        except Exception as exc:  # noqa: BLE001
            r.add("E099", "error", "",
                  f"内部校验异常 @check_stale: {type(exc).__name__}: {exc}")
    return r


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Design Intent 语义校验（M1.1）")
    ap.add_argument("path")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--print-derived", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    path = Path(args.path)
    if not path.is_file():
        print(f"找不到文件：{path}", file=sys.stderr)
        return 2
    try:
        intent = load_intent(path)
    except Exception as exc:  # noqa: BLE001
        print(f"解析失败：{exc}", file=sys.stderr)
        return 2

    report = validate(intent)
    payload = {
        "tool": "validate_intent",
        "version": "0.1",
        "input": str(path),
        "verdict": report.verdict,
        "counts": {"errors": len(report.errors),
                   "incomplete": len(report.incompletes),
                   "warnings": sum(1 for i in report.issues if i.severity == "warning")},
        "issues": [i.as_dict() for i in report.issues],
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                       encoding="utf-8")

    if not args.quiet:
        print(f"\n=== Design Intent: {path.name} ===")
        print(f"verdict: {report.verdict}  "
              f"(errors={payload['counts']['errors']}, "
              f"incomplete={payload['counts']['incomplete']}, "
              f"warnings={payload['counts']['warnings']})")
        for issue in report.issues:
            print(f"  [{issue.code}] {issue.severity:<10} {issue.path}: {issue.message}")

    if args.print_derived:
        print(json.dumps(report.derived_calc or resolve_all(intent),
                         ensure_ascii=False, indent=2))

    return 0 if report.verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
