"""pcb_analysis 的回归测试（M5）。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import pcb_analysis  # noqa: E402


class TriageTests(unittest.TestCase):
    def test_groups_and_counts(self):
        report = {
            "violations": [
                {"rule": "clearance", "severity": "error", "description": "a"},
                {"rule": "clearance", "severity": "error", "description": "b"},
                {"rule": "silk", "severity": "warning", "description": "c"},
            ],
            "unconnected_items": [1, 2],
            "schematic_parity": [],
        }
        out = pcb_analysis.triage_drc(report)
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["unconnected_items"], 2)
        self.assertEqual(out["groups"][0]["rule"], "clearance")
        self.assertEqual(out["groups"][0]["count"], 2)

    def test_invalid_report_rejected(self):
        with self.assertRaises(ValueError):
            pcb_analysis.triage_drc({"violations": "x"})


class BomTests(unittest.TestCase):
    def test_flags_missing_and_duplicates(self):
        rows = [
            {"Reference": "R1", "Value": "10k", "Package": "0603",
             "MPN": "M1", "LCSC": "C1", "DNP": "no"},
            {"Reference": "R1", "Value": "10k", "Package": "0603",
             "MPN": "M1", "LCSC": "C1", "DNP": "no"},
            {"Reference": "C1", "Value": "", "Package": "",
             "MPN": "", "LCSC": "", "DNP": "maybe"},
        ]
        out = pcb_analysis.audit_bom(rows)
        codes = {i["code"] for i in out["issues"]}
        self.assertIn("BOM_DUPLICATE_REFERENCE", codes)
        self.assertIn("BOM_MISSING_MPN", codes)
        self.assertIn("BOM_BAD_DNP", codes)
        self.assertTrue(out["requires"])

    def test_clean_rows(self):
        rows = [{"Reference": "R1", "Value": "10k", "Package": "0603",
                 "MPN": "M1", "LCSC": "C1", "DNP": "no"}]
        out = pcb_analysis.audit_bom(rows)
        self.assertEqual(out["issues"], [])

    def test_null_fields_are_missing_not_literal_none(self):
        rows = [{"Reference": None, "Value": None, "Package": None,
                 "MPN": None, "LCSC": None, "DNP": "no"}]
        out = pcb_analysis.audit_bom(rows)
        codes = {i["code"] for i in out["issues"]}
        self.assertIn("BOM_NO_REFERENCE", codes)
        self.assertEqual(out["counts"]["error"], 1)


class CliTests(unittest.TestCase):
    def test_same_input_output_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bom.json"
            original = json.dumps([{"Reference": "R1", "Value": "10k",
                                    "Package": "0603", "MPN": "M1",
                                    "LCSC": "C1", "DNP": "no"}])
            path.write_text(original, encoding="utf-8")
            rc = pcb_analysis.main(["--op", "audit_bom",
                                    "--input", str(path),
                                    "--json", str(path)])
            self.assertEqual(rc, 2)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_no_resource_warning(self):
        import gc
        import warnings
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "bom.json"
            out = Path(tmp) / "report.json"
            src.write_text(json.dumps([{"Reference": "R1", "Value": "10k",
                                        "Package": "0603", "MPN": "M1",
                                        "LCSC": "C1", "DNP": "no"}]),
                           encoding="utf-8")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ResourceWarning)
                pcb_analysis.main(["--op", "audit_bom",
                                   "--input", str(src), "--json", str(out)])
                gc.collect()
            self.assertFalse([w for w in caught
                              if issubclass(w.category, ResourceWarning)])


class RuleAuditTests(unittest.TestCase):
    def test_summary(self):
        report = {
            "rules": [
                {"name": "r1", "eligible": True, "severity": "error",
                 "constraints": {"clearance": "min=0.2mm"}, "condition": "A"},
                {"name": "r2", "eligible": False, "severity": "error",
                 "constraints": {}, "reasons": ["x"]},
            ],
            "findings": [
                {"code": "L007", "effect": "block"},
                {"code": "L010", "effect": "review"},
            ],
            "errors": [],
        }
        out = pcb_analysis.rule_audit(report)
        self.assertEqual(out["rule_count"], 2)
        self.assertEqual(out["eligible"], 1)
        self.assertEqual(out["block"], 1)
        self.assertEqual(out["review"], 1)
        self.assertEqual(out["findings"]["by_code"]["L007"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
