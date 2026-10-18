"""validate_intent 的回归测试（M1.1）。

分两层：
  1. validator 的跨字段 invariant
  2. resolver 的算术与域策略（含 FAB-in-soft 回归）

运行：python -m unittest discover -s tests -v
"""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import validate_intent as vi  # noqa: E402


def base_intent():
    return {
        "schema_version": 1,
        "project_id": "test",
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
                     "level": "MUST", "source": "S-001"},
                ],
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


def codes(report):
    return {i.code for i in report.issues}


class ValidatorTests(unittest.TestCase):
    def check(self, intent=None, *codes_expected, verdict=None):
        report = vi.validate(intent or base_intent())
        found = codes(report)
        for code in codes_expected:
            self.assertIn(code, found, f"期望 {code}，实际 {sorted(found)}")
        if verdict:
            self.assertEqual(report.verdict, verdict)
        return report

    def test_valid_intent_passes(self):
        report = vi.validate(base_intent())
        self.assertEqual(report.issues, [])
        self.assertEqual(report.verdict, "PASS")

    def test_unknown_domain(self):
        i = base_intent()
        i["requirements"]["min_clearance"]["domain"] = "mechanical"
        self.check(i, "E006", verdict="FAIL")

    def test_units_not_canonical(self):
        i = base_intent()
        i["units"]["length"] = "mil"
        self.check(i, "E003", verdict="FAIL")

    def test_missing_core_unit(self):
        i = base_intent()
        del i["units"]["impedance"]
        self.check(i, "E003", verdict="FAIL")

    def test_unit_suffix_field(self):
        i = base_intent()
        i["requirements"]["min_clearance"]["max_skew_mm"] = 0.5
        self.check(i, "E004", verdict="FAIL")

    def test_unknown_source_reference(self):
        i = base_intent()
        i["requirements"]["min_clearance"]["candidates"][0]["source"] = "S-999"
        self.check(i, "E009", verdict="FAIL")

    def test_requirement_without_candidate_or_assumption(self):
        i = base_intent()
        i["requirements"]["min_clearance"]["candidates"] = []
        i["derived"]["constraints"]["min_clearance"] = {
            "status": "unresolved", "reason": "no_candidate"}
        self.check(i, "I001", verdict="INCOMPLETE")

    def test_shipped_fixture_is_valid(self):
        import json as _json
        path = HERE / "fixtures" / "intent_valid.json"
        report = vi.validate(_json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(report.issues, [])
        self.assertEqual(report.verdict, "PASS")

    def test_basis_references_unknown_candidate(self):
        i = base_intent()
        i["derived"]["constraints"]["min_clearance"]["basis"] = ["C-999"]
        self.check(i, "E013", verdict="FAIL")

    def test_overridden_from_other_requirement(self):
        i = base_intent()
        i["requirements"]["min_track"] = {
            "domain": "manufacturing", "direction": "at_least", "level": "MUST",
            "waiver_policy": "authority_required",
            "candidates": [{"id": "C-001", "value": 0.15, "authority": "FAB",
                            "level": "MUST", "source": "S-001"}],
        }
        i["derived"]["constraints"]["min_track"] = {
            "status": "adopted", "value": 0.15, "basis": ["C-001"], "overridden": []}
        i["derived"]["constraints"]["min_clearance"]["overridden"] = ["C-002"]
        self.check(i, "E013", verdict="FAIL")

    def test_conflict_must_not_carry_value(self):
        i = base_intent()
        i["derived"]["constraints"]["min_clearance"] = {
            "status": "conflict", "value": 0.15,
            "conflict": {"code": "project_loosen_hard_bound"}}
        self.check(i, "E014", verdict="FAIL")

    def test_adopted_requires_basis(self):
        i = base_intent()
        i["derived"]["constraints"]["min_clearance"] = {
            "status": "adopted", "value": 0.15, "basis": [], "overridden": []}
        self.check(i, "E012", verdict="FAIL")

    def test_assumption_phase_invalid(self):
        i = base_intent()
        i["assumptions"]["A-001"] = {
            "item": "ambient", "assumed_value": {"value": 25, "unit": "C"},
            "impact": ["trace_width"],
            "must_resolve_before": "P11", "status": "active", "owner": "user"}
        self.check(i, "E016", verdict="FAIL")

    def test_stale_derived_detected(self):
        i = base_intent()
        i["derived"]["constraints"]["min_clearance"]["value"] = 0.2
        self.check(i, "E018", verdict="FAIL")

    def test_missing_derived_entry(self):
        i = base_intent()
        i["derived"]["constraints"] = {}
        self.check(i, "I002", verdict="INCOMPLETE")

    def test_unknown_top_level_is_warning_only(self):
        i = base_intent()
        i["extra_section"] = {}
        report = vi.validate(i)
        self.assertIn("W001", codes(report))
        self.assertEqual(report.verdict, "PASS")

    def test_duplicate_candidate_id(self):
        i = base_intent()
        i["requirements"]["min_clearance"]["candidates"].append(
            {"id": "C-001", "value": 0.2, "authority": "PROJECT",
             "level": "SHOULD", "source": "S-002"})
        self.check(i, "E008", verdict="FAIL")


class ResolverTests(unittest.TestCase):
    def req(self, **over):
        r = base_intent()["requirements"]["min_clearance"]
        r = copy.deepcopy(r)
        r.update(over)
        return r

    def test_project_loosening_hard_is_conflict(self):
        r = self.req(candidates=[
            {"id": "C-001", "value": 0.15, "authority": "FAB", "level": "MUST", "source": "S-001"},
            {"id": "C-002", "value": 0.10, "authority": "PROJECT", "level": "SHOULD", "source": "S-002"},
        ])
        out = vi.resolve_requirement(r)
        self.assertEqual(out["status"], "conflict")
        self.assertEqual(out["conflict"]["code"], "project_loosen_hard_bound")
        self.assertEqual(out["conflict"]["hard"], ["C-001"])

    def test_project_may_tighten(self):
        r = self.req(candidates=[
            {"id": "C-001", "value": 0.15, "authority": "FAB", "level": "MUST", "source": "S-001"},
            {"id": "C-002", "value": 0.20, "authority": "PROJECT", "level": "SHOULD", "source": "S-002"},
        ])
        out = vi.resolve_requirement(r)
        self.assertEqual(out["status"], "adopted")
        self.assertAlmostEqual(out["value"], 0.20)
        self.assertEqual(out["basis"], ["C-001", "C-002"])
        self.assertEqual(out["overridden"], [])

    def test_at_most_takes_min(self):
        out = vi.combine([{"value": 10}, {"value": 8}], "at_most")
        self.assertEqual(out, {"ok": True, "value": 8.0})

    def test_exact_intersection(self):
        out = vi.combine([{"range": {"min": 45, "max": 55}}, {"range": {"min": 48, "max": 52}}], "exact")
        self.assertTrue(out["ok"])
        self.assertEqual(out["range"], {"min": 48.0, "max": 52.0})

    def test_exact_empty_intersection(self):
        out = vi.combine([{"range": {"min": 45, "max": 47}}, {"range": {"min": 48, "max": 52}}], "exact")
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "empty_intersection")

    def test_equal_mismatch(self):
        out = vi.combine([{"value": "A"}, {"value": "B"}], "equal")
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "value_mismatch")

    def test_invalid_value_returns_conflict_not_exception(self):
        self.assertEqual(vi.combine([{"value": None}], "at_least")["code"], "invalid_value")
        self.assertEqual(vi.combine([{"value": {}}], "equal")["code"], "invalid_value")

    def test_no_candidate_is_unresolved(self):
        out = vi.resolve_requirement(self.req(candidates=[]))
        self.assertEqual(out["status"], "unresolved")
        self.assertEqual(out["reason"], "no_candidate")

    def test_fab_should_is_not_dropped_by_fallback(self):
        """回归：manufacturing 域里没有 MUST 时，FAB 的 SHOULD 必须优先于 PROJECT。"""
        r = self.req(candidates=[
            {"id": "C-001", "value": 0.20, "authority": "FAB", "level": "SHOULD", "source": "S-001"},
            {"id": "C-002", "value": 0.10, "authority": "PROJECT", "level": "SHOULD", "source": "S-002"},
        ])
        out = vi.resolve_requirement(r)
        self.assertEqual(out["status"], "adopted")
        self.assertAlmostEqual(out["value"], 0.20)
        self.assertEqual(out["basis"], ["C-001"])
        self.assertEqual(out["overridden"], ["C-002"])

    def test_safety_requires_standard_hard(self):
        r = {"domain": "safety", "direction": "at_least", "level": "MUST",
             "waiver_policy": "prohibited",
             "candidates": [
                 {"id": "C-001", "value": 0.5, "authority": "STANDARD", "level": "MUST", "source": "S-001"},
                 {"id": "C-002", "value": 3.0, "authority": "PROJECT", "level": "SHOULD", "source": "S-002"},
             ]}
        out = vi.resolve_requirement(r)
        self.assertEqual(out["status"], "adopted")
        self.assertAlmostEqual(out["value"], 3.0)   # 项目更严 -> 采用
        self.assertEqual(out["basis"], ["C-001", "C-002"])

    def test_heuristic_only_is_flagged(self):
        r = self.req(candidates=[
            {"id": "C-001", "value": 0.3, "authority": "GENERIC", "level": "HEURISTIC", "source": "S-002"}])
        out = vi.resolve_requirement(r)
        self.assertEqual(out["status"], "adopted")
        self.assertEqual(out.get("level"), "HEURISTIC")


