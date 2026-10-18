"""pcb_calc 的回归测试（M5）。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import pcb_calc  # noqa: E402


class TraceWidthTests(unittest.TestCase):
    def test_3a_10c_1oz_outer(self):
        out = pcb_calc.trace_width({"current_a": 3, "delta_t_c": 10,
                                    "copper_oz": 1, "layer": "external"})
        self.assertAlmostEqual(out["width_mm"], 1.375, places=2)

    def test_inner_is_wider(self):
        outer = pcb_calc.trace_width({"current_a": 3, "delta_t_c": 10,
                                      "layer": "external"})
        inner = pcb_calc.trace_width({"current_a": 3, "delta_t_c": 10,
                                      "layer": "internal"})
        self.assertGreater(inner["width_mm"], outer["width_mm"] * 2)

    def test_invalid_layer_rejected(self):
        with self.assertRaises(ValueError):
            pcb_calc.trace_width({"current_a": 1, "delta_t_c": 10,
                                  "layer": "top"})

    def test_negative_current_rejected(self):
        with self.assertRaises(ValueError):
            pcb_calc.trace_width({"current_a": -1, "delta_t_c": 10})


class ViaTests(unittest.TestCase):
    def test_03mm_via(self):
        out = pcb_calc.via_current({"drill_mm": 0.3, "plating_um": 25,
                                    "delta_t_c": 10})
        self.assertAlmostEqual(out["current_a"], 0.842, places=2)
        self.assertAlmostEqual(out["finished_hole_mm"], 0.25, places=3)

    def test_thicker_plating_carries_more_but_shrinks_hole(self):
        a = pcb_calc.via_current({"drill_mm": 0.3, "plating_um": 25})
        b = pcb_calc.via_current({"drill_mm": 0.3, "plating_um": 50})
        self.assertGreater(b["current_a"], a["current_a"])
        self.assertLess(b["finished_hole_mm"], a["finished_hole_mm"])

    def test_plating_larger_than_radius_rejected(self):
        with self.assertRaises(ValueError):
            pcb_calc.via_current({"drill_mm": 0.05, "plating_um": 30})


class ImpedanceTests(unittest.TestCase):
    def test_microstrip_example(self):
        out = pcb_calc.impedance({"kind": "microstrip", "er": 4.3,
                                  "h_mm": 0.2, "w_mm": 0.35,
                                  "t_mm": 0.035})
        self.assertAlmostEqual(out["z0_ohm"], 48.57, places=1)

    def test_stripline_positive(self):
        out = pcb_calc.impedance({"kind": "stripline", "er": 4.3,
                                  "h_mm": 0.2, "b_mm": 1.0,
                                  "w_mm": 0.2, "t_mm": 0.035})
        self.assertGreater(out["z0_ohm"], 0)

    def test_differential_less_than_twice_single(self):
        out = pcb_calc.impedance({"kind": "differential_microstrip",
                                  "er": 4.3, "h_mm": 0.2, "w_mm": 0.2,
                                  "t_mm": 0.035, "s_mm": 0.15})
        self.assertLess(out["zdiff_ohm"], 2 * out["z0_ohm"])

    def test_bad_w_h_warns(self):
        out = pcb_calc.impedance({"kind": "microstrip", "er": 4.3,
                                  "h_mm": 1.0, "w_mm": 0.05,
                                  "t_mm": 0.035})
        self.assertTrue(any("w/h" in w for w in out["warnings"]))

    def test_geometry_outside_formula_rejected(self):
        with self.assertRaises(ValueError):
            pcb_calc.impedance({"kind": "microstrip", "er": 4.3,
                                "h_mm": 0.1, "w_mm": 2.0,
                                "t_mm": 0.035})


class StackupTests(unittest.TestCase):
    def test_sum_and_target(self):
        out = pcb_calc.stackup({"layers": [
            {"name": "core", "thickness_mm": 1.0},
            {"name": "pp", "thickness_mm": 0.6}], "target_mm": 1.6})
        self.assertAlmostEqual(out["total_mm"], 1.6, places=3)
        self.assertEqual(out["delta_mm"], 0)

    def test_off_target_warns(self):
        out = pcb_calc.stackup({"layers": [
            {"thickness_mm": 1.0}], "target_mm": 1.6})
        self.assertTrue(out["warnings"])

    def test_empty_layers_rejected(self):
        with self.assertRaises(ValueError):
            pcb_calc.stackup({"layers": []})


class CircuitTests(unittest.TestCase):
    def test_divider(self):
        out = pcb_calc.circuit({"op": "divider", "vin": 5,
                                "r1": 10000, "r2": 10000})
        self.assertAlmostEqual(out["vout"], 2.5)

    def test_led_resistor(self):
        out = pcb_calc.circuit({"op": "led_resistor", "vs": 5,
                                "vf": 2, "if_a": 0.01})
        self.assertAlmostEqual(out["r_ohm"], 300.0)

    def test_i2c_pullup_range(self):
        out = pcb_calc.circuit({"op": "i2c_pullup", "vcc": 3.3,
                                "vol": 0.4, "iol_a": 0.003,
                                "cbus_pf": 200, "tr_ns": 300})
        self.assertLess(out["r_min_ohm"], out["r_max_ohm"])

    def test_crystal_load(self):
        out = pcb_calc.circuit({"op": "crystal_load", "cl_pf": 12,
                                "cstray_pf": 4})
        self.assertAlmostEqual(out["c_pf"], 16.0)

    def test_tiny_current_keeps_positive_width(self):
        out = pcb_calc.trace_width({"current_a": 1e-6, "delta_t_c": 10,
                                    "copper_oz": 1})
        self.assertGreater(out["width_mm"], 0)
        self.assertLess(out["width_mm"], 1e-6)

    def test_ldo_power_and_tj(self):
        out = pcb_calc.circuit({"op": "ldo_power", "vin": 5, "vout": 3.3,
                                "iout": 0.5, "theta_ja": 60, "ta_c": 25})
        self.assertAlmostEqual(out["power_w"], 0.85, places=3)
        self.assertAlmostEqual(out["tj_c"], 76.0, places=2)

    def test_ldo_stepdown_only(self):
        with self.assertRaises(ValueError):
            pcb_calc.circuit({"op": "ldo_power", "vin": 3.3, "vout": 5,
                              "iout": 1, "theta_ja": 60, "ta_c": 25})

    def test_divider_overflow_rejected(self):
        with self.assertRaises(ValueError):
            pcb_calc.compute({"op": "circuit",
                              "params": {"op": "divider", "vin": 1e308,
                                         "r1": 1e308, "r2": 1e308}})

    def test_i2c_infeasible_range(self):
        out = pcb_calc.circuit({"op": "i2c_pullup", "vcc": 3.3,
                                "vol": 0.4, "iol_a": 0.003,
                                "cbus_pf": 1000000, "tr_ns": 100})
        self.assertFalse(out["feasible"])
        self.assertTrue(any("无可行区间" in w for w in out["warnings"]))

    def test_i2c_vol_must_be_below_vcc(self):
        with self.assertRaises(ValueError):
            pcb_calc.circuit({"op": "i2c_pullup", "vcc": 3.3, "vol": 4,
                              "iol_a": 0.003, "cbus_pf": 200,
                              "tr_ns": 300})

    def test_i2c_vol_zero_is_allowed(self):
        out = pcb_calc.circuit({"op": "i2c_pullup", "vcc": 3.3, "vol": 0,
                                "iol_a": 0.003, "cbus_pf": 200,
                                "tr_ns": 300})
        self.assertTrue(out["feasible"])

    def test_unknown_op_rejected(self):
        with self.assertRaises(ValueError):
            pcb_calc.compute({"op": "nope", "params": {}})


class CliTests(unittest.TestCase):
    def test_same_input_output_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "req.json"
            original = '{"op":"trace_width","params":{"current_a":1,"delta_t_c":10}}'
            path.write_text(original, encoding="utf-8")
            rc = pcb_calc.main(["--request", str(path), "--json", str(path)])
            self.assertEqual(rc, 2)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_valid_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = Path(tmp) / "req.json"
            out = Path(tmp) / "out.json"
            req.write_text(json.dumps({"op": "trace_width", "params": {
                "current_a": 1, "delta_t_c": 10}}), encoding="utf-8")
            self.assertEqual(pcb_calc.main(
                ["--request", str(req), "--json", str(out)]), 0)
            self.assertIn("width_mm", json.loads(out.read_text(encoding="utf-8")))

    def test_no_resource_warning(self):
        import gc
        import warnings
        with tempfile.TemporaryDirectory() as tmp:
            req = Path(tmp) / "req.json"
            out = Path(tmp) / "out.json"
            req.write_text(json.dumps({"op": "trace_width", "params": {
                "current_a": 1, "delta_t_c": 10}}), encoding="utf-8")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ResourceWarning)
                pcb_calc.main(["--request", str(req), "--json", str(out)])
                gc.collect()
            self.assertFalse([w for w in caught
                              if issubclass(w.category, ResourceWarning)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
