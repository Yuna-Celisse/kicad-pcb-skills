"""pcb_overlap 的回归测试：用合成夹具证明“能报出来”，再用真实板验证“不误报”。

运行：
    python -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import pcb_overlap as ov  # noqa: E402


PCB_TEMPLATE = """(kicad_pcb (version 20240101) (generator "test")
  (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (31 "F.CrtYd" user) (29 "B.CrtYd" user))
{footprints}
)
"""

FOOTPRINT = """  (footprint "T:{name}" (layer "{layer}") (at {x} {y}{rot})
    (property "Reference" "{ref}" (at 0 0 0) (layer "F.Fab") (uuid "00000000-0000-0000-0000-0000000000{r:02d}"))
    (fp_rect (start -2 -2) (end 2 2) (stroke (width 0.05) (type solid)) (fill none) (layer "{crt}"))
    (pad "1" smd rect (at -1 0) (size 1 1) (layers "{cu}" "F.Paste"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "{cu}" "F.Paste")))
"""

FOOTPRINT_FAB = """  (footprint "T:{name}" (layer "F.Cu") (at {x} {y})
    (property "Reference" "{ref}" (at 0 0 0) (layer "F.Fab") (uuid "00000000-0000-0000-0000-0000000000{r:02d}"))
    (fp_rect (start -2 -2) (end 2 2) (stroke (width 0.05) (type solid)) (fill none) (layer "F.Fab")))
"""


def build_pcb(items, template=FOOTPRINT):
    fps = []
    for i, it in enumerate(items):
        side = it.get("layer", "F.Cu")
        fps.append(template.format(
            name=it["ref"], layer=side, x=it["x"], y=it["y"],
            rot=f" {it['rot']}" if it.get("rot") else "",
            ref=it["ref"], r=i, crt="F.CrtYd" if side == "F.Cu" else "B.CrtYd",
            cu=side))
    return PCB_TEMPLATE.format(footprints="\n".join(fps))


SYM_LIB = """(kicad_symbol_lib (version 20241209) (generator "test")
  (symbol "BOX"
    (property "Reference" "U" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "BOX_0_1"
      (rectangle (start -5 -5) (end 5 5) (stroke (width 0.2) (type default))
                 (fill (type none))))
    (symbol "BOX_1_1"
      (pin input line (at -7 0 0) (length 2)
        (name "P" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27))))))))
"""

SYM_TABLE = """(sym_lib_table (version 7)
  (lib (name "T") (type "KiCad") (uri "${KIPRJMOD}/T.kicad_sym")
       (options "") (descr "test")))
