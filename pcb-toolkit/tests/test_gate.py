"""gate 的回归测试（M1.5）。

覆盖：五态判定与优先级、必需检查、waiver 策略、assumption 期限、
各工具输出的归一化、CLI 退出码。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import gate  # noqa: E402


def fd(code, effect, ref=None, message="msg", policy=None):
    return {"code": code, "effect": effect, "message": message,
            "ref": ref, "detail": None, "waiver_policy": policy}


VALID_WAIVER = {
    "id": "W-1", "code": "O", "reason": "reviewed",
    "approved_by": "alice", "review_by": "2099-01-01",
    "compensating": "keepout added",
}


def ev(check, findings=(), coverage="full"):
    counts = {"block": 0, "review": 0, "incomplete": 0, "info": 0}
    for f in findings:
        counts[f["effect"]] += 1
    return {"check": check, "tool": "test", "coverage": coverage,
            "counts": counts, "findings": list(findings)}


def full_p8(drc=(), erc=(), overlap=(), lint=()):
    return [ev("drc", drc), ev("erc", erc), ev("overlap", overlap), ev("lint", lint)]


def base_intent():
    return {
        "schema_version": 1, "project_id": "gate-test", "revision": 1,
        "units": {"length": "mm", "voltage": "V", "current": "A",
                  "impedance": "ohm", "frequency": "Hz", "temperature": "C"},
        "sources": {"S-001": {"type": "fab_profile", "ref": "JLC",
                              "retrieved": "2026-10-01"}},
        "requirements": {"min_clearance": {
            "domain": "manufacturing", "direction": "at_least", "level": "MUST",
            "waiver_policy": "authority_required",
            "candidates": [{"id": "C-001", "value": 0.15, "authority": "FAB",
                            "level": "MUST", "source": "S-001"}]}},
        "assumptions": {},
        "derived": {"constraints": {"min_clearance": {
            "status": "adopted", "value": 0.15, "basis": ["C-001"],
            "overridden": []}},
            "netclasses": {}, "rule_requirements": {},
            "verification_requirements": {}},
    }


class ReportValidityTests(unittest.TestCase):
    def test_empty_reports_are_not_treated_as_clean(self):
        for check, fn in (("drc", gate.from_drc), ("erc", gate.from_erc),
                          ("overlap", gate.from_overlap), ("lint", gate.from_lint),
                          ("gen", gate.from_gen)):
            entry = fn({})
            self.assertEqual(entry["coverage"], "none", check)
            self.assertGreaterEqual(entry["counts"]["incomplete"], 1, check)

    def test_overlap_coverage_none_is_respected(self):
        entry = gate.from_overlap({"coverage": "none", "findings": []})
        self.assertEqual(entry["coverage"], "none")
        self.assertEqual(entry["counts"]["incomplete"], 1)

    def test_lint_unknown_effect_is_incomplete(self):
        entry = gate.from_lint({"errors": [],
                                "findings": [{"code": "L", "effect": "blok"}]})
        self.assertEqual(entry["counts"]["incomplete"], 1)
        self.assertEqual(entry["counts"]["block"], 0)

    def test_drc_missing_violations_key(self):
        entry = gate.from_drc({"unconnected_items": 0})
        self.assertEqual(entry["coverage"], "none")
        self.assertEqual(entry["findings"][0]["code"], "DRC_INVALID_REPORT")

    def test_drc_coverage_none_and_failed(self):
        entry = gate.from_drc({"violations": [], "coverage": "none",
                               "status": "FAILED"})
        self.assertEqual(entry["coverage"], "none")
        self.assertGreaterEqual(entry["counts"]["incomplete"], 1)

    def test_drc_string_count_is_invalid(self):
        entry = gate.from_drc({"violations": [], "schematic_parity": "202"})
        self.assertGreaterEqual(entry["counts"]["incomplete"], 1)
        self.assertEqual(entry["counts"]["block"], 0)

    def test_missing_drc_counts_are_not_zero(self):
        entry = gate.from_drc({"violations": []})
        self.assertGreaterEqual(entry["counts"]["incomplete"], 1)
        self.assertEqual(entry["counts"]["block"], 0)

    def test_truncated_drc_is_incomplete(self):
        entry = gate.from_drc({"violations": [], "unconnected_items": 0,
                               "schematic_parity": 0, "truncated": True})
        self.assertEqual(entry["coverage"], "partial")
        self.assertGreaterEqual(entry["counts"]["incomplete"], 1)
        report = gate.evaluate(
            "P8", [entry, ev("erc"), ev("overlap"), ev("lint")], [], [])
        self.assertEqual(report["verdict"], "INCOMPLETE")

    def test_truncated_must_be_bool(self):
        entry = gate.from_drc({"violations": [], "unconnected_items": 0,
                               "schematic_parity": 0, "truncated": "yes"})
        self.assertGreaterEqual(entry["counts"]["incomplete"], 1)

    def test_missing_truncated_is_not_truncation(self):
        entry = gate.from_drc({"violations": [], "unconnected_items": 0,
                               "schematic_parity": 0})
        self.assertEqual(entry["coverage"], "full")

    def test_explicit_null_truncated_is_invalid(self):
        drc = gate.from_drc({"violations": [], "unconnected_items": 0,
                             "schematic_parity": 0, "truncated": None})
        self.assertEqual(drc["coverage"], "partial")
        self.assertGreaterEqual(drc["counts"]["incomplete"], 1)
        erc = gate.from_erc({"violations": [], "truncated": None})
        self.assertEqual(erc["coverage"], "partial")
        self.assertGreaterEqual(erc["counts"]["incomplete"], 1)

    def test_truncated_erc_is_incomplete(self):
        entry = gate.from_erc({"violations": [], "truncated": True})
        self.assertEqual(entry["coverage"], "partial")
        self.assertGreaterEqual(entry["counts"]["incomplete"], 1)

    def test_fractional_count_is_invalid(self):
        entry = gate.from_drc({"violations": [], "schematic_parity": 0.5})
        self.assertGreaterEqual(entry["counts"]["incomplete"], 1)
        self.assertEqual(entry["counts"]["block"], 0)

    def test_gen_complete_contradiction_is_invalid(self):
        entry = gate.from_gen({
            "status": "PROPOSAL", "applicable": True,
            "coverage": {"conflict": 0, "unresolved": 1,
                         "unsupported": 0, "complete": True},
            "lint": {"findings": []}})
        self.assertEqual(entry["coverage"], "none")

    def test_gen_complete_must_be_bool(self):
        entry = gate.from_gen({
            "status": "PROPOSAL", "applicable": True,
            "coverage": {"conflict": 0, "unresolved": 0,
                         "unsupported": 0, "complete": "false"},
            "lint": {"findings": []}})
        self.assertEqual(entry["coverage"], "none")

    def test_lint_aborted_report(self):
        entry = gate.from_lint({"findings": [], "errors": [],
                                "coverage": "none",
                                "summary": {"aborted": True}})
        self.assertEqual(entry["coverage"], "none")
        self.assertGreaterEqual(entry["counts"]["incomplete"], 1)

    def test_gen_minimal_report_is_invalid(self):
        entry = gate.from_gen({"status": "PROPOSAL"})
        self.assertEqual(entry["coverage"], "none")
        self.assertGreaterEqual(entry["counts"]["incomplete"], 1)

    def test_empty_reports_p9_yield_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for name in ("drc", "erc", "overlap", "lint", "gen"):
                p = Path(tmp) / f"{name}.json"
                p.write_text("{}", encoding="utf-8")
                paths[name] = p
            report = gate.build(
                "P9", drc_path=paths["drc"], erc_path=paths["erc"],
                overlap_path=paths["overlap"], lint_path=paths["lint"],
                gen_path=paths["gen"])
            self.assertEqual(report["verdict"], "INCOMPLETE")
            self.assertNotEqual(report["verdict"], "PASS")


class ConflictGateTests(unittest.TestCase):
    def make_conflict(self):
        intent = base_intent()
        intent["sources"]["S-002"] = {"type": "project_constraint", "ref": "brief"}
        intent["sources"]["S-003"] = {"type": "datasheet", "ref": "unrelated"}
        intent["sources"]["S-004"] = {"type": "fab_profile", "ref": "new fab"}
        intent["requirements"]["min_clearance"]["candidates"].append(
            {"id": "C-002", "value": 0.10, "authority": "PROJECT",
             "level": "SHOULD", "source": "S-002"})
        intent["derived"]["constraints"]["min_clearance"] = {
            "status": "conflict",
            "conflict": {"code": "project_loosen_hard_bound",
                         "hard": ["C-001"], "project": ["C-002"],
                         "waiver_policy": "authority_required"}}
        return intent

    def waiver(self, **over):
        w = {"id": "W", "code": "INTENT_CONFLICT", "ref": "min_clearance",
             "requirement": "min_clearance", "reason": "r",
             "approved_by": "a", "review_by": "2099-01-01",
             "compensating": "c"}
        w.update(over)
        return w

    def run_gate(self, intent, waiver):
        ev_intent, assumptions = gate.from_intent(intent)
        return gate.evaluate("P3", [ev_intent, ev("erc")], [waiver], assumptions,
                             sources=intent.get("sources"), intent=intent)

    def test_intent_conflict_blocks(self):
        intent = self.make_conflict()
        ev_intent, assumptions = gate.from_intent(intent)
        report = gate.evaluate("P3", [ev_intent, ev("erc")], [], assumptions)
        self.assertEqual(report["verdict"], "BLOCKED")
        codes = {f["code"] for f in report["findings"]["unwaived_blocks"]}
        self.assertIn("INTENT_CONFLICT", codes)

    def test_waiver_cannot_reuse_original_authority(self):
        intent = self.make_conflict()
        waiver = self.waiver(authority="S-001",
                             replacement={"id": "C-900", "value": 0.10,
                                          "authority": "FAB", "level": "MUST",
                                          "source": "S-001"})
        report = self.run_gate(intent, waiver)
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertTrue(any("不能是冲突原主张" in r for r in
                            report["waivers_rejected"][0]["reasons"]))

    def test_waiver_needs_replacement_claim(self):
        intent = self.make_conflict()
        report = self.run_gate(intent, self.waiver(authority="S-003"))
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertTrue(any("replacement" in r for r in
                            report["waivers_rejected"][0]["reasons"]))

    def test_replacement_source_must_match_authority(self):
        intent = self.make_conflict()
        waiver = self.waiver(authority="S-004",
                             replacement={"id": "C-900", "value": 0.12,
                                          "authority": "FAB", "level": "MUST",
                                          "source": "S-003"})
        report = self.run_gate(intent, waiver)
        self.assertEqual(report["verdict"], "BLOCKED")

    def test_valid_replacement_resolves_conflict(self):
        intent = self.make_conflict()
        waiver = self.waiver(authority="S-004",
                             replacement={"id": "C-900", "value": 0.12,
                                          "authority": "FAB", "level": "MUST",
                                          "source": "S-004"})
        report = self.run_gate(intent, waiver)
        self.assertEqual(report["verdict"], "PASS_WITH_WAIVERS")

    def test_replacement_missing_id_is_invalid(self):
        intent = self.make_conflict()
        waiver = self.waiver(authority="S-004",
                             replacement={"value": 0.12, "authority": "FAB",
                                          "level": "MUST", "source": "S-004"})
        report = self.run_gate(intent, waiver)
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertTrue(any("replacement 无效" in r for r in
                            report["waivers_rejected"][0]["reasons"]))

    def test_heuristic_replacement_is_invalid(self):
        intent = self.make_conflict()
        waiver = self.waiver(authority="S-004",
                             replacement={"id": "C-900", "value": 0.12,
                                          "authority": "GENERIC",
                                          "level": "HEURISTIC",
                                          "source": "S-004"})
        report = self.run_gate(intent, waiver)
        self.assertEqual(report["verdict"], "BLOCKED")

    def test_replacement_authority_must_fit_domain(self):
        intent = self.make_conflict()
        waiver = self.waiver(authority="S-004",
                             replacement={"id": "C-900", "value": 0.12,
                                          "authority": "DATASHEET",
                                          "level": "MUST",
                                          "source": "S-004"})
        report = self.run_gate(intent, waiver)
        self.assertEqual(report["verdict"], "BLOCKED")

    def test_replacement_id_must_not_collide_with_retained(self):
        intent = self.make_conflict()
        intent["requirements"]["min_clearance"]["candidates"].append(
            {"id": "C-003", "value": 0.20, "authority": "FAB",
             "level": "SHOULD", "source": "S-001"})
        waiver = self.waiver(authority="S-004",
                             replacement={"id": "C-003", "value": 0.12,
                                          "authority": "GENERIC",
                                          "level": "SHOULD",
                                          "source": "S-004"})
        finding = gate._finding("INTENT_CONFLICT", "block", "x",
                                ref="min_clearance",
                                policy="authority_required")
        report = gate.evaluate(
            "P3", [gate._evidence("intent", "t", [finding]), ev("erc")],
            [waiver], [], sources=intent["sources"], intent=intent)
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertTrue(any("重复" in r for r in
                            report["waivers_rejected"][0]["reasons"]))

    def test_replacement_result_invariants_are_checked(self):
        intent = self.make_conflict()
        finding = gate._finding("INTENT_CONFLICT", "block", "x",
                                ref="min_clearance",
                                policy="authority_required")
        waiver = self.waiver(authority="S-004",
                             replacement={"id": "C-900", "value": 0.12,
                                          "authority": "FAB", "level": "MUST",
                                          "source": "S-004"})
        crossed = {"status": "adopted", "value": 0.2,
                   "basis": ["C-900"], "overridden": ["C-900"]}
        with mock.patch.object(gate.vi, "resolve_requirement",
                               return_value=crossed):
            issue = gate._conflict_replacement_issue(waiver, finding, intent)
        self.assertIn("交叉", issue)

    def test_gen_conflict_requires_replacement(self):
        entry = gate.from_gen({
            "status": "PROPOSAL", "applicable": False,
            "coverage": {"complete": False, "conflict": 1,
                         "unresolved": 0, "unsupported": 0},
            "lint": {"findings": []}})
        waiver = {"id": "W", "code": "GEN_CONFLICT", "reason": "r",
                  "approved_by": "a", "review_by": "2099-01-01",
                  "compensating": "c"}
        report = gate.evaluate(
            "P9", [ev("drc"), ev("erc"), ev("overlap"), ev("lint"), entry],
            [waiver], [])
        self.assertEqual(report["verdict"], "BLOCKED")

    def test_gen_conflict_blocks(self):
        entry = gate.from_gen({
            "status": "PROPOSAL", "applicable": False,
            "coverage": {"complete": False, "conflict": 1,
                         "unresolved": 0, "unsupported": 0},
            "lint": {"findings": []}})
        self.assertEqual(entry["counts"]["block"], 1)
        report = gate.evaluate("P9", [
            ev("drc"), ev("erc"), ev("overlap"), ev("lint"), entry], [], [])
        self.assertEqual(report["verdict"], "BLOCKED")


class AssumptionPhaseTests(unittest.TestCase):
    def test_p8_open_future_assumption_blocks(self):
        a = {"id": "A-001", "status": "active", "must_resolve_before": "P9"}
        report = gate.evaluate("P8", full_p8(), [], [a])
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(report["counts"]["assumptions_open"], 1)
        self.assertEqual(report["counts"]["assumptions_due"], 0)

    def test_p8_expired_future_assumption_blocks(self):
        a = {"id": "A-001", "status": "expired", "must_resolve_before": "P9"}
        report = gate.evaluate("P8", full_p8(), [], [a])
        self.assertEqual(report["verdict"], "BLOCKED")

    def test_invalid_assumption_phase_is_incomplete(self):
        a = {"id": "A-001", "status": "active", "must_resolve_before": "P11"}
        report = gate.evaluate("P6", [ev("drc"), ev("overlap")], [], [a])
        self.assertEqual(report["verdict"], "INCOMPLETE")
        self.assertEqual(len(report["assumptions_invalid"]), 1)


class VerdictTests(unittest.TestCase):
    def test_clean_p8_passes(self):
        report = gate.evaluate("P8", full_p8(), [], [])
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["counts"]["errors_total"], 0)

    def test_unwaived_block_wins(self):
        report = gate.evaluate("P8", full_p8(overlap=[fd("O", "block")]), [], [])
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(report["counts"]["errors_unwaived"], 1)

    def test_block_beats_review(self):
        report = gate.evaluate(
            "P8", full_p8(drc=[fd("D", "block")], lint=[fd("L", "review")]), [], [])
        self.assertEqual(report["verdict"], "BLOCKED")

    def test_review_is_incomplete(self):
        report = gate.evaluate("P8", full_p8(overlap=[fd("O", "review")]), [], [])
        self.assertEqual(report["verdict"], "INCOMPLETE")

    def test_missing_required_check(self):
        evidence = [ev("drc"), ev("erc"), ev("overlap")]
        report = gate.evaluate("P8", evidence, [], [])
        self.assertEqual(report["verdict"], "INCOMPLETE")
        self.assertIn("lint", report["missing_checks"])

    def test_partial_coverage_is_incomplete(self):
        evidence = full_p8()
        evidence[0]["coverage"] = "partial"
        report = gate.evaluate("P8", evidence, [], [])
        self.assertEqual(report["verdict"], "INCOMPLETE")


class WaiverTests(unittest.TestCase):
    def test_valid_waiver_turns_block_into_pass_with_waivers(self):
        waiver = dict(VALID_WAIVER, ref="R1")
        report = gate.evaluate("P8", full_p8(overlap=[fd("O", "block", "R1")]),
                               [waiver], [])
        self.assertEqual(report["verdict"], "PASS_WITH_WAIVERS")
        self.assertEqual(report["counts"]["errors_waived"], 1)
        self.assertEqual(report["counts"]["errors_unwaived"], 0)

    def test_waiver_must_match_ref(self):
        waiver = dict(VALID_WAIVER, ref="R2")
        report = gate.evaluate("P8", full_p8(overlap=[fd("O", "block", "R1")]),
                               [waiver], [])
        self.assertEqual(report["verdict"], "BLOCKED")

    def test_incomplete_waiver_is_invalid(self):
        report = gate.evaluate("P8", full_p8(overlap=[fd("O", "block")]),
                               [{"code": "O"}], [])
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertTrue(report["waivers_rejected"][0]["reasons"])

    def test_prohibited_finding_cannot_be_waived(self):
        waiver = dict(VALID_WAIVER, ref=None)
        report = gate.evaluate(
            "P8", full_p8(overlap=[fd("O", "block", policy="prohibited")]),
            [waiver], [])
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(len(report["waivers_rejected"]), 1)

    def test_authority_required_waiver_needs_authority(self):
        waiver = dict(VALID_WAIVER, ref=None)
        finding = fd("O", "block", policy="authority_required")
        report = gate.evaluate("P8", full_p8(overlap=[finding]), [waiver], [])
        self.assertEqual(report["verdict"], "BLOCKED")

        waiver["authority"] = "JLCPCB-0.08mm-special"
        report = gate.evaluate("P8", full_p8(overlap=[finding]), [waiver], [],
                               sources={"JLCPCB-0.08mm-special":
                                        {"type": "fab_profile", "ref": "JLC"}})
        self.assertEqual(report["verdict"], "PASS_WITH_WAIVERS")

    def test_authority_source_must_be_authoritative(self):
        waiver = dict(VALID_WAIVER, ref=None, authority="S-GUESS")
        finding = fd("O", "block", policy="authority_required")
        report = gate.evaluate(
            "P8", full_p8(overlap=[finding]), [waiver], [],
            sources={"S-GUESS": {"type": "heuristic", "ref": "guess"}})
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertTrue(any("authoritative" in r for r in
                            report["waivers_rejected"][0]["reasons"]))

    def test_authority_must_exist_in_sources(self):
        waiver = dict(VALID_WAIVER, ref=None,
                      authority="SOURCE-DOES-NOT-EXIST")
        finding = fd("O", "block", policy="authority_required")
        report = gate.evaluate("P8", full_p8(overlap=[finding]), [waiver], [],
                               sources={"S-001": {"type": "datasheet", "ref": "DS"}})
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertTrue(any("不存在" in r for r in
                            report["waivers_rejected"][0]["reasons"]))

    def test_review_by_must_be_iso_date(self):
        waiver = dict(VALID_WAIVER, review_by="not-a-date")
        report = gate.evaluate("P8", full_p8(overlap=[fd("O", "block")]),
                               [waiver], [])
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertTrue(any("ISO 日期" in r for r in
                            report["waivers_rejected"][0]["reasons"]))

    def test_review_by_expired_is_invalid(self):
        waiver = dict(VALID_WAIVER, review_by="2020-01-01")
        report = gate.evaluate("P8", full_p8(overlap=[fd("O", "block")]),
                               [waiver], [], today=gate.date(2026, 10, 19))
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertTrue(any("过期" in r for r in
                            report["waivers_rejected"][0]["reasons"]))

    def test_erc_waiver_matches_normalized_code_and_ref(self):
        erc = gate.from_erc({"violations": [{
            "rule": "power_pin_not_driven", "severity": "error",
            "items": [{"uuid": "U1-VDD"}], "description": "x"}]})
        finding = erc["findings"][0]
        self.assertEqual(finding["code"], "ERC_power_pin_not_driven")
        self.assertEqual(finding["ref"], "U1-VDD")
        waiver = {"id": "W", "code": finding["code"], "ref": finding["ref"],
                  "reason": "r", "approved_by": "a",
                  "review_by": "2099-01-01", "compensating": "c"}
        report = gate.evaluate(
            "P8", [erc, ev("drc"), ev("overlap"), ev("lint")], [waiver], [])
        self.assertEqual(report["verdict"], "PASS_WITH_WAIVERS")

    def test_erc_waiver_ref_scopes_one_violation(self):
        erc = gate.from_erc({"violations": [
            {"rule": "power_pin_not_driven", "severity": "error",
             "items": [{"uuid": "U1-VDD"}]},
            {"rule": "power_pin_not_driven", "severity": "error",
             "items": [{"uuid": "U2-VDD"}]}]})
        refs = [f["ref"] for f in erc["findings"]]
        self.assertEqual(refs, ["U1-VDD", "U2-VDD"])
        waiver = {"id": "W", "code": "ERC_power_pin_not_driven",
                  "ref": "U1-VDD", "reason": "r", "approved_by": "a",
                  "review_by": "2099-01-01", "compensating": "c"}
        report = gate.evaluate(
            "P8", [erc, ev("drc"), ev("overlap"), ev("lint")], [waiver], [])
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(report["counts"]["errors_waived"], 1)
        self.assertEqual(report["counts"]["errors_unwaived"], 1)

    def test_multi_item_ref_keeps_all_uuids(self):
        erc = gate.from_erc({"violations": [{
            "rule": "clearance", "severity": "error",
            "items": [{"uuid": "B"}, {"uuid": "A"}]}]})
        self.assertEqual(erc["findings"][0]["ref"], "A+B")
        waiver = {"id": "W", "code": "ERC_clearance", "ref": "A",
                  "reason": "r", "approved_by": "a",
                  "review_by": "2099-01-01", "compensating": "c"}
        blocked = gate.evaluate(
            "P8", [erc, ev("drc"), ev("overlap"), ev("lint")], [waiver], [])
        self.assertEqual(blocked["verdict"], "BLOCKED")
        waiver["ref"] = "A+B"
        passed = gate.evaluate(
            "P8", [erc, ev("drc"), ev("overlap"), ev("lint")], [waiver], [])
        self.assertEqual(passed["verdict"], "PASS_WITH_WAIVERS")

    def test_drc_ref_uses_item_uuid(self):
        drc = gate.from_drc({"violations": [{
            "rule": "clearance", "severity": "error",
            "items": [{"uuid": "D1"}]}],
            "unconnected_items": 0, "schematic_parity": 0})
        self.assertEqual(drc["findings"][0]["ref"], "D1")

    def test_ledger_row_produces_applicable_waiver(self):
        ledger = (Path(__file__).resolve().parents[2]
                  / "pcb-schematic" / "assets" / "erc-waiver-ledger.md")
        text = ledger.read_text(encoding="utf-8")
        row = next(line for line in text.splitlines()
                   if line.startswith("| W-ERC-001"))
        cells = [c.strip().strip("`") for c in row.strip("|").split("|")]
        waiver_id, code, ref = cells[0], cells[1], cells[2]
        erc = gate.from_erc({"violations": [{
            "rule": "power_pin_not_driven", "severity": "error",
            "items": [{"uuid": ref}], "description": "x"}]})
        self.assertEqual(erc["findings"][0]["code"], code)
        self.assertEqual(erc["findings"][0]["ref"], ref)
        waiver = {"id": waiver_id, "code": code, "ref": ref,
                  "reason": "r", "approved_by": "a",
                  "review_by": "2099-01-01", "compensating": "c"}
        report = gate.evaluate(
            "P8", [erc, ev("drc"), ev("overlap"), ev("lint")], [waiver], [])
        self.assertEqual(report["verdict"], "PASS_WITH_WAIVERS")

    def test_ledger_example_code_matches_gate_finding(self):
        erc = gate.from_erc({"violations": [{
            "rule": "power_pin_not_driven", "severity": "error",
            "items": [{"uuid": "u-1"}], "description": "x"}]})
        code = erc["findings"][0]["code"]
        ledger = (Path(__file__).resolve().parents[2]
                  / "pcb-schematic" / "assets" / "erc-waiver-ledger.md")
        self.assertIn(code, ledger.read_text(encoding="utf-8"))

    def test_erc_legacy_rule_name_does_not_match(self):
        erc = gate.from_erc({"violations": [{
            "rule": "power_pin_not_driven", "severity": "error",
            "uuid": "u-1", "description": "x"}]})
        waiver = {"id": "W", "code": "power_pin_not_driven",
                  "reason": "r", "approved_by": "a",
                  "review_by": "2099-01-01", "compensating": "c"}
        report = gate.evaluate(
            "P8", [erc, ev("drc"), ev("overlap"), ev("lint")], [waiver], [])
        self.assertEqual(report["verdict"], "BLOCKED")


class AssumptionTests(unittest.TestCase):
    def test_due_assumption_blocks_at_p8(self):
        a = {"id": "A-001", "status": "active", "must_resolve_before": "P8"}
        report = gate.evaluate("P8", full_p8(), [], [a])
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(report["counts"]["assumptions_open"], 1)

    def test_future_assumption_is_pass_with_assumptions(self):
        a = {"id": "A-001", "status": "active", "must_resolve_before": "P9"}
        report = gate.evaluate("P6", [ev("drc"), ev("overlap")], [], [a])
        self.assertEqual(report["verdict"], "PASS_WITH_ASSUMPTIONS")

    def test_resolved_assumption_does_not_count(self):
        a = {"id": "A-001", "status": "resolved", "must_resolve_before": "P8"}
        report = gate.evaluate("P8", full_p8(), [], [a])
        self.assertEqual(report["verdict"], "PASS")


class NormalizationTests(unittest.TestCase):
    def test_overlap_effects(self):
        report = {"findings": [
            {"kind": "overlap", "gate_effect": "block", "ref_a": "R1",
             "ref_b": "R2", "detail": "x"},
            {"kind": "touch", "gate_effect": "info", "ref_a": "R3",
             "ref_b": "R4", "detail": "y"}]}
        entry = gate.from_overlap(report)
        self.assertEqual(entry["counts"]["block"], 1)
        self.assertEqual(entry["counts"]["info"], 1)

    def test_overlap_policy_is_preserved(self):
        entry = gate.from_overlap({"findings": [{
            "kind": "overlap", "gate_effect": "block",
            "ref_a": "R1", "ref_b": "R2",
            "waiver_policy": "prohibited"}]})
        self.assertEqual(entry["findings"][0]["waiver_policy"], "prohibited")
        report = gate.evaluate(
            "P8", [ev("drc"), ev("erc"), entry, ev("lint")],
            [dict(VALID_WAIVER, code="OVERLAP_OVERLAP", ref="R1")], [])
        self.assertEqual(report["verdict"], "BLOCKED")

    def test_erc_policy_is_preserved(self):
        entry = gate.from_erc({"violations": [{
            "type": "pin", "severity": "error",
            "waiver_policy": "prohibited"}]})
        self.assertEqual(entry["findings"][0]["waiver_policy"], "prohibited")
        report = gate.evaluate(
            "P8", [ev("drc"), entry, ev("overlap"), ev("lint")],
            [dict(VALID_WAIVER, code="ERC_pin")], [])
        self.assertEqual(report["verdict"], "BLOCKED")

    def test_drc_policy_is_preserved(self):
        entry = gate.from_drc({"violations": [{
            "rule": "clearance", "severity": "error",
            "waiver_policy": "prohibited"}]})
        self.assertEqual(entry["findings"][0]["waiver_policy"], "prohibited")

    def test_drc_unconnected_and_parity(self):
        entry = gate.from_drc({"unconnected_items": 2, "schematic_parity": 3,
                               "violations": []})
        codes = {f["code"] for f in entry["findings"]}
        self.assertIn("DRC_UNCONNECTED", codes)
        self.assertIn("DRC_SCHEMATIC_PARITY", codes)
        self.assertEqual(entry["counts"]["block"], 2)

    def test_drc_list_counts(self):
        entry = gate.from_drc({"unconnected_items": [{}, {}],
                               "schematic_parity": [{}, {}, {}],
                               "violations": []})
        self.assertEqual(entry["counts"]["block"], 2)

    def test_erc_severity_mapping(self):
        entry = gate.from_erc({"violations": [
            {"severity": "error", "description": "pin conflict"},
            {"severity": "warning", "description": "not driven"}]})
        self.assertEqual(entry["counts"]["block"], 1)
        self.assertEqual(entry["counts"]["review"], 1)

    def test_lint_syntax_error_marks_partial(self):
        entry = gate.from_lint({"errors": [{"code": "E_UNCLOSED", "line": 2, "col": 1}],
                                "findings": []})
        self.assertEqual(entry["coverage"], "partial")
        self.assertEqual(entry["counts"]["incomplete"], 1)

    def test_gen_rejected_is_block(self):
        entry = gate.from_gen({"status": "REJECTED", "reasons": ["E018 stale"]})
        self.assertEqual(entry["counts"]["block"], 1)

    def test_gen_incomplete_coverage(self):
        entry = gate.from_gen({
            "status": "PROPOSAL", "applicable": True,
            "coverage": {"complete": False, "conflict": 0,
                         "unresolved": 1, "unsupported": 0},
            "lint": {"findings": []}})
        self.assertEqual(entry["counts"]["incomplete"], 1)


class BuildAndCliTests(unittest.TestCase):
    def write(self, tmp, name, data):
        path = Path(tmp) / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_build_with_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            intent = self.write(tmp, "intent.json", base_intent())
            erc = self.write(tmp, "erc.json", {"violations": []})
            report = gate.build("P3", intent_path=intent, erc_path=erc)
            self.assertEqual(report["verdict"], "PASS")
            checks = {e["check"] for e in report["evidence"]}
            self.assertEqual(checks, {"intent", "erc"})

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            intent = self.write(tmp, "intent.json", base_intent())
            erc = self.write(tmp, "erc.json", {"violations": []})
            self.assertEqual(
                gate.main(["--phase", "P3", "--intent", str(intent),
                           "--erc", str(erc), "--quiet"]), 0)

            drc = self.write(tmp, "drc.json", {"unconnected_items": 1,
                                               "violations": []})
            self.assertEqual(
                gate.main(["--phase", "P7", "--drc", str(drc), "--quiet"]), 1)

            clean_drc = self.write(tmp, "clean_drc.json", {"violations": []})
            self.assertEqual(
                gate.main(["--phase", "P8", "--drc", str(clean_drc),
                           "--quiet"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
