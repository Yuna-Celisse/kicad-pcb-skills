"""dru_condition / lint_dru 的回归测试（M1.3）。

判定口径：包含关系 True / False / None 三值；None 不得当作 False。
lint 只对 eligible 规则做确定性推断，未理解规则一律 L009/review。
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import dru_ast  # noqa: E402
import dru_condition as dc  # noqa: E402
import lint_dru  # noqa: E402


def cond(src):
    return dc.parse_condition(src)


def lint_text(src):
    parsed = dru_ast.parse(src)
    ast = dru_ast.to_json(parsed.root)
    rules = lint_dru.extract_rules(ast)
    top_unknown = [n for n in ast.get("items", [])
                   if isinstance(n, dict) and n.get("tag") in ("unknown", "unparsed")]
    return lint_dru.lint(rules, top_unknown)


def codes(findings, rule=None, constraint=None):
    out = []
    for f in findings:
        if rule is not None and f["rule"] != rule:
            continue
        if constraint is not None and f["constraint"] != constraint:
            continue
        out.append(f["code"])
    return out


class ConditionParseTests(unittest.TestCase):
    def test_standalone_call_is_predicate(self):
        node = cond("A.intersectsArea('X')")
        self.assertEqual(node["t"], "call")

    def test_and_or_precedence(self):
        node = cond("A.X == 'a' || A.Y == 'b' && A.Z == 'c'")
        self.assertEqual(node["t"], "or")
        self.assertEqual(node["items"][1]["t"], "and")

    def test_negated_comparison_is_flipped(self):
        node = cond("!(A.NetName == 'GND')")
        self.assertEqual(node["t"], "cmp")
        self.assertEqual(node["op"], "!=")

    def test_bad_expression_raises_with_offset(self):
        with self.assertRaises(dc.ConditionError) as ctx:
            cond("A.NetClass ==")
        self.assertGreaterEqual(ctx.exception.offset, 0)


class ImplicationTests(unittest.TestCase):
    def test_identical(self):
        a = cond("A.NetClass == 'P'")
        self.assertTrue(dc.implies(a, cond("A.NetClass == 'P'")))

    def test_different_netclass_is_unknown(self):
        # 一个网络可同时属于多个 netclass，不能证明互斥
        self.assertIsNone(dc.implies(cond("A.NetClass == 'P'"),
                                     cond("A.NetClass == 'Q'")))
        self.assertIsNone(dc.implies(cond("A.NetClass == 'P'"),
                                     cond("A.NetClass != 'Q'")))

    def test_conjunction_implies_conjunct(self):
        self.assertTrue(dc.implies(
            cond("A.NetClass == 'P' && A.NetName == 'X'"),
            cond("A.NetClass == 'P'")))

    def test_conjunct_does_not_imply_conjunction(self):
        self.assertFalse(dc.implies(
            cond("A.NetClass == 'P'"),
            cond("A.NetClass == 'P' && A.NetName == 'X'")))

    def test_ne_does_not_imply_other_ne(self):
        self.assertFalse(dc.implies(cond("A.NetName != 'A'"),
                                    cond("A.NetName != 'B'")))

    def test_ne_implies_same_ne(self):
        self.assertTrue(dc.implies(cond("A.NetName != 'A'"),
                                   cond("A.NetName != 'A'")))

    def test_numeric_interval(self):
        self.assertTrue(dc.implies(cond("A.Width >= 0.2"),
                                   cond("A.Width >= 0.15")))
        self.assertFalse(dc.implies(cond("A.Width >= 0.15"),
                                    cond("A.Width >= 0.2")))

    def test_inclusive_boundary(self):
        self.assertTrue(dc.implies(cond("A.Width > 0.2"),
                                   cond("A.Width >= 0.2")))
        self.assertFalse(dc.implies(cond("A.Width >= 0.2"),
                                    cond("A.Width > 0.2")))

    def test_unknown_call_relation_is_none(self):
        self.assertIsNone(dc.implies(cond("A.intersectsArea('X')"),
                                     cond("A.intersectsArea('Y')")))

    def test_or_requires_all_disjuncts(self):
        a = cond("A.X == 'a' || A.X == 'b'")
        self.assertTrue(dc.implies(a, a))
        self.assertIsNone(dc.implies(a, cond("A.X == 'a'")))

    def test_disjoint(self):
        self.assertIsNone(dc.falsey(cond("A.NetClass == 'P'"),
                                    cond("A.NetClass == 'Q'")))
        self.assertFalse(dc.falsey(cond("A.NetClass == 'P'"),
                                   cond("A.NetClass == 'P'")))

    def test_multiple_netclass_membership_is_not_exclusive(self):
        power = cond("A.NetClass == 'Power'")
        hs = cond("A.NetClass == 'HS'")
        self.assertIsNone(dc.implies(power, cond("A.NetClass != 'HS'")))
        self.assertIsNone(dc.falsey(power, hs))
        # 非 NetClass 的标量属性仍可判定互斥
        self.assertTrue(dc.falsey(cond("A.Layer == 'F.Cu'"),
                                  cond("A.Layer == 'B.Cu'")))

    def test_falsey_does_not_infer_from_property_ast(self):
        self.assertIsNone(dc.falsey(cond("A.NetName == B.NetName"),
                                    cond("A.NetName == B.NetClass")))

    def test_partial_overlap_is_not_disjoint(self):
        self.assertFalse(dc.falsey(cond("A.Width >= 0.15"),
                                   cond("A.Width <= 0.2")))


class LintOrderingTests(unittest.TestCase):
    def test_exact_duplicate_is_L004(self):
        text = """
