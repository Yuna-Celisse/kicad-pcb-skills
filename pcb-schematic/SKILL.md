---
name: pcb-schematic
description: "KiCad 原理图绘制：图面规范、命名与层次、块级电路、ERC 裁决、可测试性、图面重叠检查。触发：画原理图、加器件、连线、命名网络、层次页、ERC 报错、原理图评审。English: schematic, wire, net label, hierarchical sheet, ERC."
metadata: { version: 0.3, requires: "konnect>=0.13, kicad>=10" }
---

# 原理图（pcb-schematic）

负责**结构正确、可读、可评审**的原理图；电气规则判定交给 `pcb-verification` 与
`gate.py`，本技能只给绘制建议与 ERC 解释。

## 何时用 / 何时不用

用：

- 新建/修改原理图、放置符号、连线、命名网络。
- 划分层次页、定义 sheet pin。
- 读 ERC 报告、判断某条是"真错"还是"误报"。
- 原理图评审（含符号重叠）。

不用：

- 器件选型/降额/BOM → `pcb-components`。
- PCB 布局/布线 → `pcb-layout` / `pcb-routing`。
- 阶段推进与最终签核 → `pcb-flow`。

## 前置条件

| 项 | 要求 |
|---|---|
| 工程 | 已存在 `.kicad_sch`；库已注册（`pcb-schematic` 不创建库） |
| Konnect | 已加载 `sch_components` / `sch_wiring` / `sch_analysis`；写操作走 MCP |
| Grid | 1.27mm（50mil）；所有引脚落网格 |
| 规范 | 先读 [drafting-conventions.md](references/drafting-conventions.md) 与 [naming-and-hierarchy.md](references/naming-and-hierarchy.md) |

## 决策流程

1. **定层次**：按 Power / MCU / Interface / Analog / Connector 分页；先画电源与地，
   再画信号。层次页的 sheet pin 方向必须与被连信号一致。
2. **放符号**：先大件（连接器、IC、晶振、电感），后无源件；同类器件对齐。
3. **连线**：先电源/地，再关键信号（时钟、复位、差分、模拟），最后一般信号。
4. **命名**：每个网络一个语义名；跨页只用层次标签，不用全局标签代替层次。
5. **ERC**：每页画完跑一次；完成后整树跑（`schematic_scope: hierarchy`）。
6. **评审**：符号重叠用 `pcb_overlap.py`；按 [review checklist](assets/schematic-review-checklist.md) 过一遍。
7. **交棒**：原理图冻结后交给 `pcb-layout`；验证结论走 `gate.py`。

## 图面规范（摘要）

| 规则 | 做法 |
|---|---|
| 网格 | 1.27mm；引脚、导线端点、junction 全部落网格 |
| 流向 | 信号左→右；电源在上、地在下；反馈从右回左 |
| 穿线 | 导线不得穿过符号体、文字、引脚名 |
| 四路交叉 | 打 junction 点，或拆成两个 T 型；不允许"十字不加点" |
| 跨页 | 用层次标签（hierarchical label）；全局标签只用于电源/地等真全局网 |
| 去耦 | 电源符号靠近 IC 电源脚，不堆在页角 |
| 位号 | 自动标注后人工复核；同功能块位号连续 |

细则见 [drafting-conventions.md](references/drafting-conventions.md)。

## 命名与层次

- 电源：`VCC_3V3`、`+5V_USB`、`VBAT`、`GND`、`GNDA`；不要用 `VCC1`、`+3.3` 这类含糊名。
- 差分：`USB_DP` / `USB_DN`、`CAN_H` / `CAN_L`；成对命名。
- 低有效：`nRESET`、`nCS`、`EN_N`（项目内统一一种）。
- 时钟：`CLK_24M`、`CLK_I2S`；模拟：`AIN_*`、`AOUT_*`。
- 一个网络只能有一个语义名；不要用网络标签"猜"连接。

层次与 sheet pin 规则见 [naming-and-hierarchy.md](references/naming-and-hierarchy.md)。

## 块级电路

常用块（含取值原则与常见坑）：

