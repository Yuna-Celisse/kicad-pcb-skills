"""技能入口与 gate.py 契约的一致性回归（M1.6）。

只检查文档仍然指向真实存在的脚本与字段，防止 SKILL.md 与实现对漂移。
"""

import csv
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # skills/
SCRIPTS = ROOT / "pcb-toolkit" / "scripts"
VENDOR = ROOT / "pcb-toolkit" / "tests" / "vendor"
if VENDOR.is_dir():
    sys.path.insert(0, str(VENDOR))
try:
    from jsonschema import Draft202012Validator, FormatChecker
    HAVE_JSONSCHEMA = True
except ImportError:  # pragma: no cover
    HAVE_JSONSCHEMA = False

sys.path.insert(0, str(SCRIPTS))
import validate_intent as vi  # noqa: E402


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class SkillEntryTests(unittest.TestCase):
    def test_flow_skill_calls_gate_and_preserves_output(self):
        text = read(ROOT / "pcb-flow" / "SKILL.md")
        self.assertIn("gate.py", text)
        for field in ("verdict", "evidence", "counts",
                      "waivers_applied", "waivers_rejected", "reasons"):
            self.assertIn(field, text, field)
        self.assertIn("不得", text)
        # 入口必须存在
        self.assertTrue((SCRIPTS / "gate.py").is_file())

    def test_verification_skill_calls_gate(self):
        text = read(ROOT / "pcb-verification" / "SKILL.md")
        self.assertIn("gate.py", text)
        self.assertIn("--phase", text)
        self.assertIn("--json", text)
        for tool in ("run_drc", "pcb_overlap.py", "lint_dru.py", "gen_dru.py"):
            self.assertIn(tool, text, tool)

    def test_evidence_contract_documents_gate_fields(self):
        text = read(ROOT / "pcb-verification" / "references" / "evidence-contract.md")
        for field in ("assumptions_open", "assumptions_due",
                      "missing_checks", "waivers_rejected",
                      "verdict", "counts", "evidence"):
            self.assertIn(field, text, field)
        # 文档中的阶段表必须覆盖 gate 的实现
        for phase in ("P6", "P8", "P9"):
            self.assertIn(phase, text, phase)

    def test_assumption_example_validates(self):
        text = read(ROOT / "pcb-flow" / "SKILL.md")
        blocks = re.findall(r"```json\n(.*?)```", text, re.S)
        example = None
        for block in blocks:
            try:
                data = json.loads(block)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and isinstance(data.get("assumptions"), dict):
                example = data
                break
        self.assertIsNotNone(example, "SKILL.md 缺少 assumptions JSON 示例")

        from tests.test_gate import base_intent
        intent = base_intent()
        intent["assumptions"] = example["assumptions"]
        report = vi.validate(intent)
        errors = [i for i in report.issues if i.severity == "error"]
        self.assertEqual(errors, [])

    def test_ignore_rule_semantics_documented(self):
        text = read(ROOT / "pcb-verification" / "SKILL.md")
        self.assertIn("仍参与匹配", text)
        self.assertIn("L008", text)
        self.assertNotIn("不进入有效规则集", text)

    def test_contract_requires_drc_counts(self):
        text = read(ROOT / "pcb-verification" / "references" / "evidence-contract.md")
        self.assertIn("**必需**（完整报告）", text)
        self.assertIn("truncated", text)