(rule "A" (condition "A.NetClass == 'P'") (constraint clearance (min 0.2mm)))
(rule "B" (condition "A.NetClass == 'P'") (constraint clearance (min 0.2mm)))
"""
        findings = lint_text(text)
        self.assertIn("L004", codes(findings, rule="A"))
        self.assertIn("L005", codes(findings, rule="A"))

    def test_conflicting_values_is_L006(self):
        text = """
(rule "A" (condition "A.NetClass == 'P'") (constraint clearance (min 0.2mm)))
(rule "B" (condition "A.NetClass == 'P'") (constraint clearance (min 0.15mm)))
"""
        findings = lint_text(text)
        self.assertIn("L006", codes(findings, rule="A"))

    def test_specific_written_first_is_L007(self):
        text = """
(rule "specific" (condition "A.NetClass == 'P' && A.NetName == 'X'")
  (constraint clearance (min 0.2mm)))
(rule "broad" (condition "A.NetClass == 'P'")
  (constraint clearance (min 0.2mm)))
"""
        findings = lint_text(text)
        self.assertEqual(set(codes(findings, rule="specific")), {"L007", "L005"})

    def test_broad_written_first_is_clean(self):
        text = """
(rule "broad" (condition "A.NetClass == 'P'")
  (constraint clearance (min 0.2mm)))
(rule "specific" (condition "A.NetClass == 'P' && A.NetName == 'X'")
  (constraint clearance (min 0.2mm)))
"""
        self.assertEqual(lint_text(text), [])

    def test_partial_shadow_only_marks_one_constraint(self):
        text = """
(rule "A" (condition "A.NetClass == 'P'")
  (constraint clearance (min 0.2mm))
  (constraint track_width (min 0.2mm)))
(rule "B" (condition "A.NetClass == 'P'") (constraint clearance (min 0.2mm)))
"""
        findings = lint_text(text)
        self.assertEqual(codes(findings, rule="A", constraint="clearance"), ["L004"])
        self.assertEqual(codes(findings, rule="A", constraint="track_width"), [])
        self.assertNotIn("L005", codes(findings, rule="A"))

    def test_ignore_blocker_is_L008(self):
        text = """
(rule "victim" (condition "A.NetClass == 'P'") (constraint clearance (min 0.2mm)))
(rule "blocker" (severity ignore) (condition "A.NetClass == 'P'")
  (constraint clearance (min 0.2mm)))
"""
        findings = lint_text(text)
        self.assertIn("L008", codes(findings, rule="victim"))

    def test_layer_rule_shadowed_by_later_broad_rule(self):
        text = """
(rule "on-layer" (layer "F.Cu") (condition "A.NetClass == 'P'")
  (constraint clearance (min 0.2mm)))
(rule "all-layers" (condition "A.NetClass == 'P'")
  (constraint clearance (min 0.2mm)))
"""
        findings = lint_text(text)
        self.assertIn("L007", codes(findings, rule="on-layer"))

    def test_unknown_rule_between_known_blocks_inference(self):
        text = """
(rule "first" (condition "A.NetClass == 'P'") (constraint clearance (min 0.2mm)))
(rule "mystery" (condition "A.NetClass == 'P'")
  (constraint future_constraint (min 1mm)))
(rule "last" (condition "A.NetClass == 'P'") (constraint clearance (min 0.2mm)))
"""
        findings = lint_text(text)
        self.assertIn("L009", codes(findings, rule="mystery"))
        # 只有排在未知规则之后（求值顺序更晚）的规则才失去确定性
        self.assertIn("L009", codes(findings, rule="first"))
        self.assertNotIn("L004", codes(findings, rule="first"))
        self.assertNotIn("L005", codes(findings, rule="first"))
        # 求值顺序更早的 last 不受影响
        self.assertEqual(codes(findings, rule="last"), [])

    def test_unparsable_condition_is_L009(self):
        text = """
