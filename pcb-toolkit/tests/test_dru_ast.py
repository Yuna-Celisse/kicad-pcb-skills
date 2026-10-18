"""dru_ast 的回归测试（M1.2）。

验收标准是**预期 AST 与错误位置**，不是"解析没抛异常"：
  - 真实夹具比对规则名、constraint、注释位置与源码位置
  - 小夹具比对归一化后的完整 AST
  - 语法错误比对 code + line:col
"""

import hashlib
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import dru_ast  # noqa: E402

FIXTURES = HERE / "fixtures" / "dru"
REAL = FIXTURES / "jxbadge_v1.kicad_dru"
REAL_SHA256 = "98fe6bc7ca3c450788f6dd1d989ca62c0e319d30cdf4e5ec9094dd901fe5b173"

EXPECTED_RULES = [
    "No acute track joins",
    "Antenna region: RF feed and tuning copper only",
    "L2 is the ground reference plane",
    "RF coplanar ground gap 0.2mm",
    "QFN fine pitch escape clearance",
]


def read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def norm(node):
    """去掉位置与 raw，便于整树比对。"""
    if node["kind"] == "atom":
        return {"kind": "atom", "value": node["value"]}
    if node["kind"] == "string":
        return {"kind": "string", "value": node["value"]}
    out = {"kind": node["kind"], "tag": node.get("tag"), "known": node.get("known")}
    if "name" in node:
        out["name"] = node["name"]
    out["items"] = [norm(c) for c in node.get("items", [])]
    return out


def parse_file(name):
    return dru_ast.parse(read(name))


class RealFixtureTests(unittest.TestCase):
    def test_fixture_integrity(self):
        digest = hashlib.sha256(REAL.read_bytes()).hexdigest()
        self.assertEqual(digest, REAL_SHA256, "夹具被改动或复制损坏")

    def test_parses_without_errors(self):
        result = parse_file(REAL.name)
        self.assertEqual(result.errors, [])

    def test_rule_names_and_order(self):
        ast = dru_ast.to_json(parse_file(REAL.name).root)
        names = [n["name"] for n in dru_ast.walk(ast) if n.get("tag") == "rule"]
        self.assertEqual(names, EXPECTED_RULES)

    def test_constraints_are_known(self):
        ast = dru_ast.to_json(parse_file(REAL.name).root)
        constraints = [n for n in dru_ast.walk(ast) if n.get("tag") == "constraint"]
        names = [c["name"] for c in constraints]
        self.assertEqual(names, ["track_angle", "disallow", "disallow",
                                 "clearance", "clearance", "hole_clearance"])
        self.assertTrue(all(c["known"] for c in constraints))

    def test_conditions_layers_and_comments(self):
        result = parse_file(REAL.name)
        ast = dru_ast.to_json(result.root)
        summary = dru_ast.summarize(ast)
        self.assertEqual(summary["conditions"], 4)
        self.assertEqual(summary["layers"], 1)
        self.assertEqual(summary["unknown"], [])
        self.assertEqual([c.line for c in result.comments], [3, 4])

    def test_source_positions(self):
        ast = dru_ast.to_json(parse_file(REAL.name).root)
        version, first_rule = ast["items"][0], ast["items"][1]
        self.assertEqual((version["line"], version["col"]), (1, 1))
        self.assertEqual((first_rule["line"], first_rule["col"]), (2, 1))
        constraint = next(item for item in first_rule["items"]
                          if item.get("tag") == "constraint")
        self.assertEqual((constraint["line"], constraint["col"]), (5, 3))


class CommentAndEscapeTests(unittest.TestCase):
    def test_exact_ast_for_comments_fixture(self):
        ast = dru_ast.to_json(parse_file("comments.kicad_dru").root)
        expected = {
            "kind": "document", "tag": "document", "known": True,
            "items": [
                {"kind": "list", "tag": "version", "known": True,
                 "items": [{"kind": "atom", "value": "version"},
                           {"kind": "atom", "value": "1"}]},
                {"kind": "list", "tag": "rule", "known": True, "name": "demo",
                 "items": [
                     {"kind": "atom", "value": "rule"},
                     {"kind": "string", "value": "demo"},
                     {"kind": "list", "tag": "constraint", "known": True,
                      "name": "clearance",
                      "items": [
                          {"kind": "atom", "value": "constraint"},
                          {"kind": "atom", "value": "clearance"},
                          {"kind": "list", "tag": "constraint_value", "known": True,
                           "name": "min",
                           "items": [{"kind": "atom", "value": "min"},
                                     {"kind": "atom", "value": "0.2mm"}]}
                      ]}
                 ]},
            ],
        }
        self.assertEqual(norm(ast), expected)

    def test_comment_positions(self):
        result = parse_file("comments.kicad_dru")
        self.assertEqual([c.line for c in result.comments], [1, 2, 4, 6, 7])
        self.assertTrue(all(c.text.startswith("#") for c in result.comments))

    def test_hash_inside_string_is_not_comment(self):
        result = parse_file("escapes.kicad_dru")
        self.assertEqual(len(result.comments), 1, "字符串内的 # 不应产生注释")
        ast = dru_ast.to_json(result.root)
        rule = ast["items"][1]
        self.assertEqual(rule["name"], 'quote " and \\ and # not comment')
        condition = [n for n in dru_ast.walk(ast) if n.get("tag") == "condition"][0]
        self.assertEqual(condition["items"][1]["value"], "A.NetName == 'X#Y'")

    def test_raw_preserves_source_text(self):
        ast = dru_ast.to_json(parse_file("escapes.kicad_dru").root)
        rule = ast["items"][1]
        self.assertIn('\\"', rule["items"][1]["raw"])


