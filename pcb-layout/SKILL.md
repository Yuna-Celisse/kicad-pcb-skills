---
name: pcb-layout
description: "KiCad PCB 布局与叠层：功能分区、连接器/去耦/晶振/DCDC 摆放、热与机械禁布、2/4/6 层叠层、布局评审。触发：布局、摆放、板框、安装孔、叠层、阻抗目标、去耦、晶振、散热。English: PCB layout, placement, floorplan, stackup, keepout."
metadata: { version: 0.3, requires: "konnect>=0.13, kicad>=10" }
---

# PCB 布局（pcb-layout）

目标：让**电流与信号按设计方向流动**，把热、机械、可制造性约束提前解决。
布局错了，布线只能补救。判据尽量可检查（距离、面积、重叠），经验值标 `HEURISTIC`。

## 何时用 / 何时不用

用：

- 原理图冻结后开始摆放、定板框/安装孔/叠层。
- 评审布局（分区、去耦、晶振、DCDC、热、禁布）。
- 选择 2/4/6 层叠层与阻抗目标。

不用：

- 走线与规则 → `pcb-routing`。
- 器件选型 → `pcb-components`。
- 验证签核 → `pcb-verification` / `pcb-flow`。

## 前置条件

| 项 | 要求 |
|---|---|
| 原理图 | 已冻结，网表/位号稳定 |
| 机械 | 板框、安装孔、连接器位置、高度限制已知 |
| 叠层 | 目标层数/板厚/阻抗已定（或本阶段确定） |
| 工具 | `pcb_overlap.py` 可用；Konnect `pcb_components`/`pcb_board`/`placement` |

## 决策流程

1. **定板框与机械**：安装孔、板边禁布、连接器位置、V-cut/拼板方向。
2. **分区**：按功能块聚簇，确定流向（连接器→保护→滤波→IC）。
3. **放大件**：连接器、IC、电感、晶振、大电容先落位。
4. **去耦与关键网络**：去耦贴近电源脚；晶振贴 MCU；DCDC hot loop 最小。
5. **热与敏感件**：功率器件铜箔/散热；热敏件远离热源。
6. **评审**：`pcb_overlap` 无 block；`score_placement` 看扣分项。
7. **冻结**：布局冻结后再布线；变更要回评审。

## 分区与流向

| 区域 | 内容 | 要点 |
|---|---|---|
| 入口 | 连接器、ESD、保险丝 | 靠板边，ESD 最近入口 |
| 电源 | DCDC/LDO、电感、大电容 | 远离模拟/晶振；hot loop 小 |
| 数字 | MCU、存储、总线 | 居中，靠近接口 |
| 模拟 | 前端、基准、滤波 | 远离 DCDC/SW，单独地回流 |
| RF | 天线、匹配 | 按净空/参考地要求，靠板边 |
| 接口 | USB/以太网/CAN | 连接器到 IC 路径最短 |

单向流动：连接器 → 保护 → 滤波 → IC；避免来回穿插。

## 关键摆放

### 去耦（HEURISTIC，手册优先）

- 每个电源脚 100nF，尽量 ≤2–3mm；大电容按电源域。
- 地过孔就近，回路面积最小；电容不要放在板另一面远距离。
- 多电源脚：先小后大，先近后远。

### 晶振

- 紧贴 MCU，走线短且等长；下方不走线、不铺铜（按器件要求）。
- 负载电容对称、接地就近；包地。
- 远离 DCDC/SW、时钟输出、连接器。

### 开关电源

- 输入电容紧贴 Vin/GND；hot loop（输入电容→高侧→低侧→回电容）面积最小。
- SW 节点铜箔小而短；反馈开尔文取样，远离电感。
- 电感下方不走敏感信号；地平面单点汇合。

### 连接器

- 板边、插拔方向朝外；应力由结构/固定脚承担。
- ESD 靠近入口；差分对从连接器到 IC 尽量直。
- 高连接器注意外壳与装配顺序。

## 热

- `Tj = Ta + P × θJA`；铜箔面积/thermal via 按热阻核算。
- 功率器件分散布置，避免热点叠加；热敏件远离。
- 散热焊盘电位按器件手册（GND/负电源/浮空），不默认接地。

见 [thermal.md](references/thermal.md)。

## 机械与禁布

| 项 | 经验值（`HEURISTIC`） |
|---|---|
| M3 安装孔 | 孔径 3.2mm，禁布 ≥6mm |
| 板边 | 器件/走线 ≥3–5mm（按板厂/结构） |
| V-cut | 两侧留 5mm 工艺边，槽线禁布 |
| 拼板 | Mark 点 3 个、非对称 |
| 高度 | 按外壳/装配包络 |

见 [mechanical-keepout.md](references/mechanical-keepout.md)。

## 叠层

| 层数 | 典型角色 | 用途 |
|---|---|---|
| 2 | 信号 / 地（或电源） | 低成本、低速 |
| 4 | 信号 / GND / PWR / 信号 | 通用，阻抗可控 |
| 6 | 信号/GND/信号/PWR/GND/信号 | 高速/混合信号 |

- 每个信号层尽量邻接完整参考平面；不要跨分割。
- 阻抗目标（50Ω 单端、90/100Ω 差分）与线宽/介质一起定。
- 以板厂实际叠层为准；下单前确认 PP/芯板厚度。

见 [stackup-design.md](references/stackup-design.md) 与
[stackup-presets.md](assets/stackup-presets.md)。

## 布局评审

```bash
python pcb-toolkit/scripts/pcb_overlap.py board.kicad_pcb --json reports/overlap_P6.json
```

- 符号/封装重叠 `block` 必须修；`review` 人工确认。
- `score_placement` 的扣分项逐条看（间距、对齐、边缘）。
- 布局冻结前跑一次 `pcb-verification` 的 P6（drc+overlap）。

## 速查

- 分区：[floorplanning.md](references/floorplanning.md)
- 摆放规则：[placement-rules.md](references/placement-rules.md)
- 热：[thermal.md](references/thermal.md)
- 叠层：[stackup-design.md](references/stackup-design.md)
- 机械：[mechanical-keepout.md](references/mechanical-keepout.md)
- 布线：[../pcb-routing/SKILL.md](../pcb-routing/SKILL.md)

## 反模式

| 反模式 | 后果 | 正确做法 |
|---|---|---|
| 先布线后补去耦 | 回路大、EMC 差 | 去耦先落位 |
| 晶振远离 MCU | 时钟抖动/不起振 | 贴近、包地 |
| DCDC hot loop 大 | 辐射/纹波 | 输入电容紧贴 |
| 散热焊盘默认接地 | 短路/浮空失效 | 按手册确认电位 |
| 忽视板边禁布 | 铣边伤线 | 留 3–5mm |
| 叠层先定死再算阻抗 | 阻抗失控 | 叠层与阻抗一起定 |

## 完成判据

1. 板框/安装孔/禁布/连接器符合机械图。
2. 分区与流向清晰；去耦/晶振/DCDC 按规则落位。
3. `pcb_overlap` 无 block；`score_placement` 扣分已解释。
4. 叠层与阻抗目标确定，板厂可生产。
5. 布局冻结并记录版本；P6 Gate 已跑。

## 参考与来源

- KiCad 10：Board Editor、Board Setup、Design Rules。
- IPC-2221（通用设计）、IPC-7351（焊盘）、IPC-2141（阻抗估算）。
- Konnect：`pcb_board`、`pcb_components`、`placement`。
- 规范：`../pcb-flow/references/core-semantics.md`。
