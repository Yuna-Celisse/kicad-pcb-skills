---
name: pcb-manufacturing
description: "KiCad 制造与出图：DFM 检查、板厂 profile、Gerber/钻孔/BOM/CPL 输出包、拼板、装配与测试、投板 EQ。触发：出图、Gerber、钻孔、BOM、CPL、拼板、V-cut、DFM、投板、板厂、钢网、阻抗测试。English: manufacturing, Gerber, drill, BOM, CPL, panelization, DFM, fab."
metadata: { version: 0.3, requires: "konnect>=0.13, kicad>=10" }
---

# 制造与出图（pcb-manufacturing）

目标：把设计变成**板厂能直接做、产线能直接贴**的文件包，并把能力边界写清楚。
任何能力值必须带**来源 URL + 抓取日期**；过期即重新核对。

## 何时用 / 何时不用

用：

- P9 出 Gerber/钻孔/BOM/CPL，准备投板。
- DFM 复核（线宽/间距/孔径/环宽/丝印/板边）。
- 拼板、Mark 点、工艺边、V-cut。
- 板厂 EQ（阻抗、叠层、孔铜、表面处理）。

不用：

- 布局/布线 → `pcb-layout` / `pcb-routing`。
- DRC/ERC 判定 → `pcb-verification`。
- 选型/降额 → `pcb-components`。

## 前置条件

| 项 | 要求 |
|---|---|
| 设计 | 布局/布线冻结；DRC 已跑；P8 Gate 通过 |
| 板厂 | 目标 fab profile 已选（含 URL/日期） |
| 叠层 | 层数/板厚/阻抗目标确定 |
| 输出 | 输出目录、命名规则、版本号确定 |
| 工具 | `pcb_export` / `manufacturing` toolset；`kicad-cli` |

## 流程

1. **DFM 预检**：按 §DFM 矩阵逐项，超出能力先改设计。
2. **锁 profile**：确认板厂能力值（URL + 日期），写入 `fab-profile.json`。
3. **出包**：Gerber、钻孔（PTH/NPTH 分开）、叠层图、BOM、CPL、装配图。
4. **拼板**：Mark 点、工艺边、V-cut/邮票孔、阴阳板评估。
5. **自检**：用 Gerber 查看器/`gerber` 工具复核层与孔。
6. **EQ**：把阻抗/叠层/孔铜/表面处理/颜色/公差写进下单备注。
7. **归档**：输出 manifest + 校验和；P9/P10 Gate 记录。

## DFM 矩阵（保守起点）

> 下面是**保守起点**，不是板厂承诺；以目标 fab profile 的实际能力为准。
> 孔为**成品孔径**（镀铜后），距离为**边缘到边缘**；某类孔未确认时保持待确认。

| 项 | 保守值 | 说明 |
|---|---|---|
| 线宽/间距 | ≥0.15mm | 低于 0.127mm 需确认 |
| 过孔成品孔径 | ≥0.3mm | 更小需确认/加价 |
| PTH 插件孔成品孔径 | ≥0.3mm | 按元件引脚 |
| NPTH 成品孔径 | ≥0.5mm | 按板厂；不得套用 PTH 数值 |
| 环宽 | ≥0.15mm | 按孔径与板厂 |
| 阻焊桥 | ≥0.1mm | 细间距需确认 |
| 丝印字高 | ≥0.8mm | 字宽/线宽 ≥0.15mm |
| 板边距 | ≥0.3mm 铜到边 | 按铣刀/公差 |
| 槽孔 | 按板厂 | 长宽比限制 |
| V-cut | 直线、深度一致 | 两侧 5mm 工艺边 |
| 阻抗 | 测试 coupon | 按叠层 |

完整矩阵见 [dfm-matrix.md](references/dfm-matrix.md)。

## 板厂 profile

- 每个 profile 必须含：`id`、`url`、`retrieved`（YYYY-MM-DD）、层数、最小线宽/间距、
  孔能力（via/PTH/NPTH 分开）、环宽、板边、丝印字高/线宽、表面处理、备注。