class MalformedInputTests(unittest.TestCase):
    def test_unclosed_paren_reports_opening_position(self):
        result = parse_file("unclosed_paren.kicad_dru")
        self.assertEqual(result.errors[0].code, "E_UNCLOSED")
        self.assertEqual((result.errors[0].line, result.errors[0].col), (2, 1))
        # 部分 AST 仍然可用
        self.assertIsNotNone(result.root)
        self.assertGreaterEqual(len(result.root.items), 2)

    def test_extra_close_is_reported(self):
        result = parse_file("extra_close.kicad_dru")
        self.assertEqual(result.errors[0].code, "E_UNEXPECTED_CLOSE")
        self.assertEqual((result.errors[0].line, result.errors[0].col), (2, 1))

    def test_unterminated_string_position(self):
        result = parse_file("unterminated_string.kicad_dru")
        self.assertEqual(result.errors[0].code, "E_UNTERMINATED_STRING")
        self.assertEqual((result.errors[0].line, result.errors[0].col), (1, 7))
        # 未闭合字符串后面的列表也会报未闭合
        self.assertIn("E_UNCLOSED", [e.code for e in result.errors])

    def test_cli_exit_codes(self):
        self.assertEqual(dru_ast.main([str(REAL), "--quiet"]), 0)
        self.assertEqual(
            dru_ast.main([str(FIXTURES / "unclosed_paren.kicad_dru"), "--quiet"]), 1)


class UnknownSyntaxTests(unittest.TestCase):
    def test_unknown_nodes_are_preserved_and_marked(self):
        result = parse_file("unknown_nodes.kicad_dru")
        self.assertEqual(result.errors, [])
        ast = dru_ast.to_json(result.root)

        top = [n for n in ast["items"] if n.get("tag") == "unknown"]
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0]["name"], "future_top")
        self.assertFalse(top[0]["known"])
        # 子节点没有被丢弃（items[0] 是 head atom）
        self.assertEqual(norm(top[0]["items"][1]),
                         {"kind": "list", "tag": "unparsed", "known": False,
                          "name": "thing",
                          "items": [{"kind": "atom", "value": "thing"},
                                    {"kind": "atom", "value": "1"}]})

        rule = [n for n in ast["items"] if n.get("tag") == "rule"][0]
        constraints = [n for n in rule["items"] if n.get("tag") == "constraint"]
        self.assertEqual(constraints[0]["name"], "brand_new_constraint")
        self.assertFalse(constraints[0]["known"])
        self.assertEqual(constraints[0]["items"][2]["items"][1]["value"], "1mm")

        unknown_child = [n for n in rule["items"] if n.get("tag") == "unknown"][0]
        self.assertEqual(unknown_child["name"], "weird_child")
        self.assertFalse(unknown_child["known"])

        condition = [n for n in rule["items"] if n.get("tag") == "condition"][0]
        self.assertTrue(condition["known"])


class ColumnTests(unittest.TestCase):
    def test_column_after_string(self):
        src = '(rule "x" (constraint clearance (min 0.2mm)))\n'
        ast = dru_ast.to_json(dru_ast.parse(src).root)
        rule = ast["items"][0]
        constraint = next(i for i in rule["items"] if i.get("tag") == "constraint")
        self.assertEqual((constraint["line"], constraint["col"]), (1, 11))

    def test_second_string_column(self):
        ast = dru_ast.to_json(dru_ast.parse('(rule "a" "b")').root)
        items = ast["items"][0]["items"]
        self.assertEqual(items[1]["col"], 7)
        self.assertEqual(items[2]["col"], 11)

    def test_error_column_after_string(self):
        result = dru_ast.parse('(rule "x") )')
        self.assertEqual(result.errors[0].code, "E_UNEXPECTED_CLOSE")
        self.assertEqual((result.errors[0].line, result.errors[0].col), (1, 12))


class UnknownSubtreeTests(unittest.TestCase):
    def test_unknown_constraint_child_is_marked_unknown(self):
        result = parse_file("unknown_constraint_child.kicad_dru")
        self.assertEqual(result.errors, [])
        ast = dru_ast.to_json(result.root)
        rule = ast["items"][1]
        constraint = next(i for i in rule["items"] if i.get("tag") == "constraint")
        self.assertTrue(constraint["known"])          # clearance 本身已知
        child = constraint["items"][2]
        self.assertEqual(child["tag"], "unknown")
        self.assertFalse(child["known"])
        self.assertEqual(child["name"], "future_value")
        self.assertTrue(dru_ast.summarize(ast)["unknown"])

    def test_rules_inside_unknown_container_are_not_counted(self):
        result = parse_file("hidden_rule.kicad_dru")
        self.assertEqual(result.errors, [])
        ast = dru_ast.to_json(result.root)
        summary = dru_ast.summarize(ast)
        self.assertEqual(summary["rules"], [], "未知容器内的 rule 不得计入规则")
        self.assertEqual(summary["constraints"], [])
        hidden = [n for n in dru_ast.walk(ast) if n.get("name") == "hidden"][0]
        self.assertEqual(hidden["tag"], "unparsed")
        self.assertFalse(hidden["known"])
        self.assertTrue(any(u["tag"] == "unparsed" for u in summary["unknown"]))


class DepthTests(unittest.TestCase):
    def test_deep_nesting_is_bounded(self):
        src = "(" * (dru_ast.MAX_DEPTH + 5) + ")" * (dru_ast.MAX_DEPTH + 5)
        result = dru_ast.parse(src)
        self.assertIn("E_DEPTH", [e.code for e in result.errors])


if __name__ == "__main__":
    unittest.main(verbosity=2)