"""

SYM_SCH = """(kicad_sch (version 20241209) (generator "test")
{symbols}
)
"""

SYM_INST = """  (symbol (lib_id "T:BOX") (at {x} {y} {rot}) (unit 1) (body_style 1)
    (in_bom yes) (on_board yes)
    (property "Reference" "{ref}" (at 0 0 0) (effects (font (size 1.27 1.27)))))"""


class Workspace:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def write(self, name, text):
        p = self.root / name
        p.write_text(text, encoding="utf-8")
        return p

    def cleanup(self):
        self._tmp.cleanup()


def run(path, *extra):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ov.main([str(path), "--json", str(Path(path).with_suffix(".json")), *extra])
    data = json.loads(Path(path).with_suffix(".json").read_text(encoding="utf-8"))
    return code, data, buf.getvalue()


class PcbOverlapTests(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()

    def tearDown(self):
        self.ws.cleanup()

    def test_detects_overlap(self):
        pcb = self.ws.write("a.kicad_pcb", build_pcb([
            {"ref": "R1", "x": 10, "y": 10},
            {"ref": "R2", "x": 12, "y": 10},
        ]))
        code, data, out = run(pcb)
        self.assertEqual(data["summary"]["overlaps"], 1)
        self.assertEqual(data["findings"][0]["kind"], "overlap")
        self.assertAlmostEqual(data["findings"][0]["area_mm2"], 8.0, places=2)  # 2mm x 4mm
        self.assertAlmostEqual(data["findings"][0]["penetration_mm"], 2.0, places=3)
        # 精确 courtyard 几何 -> 可阻断
        self.assertEqual(data["findings"][0]["geometry"], "courtyard_polygon")
        self.assertEqual(data["findings"][0]["gate_effect"], "block")
        self.assertEqual(data["summary"]["verdict"], "BLOCKED")
        self.assertEqual(code, 0)

    def test_fab_fallback_downgrades_to_review(self):
        pcb = self.ws.write("fab.kicad_pcb", build_pcb([
            {"ref": "R1", "x": 10, "y": 10},
            {"ref": "R2", "x": 12, "y": 10},
        ], template=FOOTPRINT_FAB))
        _, data, _ = run(pcb)
        self.assertEqual(data["summary"]["blocks"], 0)
        self.assertEqual(data["summary"]["verdict"], "INCOMPLETE")
        self.assertEqual(data["findings"][0]["geometry"], "fab_polygon")
        self.assertEqual(data["findings"][0]["gate_effect"], "review")

    def test_pad_overlap_is_blocking_when_exact(self):
        pcb = self.ws.write("pad.kicad_pcb", build_pcb([
            {"ref": "R1", "x": 10, "y": 10},
            {"ref": "R2", "x": 12, "y": 10},
        ]))
        _, data, _ = run(pcb, "--include-pads")
        pads = [f for f in data["findings"] if f["kind"] == "pad_overlap"]
        self.assertTrue(pads)
        self.assertEqual(pads[0]["geometry"], "pad_outline")
        self.assertEqual(pads[0]["gate_effect"], "block")
        self.assertGreater(data["summary"]["pad_overlaps"], 0)

    def test_separate_parts_pass(self):
        pcb = self.ws.write("b.kicad_pcb", build_pcb([
            {"ref": "R1", "x": 10, "y": 10},
            {"ref": "R2", "x": 20, "y": 10},
        ]))
        _, data, _ = run(pcb)
        self.assertEqual(data["summary"]["overlaps"], 0)
        self.assertEqual(data["summary"]["verdict"], "PASS")

    def test_opposite_sides_do_not_collide(self):
        pcb = self.ws.write("c.kicad_pcb", build_pcb([
            {"ref": "R1", "x": 10, "y": 10, "layer": "F.Cu"},
            {"ref": "R2", "x": 10, "y": 10, "layer": "B.Cu"},
        ]))
        _, data, _ = run(pcb)
        self.assertEqual(data["summary"]["overlaps"], 0)

    def test_touch_is_not_overlap(self):
        pcb = self.ws.write("d.kicad_pcb", build_pcb([
            {"ref": "R1", "x": 10, "y": 10},
            {"ref": "R2", "x": 13.99, "y": 10},  # 0.01mm 穿透
        ]))
        _, data, _ = run(pcb)
        self.assertEqual(data["summary"]["overlaps"], 0)
        self.assertEqual(data["summary"]["touches"], 1)
        self.assertEqual(data["findings"][0]["gate_effect"], "info")
        self.assertEqual(data["summary"]["verdict"], "PASS")

    def test_rotation_is_applied(self):
        # 同一位置放两个 45° 旋转的 4x4 方块：旋转后仍重叠
        pcb = self.ws.write("e.kicad_pcb", build_pcb([
            {"ref": "R1", "x": 10, "y": 10, "rot": 45},
            {"ref": "R2", "x": 10.5, "y": 10, "rot": 45},
        ]))
        _, data, _ = run(pcb)
        self.assertEqual(data["summary"]["overlaps"], 1)

    def test_fail_on_overlap_exit_code(self):
        pcb = self.ws.write("f.kicad_pcb", build_pcb([
            {"ref": "R1", "x": 10, "y": 10},
            {"ref": "R2", "x": 11, "y": 10},
        ]))
        code, _, _ = run(pcb, "--fail-on-overlap")
        self.assertEqual(code, 1)

    def test_fail_on_review_exit_code(self):
        pcb = self.ws.write("g.kicad_pcb", build_pcb([
            {"ref": "R1", "x": 10, "y": 10},
            {"ref": "R2", "x": 11, "y": 10},
        ], template=FOOTPRINT_FAB))
        code_block, _, _ = run(pcb, "--fail-on-overlap")
        self.assertEqual(code_block, 0)      # review 不阻断
        code_review, _, _ = run(pcb, "--fail-on-review")
        self.assertEqual(code_review, 1)


class SchematicOverlapTests(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()
        self.ws.write("T.kicad_sym", SYM_LIB)
        self.ws.write("sym-lib-table", SYM_TABLE)

    def tearDown(self):
        self.ws.cleanup()

    def sch(self, *placements):
        body = "\n".join(
            SYM_INST.format(ref=r, x=x, y=y, rot=rot) for r, x, y, rot in placements)
        return self.ws.write("s.kicad_sch", SYM_SCH.format(symbols=body))

    def test_detects_symbol_overlap(self):
        p = self.sch(("U1", 100, 100, 0), ("U2", 104, 100, 0))
        _, data, _ = run(p)
        self.assertEqual(data["summary"]["overlaps"], 1)
        self.assertAlmostEqual(data["findings"][0]["area_mm2"], 60.0, places=1)  # 6 x 10

    def test_far_apart_symbols_pass(self):
        p = self.sch(("U1", 100, 100, 0), ("U2", 130, 100, 0))
        _, data, _ = run(p)
        self.assertEqual(data["summary"]["overlaps"], 0)

    def test_vertical_offset_uses_inverted_y(self):
        # 元件体在库坐标里 Y 向上；同一 y 上偏移 9.9 应相交
        p = self.sch(("U1", 100, 100, 0), ("U2", 100, 109.9, 0))
        _, data, _ = run(p)
        self.assertEqual(data["summary"]["overlaps"], 1)

    def test_hierarchy_is_followed(self):
        child = self.ws.write("child.kicad_sch", SYM_SCH.format(
            symbols=SYM_INST.format(ref="U9", x=100, y=100, rot=0)))
        root = self.ws.write("root.kicad_sch", f"""(kicad_sch (version 20241209) (generator "test")
  (symbol (lib_id "T:BOX") (at 10 10 0) (unit 1) (body_style 1)
    (property "Reference" "U1" (at 0 0 0)))
  (sheet (at 50 50) (size 20 20)
    (property "Sheetfile" "child.kicad_sch" (at 0 0 0))
    (property "Sheetname" "sub" (at 0 0 0))))
""")
        _, data, _ = run(root)
        self.assertEqual(data["checks"][0]["stats"]["sheets"], 2)
        self.assertEqual(data["checks"][0]["stats"]["symbols"], 2)


class GeometryTests(unittest.TestCase):
    def test_sat_depth(self):
        a = [(0, 0), (4, 0), (4, 4), (0, 4)]
        b = [(2, 1), (6, 1), (6, 3), (2, 3)]
        self.assertAlmostEqual(ov.sat_depth(a, b), 2.0, places=6)
        c = [(5, 0), (9, 0), (9, 4), (5, 4)]
        self.assertEqual(ov.sat_depth(a, c), 0.0)

    def test_clip_area(self):
        a = [(0, 0), (4, 0), (4, 4), (0, 4)]
        b = [(2, 2), (6, 2), (6, 6), (2, 6)]
        self.assertAlmostEqual(ov.polygon_area(ov.clip_convex(a, b)), 4.0, places=6)

    def test_hull(self):
        pts = [(0, 0), (1, 0), (0, 1), (1, 1), (0.5, 0.5)]
        self.assertAlmostEqual(ov.polygon_area(ov.convex_hull(pts)), 1.0, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
