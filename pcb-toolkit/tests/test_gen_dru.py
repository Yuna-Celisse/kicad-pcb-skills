"""gen_dru 的回归测试（M1.4）。

覆盖：确定性输出、字符串转义、规则顺序、未支持项、生成后重新解析 + lint、
以及"block 时不可应用 / 不写出文件"。
"""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import dru_ast  # noqa: E402
import gen_dru  # noqa: E402
import lint_dru  # noqa: E402


def base_intent():
    return {
        "schema_version": 1,
        "project_id": "gen",
        "revision": 1,
        "units": {"length": "mm", "voltage": "V", "current": "A",
                  "impedance": "ohm", "frequency": "Hz", "temperature": "C"},
        "sources": {
            "S-001": {"type": "fab_profile", "ref": "JLC-4L", "retrieved": "2026-10-01"},
            "S-002": {"type": "datasheet", "ref": "DS-1"},
        },
        "requirements": {
            "min_clearance": {
                "domain": "manufacturing",
                "direction": "at_least",
                "level": "MUST",
                "waiver_policy": "authority_required",
                "candidates": [
                    {"id": "C-001", "value": 0.15, "authority": "FAB",
                     "level": "MUST", "source": "S-001"}],
            }
        },
        "assumptions": {},
        "derived": {
            "constraints": {
                "min_clearance": {"status": "adopted", "value": 0.15,
                                  "basis": ["C-001"], "overridden": []},
            },
            "netclasses": {},
            "rule_requirements": {},
            "verification_requirements": {},
        },
    }


def add_req(intent, name, direction, candidates, derived, domain="manufacturing"):
    intent["requirements"][name] = {
        "domain": domain, "direction": direction, "level": "MUST",
        "waiver_policy": "authority_required", "candidates": candidates}
    intent["derived"]["constraints"][name] = derived


def run(intent):
    return gen_dru.analyze(Path("intent.json"), intent)


class GenerationTests(unittest.TestCase):
    def test_generates_clearance_rule(self):
        report = run(base_intent())
        self.assertEqual(report["status"], "PROPOSAL")
        self.assertTrue(report["applicable"])
        self.assertEqual(len(report["rules"]), 1)
        rule = report["rules"][0]
        self.assertEqual(rule["rule"], "auto:min_clearance")
        self.assertEqual(rule["constraint"], "clearance")
        self.assertEqual(rule["basis"], ["C-001"])
        self.assertEqual(rule["sources"], ["S-001"])
        self.assertIn("(constraint clearance (min 0.15mm))", report["proposal"])
        self.assertEqual(report["lint"]["summary"]["block"], 0)

    def test_deterministic(self):
        first = run(base_intent())["proposal"]
        second = run(base_intent())["proposal"]
        self.assertEqual(first, second)

    def test_rules_sorted_by_requirement(self):
        intent = base_intent()
        add_req(intent, "min_track", "at_least",
                [{"id": "C-001", "value": 0.2, "authority": "FAB",
                  "level": "MUST", "source": "S-001"}],
                {"status": "adopted", "value": 0.2, "basis": ["C-001"], "overridden": []})
        names = [r["rule"] for r in run(intent)["rules"]]
        self.assertEqual(names, ["auto:min_clearance", "auto:min_track"])

    def test_generated_text_reparses_and_lints_clean(self):
        report = run(base_intent())
        parsed = dru_ast.parse(report["proposal"])
        self.assertEqual(parsed.errors, [])
        ast = dru_ast.to_json(parsed.root)
        rules = lint_dru.extract_rules(ast)
        self.assertEqual(len(rules), 1)
        self.assertEqual(lint_dru.lint(rules), [])


class EscapingTests(unittest.TestCase):
    def test_escape_quote_and_backslash(self):
        self.assertEqual(gen_dru.escape_string('a"b'), 'a\\"b')
        self.assertEqual(gen_dru.escape_string("a\\b"), "a\\\\b")

    def test_render_rule_escapes_name(self):
        text = gen_dru.render_rule('weird "name"', "clearance", [("min", 0.15)])
        self.assertIn('(rule "weird \\"name\\""', text)
        parsed = dru_ast.parse(text)
        self.assertEqual(parsed.errors, [])
        self.assertEqual(parsed.root.items[0].items[1].value, 'weird "name"')