class ContentTests(unittest.TestCase):
    def test_tj_uses_absolute_margin_not_celsius_ratio(self):
        text = read(ROOT / "pcb-components" / "references" / "derating-and-margins.md")
        self.assertNotIn("0.8 × Tj_max", text)
        self.assertIn("K", text)
        self.assertIn("55 K", text)

    def test_buck_hot_loop_excludes_inductor(self):
        text = read(ROOT / "pcb-schematic" / "references" / "circuit-blocks.md")
        self.assertIn("低侧开关", text)
        self.assertNotIn("Vin—高侧—电感—GND", text)

    def test_thermal_pad_potential_must_be_confirmed(self):
        text = read(ROOT / "pcb-components" / "references" / "package-and-assembly.md")
        self.assertIn("负电源", text)
        self.assertIn("按手册确认电位", text)

    def test_input_not_driven_does_not_use_pwr_flag(self):
        text = read(ROOT / "pcb-schematic" / "references" / "erc-adjudication.md")
        self.assertIn("普通信号不能用 `PWR_FLAG`", text)

    def test_ledger_codes_match_gate_normalization(self):
        text = read(ROOT / "pcb-schematic" / "assets" / "erc-waiver-ledger.md")
        self.assertIn("ERC_power_pin_not_driven", text)
        self.assertIn("不要手写", text)
        self.assertNotIn("`power_pin_not_driven` | `VCC_3V3", text)

    def test_bom_example_values_are_consistent(self):
        path = ROOT / "pcb-components" / "assets" / "bom-review.template.csv"
        with path.open(newline="", encoding="utf-8") as fh:
            rows = {r["Reference"]: r for r in csv.DictReader(fh)}
        c2 = rows["C2"]
        self.assertEqual(c2["MPN"], "CL10A106KP8NNNC")
        self.assertEqual(c2["LCSC"], "C19702")
        self.assertEqual(c2["Voltage"], "10V")
        self.assertEqual(c2["Tolerance"], "10%")

    def test_stackup_thickness_sums(self):
        text = read(ROOT / "pcb-layout" / "assets" / "stackup-presets.md")
        match = re.search(r"4×0\.035 \+ 2×0\.20 \+ ([\d.]+) = ([\d.]+)mm", text)
        self.assertIsNotNone(match, "缺少叠层求和校验行")
        core, total = float(match.group(1)), float(match.group(2))
        self.assertAlmostEqual(4 * 0.035 + 2 * 0.20 + core, total, places=2)

    def test_netclass_multi_membership_documented(self):
        text = read(ROOT / "pcb-routing" / "references" / "netclass-strategy.md")
        self.assertIn("多个", text)
        self.assertNotIn("只属于一个", text)

    def test_thermal_distinguishes_theta_jc_and_psi_jt(self):
        text = read(ROOT / "pcb-layout" / "references" / "thermal.md")
        self.assertIn("ΨJT", text)
        self.assertIn("θJC", text)
        self.assertIn("不能把总功耗直接代入", text)

    def test_reference_change_is_not_always_ground_via(self):
        text = read(ROOT / "pcb-routing" / "references" / "return-path.md")
        self.assertIn("GND→PWR", text)
        self.assertIn("单个地孔不能连通", text)

    def test_pour_has_stages_not_absolute(self):
        text = read(ROOT / "pcb-routing" / "references" / "pour-and-via.md")
        self.assertIn("最终验收", text)
        self.assertIn("参考平面", text)
        self.assertNotIn("不要先铺铜", text)

    def test_length_matching_near_mismatch(self):
        text = read(ROOT / "pcb-routing" / "references" / "differential-and-length.md")
        self.assertIn("失配产生处", text)
        self.assertNotIn("接收端**附近补偿", text)

    def test_no_stale_ground_via_or_pour_last_shortcuts(self):
        paths = [
            ROOT / "pcb-routing" / "SKILL.md",
            ROOT / "pcb-routing" / "references" / "impedance.md",
            ROOT / "pcb-routing" / "references" / "return-path.md",
            ROOT / "pcb-routing" / "references" / "pour-and-via.md",
            ROOT / "pcb-routing" / "references" / "differential-and-length.md",
        ]
        forbidden = ["旁边放地过孔", "地平面/铺铜最后统一", "铺铜最后做",
                     "能换层就换层并加回流地孔", "靠地过孔/缝合孔连续",
                     "铺铜是否最后做"]
        for path in paths:
            text = read(path)
            for phrase in forbidden:
                self.assertNotIn(phrase, text, f"{path.name}: {phrase}")

    def test_routing_index_covers_three_reference_cases(self):
        text = read(ROOT / "pcb-routing" / "SKILL.md")
        for token in ("同参考", "换电位", "隔离边界"):
            self.assertIn(token, text, token)

    def test_fab_profile_schema_validates_sample(self):
        if not HAVE_JSONSCHEMA:
            self.skipTest("jsonschema 不可用")
        schema = json.loads(read(ROOT / "pcb-manufacturing" / "assets"
                                 / "fab-profile.schema.json"))
        validator = Draft202012Validator(schema,
                                         format_checker=FormatChecker())
        sample = {
            "id": "jlcpcb-4l", "fab": "JLCPCB",
            "url": "https://jlcpcb.com/capabilities/pcb-capabilities",
            "retrieved": "2026-10-19", "layers": [4, 6],
            "min_trace_mm": 0.127, "min_space_mm": 0.127,
            "min_pth_hole_mm": 0.2, "min_npth_hole_mm": 0.5,
            "annular_ring_mm": 0.13, "board_edge_mm": 0.3,
            "silk_min_text_mm": 0.8, "silk_min_line_mm": 0.15,
            "finishes": ["HASL", "ENIG"],
        }
        validator.validate(sample)

        invalid = []
        bad_url = dict(sample, url="https://")
        invalid.append(bad_url)
        bad_date = dict(sample, retrieved="2026-99-99")
        invalid.append(bad_date)
        missing_silk = dict(sample)
        missing_silk.pop("silk_min_text_mm")
        invalid.append(missing_silk)
        missing_finish = dict(sample)
        missing_finish.pop("finishes")
        invalid.append(missing_finish)
        for broken in invalid:
            with self.assertRaises(Exception):
                validator.validate(broken)

    def test_mount_script_is_safe_and_idempotent(self):
        text = read(ROOT / "mount-skills.ps1")
        for token in ("-Apply", "DRY RUN",
                      "New-Item -ItemType Junction",
                      "refusing to overwrite", "skip"):
            self.assertIn(token, text, token)
        for name in ("pcb-flow", "pcb-schematic", "pcb-components",
                     "pcb-layout", "pcb-routing", "pcb-verification",
                     "pcb-manufacturing", "pcb-toolkit"):
            self.assertIn(f"'{name}'", text, name)

    def test_output_manifest_template_sections(self):
        text = read(ROOT / "pcb-manufacturing" / "assets"
                    / "output-manifest.template.md")
        for section in ("文件清单", "叠层与阻抗", "EQ / 偏差", "自检"):
            self.assertIn(section, text, section)

    def test_output_package_lists_all_copper_layers(self):
        text = read(ROOT / "pcb-manufacturing" / "references"
                    / "output-package.md")
        for layer in ("F_Cu", "In1_Cu", "In2_Cu", "B_Cu"):
            self.assertIn(f"{layer}.gbr", text, layer)
        self.assertIn("4 层 = `F_Cu + In1_Cu + In2_Cu + B_Cu`", text)

    def test_hole_capability_distinguishes_types(self):
        dfm = read(ROOT / "pcb-manufacturing" / "references" / "dfm-matrix.md")
        for token in ("PTH 插件孔", "NPTH 成品孔径", "边到边"):
            self.assertIn(token, dfm, token)
        skill = read(ROOT / "pcb-manufacturing" / "SKILL.md")
        self.assertIn("不得套用 PTH", skill)


