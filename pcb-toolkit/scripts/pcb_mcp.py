#!/usr/bin/env python3
"""pcb_mcp.py — 最小 MCP（stdio JSON-RPC）服务，暴露 pcb_* 工具。

只做 transport：判定/计算仍由 pcb_calc / pcb_analysis 的可测试函数提供。
每行一条 JSON-RPC 消息（newline-delimited），适合 stdio。

    python pcb_mcp.py
"""

from __future__ import annotations

import json
import sys

import pcb_analysis
import pcb_calc

PROTOCOL_VERSION = "2024-11-05"


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties,
            "required": required, "additionalProperties": True}


def _calc(op: str):
    """计算工具统一走 compute()，复用有限性/物理校验。"""
    return lambda args: pcb_calc.compute({"op": op, "params": args})


TOOLS = {
    "pcb_trace_width": {
        "fn": _calc("trace_width"),
        "description": "IPC-2221 载流线宽估算",
        "inputSchema": _schema({
            "current_a": {"type": "number"},
            "delta_t_c": {"type": "number"},
            "copper_oz": {"type": "number"},
            "layer": {"type": "string", "enum": ["external", "internal"]},
        }, ["current_a", "delta_t_c"]),
    },
    "pcb_via_current": {
        "fn": _calc("via_current"),
        "description": "过孔桶壁载流估算",
        "inputSchema": _schema({
            "drill_mm": {"type": "number"},
            "plating_um": {"type": "number"},
            "delta_t_c": {"type": "number"},
            "layer": {"type": "string", "enum": ["external", "internal"]},
        }, ["drill_mm"]),
    },
    "pcb_impedance": {
        "fn": _calc("impedance"),
        "description": "微带/带状线/差分阻抗估算",
        "inputSchema": _schema({
            "kind": {"type": "string",
                     "enum": ["microstrip", "stripline", "differential_microstrip"]},
            "er": {"type": "number"}, "h_mm": {"type": "number"},
            "w_mm": {"type": "number"}, "t_mm": {"type": "number"},
            "b_mm": {"type": "number"}, "s_mm": {"type": "number"},
        }, ["er", "h_mm", "w_mm"]),
    },
    "pcb_stackup": {
        "fn": _calc("stackup"),
        "description": "叠层厚度求和与目标偏差",
        "inputSchema": _schema({
            "layers": {"type": "array", "items": {"type": "object"}},
            "target_mm": {"type": "number"},
        }, ["layers"]),
    },
    "pcb_circuit": {
        "fn": _calc("circuit"),
        "description": "分压/RC/LED/LDO/晶振/I2C 上拉计算",
        "inputSchema": _schema({"op": {"type": "string"}}, ["op"]),
    },
    "pcb_triage_drc": {
        "fn": lambda a: pcb_analysis.compute("triage_drc", a),
        "description": "DRC 报告分组（只读）",
        "inputSchema": _schema({}, []),
    },
    "pcb_audit_bom": {
        "fn": lambda a: pcb_analysis.compute("audit_bom", a["rows"]),
        "description": "BOM 本地格式检查（不含供应链结论）",
        "inputSchema": _schema({
            "rows": {"type": "array", "items": {"type": "object"}},
        }, ["rows"]),
    },
    "pcb_rule_audit": {
        "fn": lambda a: pcb_analysis.compute("rule_audit", a),
        "description": "lint_dru 报告规则汇总",
        "inputSchema": _schema({}, []),
    },
}


class Server:
    def handle(self, request):
        """返回 response dict；通知（无 id）返回 None。"""
        if not isinstance(request, dict):
            return _error(None, -32600, "Invalid Request")
        if request.get("jsonrpc") != "2.0":
            return _error(request.get("id"), -32600, "jsonrpc 必须是 2.0")
        method = request.get("method")
        if not isinstance(method, str):
            return _error(request.get("id"), -32600, "method 必须是字符串")
        is_notification = "id" not in request
        response = self._dispatch(method, request, request.get("id"))
        return None if is_notification else response

    def _dispatch(self, method, request, req_id):
        if method == "initialize":
            return _result(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "pcb-toolkit", "version": "0.1"},
            })
        if method in ("notifications/initialized", "notifications/cancelled"):
            return None
        if method == "ping":
            return _result(req_id, {})
        if method == "tools/list":
            return _result(req_id, {"tools": [
                {"name": name, "description": spec["description"],
                 "inputSchema": spec["inputSchema"]}
                for name, spec in TOOLS.items()]})
        if method == "tools/call":
            params = request.get("params")
            if not isinstance(params, dict):
                return _error(req_id, -32602, "params 必须是对象")
            name = params.get("name")
            args = params.get("arguments", {})
            spec = TOOLS.get(name)
            if spec is None:
                return _error(req_id, -32602, f"未知工具 {name!r}")
            if not isinstance(args, dict):
                return _error(req_id, -32602, "arguments 必须是对象")
            try:
                payload = spec["fn"](args)
                text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
            except Exception as exc:  # noqa: BLE001
                return _result(req_id, {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                })
            return _result(req_id, {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            })
        return _error(req_id, -32601, f"未知方法 {method!r}")

    def serve(self, stdin, stdout) -> None:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                stdout.write(json.dumps(_error(None, -32700, "Parse error")) + "\n")
                stdout.flush()
                continue
            try:
                response = self.handle(request)
            except Exception as exc:  # noqa: BLE001
                req_id = request.get("id") if isinstance(request, dict) else None
                response = _error(req_id, -32603, f"内部错误：{exc}")
            if response is not None:
                try:
                    data = json.dumps(response, ensure_ascii=False,
                                      allow_nan=False)
                except ValueError:
                    data = json.dumps(_error(None, -32603,
                                             "响应包含非有限数值"))
                stdout.write(data + "\n")
                stdout.flush()


def _result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    Server().serve(sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