class UnsupportedTests(unittest.TestCase):
    def test_requirement_without_mapping_is_listed(self):
        intent = base_intent()
        add_req(intent, "usb_diff_impedance", "exact",
                [{"id": "C-001", "value": 90, "tolerance_pct": 10,
                  "authority": "DATASHEET", "level": "MUST", "source": "S-002"}],
                {"status": "adopted", "range": {"min": 81, "max": 99},
                 "basis": ["C-001"], "overridden": []},
                domain="signal_integrity")
        report = run(intent)
        self.assertTrue(report["applicable"])
        unsupported = {u["requirement"]: u["reason"] for u in report["unsupported"]}
        self.assertIn("usb_diff_impedance", unsupported)
        self.assertIn("没有 requirement→DRU 映射", unsupported["usb_diff_impedance"])
        self.assertEqual(len(report["rules"]), 1)

    def test_conflict_is_not_generated(self):
        intent = base_intent()
        intent["requirements"]["min_clearance"]["candidates"].append(
            {"id": "C-002", "value": 0.10, "authority": "PROJECT",
             "level": "SHOULD", "source": "S-002"})
        intent["derived"]["constraints"]["min_clearance"] = {
            "status": "conflict",
            "conflict": {"code": "project_loosen_hard_bound",
                         "hard": ["C-001"], "project": ["C-002"],
                         "waiver_policy": "authority_required"}}
        report = run(intent)
        self.assertEqual(report["rules"], [])
        self.assertFalse(report["applicable"])
        self.assertIn("resolver conflict", report["unsupported"][0]["reason"])

    def test_unresolved_is_not_generated(self):
        intent = base_intent()
        intent["requirements"]["min_clearance"]["candidates"] = []
        intent["requirements"]["min_clearance"]["assumptions"] = ["A-001"]
        intent["assumptions"]["A-001"] = {
            "item": "clearance", "assumed_value": {"value": 0.15, "unit": "mm"},
            "impact": ["drc"], "must_resolve_before": "P3", "status": "active"}
        intent["derived"]["constraints"]["min_clearance"] = {
            "status": "unresolved", "reason": "no_candidate"}
        report = run(intent)
        self.assertEqual(report["rules"], [])
        self.assertFalse(report["applicable"])
        self.assertIn("unresolved", report["unsupported"][0]["reason"])


class RejectionTests(unittest.TestCase):
    def test_stale_derived_is_rejected(self):
        intent = base_intent()
        intent["derived"]["constraints"]["min_clearance"]["value"] = 0.2
        report = run(intent)
        self.assertEqual(report["status"], "REJECTED")
        self.assertFalse(report["applicable"])
        self.assertEqual(report["proposal"], "")
        self.assertTrue(any("E018" in r for r in report["reasons"]))

    def test_invalid_domain_is_rejected(self):
        intent = base_intent()
        intent["requirements"]["min_clearance"]["domain"] = "mechanical"
        report = run(intent)
        self.assertEqual(report["status"], "REJECTED")
        self.assertTrue(any("E006" in r for r in report["reasons"]))


class LintGateTests(unittest.TestCase):
    def test_conflicting_generated_constraints_block_applicability(self):
        intent = base_intent()
        add_req(intent, "min_track", "at_least",
                [{"id": "C-001", "value": 0.2, "authority": "FAB",
                  "level": "MUST", "source": "S-001"}],
                {"status": "adopted", "value": 0.2, "basis": ["C-001"], "overridden": []})
        # min_track 与 track_width 都映射到 track_width，取值不同 -> lint block
        add_req(intent, "track_width", "at_least",
                [{"id": "C-001", "value": 0.3, "authority": "FAB",
                  "level": "MUST", "source": "S-001"}],
                {"status": "adopted", "value": 0.3, "basis": ["C-001"], "overridden": []})
        report = run(intent)
        self.assertFalse(report["applicable"])
        self.assertGreater(report["lint"]["summary"]["block"], 0)
        self.assertTrue(any("block" in r for r in report["reasons"]))


class PrecisionTests(unittest.TestCase):
    def test_small_value_is_not_rounded_to_zero(self):
        self.assertEqual(gen_dru.fmt_num(1e-7), "0.0000001")
        self.assertEqual(gen_dru.fmt_num(0.1500004), "0.1500004")

    def test_generation_keeps_precision(self):
        for value in (1e-7, 0.1500004):
            intent = base_intent()
            intent["requirements"]["min_clearance"]["candidates"][0]["value"] = value
            intent["derived"]["constraints"]["min_clearance"]["value"] = value
            report = run(intent)
            self.assertEqual(report["status"], "PROPOSAL", value)
            self.assertIn(f"(min {gen_dru.fmt_num(value)}mm)", report["proposal"])
            parsed = dru_ast.parse(report["proposal"])
            self.assertEqual(parsed.errors, [])
            rule = parsed.root.items[1]
            atom = rule.items[-1].items[2].items[1].value
            self.assertEqual(float(atom[:-2]), float(value))