- 能力值**不凭记忆**；从官网/工程回复抄录，并记录日期。
- 某类孔未确认时写 `null`，保持待确认，不得套用其他孔型。
- profile 过期（如 >6 个月）或板厂规则变更 → 重新核对后再出包。

结构见 [fab-profile.schema.json](assets/fab-profile.schema.json)，
示例与差异见 [fab-profiles.md](references/fab-profiles.md)。

## 输出包

| 文件 | 内容 |
|---|---|
| Gerber | 每层一个，含板框/阻焊/丝印/钢网（如需要） |
| 钻孔 | PTH / NPTH 分开，含槽孔 |
| 叠层图 | 层序、厚度、阻抗目标 |
| BOM | LCSC/MPN/位号/值/封装/DNP |
| CPL | 位号、X/Y、旋转、面 |
| 装配图 | 顶/底、极性、DNP 标识 |
| manifest | 文件清单 + 版本 + 校验和 |

命名与清单见 [output-package.md](references/output-package.md) 与
[output-manifest.template.md](assets/output-manifest.template.md)。

## 拼板

- Mark 点：3 个、非对称、阻焊开窗、远离板边。
- 工艺边：5mm；V-cut 直线、深度一致。
- 邮票孔：孔径/孔距按板厂；分板应力远离陶瓷件/晶振。
- 阴阳板：评估工艺、支撑、贴片方向。
- 拼板尺寸/利用率与板厂确认。

见 [panelization.md](references/panelization.md)。

## 装配与测试

- 测试点 ≥1.0mm、间距 2.54mm；ICT/飞针可达。
- 烧录口/调试口可访问；防呆。
- DNP 在 BOM/CPL/装配图一致。
- 钢网厚度/开孔按间距；QFN 散热焊盘分区。
- 首件确认（FAI）：极性、方向、偏移、少件。

见 [assembly-and-test.md](references/assembly-and-test.md)。

## 投板 EQ 清单

- [ ] 层数/板厚/叠层
- [ ] 阻抗目标与测试 coupon
- [ ] 孔铜厚度/表面处理（HASL/ENIG/…）
- [ ] 阻焊/丝印颜色
- [ ] 板边/V-cut/拼板
- [ ] 公差与外观标准
- [ ] 数量/交期/文件版本

## 验证衔接

```bash
python pcb-toolkit/scripts/gate.py --phase P9 --intent design-intent.json \
  --drc reports/drc_P9.json --erc reports/erc_P9.json \
  --overlap reports/overlap_P9.json --lint reports/lint_P9.json \
  --gen reports/gen_P9.json --waivers reports/waivers.json \
  --json reports/gate_P9.json
```

- P9/P10 需要 `gen`；`BLOCKED/INCOMPLETE` 不得投板。
- 出包后若改设计，必须重新出包并重跑 Gate。

## 反模式

| 反模式 | 后果 | 正确做法 |
|---|---|---|
| 凭记忆写板厂能力 | 超能力被拒/良率低 | URL + 日期 + 复核 |
| Gerber 与 BOM 版本不一致 | 贴错/缺件 | 同一版本号 + manifest |
| 钻孔 PTH/NPTH 混一起 | 孔铜/装配错误 | 分开输出 |
| 拼板只算利用率 | 分板伤件 | 应力/工艺边评估 |
| DNP 只在口头 | 多贴/少贴 | BOM/CPL/装配图一致 |
| 不看出图预览 | 层错/镜像 | Gerber 查看器复核 |

## 完成判据

1. DFM 全部项在 profile 能力内（或已书面确认）。
2. 输出包齐全，版本/校验和一致；Gerber 预览无误。
3. BOM/CPL/装配图 DNP 一致。
4. 拼板/Mark/工艺边符合板厂规则。
5. P9/P10 Gate 通过；EQ 清单已确认。

## 参考与来源

- 目标板厂能力页（URL + 抓取日期）。
- IPC-2221/7351；IPC-A-600（外观）。
- KiCad 10：Plot/Gerber、Drill、Position files。
- Konnect：`pcb_export`、`manufacturing`。
- 规范：`../pcb-flow/references/core-semantics.md`。
