"""pcb_mcp 的协议回归（M5）。"""

import io
import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import pcb_mcp  # noqa: E402

TOOL_CALLS = [
    ("pcb_trace_width", {"current_a": 1, "delta_t_c": 10}),
    ("pcb_via_current", {"drill_mm": 0.3}),
    ("pcb_impedance", {"kind": "microstrip", "er": 4.3,
                       "h_mm": 0.2, "w_mm": 0.35}),
    ("pcb_stackup", {"layers": [{"thickness_mm": 1.6}]}),
    ("pcb_circuit", {"op": "divider", "vin": 5, "r1": 1000, "r2": 1000}),
    ("pcb_triage_drc", {"violations": [], "unconnected_items": [],
                        "schematic_parity": []}),
    ("pcb_audit_bom", {"rows": [{
        "Reference": "R1", "Value": "10k", "Package": "0603",
        "MPN": "M1", "LCSC": "C1", "DNP": "no"}]}),
    ("pcb_rule_audit", {"rules": [], "findings": [], "errors": []}),
]

EXPECTED_KEYS = {
    "pcb_trace_width": "width_mm",
    "pcb_via_current": "current_a",
    "pcb_impedance": "z0_ohm",
    "pcb_stackup": "total_mm",
    "pcb_circuit": "vout",
    "pcb_triage_drc": "total",
    "pcb_audit_bom": "rows",
    "pcb_rule_audit": "rule_count",
}


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.server = pcb_mcp.Server()

    def test_initialize(self):
        out = self.server.handle({"jsonrpc": "2.0", "id": 1,
                                  "method": "initialize", "params": {}})
        self.assertEqual(out["result"]["protocolVersion"],
                         pcb_mcp.PROTOCOL_VERSION)
        self.assertIn("tools", out["result"]["capabilities"])

    def test_tools_list(self):
        out = self.server.handle({"jsonrpc": "2.0", "id": 2,
                                  "method": "tools/list"})
        names = {t["name"] for t in out["result"]["tools"]}
        for name in ("pcb_trace_width", "pcb_impedance", "pcb_triage_drc",
                     "pcb_audit_bom", "pcb_rule_audit"):
            self.assertIn(name, names)

    def test_tools_call(self):
        out = self.server.handle({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "pcb_trace_width",
                       "arguments": {"current_a": 3, "delta_t_c": 10,
                                     "copper_oz": 1, "layer": "external"}}})
        payload = json.loads(out["result"]["content"][0]["text"])
        self.assertAlmostEqual(payload["width_mm"], 1.375, places=2)

    def test_audit_bom_object_args(self):
        out = self.server.handle({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "pcb_audit_bom",
                       "arguments": {"rows": [{
                           "Reference": "R1", "Value": "10k",
                           "Package": "0603", "MPN": "M1",
                           "LCSC": "C1", "DNP": "no"}]}}})
        payload = json.loads(out["result"]["content"][0]["text"])
        self.assertEqual(payload["rows"], 1)
        self.assertFalse(out["result"]["isError"])

    def test_notification_gets_no_response(self):
        self.assertIsNone(self.server.handle(
            {"jsonrpc": "2.0", "method": "ping"}))
        self.assertIsNone(self.server.handle(
            {"jsonrpc": "2.0", "method": "tools/call",
             "params": {"name": "pcb_trace_width",
                        "arguments": {"current_a": 1, "delta_t_c": 10}}}))

    def test_bad_params_do_not_crash(self):
        out = self.server.handle({
            "jsonrpc": "2.0", "id": 8, "method": "tools/call",
            "params": "bad"})
        self.assertEqual(out["error"]["code"], -32602)

    def test_serve_recovers_after_bad_request(self):
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": "bad"}) + "\n" +
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}) + "\n")
        stdout = io.StringIO()
        self.server.serve(stdin, stdout)
        lines = [json.loads(x) for x in stdout.getvalue().splitlines()]
        self.assertEqual(lines[0]["error"]["code"], -32602)
        self.assertEqual(lines[1]["result"], {})

    def test_all_tools_via_stdio(self):
        lines = []
        for i, (name, args) in enumerate(TOOL_CALLS):
            lines.append(json.dumps({
                "jsonrpc": "2.0", "id": i + 1, "method": "tools/call",
                "params": {"name": name, "arguments": args}}))
        stdout = io.StringIO()
        self.server.serve(io.StringIO("\n".join(lines) + "\n"), stdout)
        responses = [json.loads(x) for x in stdout.getvalue().splitlines()]
        self.assertEqual(len(responses), 8)
        for (name, _), resp in zip(TOOL_CALLS, responses):
            self.assertFalse(resp["result"]["isError"], name)
            payload = json.loads(resp["result"]["content"][0]["text"])
            self.assertIn(EXPECTED_KEYS[name], payload, name)

    def test_all_tools_over_real_subprocess(self):
        lines = []
        for i, (name, args) in enumerate(TOOL_CALLS):
            lines.append(json.dumps({
                "jsonrpc": "2.0", "id": i + 1, "method": "tools/call",
                "params": {"name": name, "arguments": args}}))
        proc = subprocess.run(
            [sys.executable, str(HERE.parent / "scripts" / "pcb_mcp.py")],
            input="\n".join(lines) + "\n", capture_output=True,
            text=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0)
        responses = [json.loads(x) for x in proc.stdout.splitlines()]
        self.assertEqual(len(responses), 8)
        for (name, _), resp in zip(TOOL_CALLS, responses):
            self.assertFalse(resp["result"]["isError"], name)

    def test_calc_overflow_is_error(self):
        for name, args in (
                ("pcb_circuit", {"op": "divider", "vin": 1e308,
                                 "r1": 1e308, "r2": 1e308}),
                ("pcb_stackup", {"layers": [{"thickness_mm": 1e308},
                                            {"thickness_mm": 1e308}]})):
            out = self.server.handle({
                "jsonrpc": "2.0", "id": 9, "method": "tools/call",
                "params": {"name": name, "arguments": args}})
            self.assertTrue(out["result"]["isError"], name)
            self.assertIn("有限", out["result"]["content"][0]["text"])

    def test_overflow_over_real_subprocess(self):
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "pcb_circuit",
                        "arguments": {"op": "divider", "vin": 1e308,
                                      "r1": 1e308, "r2": 1e308}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "pcb_stackup",
                        "arguments": {"layers": [
                            {"thickness_mm": 1e308},
                            {"thickness_mm": 1e308}]}}},
        ]
        proc = subprocess.run(
            [sys.executable, str(HERE.parent / "scripts" / "pcb_mcp.py")],
            input="\n".join(json.dumps(m) for m in msgs) + "\n",
            capture_output=True, text=True, encoding="utf-8", timeout=30)
        responses = [json.loads(x) for x in proc.stdout.splitlines()]
        self.assertEqual(len(responses), 2)
        for resp in responses:
            self.assertTrue(resp["result"]["isError"])

    def test_unknown_tool(self):
        out = self.server.handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "nope", "arguments": {}}})
        self.assertEqual(out["error"]["code"], -32602)

    def test_tool_error_is_reported(self):
        out = self.server.handle({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "pcb_trace_width",
                       "arguments": {"current_a": -1, "delta_t_c": 10}}})
        self.assertTrue(out["result"]["isError"])

    def test_unknown_method(self):
        out = self.server.handle({"jsonrpc": "2.0", "id": 6,
                                  "method": "nope"})
        self.assertEqual(out["error"]["code"], -32601)

    def test_serve_stream(self):
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n" +
            "{bad json}\n")
        stdout = io.StringIO()
        self.server.serve(stdin, stdout)
        lines = [json.loads(x) for x in stdout.getvalue().splitlines()]
        self.assertEqual(lines[0]["result"], {})
        self.assertEqual(lines[1]["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main(verbosity=2)