class MetadataInjectionTests(unittest.TestCase):
    def test_project_id_cannot_inject_rules(self):
        intent = base_intent()
        intent["project_id"] = (
            'demo\n(rule "injected" (constraint hole_size (min 0.01mm)))\n#')
        report = run(intent)
        self.assertEqual(report["status"], "PROPOSAL")
        self.assertEqual(len(report["rules"]), 1)
        self.assertEqual(
            len([n for n in dru_ast.walk(report["ast"]) if n.get("tag") == "rule"]), 1)
        lines = [line.strip() for line in report["proposal"].splitlines()]
        self.assertFalse(any(line.startswith('(rule "injected"') for line in lines))


class CoverageGateTests(unittest.TestCase):
    def test_conflict_blocks_applicability_even_with_valid_rule(self):
        intent = base_intent()
        add_req(intent, "min_track", "at_least",
                [{"id": "C-001", "value": 0.15, "authority": "FAB",
                  "level": "MUST", "source": "S-001"},
                 {"id": "C-002", "value": 0.10, "authority": "PROJECT",
                  "level": "SHOULD", "source": "S-002"}],
                {"status": "conflict",
                 "conflict": {"code": "project_loosen_hard_bound",
                              "hard": ["C-001"], "project": ["C-002"],
                              "waiver_policy": "authority_required"}})
        report = run(intent)
        self.assertEqual(len(report["rules"]), 1)
        self.assertTrue(report["lint_ok"])
        self.assertEqual(report["coverage"]["conflict"], 1)
        self.assertFalse(report["coverage"]["complete"])
        self.assertFalse(report["applicable"])
        self.assertTrue(any("conflict" in r for r in report["reasons"]))


class LevelPolicyTests(unittest.TestCase):
    def test_heuristic_is_not_generated(self):
        intent = base_intent()
        intent["requirements"]["min_clearance"]["candidates"] = [
            {"id": "C-001", "value": 0.3, "authority": "GENERIC",
             "level": "HEURISTIC", "source": "S-002"}]
        intent["derived"]["constraints"]["min_clearance"] = {
            "status": "adopted", "value": 0.3, "basis": ["C-001"],
            "overridden": [], "level": "HEURISTIC"}
        report = run(intent)
        self.assertEqual(report["rules"], [])
        self.assertFalse(report["applicable"])
        self.assertIn("HEURISTIC", report["unsupported"][0]["reason"])

    def test_should_becomes_warning(self):
        intent = base_intent()
        intent["requirements"]["min_clearance"]["level"] = "SHOULD"
        intent["requirements"]["min_clearance"]["candidates"] = [
            {"id": "C-001", "value": 0.2, "authority": "FAB",
             "level": "SHOULD", "source": "S-001"}]
        intent["derived"]["constraints"]["min_clearance"] = {
            "status": "adopted", "value": 0.2, "basis": ["C-001"], "overridden": []}
        report = run(intent)
        self.assertTrue(report["applicable"])
        self.assertEqual(report["rules"][0]["level"], "SHOULD")
        self.assertEqual(report["rules"][0]["severity"], "warning")
        self.assertIn("(severity warning)", report["proposal"])
        parsed = dru_ast.parse(report["proposal"])
        rule = parsed.root.items[1]
        severities = [i for i in rule.items
                      if i.kind == "list" and i.items and i.items[0].value == "severity"]
        self.assertEqual(severities[0].items[1].value, "warning")

    def test_mixed_level_is_unsupported(self):
        intent = base_intent()
        intent["requirements"]["min_clearance"]["candidates"] = [
            {"id": "C-001", "value": 0.15, "authority": "FAB",
             "level": "MUST", "source": "S-001"},
            {"id": "C-002", "value": 0.20, "authority": "PROJECT",
             "level": "SHOULD", "source": "S-002"}]
        intent["derived"]["constraints"]["min_clearance"] = {
            "status": "adopted", "value": 0.2,
            "basis": ["C-001", "C-002"], "overridden": []}
        report = run(intent)
        self.assertEqual(report["rules"], [])
        self.assertFalse(report["applicable"])
        reason = report["unsupported"][0]["reason"]
        self.assertIn("等级混合", reason)
        self.assertIn("MUST", reason)
        self.assertIn("SHOULD", reason)