(rule "bad" (condition "A.NetClass ==") (constraint clearance (min 0.2mm)))
"""
        findings = lint_text(text)
        self.assertEqual(codes(findings, rule="bad"), ["L009"])


class PropertyComparisonTests(unittest.TestCase):
    def test_property_inequality_is_not_inferred(self):
        a = cond("A.NetName == B.NetName")
        b = cond("A.NetName != B.NetClass")
        self.assertIsNone(dc.implies(a, b))

    def test_same_expression_complements(self):
        self.assertFalse(dc.implies(cond("A.NetName == B.NetName"),
                                    cond("A.NetName != B.NetName")))

    def test_lint_does_not_block_on_unknown_property_relation(self):
        text = """
(rule "A" (condition "A.NetName == B.NetName") (constraint clearance (min 0.2mm)))
(rule "B" (condition "A.NetName != B.NetClass") (constraint clearance (min 0.15mm)))
"""
        findings = lint_text(text)
        self.assertNotIn("L007", codes(findings))
        self.assertNotIn("L005", codes(findings))
        self.assertIn("L010", codes(findings))


class EligibilityTests(unittest.TestCase):
    def rules_of(self, src):
        ast = dru_ast.to_json(dru_ast.parse(src).root)
        return {r.name: r for r in lint_dru.extract_rules(ast)}

    def test_nested_unknown_constraint_value(self):
        rule = self.rules_of(
            '(rule "x" (constraint clearance (min (future 1))))')["x"]
        self.assertFalse(rule.eligible)

    def test_condition_must_be_string(self):
        rule = self.rules_of(
            '(rule "x" (condition (future 1)) (constraint clearance (min 0.2mm)))')["x"]
        self.assertFalse(rule.eligible)
        self.assertIsNone(rule.condition_text)

    def test_unknown_severity(self):
        rule = self.rules_of(
            '(rule "x" (severity future) (constraint clearance (min 0.2mm)))')["x"]
        self.assertFalse(rule.eligible)


class UnknownRelationTests(unittest.TestCase):
    def test_unknown_relation_with_different_values_is_review(self):
        text = """
(rule "A" (condition "A.intersectsArea('X')") (constraint clearance (min 0.2mm)))
(rule "B" (condition "A.intersectsArea('Y')") (constraint clearance (min 0.15mm)))
"""
        findings = lint_text(text)
        self.assertEqual([f["code"] for f in findings], ["L010"])
        self.assertEqual(findings[0]["effect"], "review")

    def test_top_level_unknown_subtree_is_reported(self):
        text = """(version 1)
(future (rule "hidden" (constraint clearance (min 1mm))))
"""
        findings = lint_text(text)
        self.assertTrue(any(f["code"] == "L009" for f in findings))

    def test_property_conditions_with_different_values_are_reviewed(self):
        text = """
(rule "A" (condition "A.NetName == B.NetName") (constraint clearance (min 0.2mm)))
(rule "B" (condition "A.NetName == B.NetClass") (constraint clearance (min 0.15mm)))
"""
        findings = lint_text(text)
        self.assertEqual([f["code"] for f in findings], ["L010"])
        self.assertEqual(findings[0]["effect"], "review")

    def test_partial_overlap_is_reviewed(self):
        text = """
(rule "A" (condition "A.Width >= 0.15") (constraint clearance (min 0.2mm)))
(rule "B" (condition "A.Width <= 0.2") (constraint clearance (min 0.15mm)))
"""
        findings = lint_text(text)
        self.assertEqual([f["code"] for f in findings], ["L010"])


class BooleanConstantTests(unittest.TestCase):
    def test_boolean_literals(self):
        self.assertEqual(cond("false"), {"t": "false"})
        self.assertEqual(cond("true"), {"t": "true"})

    def test_true_does_not_imply_unproven_tautology(self):
        rhs = cond("A.NetName == 'X' || A.NetName != 'X'")
        self.assertIsNone(dc.implies({"t": "true"}, rhs))


class SyntaxErrorExitTests(unittest.TestCase):
    def test_syntax_error_aborts_analysis_and_exits_2(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.kicad_dru"
            p.write_text('(rule "x" (constraint clearance (min 0.2mm))\n',
                         encoding="utf-8")
            self.assertEqual(lint_dru.main([str(p), "--quiet"]), 2)
            report = lint_dru.analyze(p)
            self.assertTrue(report["summary"]["aborted"])
            self.assertEqual(report["findings"], [])


class RealFixtureLintTests(unittest.TestCase):
    def test_real_fixture_has_no_block(self):
        path = HERE / "fixtures" / "dru" / "jxbadge_v1.kicad_dru"
        report = lint_dru.analyze(path)
        self.assertEqual(report["summary"]["rules"], 5)
        self.assertEqual(report["summary"]["eligible"], 5)
        self.assertEqual(report["summary"]["block"], 0)
        # 两条 clearance 规则条件关系不可判定且取值不同 -> 保守 review
        self.assertEqual([f["code"] for f in report["findings"]], ["L010"])
        self.assertEqual(report["findings"][0]["effect"], "review")


if __name__ == "__main__":
    unittest.main(verbosity=2)
