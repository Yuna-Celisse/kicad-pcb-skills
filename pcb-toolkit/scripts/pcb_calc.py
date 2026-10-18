#!/usr/bin/env python3
"""pcb_calc.py — 确定性工程计算（stdlib，无外部数据）。

所有结果都带 `model` 与 `warnings`：这是**估算**，不是实测/板厂承诺。
CLI:
    python pcb_calc.py --request req.json --json out.json
    echo '{"op":"trace_width","params":{...}}' | python pcb_calc.py
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

MIL_MM = 0.0254
OZ_MIL = 1.37          # 1oz 铜厚（mil）
K_OUTER = 0.048        # IPC-2221 外层
K_INNER = 0.024        # IPC-2221 内层


def _num(params: dict, key: str, *, positive=False, default=None):
    value = params.get(key, default)
    if value is None:
        raise ValueError(f"缺少参数 {key}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} 必须是数值")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{key} 必须是有限数值")
    if positive and value <= 0:
        raise ValueError(f"{key} 必须 > 0")
    return value


def _check_layer(layer: str) -> float:
    if layer == "external":
        return K_OUTER
    if layer == "internal":
        return K_INNER
    raise ValueError("layer 必须是 external 或 internal")


def _round_out(value: float, digits: int = 4):
    """正数不要因四舍五入变成 0；小量用有效数字表示。"""
    if value == 0:
        return 0.0
    if abs(value) < 10 ** (-digits):
        return float(f"{value:.6g}")
    return round(value, digits)


def _check_finite(value, path="result"):
    if isinstance(value, dict):
        for key, item in value.items():
            _check_finite(item, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _check_finite(item, f"{path}[{i}]")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} 不是有限数值（可能溢出）")
    return value


def trace_width(params: dict) -> dict:
    """IPC-2221 载流线宽（A 为 mil²）。"""
    current = _num(params, "current_a", positive=True)
    delta_t = _num(params, "delta_t_c", positive=True)
    copper_oz = _num(params, "copper_oz", positive=True, default=1.0)
    layer = params.get("layer", "external")
    k = _check_layer(layer)

    area_mil2 = (current / (k * delta_t ** 0.44)) ** (1 / 0.725)
    thickness_mil = OZ_MIL * copper_oz
    width_mil = area_mil2 / thickness_mil
    width_mm = width_mil * MIL_MM
    return {
        "width_mm": _round_out(width_mm, 6),
        "area_mil2": _round_out(area_mil2, 3),
        "thickness_mil": round(thickness_mil, 3),
        "current_a": current,
        "delta_t_c": delta_t,
        "copper_oz": copper_oz,
        "layer": layer,
        "model": "IPC-2221 I=k*dT^0.44*A^0.725",
        "warnings": ["估算值；未计阻焊/气流/邻近走线，关键电源以温升实测为准"],
    }


def via_current(params: dict) -> dict:
    """按镀铜桶壁截面积套 IPC-2221；默认内层系数（保守）。"""
    drill = _num(params, "drill_mm", positive=True)
    plating_um = _num(params, "plating_um", positive=True, default=25.0)
    delta_t = _num(params, "delta_t_c", positive=True, default=10.0)
    layer = params.get("layer", "internal")
    k = _check_layer(layer)

    plating_mm = plating_um / 1000.0
    outer_r = drill / 2
    inner_r = outer_r - plating_mm
    if inner_r <= 0:
        raise ValueError("镀铜厚度过大：钻刀半径必须大于镀层厚度")
    area_mm2 = math.pi * (outer_r ** 2 - inner_r ** 2)
    area_mil2 = area_mm2 / (MIL_MM ** 2)
    current = k * delta_t ** 0.44 * area_mil2 ** 0.725
    return {
        "current_a": round(current, 3),
        "area_mm2": round(area_mm2, 6),
        "area_mil2": round(area_mil2, 3),
        "drill_mm": drill,
        "finished_hole_mm": round(drill - 2 * plating_mm, 4),
        "plating_um": plating_um,
        "delta_t_c": delta_t,
        "layer": layer,
        "model": "IPC-2221 + 桶壁面积 π[(D/2)²−(D/2−t)²]",
        "warnings": ["drill_mm 为钻刀直径；成品孔径=D−2t；多孔并联并留余量"],
    }


def impedance(params: dict) -> dict:
    """微带/带状线/差分微带估算。"""
    kind = params.get("kind", "microstrip")
    er = _num(params, "er", positive=True)
    h = _num(params, "h_mm", positive=True)
    w = _num(params, "w_mm", positive=True)
    t = _num(params, "t_mm", positive=True, default=0.035)
    warnings = []

    if kind == "microstrip":
        denom = 0.8 * w + t
        if 5.98 * h <= denom:
            raise ValueError("微带几何超出适用域：5.98h 必须大于 0.8w+t")
        z0 = 87 / math.sqrt(er + 1.41) * math.log(5.98 * h / denom)
        ratio = w / h
        if not 0.1 <= ratio <= 2:
            warnings.append(f"w/h={ratio:.2f} 超出公式常用范围 0.1–2")
        result = {"kind": kind, "z0_ohm": round(z0, 2)}
    elif kind == "stripline":
        b = _num(params, "b_mm", positive=True)
        arg = 4 * b / (0.67 * math.pi * w * (0.8 + t / w))
        if arg <= 1:
            raise ValueError("带状线几何超出适用域：4b 必须大于 0.67πw(0.8+t/w)")
        z0 = 60 / math.sqrt(er) * math.log(arg)
        result = {"kind": kind, "z0_ohm": round(z0, 2), "b_mm": b}
    elif kind == "differential_microstrip":
        s = _num(params, "s_mm", positive=True)
        denom = 0.8 * w + t
        if 5.98 * h <= denom:
            raise ValueError("差分微带几何超出适用域：5.98h 必须大于 0.8w+t")
        z0 = 87 / math.sqrt(er + 1.41) * math.log(5.98 * h / denom)
        zdiff = 2 * z0 * (1 - 0.48 * math.exp(-0.96 * s / h))
        result = {"kind": kind, "z0_ohm": round(z0, 2),
                  "zdiff_ohm": round(zdiff, 2), "s_mm": s}
    else:
        raise ValueError("kind 必须是 microstrip/stripline/differential_microstrip")

    result["model"] = "IPC-2141 近似"
    result["warnings"] = warnings + ["公式误差约 10–20%；以板厂叠层/场求解为准"]
    return result


def stackup(params: dict) -> dict:
    layers = params.get("layers")
    if not isinstance(layers, list) or not layers:
        raise ValueError("layers 必须是非空列表")
    total = 0.0
    detail = []
    for i, layer in enumerate(layers):
        if not isinstance(layer, dict):
            raise ValueError(f"layers[{i}] 必须是对象")
        name = layer.get("name", f"L{i + 1}")
        thickness = _num(layer, "thickness_mm", positive=True)
        total += thickness
        detail.append({"name": name, "thickness_mm": thickness,
                       "role": layer.get("role")})
    target = params.get("target_mm")
    warnings = []
    delta = None
    if target is not None:
        target = _num({"target_mm": target}, "target_mm", positive=True)
        delta = round(total - target, 4)
        if abs(delta) > 0.05:
            warnings.append(f"总厚 {total:.2f}mm 与目标 {target:.2f}mm 偏差 {delta:+.2f}mm")
    return {
        "total_mm": round(total, 4),
        "target_mm": target,
        "delta_mm": delta,
        "layers": detail,
        "model": "厚度求和",
        "warnings": warnings,
    }


def circuit(params: dict) -> dict:
    op = params.get("op")
    if op == "divider":
        vin = _num(params, "vin", positive=True)
        r1 = _num(params, "r1", positive=True)
        r2 = _num(params, "r2", positive=True)
        return {"vout": round(vin * r2 / (r1 + r2), 6),
                "model": "Vout=Vin*R2/(R1+R2)", "warnings": []}
    if op == "rc":
        r = _num(params, "r_ohm", positive=True)
        c = _num(params, "c_f", positive=True)
        tau = r * c
        return {"tau_s": tau, "fc_hz": 1 / (2 * math.pi * tau),
                "model": "tau=RC, fc=1/(2*pi*RC)", "warnings": []}
    if op == "led_resistor":
        vs = _num(params, "vs", positive=True)
        vf = _num(params, "vf", positive=True)
        if if_a := _num(params, "if_a", positive=True):
            r = (vs - vf) / if_a
            if r <= 0:
                raise ValueError("Vs 必须大于 Vf")
            return {"r_ohm": round(r, 3), "power_w": round((vs - vf) * if_a, 4),
                    "model": "R=(Vs-Vf)/If", "warnings": []}
    if op == "ldo_power":
        vin = _num(params, "vin", positive=True)
        vout = _num(params, "vout", positive=True)
        iout = _num(params, "iout", positive=True)
        if vin <= vout:
            raise ValueError("LDO 必须 Vin > Vout（LDO 不升压）")
        p = (vin - vout) * iout
        out = {"power_w": round(p, 4), "model": "P=(Vin-Vout)*Iout"}
        theta = params.get("theta_ja")
        ta = params.get("ta_c")
        if theta is not None and ta is not None:
            theta = _num(params, "theta_ja", positive=True)
            ta = _num(params, "ta_c")
            out["tj_c"] = round(ta + p * theta, 2)
        out["warnings"] = []
        return out
    if op == "crystal_load":
        cl = _num(params, "cl_pf", positive=True)
        cstray = _num(params, "cstray_pf", positive=True, default=4.0)
        c = 2 * (cl - cstray)
        if c <= 0:
            raise ValueError("CL 必须大于 Cstray")
        return {"c_pf": round(c, 2), "model": "C=2*(CL-Cstray)",
                "warnings": ["Cstray 为估值；按布局/实测修正"]}
    if op == "i2c_pullup":
        vcc = _num(params, "vcc", positive=True)
        vol = _num(params, "vol")
        if vol < 0:
            raise ValueError("VOL 必须 >= 0")
        if vol >= vcc:
            raise ValueError("I2C 要求 0 <= VOL < VCC")
        iol = _num(params, "iol_a", positive=True)
        cbus = _num(params, "cbus_pf", positive=True)
        tr = _num(params, "tr_ns", positive=True)
        rmax = (tr * 1e-9) / (0.8473 * cbus * 1e-12)
        rmin = (vcc - vol) / iol
        feasible = rmin < rmax
        warnings = ["取 rmin<Rp<rmax，并核对总线电容上限"]
        if not feasible:
            warnings = ["无可行区间：r_min >= r_max（减小 Cbus/提高 Iol/降低速率）"]
        return {"r_min_ohm": round(rmin, 1), "r_max_ohm": round(rmax, 1),
                "feasible": feasible,
                "model": "Rp(max)=tr/(0.8473*Cbus), Rp(min)=(Vcc-Vol)/Iol",
                "warnings": warnings}
    raise ValueError(f"未知电路计算 op: {op}")


OPS = {
    "trace_width": trace_width,
    "via_current": via_current,
    "impedance": impedance,
    "stackup": stackup,
    "circuit": circuit,
}


def compute(request: dict) -> dict:
    if not isinstance(request, dict):
        raise ValueError("request 必须是对象")
    op = request.get("op")
    fn = OPS.get(op)
    if fn is None:
        raise ValueError(f"未知 op: {op}")
    params = request.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("params 必须是对象")
    result = fn(params)
    _check_finite(result)
    return {"tool": "pcb_calc", "version": "0.1", "op": op, **result}


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="PCB 确定性计算")
    ap.add_argument("--request", help="JSON 文件；省略则从 stdin 读")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)
    try:
        if args.request:
            source = Path(args.request).resolve()
            if args.json_out and Path(args.json_out).resolve() == source:
                raise ValueError("--json 不能与 --request 指向同一文件")
            with open(args.request, encoding="utf-8-sig") as fh:
                request = json.load(fh)
        else:
            request = json.loads(sys.stdin.read())
        report = compute(request)
    except Exception as exc:  # noqa: BLE001
        print(f"输入错误：{exc}", file=sys.stderr)
        return 2
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