class PathGuardTests(unittest.TestCase):
    def write(self, tmp, intent, name="intent.json"):
        path = Path(tmp) / name
        path.write_text(json.dumps(intent), encoding="utf-8")
        return path

    def test_out_refuses_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self.write(tmp, base_intent())
            out = Path(tmp) / "proposal.kicad_dru"
            out.write_text("keep me", encoding="utf-8")
            code = gen_dru.main([str(src), "--out", str(out), "--quiet"])
            self.assertEqual(code, 2)
            self.assertEqual(out.read_text(encoding="utf-8"), "keep me")

    def test_out_refuses_input_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self.write(tmp, base_intent())
            original = src.read_text(encoding="utf-8")
            self.assertEqual(gen_dru.main([str(src), "--out", str(src), "--quiet"]), 2)
            self.assertEqual(src.read_text(encoding="utf-8"), original)

    def test_json_refuses_input_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self.write(tmp, base_intent())
            original = src.read_text(encoding="utf-8")
            self.assertEqual(gen_dru.main([str(src), "--json", str(src), "--quiet"]), 2)
            self.assertEqual(src.read_text(encoding="utf-8"), original)

    def test_json_and_out_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self.write(tmp, base_intent())
            same = Path(tmp) / "same.out"
            code = gen_dru.main([str(src), "--json", str(same),
                                 "--out", str(same), "--quiet"])
            self.assertEqual(code, 2)
            self.assertFalse(same.exists())


class VerifyShapeTests(unittest.TestCase):
    def setUp(self):
        self.report = run(base_intent())

    def problems_for(self, old, new):
        text = self.report["proposal"].replace(old, new, 1)
        parsed = dru_ast.parse(text)
        self.assertEqual(parsed.errors, [])
        ast = dru_ast.to_json(parsed.root)
        return gen_dru.verify_proposal(ast, self.report["rules"])

    def test_extra_value_item_rejected(self):
        problems = self.problems_for("(min 0.15mm)", "(min 0.15mm) (max 0.1mm)")
        self.assertTrue(any("取值集合" in p for p in problems), problems)

    def test_duplicate_value_item_rejected(self):
        problems = self.problems_for("(min 0.15mm)", "(min 0.15mm) (min 0.2mm)")
        self.assertTrue(any("重复" in p or "取值集合" in p for p in problems), problems)

    def test_extra_constraint_rejected(self):
        problems = self.problems_for(
            "(constraint clearance (min 0.15mm)))",
            "(constraint clearance (min 0.15mm))\n"
            "  (constraint hole_size (min 0.01mm)))")
        self.assertTrue(any("constraint 数量" in p for p in problems), problems)

    def test_unexpected_rule_node_rejected(self):
        problems = self.problems_for(
            "(constraint clearance (min 0.15mm)))",
            "(condition \"A.X == 'Y'\")\n"
            "  (constraint clearance (min 0.15mm)))")
        self.assertTrue(any("未预期" in p for p in problems), problems)

    def test_stray_atom_rejected(self):
        problems = self.problems_for(
            "(constraint clearance", "unexpected\n  (constraint clearance")
        self.assertTrue(any("未预期" in p for p in problems), problems)

    def test_severity_with_extra_argument_rejected(self):
        intent = base_intent()
        intent["requirements"]["min_clearance"]["level"] = "SHOULD"
        intent["requirements"]["min_clearance"]["candidates"][0]["level"] = "SHOULD"
        report = run(intent)
        text = report["proposal"].replace("(severity warning)",
                                          "(severity warning extra)")
        parsed = dru_ast.parse(text)
        self.assertEqual(parsed.errors, [])
        problems = gen_dru.verify_proposal(dru_ast.to_json(parsed.root),
                                           report["rules"])
        self.assertTrue(any("severity 形式异常" in p for p in problems), problems)


class CliTests(unittest.TestCase):
    def write(self, tmp, intent, name="intent.json"):
        path = Path(tmp) / name
        path.write_text(json.dumps(intent), encoding="utf-8")
        return path

    def test_out_written_when_applicable(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self.write(tmp, base_intent())
            out = Path(tmp) / "proposal.kicad_dru"
            code = gen_dru.main([str(src), "--out", str(out), "--quiet"])
            self.assertEqual(code, 0)
            text = out.read_text(encoding="utf-8")
            self.assertIn("(constraint clearance (min 0.15mm))", text)

    def test_out_refused_when_not_applicable(self):
        intent = base_intent()
        intent["requirements"]["min_clearance"]["candidates"] = []
        intent["derived"]["constraints"]["min_clearance"] = {
            "status": "unresolved", "reason": "no_candidate"}
        with tempfile.TemporaryDirectory() as tmp:
            src = self.write(tmp, intent)
            out = Path(tmp) / "proposal.kicad_dru"
            code = gen_dru.main([str(src), "--out", str(out), "--quiet"])
            self.assertEqual(code, 2)
            self.assertFalse(out.exists())

    def test_rejected_intent_exits_2(self):
        intent = base_intent()
        intent["derived"]["constraints"]["min_clearance"]["value"] = 0.2
        with tempfile.TemporaryDirectory() as tmp:
            src = self.write(tmp, intent)
            self.assertEqual(gen_dru.main([str(src), "--quiet"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