class RobustnessTests(unittest.TestCase):
    """复现上一轮评审报告的结构异常与语义漏洞。"""

    def codes(self, intent):
        return {i.code for i in vi.validate(intent).issues}

    def test_sources_as_list_does_not_crash(self):
        i = base_intent()
        i["sources"] = ["bad"]
        found = self.codes(i)
        self.assertIn("E002", found)
        self.assertNotIn("E099", found)

    def test_requirement_as_string_does_not_crash(self):
        i = base_intent()
        i["requirements"]["min_clearance"] = "oops"
        found = self.codes(i)
        self.assertIn("E006", found)
        self.assertNotIn("E099", found)

    def test_basis_null_does_not_crash(self):
        i = base_intent()
        i["derived"]["constraints"]["min_clearance"]["basis"] = None
        found = self.codes(i)
        self.assertIn("E013", found)
        self.assertNotIn("E099", found)

    def test_derived_value_as_string(self):
        i = base_intent()
        i["derived"]["constraints"]["min_clearance"]["value"] = "0.15"
        found = self.codes(i)
        self.assertTrue({"E021", "E018"} & found, found)
        self.assertNotIn("E099", found)

    def test_at_least_candidate_with_range_only(self):
        i = base_intent()
        i["requirements"]["min_clearance"]["candidates"] = [
            {"id": "C-001", "range": {"min": 0.1, "max": 0.2},
             "authority": "FAB", "level": "MUST", "source": "S-001"}]
        found = self.codes(i)
        self.assertIn("E019", found)
        self.assertNotIn("E099", found)

    def test_conflict_candidate_reference_tampering(self):
        i = base_intent()
        i["requirements"]["min_clearance"]["candidates"].append(
            {"id": "C-002", "value": 0.10, "authority": "PROJECT",
             "level": "SHOULD", "source": "S-002"})
        i["derived"]["constraints"]["min_clearance"] = {
            "status": "conflict",
            "conflict": {"code": "project_loosen_hard_bound",
                         "hard": ["C-999"], "project": ["C-002"],
                         "waiver_policy": "authority_required"}}
        self.assertIn("E013", self.codes(i))

    def test_conflict_waiver_policy_tampering(self):
        i = base_intent()
        i["requirements"]["min_clearance"]["candidates"].append(
            {"id": "C-002", "value": 0.10, "authority": "PROJECT",
             "level": "SHOULD", "source": "S-002"})
        i["derived"]["constraints"]["min_clearance"] = {
            "status": "conflict",
            "conflict": {"code": "project_loosen_hard_bound",
                         "hard": ["C-001"], "project": ["C-002"],
                         "waiver_policy": "project_acceptance"}}
        self.assertIn("E018", self.codes(i))

    def test_small_values_are_not_rounded_away(self):
        out = vi.combine([{"value": 1e-10}, {"value": 2e-10}], "at_least")
        self.assertAlmostEqual(out["value"], 2e-10, places=20)
        self.assertNotEqual(out["value"], 0.0)

    def test_adopted_with_null_conflict_field(self):
        i = base_intent()
        i["derived"]["constraints"]["min_clearance"]["conflict"] = None
        self.assertIn("E014", self.codes(i))

    def test_schema_version_bool_rejected(self):
        i = base_intent()
        i["schema_version"] = True
        self.assertIn("E001", self.codes(i))

    def test_heuristic_project_candidate_cannot_loosen_hard(self):
        r = base_intent()["requirements"]["min_clearance"]
        r["candidates"] = [
            {"id": "C-001", "value": 0.15, "authority": "FAB", "level": "MUST", "source": "S-001"},
            {"id": "C-002", "value": 0.05, "authority": "PROJECT", "level": "HEURISTIC",
             "source": "S-002"},
        ]
        out = vi.resolve_requirement(copy.deepcopy(r))
        self.assertEqual(out["status"], "adopted")
        self.assertAlmostEqual(out["value"], 0.15)
        self.assertEqual(out["overridden"], ["C-002"])

    def test_duplicate_basis_is_diagnosed_separately(self):
        i = base_intent()
        i["derived"]["constraints"]["min_clearance"]["basis"] = ["C-001", "C-001"]
        found = self.codes(i)
        self.assertIn("E020", found)
        self.assertNotIn("E018", found)

    def test_equal_direction_accepts_strings(self):
        i = base_intent()
        req = i["requirements"]["min_clearance"]
        req["domain"] = "signal_integrity"
        req["direction"] = "equal"
        req["candidates"] = [{"id": "C-001", "value": "PIN_1", "authority": "DATASHEET",
                              "level": "MUST", "source": "S-002"}]
        i["derived"]["constraints"]["min_clearance"] = {
            "status": "adopted", "value": "PIN_1", "basis": ["C-001"], "overridden": []}
        report = vi.validate(i)
        self.assertEqual(report.verdict, "PASS", [x.as_dict() for x in report.issues])


    def test_tiny_value_stale_is_detected(self):
        i = base_intent()
        req = i["requirements"]["min_clearance"]
        req["candidates"] = [{"id": "C-001", "value": 1e-13, "authority": "FAB",
                              "level": "MUST", "source": "S-001"}]
        i["derived"]["constraints"]["min_clearance"] = {
            "status": "adopted", "value": 0, "basis": ["C-001"], "overridden": []}
        self.assertIn("E018", self.codes(i))

    def test_equal_direction_uses_exact_comparison(self):
        i = base_intent()
        req = i["requirements"]["min_clearance"]
        req["domain"] = "signal_integrity"
        req["direction"] = "equal"
        req["candidates"] = [{"id": "C-001", "value": 1000000000, "authority": "DATASHEET",
                              "level": "MUST", "source": "S-002"}]
        i["derived"]["constraints"]["min_clearance"] = {
            "status": "adopted", "value": 1000000001, "basis": ["C-001"], "overridden": []}
        self.assertIn("E018", self.codes(i))

    def test_exact_rejects_value_and_range_together(self):
        i = base_intent()
        req = i["requirements"]["min_clearance"]
        req["direction"] = "exact"
        req["candidates"] = [{"id": "C-001", "value": 90, "range": {"min": 80, "max": 100},
                              "authority": "FAB", "level": "MUST", "source": "S-001"}]
        self.assertIn("E019", self.codes(i))

    def test_exact_rejects_range_with_tolerance(self):
        i = base_intent()
        req = i["requirements"]["min_clearance"]
        req["direction"] = "exact"
        req["candidates"] = [{"id": "C-001", "range": {"min": 80, "max": 100},
                              "tolerance_pct": 10,
                              "authority": "FAB", "level": "MUST", "source": "S-001"}]
        self.assertIn("E019", self.codes(i))

    def test_tolerance_must_be_finite_non_negative(self):
        for bad in ("ten", -5, float("inf")):
            i = base_intent()
            req = i["requirements"]["min_clearance"]
            req["direction"] = "exact"
            req["candidates"] = [{"id": "C-001", "value": 90, "tolerance_pct": bad,
                                  "authority": "FAB", "level": "MUST", "source": "S-001"}]
            self.assertIn("E019", self.codes(i), f"tolerance={bad!r} 应被拒绝")

    def test_infinite_value_is_rejected(self):
        i = base_intent()
        i["requirements"]["min_clearance"]["candidates"][0]["value"] = float("inf")
        self.assertIn("E019", self.codes(i))

    def test_heuristic_disagreement_is_unresolved_not_conflict(self):
        req = {"domain": "practice", "direction": "equal", "level": "SHOULD",
               "waiver_policy": "project_acceptance",
               "candidates": [
                   {"id": "C-001", "value": "A", "authority": "GENERIC",
                    "level": "HEURISTIC", "source": "S-001"},
                   {"id": "C-002", "value": "B", "authority": "GENERIC",
                    "level": "HEURISTIC", "source": "S-002"}]}
        out = vi.resolve_requirement(req)
        self.assertEqual(out["status"], "unresolved")
        self.assertEqual(out["reason"], "heuristic_disagreement")

    def test_derived_level_tampering_detected(self):
        i = base_intent()
        req = i["requirements"]["min_clearance"]
        req["candidates"] = [{"id": "C-001", "value": 0.3, "authority": "GENERIC",
                              "level": "HEURISTIC", "source": "S-001"}]
        i["derived"]["constraints"]["min_clearance"] = {
            "status": "adopted", "value": 0.3, "basis": ["C-001"],
            "overridden": [], "level": "MUST"}
        self.assertIn("E018", self.codes(i))

    def test_resolver_never_raises_on_malformed_input(self):
        cases = [
            "not a dict",
            {"domain": "manufacturing", "direction": "at_least", "candidates": None},
            {"domain": "manufacturing", "direction": "nope", "candidates": []},
            {"domain": "nope", "direction": "at_least", "candidates": []},
        ]
        for req in cases:
            out = vi.resolve_requirement(req)
            self.assertEqual(out["status"], "unresolved", req)


    def test_resolver_guards_malformed_types(self):
        cases = [
            {"domain": "manufacturing", "direction": [], "candidates": []},
            {"domain": "manufacturing", "direction": "at_least", "candidates": 1},
            {"domain": "manufacturing", "direction": "at_least", "candidates": True},
            {"domain": "manufacturing", "direction": "at_least", "candidates": []},
        ]
        for req in cases:
            out = vi.resolve_requirement(req)  # 不应抛异常
            self.assertEqual(out["status"], "unresolved", req)

    def test_huge_integer_value_does_not_raise(self):
        req = {"domain": "manufacturing", "direction": "at_least",
               "candidates": [{"id": "C-001", "value": 10 ** 400, "authority": "FAB",
                               "level": "MUST", "source": "S-001"}]}
        out = vi.resolve_requirement(req)
        self.assertIn(out["status"], {"conflict", "unresolved"})

        i = base_intent()
        i["requirements"]["min_clearance"]["candidates"][0]["value"] = 10 ** 400
        self.assertIn("E019", self.codes(i))

    def test_equal_keeps_integer_precision_above_2_53(self):
        i = base_intent()
        req = i["requirements"]["min_clearance"]
        req["domain"] = "signal_integrity"
        req["direction"] = "equal"
        req["candidates"] = [{"id": "C-001", "value": 9007199254740992,
                              "authority": "DATASHEET", "level": "MUST", "source": "S-002"}]
        i["derived"]["constraints"]["min_clearance"] = {
            "status": "adopted", "value": 9007199254740993,
            "basis": ["C-001"], "overridden": []}
        self.assertIn("E018", self.codes(i))

    def test_exact_overflow_becomes_unresolved(self):
        req = {"domain": "signal_integrity", "direction": "exact",
               "candidates": [{"id": "C-001", "value": 1e308, "tolerance_pct": 1000,
                               "authority": "DATASHEET", "level": "MUST", "source": "S-001"}]}
        out = vi.resolve_requirement(req)
        self.assertEqual(out["status"], "unresolved")
        self.assertEqual(out["reason"], "non_finite_result")

    def test_derived_infinite_range_rejected(self):
        i = base_intent()
        req = i["requirements"]["min_clearance"]
        req["direction"] = "exact"
        req["candidates"] = [{"id": "C-001", "value": 1e308, "tolerance_pct": 10,
                              "authority": "FAB", "level": "MUST", "source": "S-001"}]
        i["derived"]["constraints"]["min_clearance"] = {
            "status": "adopted",
            "range": {"min": float("-inf"), "max": float("inf")},
            "basis": ["C-001"], "overridden": []}
        self.assertIn("E022", self.codes(i))


    def test_assumption_value_must_be_string_or_finite_number(self):
        for bad in ({}, True, float("inf")):
            i = base_intent()
            i["assumptions"]["A-001"] = {
                "item": "ambient", "assumed_value": {"value": bad, "unit": "C"},
                "impact": ["trace_width"], "must_resolve_before": "P3", "status": "active"}
            self.assertIn("E016", self.codes(i), f"value={bad!r}")

    def test_assumption_impact_must_be_strings(self):
        i = base_intent()
        i["assumptions"]["A-001"] = {
            "item": "ambient", "assumed_value": {"value": 25, "unit": "C"},
            "impact": [123], "must_resolve_before": "P3", "status": "active"}
        self.assertIn("E016", self.codes(i))

    def test_assumption_requires_unit(self):
        i = base_intent()
        i["assumptions"]["A-001"] = {
            "item": "ambient", "assumed_value": {"value": 25},
            "impact": ["trace_width"], "must_resolve_before": "P3", "status": "active"}
        self.assertIn("E016", self.codes(i))


class FileTests(unittest.TestCase):
    def test_loads_json_and_cli_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "intent.json"
            p.write_text(json.dumps(base_intent()), encoding="utf-8")
            self.assertEqual(vi.main([str(p), "--quiet"]), 0)

            bad = base_intent()
            bad["requirements"]["min_clearance"]["domain"] = "nope"
            p2 = Path(tmp) / "bad.json"
            p2.write_text(json.dumps(bad), encoding="utf-8")
            self.assertEqual(vi.main([str(p2), "--quiet"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
