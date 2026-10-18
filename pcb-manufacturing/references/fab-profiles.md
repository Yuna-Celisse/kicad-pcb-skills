# 板厂 profile（fab-profiles）

## 结构

每个 profile 是一份 JSON（见 [fab-profile.schema.json](../assets/fab-profile.schema.json)）：

```json
{
  "id": "jlcpcb-4l",
  "fab": "JLCPCB",
  "url": "https://jlcpcb.com/capabilities/pcb-capabilities",
  "retrieved": "2026-10-19",
  "layers": [4, 6],
  "min_trace_mm": 0.127,
  "min_space_mm": 0.127,
  "min_via_hole_mm": 0.2,
  "min_pth_hole_mm": 0.2,
  "min_npth_hole_mm": 0.5,
  "annular_ring_mm": 0.13,
  "board_edge_mm": 0.3,
  "silk_min_text_mm": 0.8,
  "silk_min_line_mm": 0.15,
  "finishes": ["HASL", "ENIG"],
  "notes": "示例值；下单前按官网/工程回复复核"
}
```

> 上例是**模板值**，不是承诺。真实项目必须重新核对 URL 并更新 `retrieved`。
> 孔能力分 `via / PTH / NPTH` 三类；某类未列出时写 `null`（待确认），
> 不能拿另一类的数值套用。NPTH 通常明显大于 PTH。

**口径**：

- 孔尺寸为**成品孔径**（镀铜后）；钻刀尺寸由板厂补偿，不要混用。
- 距离为**边缘到边缘**（孔到孔、孔到铜），不是中心距。

## 已知平台差异（需复核）

| 平台 | 特点 | 注意 |
|---|---|---|
| JLCPCB | 基础库/上料费、4/6 层 | 能力页随工艺更新 |
| PCBWay | 打样/小批量 | 阻抗/特殊工艺另询 |
| OSH Park | 美产、紫色阻焊 | 层数/尺寸限制 |

不要把某一家的数值套到另一家。

## 使用规则

1. 选定板厂 → 打开能力页 → 逐项抄录 → 写 `retrieved`。
2. 设计规则（`.kicad_dru`/netclass）不得低于 profile 能力。
3. profile 变更 → 重跑 DFM 检查与 DRC。
4. 超能力项必须走 EQ 书面确认，不能默认"应该能做"。
5. 归档：profile 随输出包保存，便于追溯。

## 过期

- `retrieved` 超过 6 个月（`HEURISTIC`）→ 重新核对。
- 板厂公告/工艺变更 → 立即重核。
- 用旧 profile 出的包，投板前再确认一次。
