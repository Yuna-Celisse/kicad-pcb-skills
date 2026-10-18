---
name: pcb-components
description: KiCad 器件选型与 BOM 健康：降额、无源/有源选择、封装装配、供货与生命周期、替代料。触发：选型、选电阻电容、降额、BOM 审查、替代料、停产、JLC 基础库、封装选择。English: component selection, derating, BOM, sourcing, alternate parts.
metadata: { version: 0.3, requires: "konnect>=0.13, kicad>=10" }
---

# 器件选型（pcb-components）

负责**可核算的降额、可采购的料号、可装配的封装**。权威按域解析
（core-semantics §2 的 `DOMAIN_POLICY`）：安全项看 `STANDARD`，制造项看 `FAB`，
器件参数看 `DATASHEET`/`STANDARD`，项目只能在允许的域内收紧。
经验值不是基线，必须标 `HEURISTIC`；项目正式采用后登记为 candidate，而非 assumption。

## 何时用 / 何时不用

用：

- 新设计选型、BOM 审查、替代料评估。
- 降额核算、封装/装配可行性、供货风险。
- 判断某个料是否该进 BOM、是否该 DNP。

不用：

- 画图/连线 → `pcb-schematic`。
- 布局/布线 → `pcb-layout` / `pcb-routing`。
- 阶段推进/签核 → `pcb-flow`。

## 前置条件

| 项 | 要求 |
|---|---|
| 需求 | 电压/电流/温度/精度/封装约束已写入 Design Intent |
| 工具 | Konnect `integration` 工具可用：`search_jlcpcb_parts`、`get_jlcpcb_part`、`suggest_jlcpcb_alternatives`、`check_bom_health` |
| 数据手册 | 关键器件必须有可追溯手册（URL 或本地 PDF + 版本） |
| 板厂 | 目标 fab profile（如 JLCPCB 2L/4L）与其能力值、日期 |

## 决策流程

1. **列约束**：每路电源/信号给出电压、电流、频率、温度、精度、封装上限。
2. **定品类**：先无源后有源；先基础库后扩展库。
3. **算降额**：按 §降额基线 逐项核算，记录"计算值 / 额定值 / 余量"。
4. **查供货**：库存、MOQ、生命周期、替代料（同封装同引脚）。
5. **定封装**：装配能力（手焊/回流）、焊盘、散热、机械固定。
6. **落 BOM**：字段齐全、值收敛、一料一源。
7. **复核**：`check_bom_health` + BOM 模板逐项；P2 Gate 通过后冻结。

## 降额基线（必须逐项核算）

| 器件 | 规则 | 说明 |
|---|---|---|
| 电阻 | 实际功率 ≤ 50–60% 额定 | 脉冲/浪涌另算 |
| 陶瓷电容 | 耐压 ≥ 1.5–2× 工作电压 | 必须计入 DC bias 容量损失 |
| 电解电容 | 耐压 ≥ 1.25×；按 105°C 寿命折算 | 纹波电流也要满足 |
| 电感 | Isat ≥ 1.3× 峰值电流 | 同时算 DCR 压降与温升 |
| 二极管/MOS | Vr/Vds ≥ 1.5–2× 实际应力 | 雪崩/浪涌另算 |
| 半导体结温 | `Tj ≤ Tj_max(手册) − 裕量` | 用 K 计裕量；不用摄氏比例 |
| 连接器 | 电流 ≥ 1.5× 实际 | 每 pin 与整体都要满足 |
| TVS | 钳位电压 < 被保护脚 abs max | 同时看峰值脉冲功率 |

规则是**通用经验基线（`HEURISTIC`）**，不是硬约束；数据手册更严时以手册为准。
来源与等级：

- 电阻/陶瓷/电解/电感/连接器的倍率：`HEURISTIC`（行业惯例，项目需自行确认）。
- TVS 钳位：来自被保护器件 `abs max`（`DATASHEET`）。
- 结温上限：来自器件手册的 `Tj_max`（`DATASHEET`）。

项目若正式采用某倍率，登记为 candidate（`authority=PROJECT`、`source` 指向项目记录），
不能只写成 assumption。

降额不满足即**不合格**：换料、改设计，或取得 `authority_required` 豁免（需提供替代主张
并重解析通过）。不得用 assumption 掩盖已知的不满足。

推导与算例见 [derating-and-margins.md](references/derating-and-margins.md)。

## 无源件