class StructureTests(unittest.TestCase):
    def test_skills_have_required_sections(self):
        for name in ("pcb-schematic", "pcb-components",
                     "pcb-layout", "pcb-routing", "pcb-manufacturing"):
            text = read(ROOT / name / "SKILL.md")
            for section in ("## 何时用 / 何时不用", "## 前置条件",
                            "## 反模式", "## 完成判据", "## 参考与来源"):
                self.assertIn(section, text, f"{name}: {section}")

    def test_all_local_links_resolve(self):
        bad = []
        for folder in ("pcb-flow", "pcb-verification", "pcb-schematic",
                       "pcb-components", "pcb-layout", "pcb-routing",
                       "pcb-manufacturing"):
            for md in (ROOT / folder).rglob("*.md"):
                text = read(md)
                for target in re.findall(r"\]\(([^)]+)\)", text):
                    if target.startswith(("http://", "https://", "#", "mailto:")):
                        continue
                    path = (md.parent / target.split("#")[0]).resolve()
                    if not path.exists():
                        bad.append(f"{md.name} -> {target}")
        root = ROOT / "README.md"
        text = read(root)
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            path = (root.parent / target.split("#")[0]).resolve()
            if not path.exists():
                bad.append(f"README.md -> {target}")
        self.assertEqual(bad, [])

    def test_netclass_presets_parse(self):
        path = (ROOT / "pcb-routing" / "assets" / "netclass-presets.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        names = set()
        for cls in data["classes"]:
            for key in ("name", "width_mm", "clearance_mm", "via_mm"):
                self.assertIn(key, cls)
            self.assertGreater(cls["width_mm"], 0)
            self.assertEqual(len(cls["via_mm"]), 2)
            names.add(cls["name"])
            if "diff_impedance_ohm" in cls:
                self.assertIn("gap_mm", cls)
        self.assertEqual(len(names), len(data["classes"]))

    def test_routing_formulas_present(self):
        current = read(ROOT / "pcb-routing" / "references" / "current-and-width.md")
        for token in ("0.048", "0.024", "0.725", "ΔT"):
            self.assertIn(token, current, token)
        impedance = read(ROOT / "pcb-routing" / "references" / "impedance.md")
        for token in ("87", "60", "sqrt", "εr"):
            self.assertIn(token, impedance, token)

    def test_bom_template_parses(self):
        path = ROOT / "pcb-components" / "assets" / "bom-review.template.csv"
        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertTrue(rows, "BOM 模板为空")
        for column in ("Reference", "Value", "MPN", "LCSC",
                       "Package", "DNP"):
            self.assertIn(column, rows[0])

    def test_m2_skills_point_at_real_tools(self):
        schematic = read(ROOT / "pcb-schematic" / "SKILL.md")
        self.assertIn("pcb_overlap.py", schematic)
        components = read(ROOT / "pcb-components" / "SKILL.md")
        for tool in ("search_jlcpcb_parts", "check_bom_health",
                     "suggest_jlcpcb_alternatives"):
            self.assertIn(tool, components, tool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
