#!/usr/bin/env python3
"""pcb_overlap.py — 只读的元件重叠检测器（KiCad PCB / 原理图）。

不修改任何 .kicad_* 文件；只解析文本并做几何判定。

用法：
    python pcb_overlap.py board.kicad_pcb
    python pcb_overlap.py root.kicad_sch
    python pcb_overlap.py project.kicad_pro          # 同时查 PCB 与原理图
    python pcb_overlap.py board.kicad_pcb --json r.json --svg r.svg --fail-on-overlap

判定口径：
    PCB       同面（F/B）footprint 的 courtyard 多边形相交 -> overlap
              courtyard 缺失时退回 F.Fab / B.Fab 包络，并标注 confidence=low
              可选 --include-pads：不同 footprint 的铜箔焊盘相交 -> pad_overlap
    原理图    同一张图内 symbol 器件体（body）包络相交 -> overlap
              库解析失败时输出 unresolved，不猜几何

退出码：0 无重叠；1 有重叠（仅当 --fail-on-overlap）；2 输入/解析错误。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# S-expression
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+')


def parse_sexpr(text: str):
    tokens = _TOKEN_RE.findall(text)
    stack: list[list] = [[]]
    for tok in tokens:
        if tok == "(":
            node: list = []
            stack[-1].append(node)
            stack.append(node)
        elif tok == ")":
            if len(stack) == 1:
                raise ValueError("unbalanced ')'")
            stack.pop()
        else:
            if tok.startswith('"'):
                tok = tok[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            stack[-1].append(tok)
    if len(stack) != 1:
        raise ValueError("unbalanced '('")
    return stack[0]


def node_name(node) -> str | None:
    return node[0] if isinstance(node, list) and node and isinstance(node[0], str) else None


def children(node, name: str | None = None):
    for c in node[1:]:
        if isinstance(c, list):
            if name is None or node_name(c) == name:
                yield c


def first(node, name: str):
    for c in children(node, name):
        return c
    return None


def atom(node, idx: int, default=None):
    if node is not None and len(node) > idx and not isinstance(node[idx], list):
        return node[idx]
    return default


def to_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def xy(node) -> tuple[float, float]:
    return to_float(atom(node, 1)), to_float(atom(node, 2))


# --------------------------------------------------------------------------
# 几何
# --------------------------------------------------------------------------

Point = tuple[float, float]


def rotate_kicad(p: Point, deg: float) -> Point:
    """KiCad RotatePoint：正角在屏幕坐标（Y 向下）下呈逆时针。"""
    if not deg:
        return p
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    x, y = p
    return (x * c + y * s, -x * s + y * c)


def translate(points, dx: float, dy: float):
    return [(x + dx, y + dy) for x, y in points]


def convex_hull(points: list[Point]) -> list[Point]:
    pts = sorted(set((round(x, 6), round(y, 6)) for x, y in points))
    if len(pts) <= 2:
        return pts
    lower: list[Point] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Point] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def polygon_area(poly: list[Point]) -> float:
    if len(poly) < 3:
        return 0.0
    s = 0.0
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        s += p[0] * q[1] - q[0] * p[1]
    return abs(s) / 2.0


def polygon_centroid(poly: list[Point]) -> Point:
    if not poly:
        return (0.0, 0.0)
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))


def project(poly: list[Point], axis: Point) -> tuple[float, float]:
    vals = [p[0] * axis[0] + p[1] * axis[1] for p in poly]
    return min(vals), max(vals)


def sat_overlap(a: list[Point], b: list[Point]) -> bool:
    return sat_depth(a, b) > 0.0


def sat_depth(a: list[Point], b: list[Point]) -> float:
    """凸多边形穿透深度：所有分离轴上重叠量的最小值；<=0 表示分离。"""
    depth = float("inf")
    for poly in (a, b):
        for i, p in enumerate(poly):
            q = poly[(i + 1) % len(poly)]
            edge = (q[0] - p[0], q[1] - p[1])
            axis = (-edge[1], edge[0])
            n = math.hypot(*axis)
            if n == 0:
                continue
            axis = (axis[0] / n, axis[1] / n)
            amin, amax = project(a, axis)
            bmin, bmax = project(b, axis)
            overlap = min(amax, bmax) - max(amin, bmin)
            if overlap <= 0:
                return 0.0
            depth = min(depth, overlap)
    return 0.0 if depth == float("inf") else depth


def clip_convex(subject: list[Point], clipper: list[Point]) -> list[Point]:
    """Sutherland–Hodgman：clipper 必须为凸多边形（CCW）。"""
    if len(clipper) < 3:
        return []
    out = list(subject)
    for i, cp1 in enumerate(clipper):
        cp2 = clipper[(i + 1) % len(clipper)]
        input_list = out
        out = []
        if not input_list:
            break
        s = input_list[-1]
        for e in input_list:
            inside_e = cross(cp1, cp2, e) >= -1e-12
            inside_s = cross(cp1, cp2, s) >= -1e-12
            if inside_e:
                if not inside_s:
                    out.append(line_intersect(s, e, cp1, cp2))
                out.append(e)
            elif inside_s:
                out.append(line_intersect(s, e, cp1, cp2))
            s = e
    return out


def line_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> Point:
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-12:
        return p1
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def circle_poly(center: Point, radius: float, segments: int = 24) -> list[Point]:
    cx, cy = center
    return [
        (cx + radius * math.cos(2 * math.pi * i / segments),
         cy + radius * math.sin(2 * math.pi * i / segments))
        for i in range(segments)
    ]


def arc_poly(start: Point, mid: Point, end: Point, segments: int = 12) -> list[Point]:
    """三点圆弧采样。"""
    ax, ay = start
    bx, by = mid
    cx, cy = end
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return [start, end]
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    a0 = math.atan2(ay - uy, ax - ux)
    a1 = math.atan2(by - uy, bx - ux)
    a2 = math.atan2(cy - uy, cx - ux)
    # 保证经过 mid：选择 start->end 的两个方向中夹住 mid 的那个
    def norm(a):
        return a % (2 * math.pi)

    two_pi = 2 * math.pi
    d1 = norm(a2 - a0)
    mid_rel = norm(a1 - a0)
    if mid_rel <= d1:
        angles = [a0 + d1 * i / segments for i in range(segments + 1)]
    else:
        d2 = d1 - two_pi
        angles = [a0 + d2 * i / segments for i in range(segments + 1)]
    return [(ux + r * math.cos(a), uy + r * math.sin(a)) for a in angles]


def chain_segments(segments: list[tuple[Point, Point]], tol: float = 1e-3) -> list[list[Point]]:
    """把线段链成闭合环；失败的段丢弃。"""
    rings: list[list[Point]] = []
    remaining = [(a, b) for a, b in segments if a != b]
    while remaining:
        a, b = remaining.pop(0)
        ring = [a, b]
        extended = True
        while extended and remaining:
            extended = False
            for i, (c, d) in enumerate(remaining):
                if math.dist(ring[-1], c) <= tol:
                    ring.append(d)
                    remaining.pop(i)
                    extended = True
                    break
                if math.dist(ring[-1], d) <= tol:
                    ring.append(c)
                    remaining.pop(i)
                    extended = True
                    break
        if len(ring) >= 4 and math.dist(ring[0], ring[-1]) <= tol:
            rings.append(ring[:-1])
    return rings


def shape_from_primitives(prims: list[list[Point]]) -> tuple[list[list[Point]], bool]:
    """返回 (多边形列表, 是否严格闭合)。矩形/多边形直接可用；线段尝试闭环。"""
    polys: list[list[Point]] = []
    segments: list[tuple[Point, Point]] = []
    for prim in prims:
        if len(prim) == 2:
            segments.append((prim[0], prim[1]))
        elif len(prim) >= 3:
            polys.append(prim)
    if segments:
        rings = chain_segments(segments)
        polys.extend(rings)
        if not rings:
            polys.append(convex_hull([p for s in segments for p in s]))
            return polys, False
    return polys, True


# --------------------------------------------------------------------------
# 数据模型
# --------------------------------------------------------------------------

@dataclass
class Item:
    ref: str
    lib_id: str
    side: str                     # "F" / "B" / "sheet"
    origin: Point
    rotation: float
    polygons: list[list[Point]]   # 已变换到全局坐标
    source: str = "courtyard"     # courtyard / fab / pads / body / unresolved
    confidence: str = "exact"     # exact / approx / none
    geometry: str = ""
    pads: list[list[Point]] = field(default_factory=list)
    pads_approx: bool = False
    sheet: str = ""


@dataclass
class Finding:
    kind: str
    severity: str
    ref_a: str
    ref_b: str
    area_mm2: float
    distance_mm: float
    where: str
    detail: str
    confidence: str = "exact"     # exact / approx / none
    geometry: str = ""
    gate_effect: str = "info"     # block / review / incomplete / info
    penetration_mm: float = 0.0

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "ref_a": self.ref_a,
            "ref_b": self.ref_b,
            "area_mm2": round(self.area_mm2, 4),
            "penetration_mm": round(self.penetration_mm, 4),
            "distance_mm": round(self.distance_mm, 3),
            "where": self.where,
            "detail": self.detail,
            "confidence": self.confidence,
            "geometry": self.geometry,
            "gate_effect": self.gate_effect,
        }


# --------------------------------------------------------------------------
# PCB
# --------------------------------------------------------------------------

COURTYARD_LAYERS = {"F": "F.CrtYd", "B": "B.CrtYd"}
FAB_LAYERS = {"F": "F.Fab", "B": "B.Fab"}


def pcb_graphic_points(node) -> list[list[Point]]:
    """把一个 fp_* 图元转换成本地点列表/线段对。"""
    nm = node_name(node)
    if nm == "fp_rect":
        s, e = xy(first(node, "start")), xy(first(node, "end"))
        return [[s, (e[0], s[1]), e, (s[0], e[1])]]
    if nm == "fp_line":
        return [[xy(first(node, "start")), xy(first(node, "end"))]]
    if nm == "fp_poly":
        pts = first(node, "pts")
        return [[xy(p) for p in children(pts, "xy")]] if pts else []
    if nm == "fp_circle":
        c = xy(first(node, "center"))
        e = xy(first(node, "end"))
        return [circle_poly(c, math.dist(c, e))]
    if nm == "fp_arc":
        return [arc_poly(xy(first(node, "start")), xy(first(node, "mid")), xy(first(node, "end")))]
    if nm == "fp_curve":
        pts = first(node, "pts")
        if not pts:
            return []
        p = [xy(x) for x in children(pts, "xy")]
        return [p] if len(p) >= 3 else []
    return []


def transform_footprint(prims: list[list[Point]], origin: Point, rot: float, flip: bool):
    out: list[list[Point]] = []
    for prim in prims:
        tp = []
        for x, y in prim:
            if flip:
                y = -y
            rx, ry = rotate_kicad((x, y), rot)
            tp.append((rx + origin[0], ry + origin[1]))
        out.append(tp)
    return out


def footprint_pads(node, origin: Point, rot: float, flip: bool, layer: str):
    """返回 (焊盘多边形列表, 是否含近似外形)。"""
    pads: list[list[Point]] = []
    any_approx = False
    side_layer = layer
    for pad in children(node, "pad"):
        at = first(pad, "at")
        size = first(pad, "size")
        if at is None or size is None:
            continue
        shape = atom(pad, 3, "rect")
        px, py = to_float(atom(at, 1)), to_float(atom(at, 2))
        pad_rot = to_float(atom(at, 3))
        w, h = to_float(atom(size, 1)), to_float(atom(size, 2))
        layers = [x for x in (first(pad, "layers") or [])[1:] if isinstance(x, str)]
        on_layer = any(l in (side_layer, "*.Cu", "F&B.Cu") for l in layers)
        if not on_layer:
            continue
        if shape == "circle":
            rect = circle_poly((0.0, 0.0), w / 2, 16)
            any_approx = True          # 16 边形近似圆
        elif shape in ("oval", "roundrect", "custom"):
            rect = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
            any_approx = True          # 外接矩形高估
        else:
            rect = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
        pts = []
        for x, y in rect:
            rx, ry = rotate_kicad((x, y), pad_rot)
            px2, py2 = px + rx, py + ry
            if flip:
                py2 = -py2
            gx, gy = rotate_kicad((px2, py2), rot)
            pts.append((gx + origin[0], gy + origin[1]))
        pads.append(pts)
    return pads, any_approx


def extract_pcb(path: Path, include_pads: bool) -> tuple[list[Item], dict]:
    root = parse_sexpr(path.read_text(encoding="utf-8", errors="replace"))
    if not root or node_name(root[0]) != "kicad_pcb":
        raise ValueError(f"{path} 不是 .kicad_pcb")
    board = root[0]
    items: list[Item] = []
    stats = {"footprints": 0, "missing_courtyard": 0, "hull_fallback": 0, "pads": 0}

    for fp in children(board, "footprint"):
        stats["footprints"] += 1
        lib_id = atom(fp, 1, "") or ""
        layer = atom(first(fp, "layer"), 1, "F.Cu")
        side = "F" if str(layer).startswith("F.") else "B"
        flip = side == "B"
        at = first(fp, "at")
        ox, oy = to_float(atom(at, 1)), to_float(atom(at, 2))
        rot = to_float(atom(at, 3))
        ref = ""
        for prop in children(fp, "property"):
            if atom(prop, 1) == "Reference":
                ref = atom(prop, 2, "")
                break
        if not ref:
            txt = first(fp, "fp_text")
            if txt and atom(txt, 1) == "reference":
                ref = atom(txt, 2, "")
        ref = ref or f"<{stats['footprints']}>"

        court_layer = COURTYARD_LAYERS[side]
        fab_layer = FAB_LAYERS[side]
        court_prims, fab_prims = [], []
        for child in fp:
            if not node_name(child) or not node_name(child).startswith("fp_"):
                continue
            lay = atom(first(child, "layer"), 1, "")
            if lay == court_layer:
                court_prims.extend(pcb_graphic_points(child))
            elif lay == fab_layer:
                fab_prims.extend(pcb_graphic_points(child))

        source, conf, geometry = "courtyard", "exact", "courtyard_polygon"
        prims = court_prims
        if not prims:
            stats["missing_courtyard"] += 1
            prims = fab_prims
            source, conf, geometry = "fab", "approx", "fab_polygon"
        if not prims:
            pad_polys, _ = footprint_pads(fp, (ox, oy), rot, flip, layer)
            prims = [convex_hull([p for pad in pad_polys for p in pad])] if pad_polys else []
            source, conf, geometry = "pads", "approx", "pad_envelope"
        if not prims:
            continue

        polys, closed = shape_from_primitives(prims)
        if not closed:
            stats["hull_fallback"] += 1
            conf = "approx"
            geometry = "convex_hull"
        polys = [convex_hull(p) for p in polys if len(p) >= 3]
        if not polys:
            continue
        global_polys = transform_footprint(polys, (ox, oy), rot, flip)
        if include_pads:
            pads_g, pads_approx = footprint_pads(fp, (ox, oy), rot, flip, layer)
        else:
            pads_g, pads_approx = [], False
        stats["pads"] += len(pads_g)
        items.append(Item(ref=ref, lib_id=lib_id, side=side, origin=(ox, oy),
                          rotation=rot, polygons=[convex_hull(p) for p in global_polys],
                          source=source, confidence=conf, geometry=geometry,
                          pads=pads_g, pads_approx=pads_approx))
    return items, stats


# --------------------------------------------------------------------------
# 原理图
# --------------------------------------------------------------------------

SYMBOL_LIB_TABLE = "sym-lib-table"
_BODY_PRIMS = {"rectangle", "polyline", "circle", "arc", "bezier"}


def kicad_symbol_dirs() -> list[Path]:
    dirs: list[Path] = []
    for env in ("KICAD10_SYMBOL_DIR", "KICAD9_SYMBOL_DIR", "KICAD8_SYMBOL_DIR", "KICAD_SYMBOL_DIR"):
        v = os.environ.get(env)
        if v:
            dirs.append(Path(v))
    for base in (r"C:\Program Files\KiCad", r"C:\Program Files (x86)\KiCad"):
        p = Path(base)
        if p.is_dir():
            for ver in sorted(p.iterdir(), reverse=True):
                d = ver / "share" / "kicad" / "symbols"
                if d.is_dir():
                    dirs.append(d)
    return dirs


def load_lib_table(project_dir: Path) -> dict[str, list[Path]]:
    table: dict[str, list[Path]] = {}
    local = project_dir / SYMBOL_LIB_TABLE
    tables = [local] if local.is_file() else []
    # 全局 sym-lib-table
    appdata = os.environ.get("APPDATA")
    if appdata:
        for cand in (Path(appdata) / "kicad" / "10.0" / "sym-lib-table",
                     Path(appdata) / "kicad" / "9.0" / "sym-lib-table"):
            if cand.is_file():
                tables.append(cand)
    for t in tables:
        try:
            root = parse_sexpr(t.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not root:
            continue
        for lib in children(root[0], "lib"):
            name = atom(lib, 1)
            uri = None
            for child in children(lib):
                if node_name(child) == "uri":
                    uri = atom(child, 1)
            if not name or not uri:
                continue
            uri = uri.replace("${KIPRJMOD}", str(project_dir))
            table.setdefault(name, []).append(Path(uri))
    return table


class SymbolLibs:
    def __init__(self, project_dir: Path):
        self.table = load_lib_table(project_dir)
        self.search_dirs = kicad_symbol_dirs() + [project_dir]
        self._cache: dict[str, list[list[Point]] | None] = {}

    def _candidates(self, lib_name: str) -> list[Path]:
        out = list(self.table.get(lib_name, []))
        for d in self.search_dirs:
            out.append(d / f"{lib_name}.kicad_sym")
        return out

    def body(self, lib_id: str, unit: int, style: int) -> list[list[Point]] | None:
        key = f"{lib_id}|{unit}|{style}"
        if key in self._cache:
            return self._cache[key]
        if ":" not in lib_id:
            self._cache[key] = None
            return None
        lib_name, sym_name = lib_id.split(":", 1)
        result = None
        for path in self._candidates(lib_name):
            if not path.is_file():
                continue
            try:
                root = parse_sexpr(path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            if not root:
                continue
            target = None
            for sym in children(root[0], "symbol"):
                if atom(sym, 1) == sym_name:
                    target = sym
                    break
            if target is None:
                continue
            result = self._extract_body(target, unit, style)
            break
        self._cache[key] = result
        return result

    @staticmethod
    def _extract_body(sym, unit: int, style: int) -> list[list[Point]]:
        prims: list[list[Point]] = []
        for sub in children(sym, "symbol"):
            sub_name = atom(sub, 1, "")
            m = re.search(r"_(\d+)_(\d+)$", sub_name)
            if m:
                su, ss = int(m.group(1)), int(m.group(2))
                if su not in (0, unit) or ss not in (0, style):
                    continue
            for prim in sub:
                nm = node_name(prim)
                if nm not in _BODY_PRIMS:
                    continue  # 排除 pin：引脚外伸不是器件体
                pts = SymbolLibs._prim_points(nm, prim)
                if pts:
                    prims.extend(pts)
        return prims

    @staticmethod
    def _prim_points(nm: str, node) -> list[list[Point]]:
        if nm == "rectangle":
            s, e = xy(first(node, "start")), xy(first(node, "end"))
            return [[s, (e[0], s[1]), e, (s[0], e[1])]]
        if nm == "polyline":
            pts = first(node, "pts")
            if not pts:
                return []
            xypts = [xy(p) for p in children(pts, "xy")]
            return [xypts] if len(xypts) >= 2 else []
        if nm == "circle":
            c, e = xy(first(node, "center")), xy(first(node, "end"))
            return [circle_poly(c, math.dist(c, e), 24)]
        if nm == "arc":
            return [arc_poly(xy(first(node, "start")), xy(first(node, "mid")),
                             xy(first(node, "end")))]
        if nm == "bezier":
            pts = first(node, "pts")
            if not pts:
                return []
            p = [xy(x) for x in children(pts, "xy")]
            return [convex_hull(p)] if len(p) >= 3 else []
        return []


def schematic_sheet_files(root_file: Path) -> list[Path]:
    seen: list[Path] = []
    queue = [root_file]
    while queue:
        f = queue.pop(0).resolve()
        if f in seen or not f.is_file():
            continue
        seen.append(f)
        try:
            root = parse_sexpr(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not root:
            continue
        for sheet in children(root[0], "sheet"):
            for prop in children(sheet, "property"):
                if atom(prop, 1) == "Sheetfile":
                    target = atom(prop, 2, "")
                    if target and (f.parent / target).is_file():
                        queue.append(f.parent / target)
    return seen


def transform_symbol(prims: list[list[Point]], origin: Point, rot: float,
                     mirror: str | None) -> list[list[Point]]:
    out = []
    for prim in prims:
        tp = []
        for x, y in prim:
            sx, sy = x, -y                      # 库坐标 Y 向上 -> 屏幕 Y 向下
            if mirror == "x":
                sy = -sy
            elif mirror == "y":
                sx = -sx
            rx, ry = rotate_kicad((sx, sy), rot)
            tp.append((rx + origin[0], ry + origin[1]))
        out.append(tp)
    return out


def extract_schematic(path: Path) -> tuple[list[Item], dict]:
    libs = SymbolLibs(path.parent)
    stats = {"sheets": 0, "symbols": 0, "resolved": 0, "unresolved": 0, "no_geometry": 0}
    items: list[Item] = []
    for sheet_file in schematic_sheet_files(path):
        stats["sheets"] += 1
        try:
            root = parse_sexpr(sheet_file.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not root:
            continue
        for sym in children(root[0], "symbol"):
            stats["symbols"] += 1
            lib_id = atom(first(sym, "lib_id"), 1, "")
            at = first(sym, "at")
            ox, oy = to_float(atom(at, 1)), to_float(atom(at, 2))
            rot = to_float(atom(at, 3))
            mirror_node = first(sym, "mirror")
            mirror = atom(mirror_node, 1) if mirror_node else None
            unit = int(to_float(atom(first(sym, "unit"), 1), 1))
            style = int(to_float(atom(first(sym, "body_style"), 1), 1))
            ref = ""
            for prop in children(sym, "property"):
                if atom(prop, 1) == "Reference":
                    ref = atom(prop, 2, "")
                    break
            prims = libs.body(lib_id, unit, style)
            if prims is None:
                stats["unresolved"] += 1
                items.append(Item(ref=ref or "?", lib_id=lib_id, side="sheet",
                                  origin=(ox, oy), rotation=rot, polygons=[],
                                  source="unresolved", confidence="none",
                                  geometry="none", sheet=sheet_file.name))
                continue
            stats["resolved"] += 1
            if not prims:
                stats["no_geometry"] += 1
                continue
            # 全部由矩形组成时，凸包与原形状等价 -> exact；含圆/多边形 -> approx
            conf = "exact" if all(len(p) == 4 for p in prims) else "approx"
            polys = [convex_hull(p) for p in prims if len(p) >= 3]
            polys = transform_symbol(polys, (ox, oy), rot, mirror)
            items.append(Item(ref=ref or "?", lib_id=lib_id, side="sheet",
                              origin=(ox, oy), rotation=rot,
                              polygons=[convex_hull(p) for p in polys],
                              source="body", confidence=conf,
                              geometry="symbol_body", sheet=sheet_file.name))
    return items, stats


# --------------------------------------------------------------------------
# 检测
# --------------------------------------------------------------------------

def bbox_of(polys: list[list[Point]]):
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def bbox_gap(a, b) -> float:
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return math.hypot(dx, dy)


def pair_overlap(a: Item, b: Item, min_area: float, kind: str,
                 touch_mm: float = 0.0) -> Finding | None:
    best_area = 0.0
    best_depth = 0.0
    for pa in a.polygons:
        for pb in b.polygons:
            if polygon_area(pa) <= 0 or polygon_area(pb) <= 0:
                continue
            depth = sat_depth(pa, pb)
            if depth <= 0:
                continue
            inter = clip_convex(pa, pb)
            area = polygon_area(inter) if len(inter) >= 3 else 0.0
            if area > best_area:
                best_area = area
                best_depth = depth
    if best_area <= 0 or best_area < min_area:
        return None
    conf = "approx" if (a.confidence == "approx" or b.confidence == "approx") else "exact"
    geometry = a.geometry if a.geometry == b.geometry else f"{a.geometry}+{b.geometry}"
    # 几何精确 -> block；近似 -> review（不得直接阻断）
    effect = "block" if conf == "exact" else "review"
    # 包络相切（穿透深度小于容差）视为“贴边”而非真重叠：
    # courtyard 本身是余量，亚 0.02mm 的相交属于网格/制造噪声。
    touching = kind == "overlap" and 0 < best_depth < touch_mm
    if touching:
        return Finding(kind="touch", severity="info",
                       ref_a=a.ref, ref_b=b.ref, area_mm2=best_area,
                       distance_mm=0.0, where=a.side if a.side != "sheet" else a.sheet,
                       detail=f"{a.source}/{b.source} 相切（穿透 {best_depth*1000:.0f}µm）",
                       confidence=conf, geometry=geometry, gate_effect="info",
                       penetration_mm=best_depth)
    return Finding(kind=kind, severity="error" if effect == "block" else "warning",
                   ref_a=a.ref, ref_b=b.ref, area_mm2=best_area, distance_mm=0.0,
                   where=a.side if a.side != "sheet" else a.sheet,
                   detail=f"{a.source}/{b.source} 包络相交", confidence=conf,
                   geometry=geometry, gate_effect=effect,
                   penetration_mm=best_depth)


def detect(items: list[Item], min_area: float, include_pads: bool,
           touch_mm: float = 0.02) -> list[Finding]:
    findings: list[Finding] = []
    by_side: dict[tuple[str, str], list[Item]] = {}
    for it in items:
        if not it.polygons:
            continue
        # 原理图按“图页 + 面”分组：跨图页的符号本来就可以重叠
        by_side.setdefault((it.side, it.sheet), []).append(it)

    for (side, _sheet), group in by_side.items():
        boxes = {id(it): bbox_of(it.polygons) for it in group}
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                ba, bb = boxes[id(a)], boxes[id(b)]
                if ba and bb and bbox_gap(ba, bb) > 40.0:
                    continue  # 粗筛：相距 40mm 以上不可能相交
                f = pair_overlap(a, b, min_area, "overlap", touch_mm)
                if f:
                    findings.append(f)
                if include_pads and a.pads and b.pads:
                    pad_conf = "approx" if (a.pads_approx or b.pads_approx) else "exact"
                    pad_geom = "pad_aabb" if pad_conf == "approx" else "pad_outline"
                    pad_effect = "block" if pad_conf == "exact" else "review"
                    for pa in a.pads:
                        for pb in b.pads:
                            if sat_overlap(pa, pb):
                                inter = clip_convex(pa, pb)
                                area = polygon_area(inter) if len(inter) >= 3 else 0.0
                                if area > 1e-6:
                                    findings.append(Finding(
                                        kind="pad_overlap",
                                        severity="error" if pad_effect == "block" else "warning",
                                        ref_a=a.ref, ref_b=b.ref, area_mm2=area,
                                        distance_mm=0.0, where=side,
                                        detail="不同 footprint 的铜箔焊盘相交",
                                        confidence=pad_conf, geometry=pad_geom,
                                        gate_effect=pad_effect))
    return findings


def unresolved_findings(items: list[Item]) -> list[Finding]:
    return [Finding(kind="unresolved_symbol", severity="warning", ref_a=it.ref,
                    ref_b=it.lib_id, area_mm2=0.0, distance_mm=0.0,
                    where=it.sheet, detail="符号库未解析，未参与几何判定",
                    confidence="none", geometry="none", gate_effect="incomplete")
            for it in items if it.source == "unresolved"]


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------

def render_svg(items: list[Item], findings: list[Finding], out: Path, title: str):
    all_polys = [p for it in items for p in it.polygons]
    bb = bbox_of(all_polys)
    if not bb:
        out.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
        return
    pad = 8.0
    x0, y0, x1, y1 = bb[0] - pad, bb[1] - pad, bb[2] + pad, bb[3] + pad
    w, h = max(x1 - x0, 1e-3), max(y1 - y0, 1e-3)
    scale = 1400.0 / max(w, h)

    hit_refs = {f.ref_a for f in findings if f.kind in ("overlap", "pad_overlap")} | \
               {f.ref_b for f in findings if f.kind in ("overlap", "pad_overlap")}
    touch_refs = {f.ref_a for f in findings if f.kind == "touch"} | \
                 {f.ref_b for f in findings if f.kind == "touch"}
    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{w*scale:.0f}' height='{h*scale:.0f}' "
        f"viewBox='{x0:.3f} {y0:.3f} {w:.3f} {h:.3f}'>",
        "<style>text{font-family:Consolas,monospace;font-size:1.6px;fill:#eee}"
        ".ok{fill:#1b4d3e;fill-opacity:.45;stroke:#2ec4a6;stroke-width:.08}"
        ".warn{fill:#5c4b12;fill-opacity:.6;stroke:#e6b800;stroke-width:.12}"
        ".bad{fill:#7a1f1f;fill-opacity:.75;stroke:#ff5252;stroke-width:.15}"
        "</style>",
        f"<rect x='{x0:.3f}' y='{y0:.3f}' width='{w:.3f}' height='{h:.3f}' fill='#111'/>",
    ]
    for it in items:
        if it.ref in hit_refs:
            cls = "bad"
        elif it.ref in touch_refs:
            cls = "warn"
        else:
            cls = "ok"
        for poly in it.polygons:
            pts = " ".join(f"{x:.3f},{y:.3f}" for x, y in poly)
            parts.append(f"<polygon class='{cls}' points='{pts}'/>")
        if it.polygons:
            cx, cy = polygon_centroid(it.polygons[0])
            parts.append(f"<text x='{cx:.3f}' y='{cy:.3f}' text-anchor='middle'>{it.ref}</text>")
    parts.append(f"<text x='{x0+1:.2f}' y='{y1-1:.2f}' style='font-size:2.4px'>{title}</text>")
    parts.append("</svg>")
    out.write_text("\n".join(parts), encoding="utf-8")


def print_report(findings: list[Finding], stats: dict, label: str, quiet: bool):
    if quiet:
        return
    print(f"\n=== {label} ===")
    print("统计：" + ", ".join(f"{k}={v}" for k, v in stats.items()))
    if not findings:
        print("结果：未发现重叠 → PASS")
        return
    blocks = [f for f in findings if f.gate_effect == "block"]
    reviews = [f for f in findings if f.gate_effect == "review"]
    incomplete = [f for f in findings if f.gate_effect == "incomplete"]
    touch = [f for f in findings if f.kind == "touch"]
    print(f"结果：block={len(blocks)} review={len(reviews)} "
          f"incomplete={len(incomplete)} info(相切)={len(touch)}")
    if blocks or reviews:
        print(f"{'类型':<14}{'A':<8}{'B':<8}{'面积mm²':>9}{'穿透mm':>8}{'几何':<20}{'影响':<10}")
        for f in blocks + reviews:
            print(f"{f.kind:<14}{f.ref_a:<8}{f.ref_b:<8}{f.area_mm2:>9.3f}"
                  f"{f.penetration_mm:>8.3f}{f.geometry:<20}{f.gate_effect:<10}")
    if touch:
        print("相切（穿透 < 阈值，通常为贴边摆放，info）：")
        for f in touch:
            print(f"  {f.ref_a} ↔ {f.ref_b}  穿透 {f.penetration_mm*1000:.0f}µm  ({f.where})")
    if incomplete:
        print("未解析（未参与几何判定 → INCOMPLETE）：")
        for f in incomplete:
            print(f"  {f.ref_a}  {f.detail}")


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="KiCad 元件重叠检测（只读）")
    ap.add_argument("path")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--svg", dest="svg_out")
    ap.add_argument("--min-area", type=float, default=0.0, help="小于该面积(mm²)的相交忽略")
    ap.add_argument("--touch-mm", type=float, default=0.02,
                    help="穿透深度小于该值视为贴边相切（默认 0.02mm）")
    ap.add_argument("--include-pads", action="store_true", help="同时检查不同 footprint 的焊盘相交")
    ap.add_argument("--fail-on-overlap", action="store_true",
                    help="存在 gate_effect=block 的重叠时退出码 1")
    ap.add_argument("--fail-on-review", action="store_true",
                    help="存在 block 或待复核(review)时退出码 1")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    path = Path(args.path)
    if not path.is_file():
        print(f"找不到文件：{path}", file=sys.stderr)
        return 2

    report = {"tool": "pcb_overlap", "version": "0.1", "inputs": [str(path)],
              "checks": []}
    findings: list[Finding] = []
    all_items: list[Item] = []
    labels = []

    try:
        if path.suffix == ".kicad_pcb":
            items, stats = extract_pcb(path, args.include_pads)
            all_items += items
            findings += detect(items, args.min_area, args.include_pads, args.touch_mm)
            findings += unresolved_findings(items)
            report["checks"].append({"kind": "pcb", "stats": stats})
            labels.append("PCB")
        elif path.suffix == ".kicad_sch":
            items, stats = extract_schematic(path)
            all_items += items
            findings += detect(items, args.min_area, False, args.touch_mm)
            findings += unresolved_findings(items)
            report["checks"].append({"kind": "schematic", "stats": stats})
            labels.append("原理图")
        elif path.suffix == ".kicad_pro":
            pcb = path.with_suffix(".kicad_pcb")
            sch = path.with_suffix(".kicad_sch")
            if pcb.is_file():
                items, stats = extract_pcb(pcb, args.include_pads)
                all_items += items
                findings += detect(items, args.min_area, args.include_pads, args.touch_mm)
                findings += unresolved_findings(items)
                report["checks"].append({"kind": "pcb", "stats": stats, "file": str(pcb)})
            if sch.is_file():
                items, stats = extract_schematic(sch)
                all_items += items
                findings += detect(items, args.min_area, False, args.touch_mm)
                findings += unresolved_findings(items)
                report["checks"].append({"kind": "schematic", "stats": stats, "file": str(sch)})
            labels.append("PCB + 原理图")
        else:
            print(f"不支持的文件类型：{path.suffix}", file=sys.stderr)
            return 2
    except Exception as exc:  # noqa: BLE001
        if os.environ.get("PCB_OVERLAP_DEBUG"):
            import traceback
            traceback.print_exc()
        print(f"解析失败：{exc}", file=sys.stderr)
        return 2

    findings.sort(key=lambda f: (f.kind, -f.area_mm2))
    report["findings"] = [f.as_dict() for f in findings]
    blocks = [f for f in findings if f.gate_effect == "block"]
    reviews = [f for f in findings if f.gate_effect == "review"]
    incompletes = [f for f in findings if f.gate_effect == "incomplete"]
    verdict = "BLOCKED" if blocks else ("INCOMPLETE" if (reviews or incompletes) else "PASS")
    report["summary"] = {
        "blocks": len(blocks),
        "reviews": len(reviews),
        "incomplete": len(incompletes),
        "touches": sum(1 for f in findings if f.kind == "touch"),
        "overlaps": sum(1 for f in findings if f.kind in ("overlap", "pad_overlap")),
        "pad_overlaps": sum(1 for f in findings if f.kind == "pad_overlap"),
        "unresolved": sum(1 for f in findings if f.kind == "unresolved_symbol"),
        "verdict": verdict,
    }

    print_report(findings, {"items": len(all_items)}, " / ".join(labels), args.quiet)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    if args.svg_out:
        render_svg(all_items, findings, Path(args.svg_out), " / ".join(labels))

    if args.fail_on_overlap and report["summary"]["blocks"]:
        return 1
    if args.fail_on_review and (report["summary"]["blocks"] or report["summary"]["reviews"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