- **陶瓷**：C0G/NP0 用于定时、滤波、采样；X7R 用于去耦；避免 Y5V/Z5U。
- **容差**：分压/采样 0.1–1%；去耦 10–20%；定时看振荡器要求。
- **DC bias**：高容值小封装（如 10µF 0603）实际容量可能掉 50%+；按手册曲线核。
- **磁珠**：看 DC bias 后的阻抗与 DCR，不只看 100MHz 标称。
- **电阻**：薄膜/厚膜按精度与温漂；分流电阻看 TCR 与功率。
- **电感**：饱和电流、DCR、屏蔽类型；DCDC 选型见手册。

细则见 [passive-selection.md](references/passive-selection.md)。

## 有源件

- 优先 pin-compatible 多源；避免 EOL/NRND。
- 静态电流（电池设备）、使能/UVLO、内置保护（OVP/OCP/OTP）。
- 逻辑电平匹配（3.3V/5V）、输入阈值、总线电容。
- 隔离器件看隔离等级、爬电距离、认证。
- MCU 看外设数量、封装、调试口、供货周期。

见 [active-and-ic-selection.md](references/active-and-ic-selection.md)。

## 封装与装配

| 场景 | 下限/要求 |
|---|---|
| 手焊 | 0603 及以上；避免 0402 以下 |
| 回流 | 0402/0201 需钢网与贴片能力 |
| QFN/BGA | 回流 + 散热焊盘 + 过孔 |
| 连接器 | 优先带机械固定脚/定位柱 |
| 大功率 | 散热焊盘、铜箔面积、thermal via |

见 [package-and-assembly.md](references/package-and-assembly.md)。

## 供货与生命周期

- JLCPCB Basic 优先（免上料费/库存稳）；Extended 需确认库存与 MOQ。
- 替代料必须同封装、同引脚、同极性；参数不得降级。
- 生命周期：Active > NRND > EOL；EOL 必须给替代料或最后一次采购计划。
- 交期与库存深度写入选型记录；关键料至少一个替代。

见 [sourcing-and-lifecycle.md](references/sourcing-and-lifecycle.md)。

## BOM 卫生

必填字段：

```
Reference, Value, MPN, LCSC, Package, Tolerance, Voltage, Dielectric,
Current, Power, DNP, Source, Notes
```

- 一料一源；同一值不要出现多种封装/精度而无理由。
- DNP 必须显式标注，不能靠"不贴"口头约定。
- 替代料放独立列或独立表，不覆盖主料。
- 每个关键料附数据手册链接与抓取日期。

模板：[bom-review.template.csv](assets/bom-review.template.csv)；
选型记录：[selection-record.template.md](assets/selection-record.template.md)。

## 工具

```text
mcp__konnect__search_jlcpcb_parts(query="10uF 0603 X7R 25V", basic_only=true)
mcp__konnect__get_jlcpcb_part(lcsc_id="C19702")
mcp__konnect__suggest_jlcpcb_alternatives(value="10uF", footprint="C_0603_1608Metric")
mcp__konnect__check_bom_health(schematic="board.kicad_sch")
mcp__konnect__get_datasheet_url(mpn="...")
```

- 工具返回的库存/价格是**快照**；投板前复核。
- 选型结论写入 BOM/选型记录，不只看聊天记录。

## 反模式

| 反模式 | 后果 | 正确做法 |
|---|---|---|
| 只看标称值不看 DC bias | 实际容量不足 | 按手册曲线降额 |
| 用 Y5V 做去耦/定时 | 温漂/容量崩 | C0G/X7R |
| 电感只看 Isat 不看 DCR | 压降/发热超标 | 两者同时核算 |
| 连接器按整排电流选 | 单 pin 过流 | 每 pin 与整体都核 |
| 替代料只对参数不对封装 | 焊盘不兼容 | 同封装同引脚 |
| BOM 无 MPN/LCSC | 无法采购/追溯 | 字段齐全 |
| 把经验值当硬约束 | 过度设计/冲突 | 标 `HEURISTIC` 并给来源 |

## 完成判据

1. 每个器件有 MPN/LCSC/封装/值/容差/耐压（按品类）。
2. 降额逐项核算并有记录；不满足项有处置。
3. 关键料有数据手册来源与日期；替代料已确认。
4. `check_bom_health` 无未解释的高风险项。
5. BOM 通过评审并冻结；P2 Gate 记录在案。

## 参考与来源

- 数据手册（每器件，版本/日期）。
- JLCPCB 库存与价格（快照，投板前复核）。
- IPC-2221（通用设计）、IPC-7351（焊盘）。
- 规范：`../pcb-flow/references/core-semantics.md`（证据/置信/`HEURISTIC`）。
- 验证：`../pcb-verification/SKILL.md`（BOM 与 DRC 的门禁）。