| 块 | 关键点 |
|---|---|
| LDO / DCDC 外围 | 输入/输出电容按手册；反馈分压精度；EN/UVLO；电感饱和电流 |
| MCU 最小系统 | 每电源脚 100nF；复位 RC；BOOT 脚；调试口 |
| 晶振 | 负载电容按 CL 计算；串联电阻；包地 |
| USB | CC1/CC2 5.1k（UFP）；D+/D- 串阻/ESD；VBUS 检测分压 |
| I²C | 上拉按总线电容与速率算；地址冲突检查 |
| SPI/UART/CAN | 片选上拉；CAN 终端 120Ω 可切；隔离边界 |
| ADC 前端 | 输入阻抗、采样保持、抗混叠、基准去耦 |
| 保护 | 反接、过流、过压、ESD；TVS 钳位低于被保护脚 abs max |

细节与取值推导见 [circuit-blocks.md](references/circuit-blocks.md)。

## ERC 裁决

ERC 只说明"引脚类型/连接关系"可疑，不等于电路错。按 [erc-adjudication.md](references/erc-adjudication.md) 分类：

- 真错：电源无驱动、输出对输出、必需 pin 悬空、层次 pin 未连。
- 误报：`PWR_FLAG` 缺失、合法的 NC、测试点/跳线造成的多驱动。
- 处理：真错改图；误报加 `PWR_FLAG` / `no_connect` / 说明，并记入
  [ERC waiver 台账](assets/erc-waiver-ledger.md)。

不要在原理图技能里宣布 "ERC PASS"；最终结论由 `pcb-verification` 调 `gate.py` 给出。

## 图面评审

```bash
python pcb-toolkit/scripts/pcb_overlap.py board.kicad_sch --json reports/overlap_sch.json
```

- `gate_effect=block` 的符号重叠必须修（文字压符号、符号互叠）。
- `review` 项人工确认是否可读性可接受。
- 评审清单：[schematic-review-checklist.md](assets/schematic-review-checklist.md)。

## 速查

- 图面规范：[drafting-conventions.md](references/drafting-conventions.md)
- 命名/层次：[naming-and-hierarchy.md](references/naming-and-hierarchy.md)
- 电路块：[circuit-blocks.md](references/circuit-blocks.md)
- ERC 裁决：[erc-adjudication.md](references/erc-adjudication.md)
- 可测试性：[testability.md](references/testability.md)
- 规范总纲：[../pcb-flow/references/core-semantics.md](../pcb-flow/references/core-semantics.md)
- 验证与 gate：[../pcb-verification/SKILL.md](../pcb-verification/SKILL.md)

## 反模式

| 反模式 | 后果 | 正确做法 |
|---|---|---|
| 用全局标签代替层次标签 | 跨页连接不可见、重名冲突 | 层次页用 hierarchical label |
| 网络名随手起 | 同一网多名/异网同名 | 按命名法，一网一名 |
| 十字交叉不打点 | 误连/漏连 | 打 junction 或拆 T |
| 引脚不落 1.27mm 网格 | 连线虚接、ERC 误报 | 全部对齐网格 |
| 把 ERC 误报当"忽略即可" | 真错被掩盖 | 分类、记录、必要时 waiver |
| 在原理图阶段宣布 PASS | 绕过 gate 与覆盖 | 交给 `pcb-verification` |

## 完成判据

1. 所有页通过 `validate`/打开无解析错误；符号无重叠 block。
2. ERC 已跑（整树）；真错清零，误报有记录。
3. 网络命名与层次符合 references；电源/地完整。
4. 评审清单逐项打勾；可测试性项（测试点/跳线/DNP）已决定。
5. 交给 `pcb-layout` 的网表/位号已冻结。

## 参考与来源

- KiCad 10 文档：Schematic Editor、Hierarchical Sheets、ERC。
- Konnect toolset：`sch_components`、`sch_wiring`、`sch_analysis`、`sch_hierarchy`。
- 规范：`core-semantics.md`（判定词/证据/置信）。
- 行业惯例：IPC-2221（设计通用要求）；具体器件以数据手册为准。
