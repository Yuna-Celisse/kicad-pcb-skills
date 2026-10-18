"""Schema 与 validator 的共享夹具测试。

每个 case_*.json 都带 `expect: {schema, codes}`，两边**分别**断言同一预期：
  - JSON Schema 断言结构是否合法
  - validate_intent 断言诊断码
只断言"两边结果相同"会让它们一起接受错误输入。
"""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))
VENDOR = HERE / "vendor"
if VENDOR.is_dir():
    sys.path.insert(0, str(VENDOR))

import validate_intent as vi  # noqa: E402

try:
    import jsonschema
    from jsonschema import Draft202012Validator
    HAVE_JSONSCHEMA = True
except ImportError:  # pragma: no cover - 环境缺库时跳过结构侧
    HAVE_JSONSCHEMA = False

SCHEMA_PATH = ROOT.parent / "pcb-flow" / "assets" / "design-intent.schema.json"
CASES_DIR = HERE / "fixtures" / "intent"


def load_cases():
    cases = []
    for path in sorted(CASES_DIR.glob("case_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cases.append((path.name, data))
    return cases


@unittest.skipUnless(HAVE_JSONSCHEMA, "需要 jsonschema（可 pip install --target tests/vendor jsonschema）")
class SchemaFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def test_schema_itself_is_valid(self):
        Draft202012Validator.check_schema(self.schema)

    def test_schema_matches_expectation(self):
        for name, case in load_cases():
            with self.subTest(case=name):
                errors = list(self.validator.iter_errors(case["intent"]))
                self.assertEqual(not errors, case["expect"]["schema"],
                                 f"{name}: {[e.message for e in errors]}")


class FixtureContractTests(unittest.TestCase):
    """不依赖 jsonschema：夹具与 validator 的契约必须始终可跑。"""

    def test_cases_exist(self):
        self.assertGreaterEqual(len(load_cases()), 9)

    def test_validator_matches_expectation(self):
        for name, case in load_cases():
            with self.subTest(case=name):
                found = {i.code for i in vi.validate(case["intent"]).issues}
                for code in case["expect"]["codes"]:
                    self.assertIn(code, found, f"{name}: 实际 {sorted(found)}")
                if not case["expect"]["codes"]:
                    self.assertEqual(found, set(), f"{name}: {sorted(found)}")

    def test_all_cases_load_and_validate_without_crashing(self):
        for name, case in load_cases():
            with self.subTest(case=name):
                report = vi.validate(case["intent"])
                self.assertNotIn("E099", {i.code for i in report.issues})


if __name__ == "__main__":
    unittest.main(verbosity=2)
