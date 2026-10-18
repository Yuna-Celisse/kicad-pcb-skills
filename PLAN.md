# KiCad 全流程 PCB 工程技能套件（Skill + MCP）方案 v0.3.2

- 日期：2026-10-19
- 目标环境：KiCad 10.0.7 · Konnect 0.13.0（228 tools / 21 toolsets）
- 落地目录：`C:\Users\YunaCelisse\Desktop\Software\skills\`
- 状态：**M5 完成**（calc/analysis/MCP，328 tests）；全部里程碑完成

## 修订记录

v0.1 → v0.2 按评审意见做了 10 项调整，未推翻三层架构与 7 技能拆分。

| 评审意见 | v0.2 处置 | 章节 |
|---|---|---|
| ①「所有数字必须计算」过度 | 改为**可追溯**：六类来源 + 记录 schema | §2.2 |
| ② 缺 Design Intent | 提升为核心 SSOT 对象 | §2.4 |
| ③ `.kicad_dru` 与"禁止直接编辑"冲突 | 改为 **proposal → 应用 → lint → DRC**，工具不落盘 | §7 |
| ④ 规则优先级未成一等概念 | `lint_dru` 增加 shadow / precedence / 可达性分析 | §7.3 |
| ⑤ 经验值被写成硬 Gate | 引入 **等级 × 权威** 二维模型 | §2.3 |
| ⑥ 验收"唯一命中"不合理 | 改为 **唯一 Primary + 可选 Supporting** | §9.2 |
| ⑦ analog 自动切地危险 | 改为**回流路径规划**，禁止自动分割 | §3.9 |
| ⑧ calculator 与 oracle 混在一起 | 工具层拆 `calc / rules / analysis` | §6 |
| ⑨ `stackup_propose` 被当成 PASS | 返回 `CANDIDATE`，两级验收 | §6.1 |
| ⑩ 缺"参数未知"状态 | 新增 **Assumption Registry** 与 `ASSUMPTION` 状态 | §2.5 |

### v0.3 → v0.3.1（Core Semantics 0.2）

| 修正 | 内容 |
|---|---|
| `specificity_order_violation` | 方向纠正：违规 = `earlier(r_br, r_sp)`（宽规则在求值顺序中更早） |
| `ignore_shadow` | 主语纠正：危险的是**遮蔽者**为 `ignore`，不是被遮蔽者 |
| `DOMAIN_POLICY` | 取消全局 fallback 数组，按域给 hard/soft；补回被漏掉的 `FAB` |
| `combine` | 形式化为部分函数；空交集 / 多 PROJECT 冲突返回 `CONFLICT` |
| `waiver_policy` | 新增 `prohibited` / `authority_required` / `project_acceptance` |
| 证据两轴 | `basis`（要求依据）与 `verification`（实现验证）分离，不再混排 |
| `derived` | 必须带 `model_status: validated\|candidate`；candidate 只能 `review` |
| 单位 | 去掉字段名单位后缀，统一由 `units` 块声明 |
| 阶段 | 统一为"自 P8 起"禁止带假设 |

### v0.3.1 → v0.3.2（M1.1 数据模型冻结）

| 决定 | 内容 |
|---|---|
| 输入 / 结果分离 | `requirements`（候选主张）与 `derived.constraints`（resolver 结果）不再共用字段 |
| Candidate | 内联在 requirement 下，带局部 `id`；不做全局候选表 |
| 全局 ID | 只有 `sources` / `assumptions` / `waivers` 全局化 |
| derived | tagged result：`adopted` / `conflict` / `unresolved`，禁止 `conflict: null` |
| basis | 记录 candidate id，不记录 source id |
| level | requirement 与 candidate 各一层；resolver 用 `candidate.level` 识别硬约束 |
| waiver_policy | 只放在 requirement 上，不进 candidate |

另：评审提出的**元件重叠检测**已实现并在真实板上验证，见 §6.2 与 `pcb-toolkit/README.md`。

### v0.2 → v0.3（规范层修订，M1.0）

| 评审意见 | 处置 | 位置 |
|---|---|---|
| 权威顺序不能是全局 total order | 改为**按约束域解析**；项目不得放宽 safety/manufacturing/component 硬约束 | §2.3、core-semantics §2 |
| `ASSUMPTION` 与词表不一致 | 删除该 verdict；签核阶段到期假设 → `BLOCKED` | §2.5、core-semantics §3 |
| `unreachable` 定义方向错误 | 重写为基于 `eval_order = reverse(file_order)` 的形式化模型 | §7.3、core-semantics §7 |
| overlap 未区分 confidence | 每个 finding 自带 `geometry` / `confidence` / `gate_effect`；approx 只能 `review` | §6.2、core-semantics §4 |
| 残留"以严格者为准" | 全部替换为域解析 | §2.1、§9.3 |
| Gate 用文字判据 | 统一改为计数：`errors_unwaived == 0` | §4、core-semantics §3.4 |

---

## 0. 结论摘要

做 **7 个技能 + 1 个工具层**，与 PCB 生命周期 7 个阶段一一对应，全部平铺在 `skills\` 下：

| 技能目录 | 定位 | 核心交付 |
|---|---|---|
| `pcb-flow/` | 总控：约束采集 → 门禁 → 交付 | Design Intent、Assumption Registry、10 个 Gate |
| `pcb-schematic/` | 绘制经验 + 电路块库 | 图面规范、命名、层次、块级电路、ERC 判定 |
| `pcb-components/` | 器件选型 + BOM 健康 | 降额、封装、介质、生命周期、替代料 |
| `pcb-layout/` | 布局 + 叠层 | 分区、热、去耦、晶振、DCDC 热环路、2/4/6 层 |
| `pcb-routing/` | 布线经验与规则 | netclass、载流、阻抗、差分/等长、回流路径 |
| `pcb-verification/` | DRC/ERC 全流程 | 分阶段 runbook、违规矩阵、规则包、waiver、重叠检测 |
| `pcb-manufacturing/` | DFM/DFA + 出图 | 板厂 profile、DFM 矩阵、输出 manifest、拼板/测试 |
| `pcb-toolkit/` | 确定性工具层 | 几何判定（已实现）、计算器、规则生成/校验（规划） |

**三条支柱**（替代 v0.1 的单条"铁律"）：

1. **数值可追溯**：影响 Gate 的每个数值都有来源记录，禁止无来源数值。来源可以是计算、手册、标准、板厂、项目约束或标注过的经验值。
2. **意图先行**：Design Intent 是唯一事实来源，netclass / DRC 规则 / 布线选择 / 验证项都由它派生，而不是反过来从 DRC 报错猜意图。
3. **检查必须可复跑**：任何结论都要能由一个确定性工具或一次 KiCad 检查复现；不能复跑的结论只能登记为假设（Assumption record），并计入 `PASS_WITH_ASSUMPTIONS`。

**覆盖范围**：不绑定单一品类。主规则写"框架 + 参数"，五类场景用领域扩展包补齐（§3.9）。

---

## 1. 现状盘点与缺口

### 1.1 已有资产（`~/.agents/skills`，已 junction 到 `~/.dsh/skills`）

| 技能 | 体量 | 强项 | 性质 |
|---|---|---|---|
| `konnect` | 8.5KB + 10KB 契约 | 文件保护、通道选择、可靠性契约 | 操作纪律 |
| `kicad-schematic` | 16.6KB + 8.7KB | 连线/批量/层次工具用法 | 工具手册 |
| `kicad-pcb` | 22.9KB + 8KB | 布局顺序、路由工具、zone、DRC 调用 | 工具手册 |
| `kicad-review` | 13.2KB + 6.3KB | 快速检查、严重度、报告格式 | 检查清单 |
| `kicad-library` | 21KB | 符号/封装创建 | 工具手册 |
| `kicad-manufacture` | 9KB + 6.1KB | Gerber/BOM/CPL 导出 | 工具手册 |

结论不变：**"怎么调工具"够用，"工程上怎么判断"几乎空白**（references 合计约 24KB）。

### 1.2 缺口矩阵

| 能力域 | 现有覆盖 | 缺口 |
|---|---|---|
| ERC | `run_erc()` + 5 条分类 | 引脚冲突矩阵、误报识别、分阶段执行、waiver 台账 |
| DRC | `run_drc()` + 7 条常见错误 | 分阶段执行、根因矩阵、owner 归属处置、覆盖率语义 |
| 自定义规则 | `set_layer_constraints`（仅层约束） | 完整 `.kicad_dru` 语法、条件表达式、**优先级/shadow 分析** |
| 绘制经验 | 6 个简单 pattern | 图面规范、命名、层次、块级电路库、评审清单 |
| 器件选型 | 无 | 降额、封装、介质、生命周期、替代料、BOM 卫生 |
| 布局 | 4 条 bullet + `score_placement` | 分区、热、晶振、DCDC 热环路、机械禁布区 |
| 布线 | 路由工具 + 3 条规则 | netclass、载流、阻抗、差分、回流、铺铜策略 |
| 叠层 | 无 | 2/4/6 层预设、阻抗目标、板厂映射 |
| DFM | 2 个小 reference | DFM 矩阵、板厂 profile、拼板、测试点 |
| **元件重叠** | `score_placement` 只给 courtyard 汇总结论；`check_clearance` 只能两点测距 | **全板成对检测 + 原理图符号检测**（已由 `pcb_overlap` 补上） |

### 1.3 关键约束（实测）

- `run_drc` 调 `kicad-cli pcb drc`，跑完整规则集，**无法按测试项筛选**；可落盘 JSON。
- `set_layer_constraints` 会写 `.kicad_dru`，但只支持层级的 min width / clearance，不支持 condition、差分、长度、skew、disallow。
- `run_design_review` 已统一 `PASS / INCOMPLETE` 语义，本方案沿用并扩展。
- 原理图无 item-level IPC；PCB 走实时 IPC。所有写入经 Konnect，禁止直接编辑 `.kicad_*`。

---

## 2. 架构

> **规范层定义**（判定词、权威解析、置信、单位、求值模型）以
> [`pcb-flow/references/core-semantics.md`](pcb-flow/references/core-semantics.md) 为准；
> 本节只做摘要，冲突时以该文档为规范性依据。

```
                    pcb-flow
                        │
                 Design Intent  ←────────── Assumption Registry
                        │
       ┌────────────────┼─────────────────┐
       ▼                ▼                 ▼
 pcb-schematic     pcb-layout       pcb-components
       │                │                 │
       └─────────► pcb-routing ◄──────────┘
                        │
                        ▼
                pcb-verification
                        │
                        ▼
               pcb-manufacturing
─────────────────────────────────────────────
 L0 知识层   references/ · profiles/ · domain packs/ · datasheet constraints
 L2 执行层   Konnect MCP  +  pcb-toolkit（calc / rules / analysis）
```

### 2.1 与已装 Konnect 技能的分工

- `kicad-*`（已装）= **工具手册**：工具叫什么、参数是什么、有什么坑。
- `pcb-*`（本套件）= **工程手册**：该不该这么做、做到什么程度算合格。

优先级：`konnect`（操作纪律）> `pcb-flow` / 阶段技能（工程判断）> `kicad-*`（工具细节）。冲突按 §2.3 的域解析模型处理，不得简单取严格者。

### 2.2 数值可追溯（替代"所有数字必须计算"）

影响 Gate 判定的每个数值，必须带一条来源记录：

```yaml
value: 0.20            # mm
source_type: fab_profile
source: JLCPCB-4L-2026-10
confidence: authoritative
```

```yaml
value: 1.8             # mm
source_type: calculation
calculator: pcb_trace_width
inputs: {current_a: 3.0, copper_oz: 1, temp_rise_c: 10, layer: external}
confidence: derived
```

| `source_type` | 含义 | 典型 `confidence` |
|---|---|---|
| `calculation` | 工具计算，输入可复现 | derived |
| `datasheet` | 器件手册 / 应用笔记 / 厂商 layout guide | authoritative |
| `standard` | IPC / IEC / 协议规范 | authoritative |
| `fab_profile` | 板厂工艺能力（带 URL + 抓取日期） | authoritative / dated |
| `project_constraint` | 项目明确约束（机械、成本、认证） | authoritative |
| `heuristic` | 经验值，无外部依据 | advisory |

规则：
- `source_type: heuristic` 的值**不得单独决定 Gate 通过**，只能作为 `SHOULD`/`HEURISTIC` 级建议（见 §2.3）。
- 数值变更时旧记录作废，不允许"沿用上次"。
- 无法给出任何来源 → 登记为假设（进入 Assumption Registry）或判 `INCOMPLETE`，二者择一，不得默认通过。

### 2.3 规则分级与权威解析（按域，不按全局顺序）

数值和规则带两个维度：

| 维度 | 取值 |
|---|---|
| 等级 | `MUST` / `SHOULD` / `HEURISTIC` / `INFO` |
| 权威 | `PROJECT` / `DATASHEET` / `STANDARD` / `FAB` / `DOMAIN` / `GENERIC` |

**v0.2 的 `PROJECT > DATASHEET > ...` 不是全局覆盖顺序**：项目要求不能放宽安规与板厂硬限。v0.3 改为按约束域解析：

| domain | 硬约束来源 | 项目能做什么 |
|---|---|---|
| `safety` | `STANDARD`（MUST） | 只能更严 |
| `manufacturing` | `FAB` 硬限 | 只能更严 |
| `component` | `DATASHEET` / `STANDARD`（MUST） | 只能加裕量 |
| `signal_integrity` | `STANDARD` / `DATASHEET`（MUST） | 只能更严 |
| `project` | `PROJECT` | 自主 |
| `practice` | 无 | 仅参考 |

- 项目值比硬约束更宽松 → `CONFLICT` → Gate `BLOCKED`；除非 `waiver_policy` 允许且豁免有效（见 core-semantics §2.6）。
- 域策略表（hard / soft）见 core-semantics §2.3；`FAB` 始终在 manufacturing 的 soft 中，不会被 fallback 忽略。
- 只有**同域、同权威**冲突时才比较严格程度（`at_least` 取 max、`at_most` 取 min、`exact` 取交集）。
- `HEURISTIC` / `INFO` 永不覆盖 authoritative，也不参与绑定；典型例子：FPGA/SoC 的 PDN 以厂商 `DATASHEET` 为准，覆盖 `GENERIC` 的"每脚 100nF"。
- 解析必须记录 `basis`（胜出候选）与 `overridden`（被压制候选），保证可审计。

算法伪代码与冲突记录样例见 core-semantics §2。对外呈现时，每条建议标注 `MUST/SHOULD/HEURISTIC` 与依据来源。

### 2.4 Design Intent（核心 SSOT）

v0.1 的信息分散在 brief / BOM / netclass / 计算 / DRC 里，导致"DRC 报错 → Agent 再猜意图"。v0.3.2 起采用**输入 / 结果分离**：`requirements` 存候选主张，`derived.constraints` 存 resolver 结果（core-semantics §2.5.1）。

```yaml
schema_version: 1
project_id: jxbadge
revision: 4

units: {length: mm, voltage: V, current: A, impedance: ohm, frequency: Hz, temperature: C}

sources:
  S-001: {type: fab_profile, ref: JLCPCB-4L-2026-10, retrieved: 2026-10-01}
  S-002: {type: datasheet,  ref: ESP32-S3_datasheet_p47}

requirements:
  min_clearance:
    domain: manufacturing
    direction: at_least
    level: MUST
    waiver_policy: authority_required
    candidates:
      - {id: C-001, value: 0.15, authority: FAB, level: MUST, source: S-001}

  usb_diff_impedance:
    domain: signal_integrity
    direction: exact
    level: MUST
    waiver_policy: prohibited
    candidates:
      - {id: C-001, value: 90, tolerance_pct: 10,
         authority: DATASHEET, level: MUST, source: S-002}

  antenna_keepout:
    domain: project
    direction: at_least
    level: SHOULD
    waiver_policy: project_acceptance
    assumptions: [A-017]
    candidates: []

assumptions:
  A-017:
    item: antenna_keepout
    assumed_value: {value: 5, unit: mm}
    impact: [floorplan, rf_clearance]
    confidence: low
    must_resolve_before: P3
    status: active

derived:
  constraints:
    min_clearance:
      status: adopted
      value: 0.15
      basis: [C-001]
      overridden: []
    usb_diff_impedance:
      status: adopted
      range: {min: 81, max: 99}
      basis: [C-001]
      overridden: []
    antenna_keepout:
      status: unresolved
      reason: no_candidate

  netclasses: {}
  rule_requirements: {}
  verification_requirements: {}
```

三条硬规则：

1. `requirements` 只放输入语义（domain / direction / level / waiver_policy / candidates）；`derived.constraints` 只放结果与 provenance，**不复制**这些字段。
2. `derived` 必须是 tagged result：`adopted`（含 value/range + basis）、`conflict`（含 `conflict.code`，禁止 value）、`unresolved`（含 reason，禁止 value）。不用 `conflict: null`。
3. `basis` / `overridden` 引用 **candidate id**（requirement 内唯一），不是 source id——同一 source 可能给出多条主张。

validator 额外要求：`requirements` 里出现过的键，`derived.constraints` 必须有对应条目；缺失即视为"resolver 未运行"，判 `INCOMPLETE`。

派生链：

```
Design Intent ──► netclass ──► .kicad_dru 规则 ──► 布线决策
      │                                              │
      └──────────────► 验证项（DRC/长度/阻抗/重叠）◄──┘
```

约束：
- Design Intent 由 `pcb-flow` 在 P1 建立、在 P5 冻结；之后每次变更都要记版本。
- 任何 netclass / DRU 规则必须能指回某条 intent；指不回去的规则视为可疑。
- 验证报告必须按 intent 条目回填"已满足 / 未满足 / 未验证"。

### 2.5 Assumption Registry（缺参数不再停工）

工程 Agent 经常因为一个参数不知道就停下。改为显式假设：

```yaml
A-017:
  item: ambient_temperature
  assumed_value: {value: 25, unit: C}
  impact: [trace_width, thermal_margin]
  confidence: low
  must_resolve_before: P8
  status: active
```

规则：
- 不得因为缺参数直接 `BLOCKED`；先登记假设，标 `impact` 与 `must_resolve_before`。
- P0–P7 允许带假设推进，verdict 记 `PASS_WITH_ASSUMPTIONS`。
- P8/P9 起，`must_resolve_before <= P8` 的假设到期未关闭 → `BLOCKED`。签核阶段不存在"带假设通过"。
- 假设不等于 waiver：假设是"我不知道"，waiver 是"我知道且接受"。

### 2.6 每个 SKILL.md 的统一骨架

```markdown
---
name: pcb-routing
description: <中文触发词 + English triggers，≤500 字符>
metadata: { version: 0.3, requires: konnect>=0.13, kicad>=9 }
---
# 标题
## 何时用 / 何时不用
## 前置条件（toolset、阶段、Design Intent 是否已冻结）
## 决策流程（步骤 + 每步判据 + 判据来源类型）
## 速查（链接 references，不内联大表）
## 反模式
## 完成判据（可验证的 exit criteria）
## 参考与来源
```

---

## 3. 技能清单

### 3.1 `pcb-flow/` — 总控编排

**触发**：开始新板、继续项目、"下一步做什么"、"能不能投板"。

- Design Intent 的建立、冻结、版本化；Assumption Registry 的维护。
- 10 阶段流水线与 Gate（§4）。
- 判定词表：`PASS` / `PASS_WITH_WAIVERS` / `PASS_WITH_ASSUMPTIONS` / `BLOCKED` / `INCOMPLETE`。
- 证据强度按 §2 的域内 `DOMAIN_POLICY` 解析（安全看 STANDARD、制造看 FAB、器件看 DATASHEET/STANDARD），不存在全局权威顺序；数据手册/ERC/几何查询的强弱取决于所在域与 requirement。
- 用户要求跳过检查时的降级记录方式（绝不沉默通过）。

`references/`：`phase-gates.md`、`artifact-contract.md`、`project-bootstrap.md`、`evidence-hierarchy.md`、`design-intent-schema.md`、`assumption-registry.md`
`assets/`：`design-brief.template.md`、`design-intent.template.yaml`、`design-log.template.md`

### 3.2 `pcb-schematic/` — 绘制经验 + 电路块库

- **图面规范**：1.27mm 网格；信号左→右、电源上、地下；线不穿符号；四路交叉打点或拆成两个 T 型；跨页用层次标签。
- **命名法**：`VCC_3V3` / `+5V_USB` / `GND` / `GNDA`；差分 `_P/_N`；低有效 `nRESET`；时钟 `CLK_*`；模拟 `AIN_*`。一个网络一个语义名。
- **层次划分**：Power / MCU / Interface / Analog / Connector；层次引脚方向与被连信号一致。
- **块级电路库**：电源树与 LDO/DCDC 外围、MCU 最小系统、晶振、USB（CC 电阻/ESD/VBUS 检测）、I²C（上拉与总线电容预算）、SPI/UART/CAN、ADC 前端、保护（反接/过流/过压/ESD）。
- **ERC 判定**：引脚类型冲突矩阵；`PWR_FLAG` 位置；`no_connect` 与"合法悬空"；层次引脚未连的成因；真错 vs 误报。
- **图面评审**：调用 `pcb_overlap` 查符号重叠（见 §6.2）。
- **可测试性**：测试点、跳线、0Ω 选项、DNP。

`references/`：`drafting-conventions.md`、`naming-and-hierarchy.md`、`circuit-blocks.md`、`erc-adjudication.md`、`testability.md`
`assets/`：`erc-waiver-ledger.md`、`schematic-review-checklist.md`

### 3.3 `pcb-components/` — 器件选型

- **降额基线**（每条可核算）：电阻功率 ≤50–60%；陶瓷电容耐压 ≥1.5–2× 且计入 DC bias 容量损失；电解 ≥1.25× 且按寿命折算；电感 Isat ≥1.3× 峰值并同时核算 DCR 压降；半导体 Vds/Vr ≥1.5–2×、Tj 低于手册 Tj_max 并留明确 K 裕量；连接器 ≥1.5×；TVS 钳位 < 被保护器件 abs max。倍率为 HEURISTIC，手册更严时以手册为准。
- **无源件**：C0G/NP0（定时/滤波/采样）→ X7R（去耦）→ 避免 Y5V；分压采样 0.1–1%；磁珠看 DC bias 后的阻抗与 DCR。
- **封装与装配**：手焊下限 0603；QFN/BGA 需回流与散热焊盘；连接器优先带机械固定脚。
- **有源件**：pin-compatible 多源、避免 EOL/NRND、静态电流、内置 vs 外置保护。
- **供应链**：JLC Basic vs Extended、MOQ、库存深度、替代料同封装同引脚。
- **BOM 卫生**：MPN/LCSC/封装/值/容差/耐压/介质/DNP 齐全；值收敛；一料一源。

`references/`：`derating-and-margins.md`、`passive-selection.md`、`active-and-ic-selection.md`、`package-and-assembly.md`、`sourcing-and-lifecycle.md`
`assets/`：`bom-review.template.csv`、`selection-record.template.md`

### 3.4 `pcb-layout/` — 布局 + 叠层

- **分区与流向**：按功能块聚簇；单向（连接器→保护→滤波→IC）；模拟/数字/RF/功率分区。
- **连接器**：板边、插拔方向、应力释放、ESD 贴近入口。
- **去耦**：100nF 每电源脚、≤2–3mm、地过孔就近、回路面积最小——**这些是 `HEURISTIC`，被器件手册覆盖时以手册为准**。
- **晶振**：紧贴 MCU、下方不走线、负载电容对称、包地。
- **开关电源**：hot loop 面积最小；SW 节点铜箔小而短；反馈开尔文取样并远离电感；地平面单点汇合。
- **热**：铜箔面积、thermal via、与温度敏感件间距、气流方向。
- **机械与禁布区**：安装孔（M3 ≥6mm）、板边 ≥3–5mm、V-cut 两侧、插拔包络、高度限制。
- **叠层**：2/4/6 层预设，阻抗目标与线宽/介质厚度对照，板厚 1.6/1.0/0.8。
- **布局评审**：`pcb_overlap` + `score_placement`，重叠是第一道硬门。

`references/`：`floorplanning.md`、`placement-rules.md`、`thermal.md`、`stackup-design.md`、`mechanical-keepout.md`
`assets/`：`stackup-presets.md`、`floorplan.template.md`

### 3.5 `pcb-routing/` — 布线经验与规则

- **顺序**：netclass → 关键网络（电源/时钟/差分/模拟）→ 一般信号 → 铺铜。铺铜永远最后。
- **载流**：IPC-2221 `I = k·ΔT^0.44·A^0.725`（mil²，外层 k=0.048、内层 0.024），同时满足压降与温升；大电流用铺铜/多孔。
- **过孔**：电源地多孔并联；信号少换层；避免盘中孔；环宽 ≥ 板厂下限。
- **阻抗**：微带/带状线 + 实际叠层；换层/换参考面重新核算；参考平面不得开槽。
- **差分与等长**：等宽等距、同层、少过孔；对内 skew 按协议；不要求等长时不要盲目蛇形。
- **回流路径**：每条信号都有回流；跨分割是首要风险；换层旁放地过孔。
- **串扰与 EMC**：3W（时钟）、20H（电源平面）、45° 折角、包地。
- **铺铜**：GND 双面、thermal relief、清孤岛、板边间距。
- **可制造性**：线宽/间距不贴下限（留 20% 余量）、避免颈缩与酸角。

`references/`：`netclass-strategy.md`、`current-and-width.md`、`impedance.md`、`differential-and-length.md`、`return-path.md`、`pour-and-via.md`
`assets/`：`netclass-presets.json`、`routing-order.md`

### 3.6 `pcb-verification/` — DRC / ERC 全流程（核心）

- **分阶段**：布局后（courtyard/板边/安装孔/丝印）、布线后（clearance/unconnected/width/via/差分）、出图前（silk/mask/drill/板框/zone fill）。
- **ERC**：绘制中先跑（power flag/NC/重复位号），完成后跑（引脚冲突/驱动缺失）；层次化必须 `schematic_scope: hierarchy`。
- **重叠检测**：`pcb_overlap` 作为布局后与投板前的必跑项（原理图 + PCB）。
- **自定义规则**：语法、条件表达式、优先级（§7）。
- **违规矩阵**：症状 → 根因 → 修法 → 工具 → 验证（30+ 行）。
- **waiver 台账**：id、规则、位置、理由、补偿措施、批准人、复核日期；`ignored` 不进台账视为未处理。
- **判定**：DRC error 未清零且无豁免 = `BLOCKED`；覆盖不全 = `INCOMPLETE`；缺参数 = 已登记的 Assumption，未登记则 `INCOMPLETE`。

`references/`：`drc-runbook.md`、`erc-runbook.md`、`violation-matrix.md`、`custom-rules.md`、`rule-precedence.md`、`waiver-policy.md`、`signoff-criteria.md`
`assets/`：`rules/*.kicad_dru`（proposal 模板）、`report.schema.json`

### 3.7 `pcb-manufacturing/` — DFM/DFA + 出图

- **DFM 矩阵**：线宽/间距、孔径、环宽、阻焊桥、丝印字高 ≥0.8mm / 线宽 ≥0.15mm、板边距、槽孔、V-cut/邮票孔、阻抗测试条。
- **板厂 profile**：`jlcpcb-2l / jlcpcb-4l / pcbway / oshpark`，每条能力值带 URL 与抓取日期。
- **输出包 manifest**：Gerber 层清单、钻孔（PTH/NPTH 分开）、叠层图、BOM（LCSC/MPN）、CPL、装配图、钢网说明。
- **拼板**：Mark 点（3 个、非对称）、工艺边 5mm、V-cut 方向、阴阳板风险。
- **测试**：测试点 ≥1.0mm / 间距 2.54mm、ICT/FCT、飞针、烧录口。
- **投板 EQ 清单**：阻抗、叠层、孔铜、表面处理、颜色、公差。

`references/`：`dfm-matrix.md`、`fab-profiles.md`、`output-package.md`、`panelization.md`、`assembly-and-test.md`
`assets/`：`fab-profile.schema.json`、`output-manifest.template.md`

### 3.8 `pcb-toolkit/` — 确定性工具层

见 §6。

### 3.9 领域扩展包（按需加载）

主规则只写与品类无关的框架，五类场景各一份 `references/domain-*.md`：

| 扩展包 | 宿主 | 增补约束 |
|---|---|---|
| `domain-mcu-digital` | schematic / layout | 最小系统、BOOT/调试口、多电源域时序、时钟树、总线端接 |
| `domain-analog` | layout / routing | **回流路径规划**与模拟/数字分区（**不自动切地**）、基准源、低噪声供电、ADC 前端阻抗、guarding |
| `domain-rf` | routing / layout | 共面波导、阻抗控制、天线净空与参考地、过孔栅栏、屏蔽腔、材料 Dk/Df |
| `domain-high-voltage` | layout / verification | 爬电距离与电气间隙（IEC 60664）、隔离带开槽、安规器件、耐压测试点 |
| `domain-motor-power` | routing / layout / components | 大电流载流与铜厚、续流回路、热、大电流连接器、母线电容 |

**关于地平面**：`domain-analog` 的默认立场是"**分区 ≠ 分割地平面**"。混合信号板优先保持连续地平面，通过器件摆放与信号路径控制回流；只有在器件手册明确要求、或隔离/安规要求时才分割，且必须在报告中给出依据。禁止由 Agent 自行决定"切地 + 单点连接"。

---

## 4. 全流程与门禁

| # | 阶段 | 主导技能 | 产物 | Gate | 证据 |
|---|---|---|---|---|---|
| P0 | 立项与约束 | `pcb-flow` | brief + 初始 intent + 假设登记 | 关键项有值或已登记假设 | 文档 |
| P1 | 架构与电源树 | flow + components | 电源树、电流预算 | 每路电源有源/负载/电流/裕量/时序 | 计算记录 |
| P2 | 器件选型 | components | BOM v0 + 选型记录 | 降额、封装、供货、替代料、生命周期 | BOM 审查 |
| P3 | 原理图绘制 | schematic | 原理图 + ERC | ERC 0 error；NC 全标注；去耦覆盖；命名合规 | `run_erc(hierarchy)` |
| P4 | 原理图评审 | schematic + verification | 评审清单 | 手册 pinout/极性/保护/测试点/DNP；**符号重叠 = 0** | 清单 + `pcb_overlap` |
| P5 | 叠层与布局规划 | layout | 叠层表 + 分区图 + **冻结的 intent** | 阻抗可实现、层数满足成本、禁布区明确 | `stackup_propose` |
| P6 | 布局 | layout | 摆放后板 | courtyard 重叠 = 0；去耦距离；连接器到位；热间距 | `pcb_overlap` + DRC |
| P7 | 布线 | routing | 布通板 | 100% routed；netclass 生效；差分/等长；回流连续；zone refill | `run_drc` |
| P8 | 验证 | verification | DRC/ERC + waiver + 重叠报告 | `errors_unwaived == 0`；ERC 复跑；规则覆盖 100%；**假设已关闭** | `run_drc` + `run_erc` + `pcb_overlap` |
| P9 | 制造 | manufacturing | 输出包 + DFM 报告 | DFM pass；manifest 完整；EQ 关闭 | `audit_manufacturing` |
| P10 | 发布 | flow | 版本 + 日志 | 版本/变更/遗留/下版建议 | 文档 |

**判定词表**

| 词 | 含义 |
|---|---|
| `PASS` | 证据完整且满足 |
| `PASS_WITH_WAIVERS` | 有登记豁免，且每条有补偿措施 |
| `PASS_WITH_ASSUMPTIONS` | 结论成立但依赖未关闭假设；**禁止用于 P8/P9** |
| `BLOCKED` | 存在未解决硬伤 |
| `INCOMPLETE` | 检查未覆盖 |

**组合优先级**：`BLOCKED > INCOMPLETE > PASS_WITH_ASSUMPTIONS > PASS_WITH_WAIVERS > PASS`。
Gate 判据一律用计数（`errors_total / errors_waived / errors_unwaived / reviews_open / assumptions_open`），不用文字描述。状态机与阶段合法性见 core-semantics §3。

---

## 5. 目录结构

```
skills/
├── PLAN.md
├── README.md
├── pcb-flow/
│   ├── SKILL.md
│   ├── assets/design-intent.schema.json   ← M1.1 结构契约
│   └── references/
│       ├── core-semantics.md              ← 规范层 0.2.3
│       └── design-intent-schema.md        ← 数据模型说明
├── pcb-schematic/
│   ├── SKILL.md                           ← M2 绘制入口
│   ├── assets/{erc-waiver-ledger.md, schematic-review-checklist.md}
│   └── references/{drafting-conventions, naming-and-hierarchy,
│                   circuit-blocks, erc-adjudication, testability}.md
├── pcb-components/
│   ├── SKILL.md                           ← M2 选型入口
│   ├── assets/{bom-review.template.csv, selection-record.template.md}
│   └── references/{derating-and-margins, passive-selection,
│                   active-and-ic-selection, package-and-assembly,
│                   sourcing-and-lifecycle}.md
├── pcb-layout/
│   ├── SKILL.md                           ← M3 布局入口
│   ├── assets/{stackup-presets.md, floorplan.template.md}
│   └── references/{floorplanning, placement-rules, thermal,
│                   stackup-design, mechanical-keepout}.md
├── pcb-routing/
│   ├── SKILL.md                           ← M3 布线入口
│   ├── assets/{netclass-presets.json, routing-order.md}
│   └── references/{netclass-strategy, current-and-width, impedance,
│                   differential-and-length, return-path, pour-and-via}.md
├── pcb-verification/
│   ├── SKILL.md                           ← M1.6 验证入口（调用 gate.py）
│   └── references/evidence-contract.md    ← 各报告字段与非法情形
├── pcb-manufacturing/
│   ├── SKILL.md                           ← M4 制造入口
│   ├── assets/{fab-profile.schema.json, output-manifest.template.md}
│   └── references/{dfm-matrix, fab-profiles, output-package,
│                   panelization, assembly-and-test}.md
├── README.md                              ← 套件索引与安装
├── mount-skills.ps1                       ← junction 挂载脚本
└── pcb-toolkit/
    ├── README.md                      ← 工具使用与契约
    ├── scripts/pcb_overlap.py         ← 已实现（含 gate_effect 语义）
    ├── scripts/validate_intent.py     ← 语义校验 + resolver
    ├── scripts/dru_ast.py             ← .kicad_dru 结构解析（M1.2）
    ├── scripts/dru_condition.py       ← condition 解析 + 三值包含判定（M1.3）
    ├── scripts/lint_dru.py            ← 规则遮蔽/优先级分析（M1.3）
    ├── scripts/gen_dru.py             ← Design Intent → proposal（M1.4）
    ├── scripts/gate.py                ← 统一 evidence + 五态判定（M1.5）
    ├── scripts/pcb_calc.py            ← 线宽/过孔/阻抗/叠层/电路（M5）
    ├── scripts/pcb_analysis.py        ← DRC 分诊 / BOM 检查 / 规则汇总（M5）
    ├── scripts/pcb_mcp.py             ← stdio JSON-RPC，pcb_* 工具（M5）
    ├── tests/test_pcb_overlap.py      ← 16 个用例
    ├── tests/test_validate_intent.py  ← 59 个用例
    ├── tests/test_intent_schema.py    ← schema × validator 双断言（11 个夹具）
    ├── tests/test_dru_ast.py          ← 21 个用例（真实夹具 + 畸形输入）
    ├── tests/test_lint_dru.py         ← 41 个用例（条件判定 + 遮蔽/优先级）
    ├── tests/test_gen_dru.py          ← 32 个用例（生成/拒绝/门槛）
    ├── tests/test_gate.py             ← 70 个用例（五态/豁免/归一化/台账）
    ├── tests/test_pcb_calc.py         ← 30 个用例（线宽/过孔/阻抗/叠层/电路）
    ├── tests/test_pcb_analysis.py     ← 8 个用例（分诊/BOM/规则/CLI）
    ├── tests/test_pcb_mcp.py          ← 15 个用例（协议/工具/错误/stdio）
    ├── tests/test_skill_docs.py       ← 31 个用例（入口/结构/链接/工程内容）
    ├── tests/fixtures/intent/         ← case_*.json 共享夹具
    ├── tests/fixtures/intent_valid.json
    ├── tests/fixtures/dru/            ← JXBadge 真实 DRU + 畸形夹具 + SOURCE.md
    ├── tests/vendor/                  ← jsonschema（仅测试，可删）
    └── out/                           ← 验证产物（JSON/SVG/PNG）
```

规模预估：技能部分约 40 个 markdown、130–180KB；每个 `SKILL.md` 250–450 行，每个 reference 120–300 行。

---

## 6. 工具层

按"计算器 / 规则 / 分析"三组拆分，避免把需要外部数据的东西伪装成纯计算。

### 6.1 分组

| 组 | 工具 | 性质 | 状态 |
|---|---|---|---|
| `pcb-calc` | `trace_width`、`via_current`、`impedance`、`stackup`、`circuit_calc` | 纯函数，stdlib | 规划 |
| `pcb-rules` | `gen_dru`（proposal）、`lint_dru`、`rule_audit` | 语法/优先级分析 | 规划 |
| `pcb-analysis` | `overlap`、`triage_drc`、`audit_bom` | 读取工程产物；`audit_bom` 需外部数据 | overlap 已实现 |

**`audit_bom` 的数据依赖**：EOL / 单一来源 / 库存风险无法用 stdlib 判断，必须接 LCSC、DigiKey、Mouser 或厂商 lifecycle 数据。v1 先做"格式与降额一致性检查"（纯本地），供应链风险明确标注 `requires: external_datasource`，不得在报告中伪装成已完成。

**`stackup_propose` 只是候选**：真实阻抗取决于 prepreg/core、压合后厚度、Dk(f)、阻焊、铜厚、电镀与蚀刻补偿。输出必须带：

```json
{"status": "CANDIDATE", "target_impedance": 50, "estimated_impedance": 49.3,
 "requires_fab_confirmation": true}
```

验收分两级：**模型回归**（与 KiCad Transmission Line Calculator 偏差 ≤3%）只是"算得对"，**工程签核**必须由板厂叠层确认。

### 6.2 已实现：`pcb_overlap.py`

只读解析 `.kicad_pcb` / `.kicad_sch`，不改文件、不需要 KiCad 运行、仅 Python 标准库。

```powershell
python scripts\pcb_overlap.py board.kicad_pcb --json r.json --svg r.svg
python scripts\pcb_overlap.py root.kicad_sch
python scripts\pcb_overlap.py project.kicad_pro       # PCB + 原理图
python scripts\pcb_overlap.py board.kicad_pcb --fail-on-overlap
```

判定口径：

| 对象 | 几何来源 | 判定 |
|---|---|---|
| PCB footprint | `F.CrtYd`/`B.CrtYd` 多边形（缺失回退 `F.Fab`，`confidence=low`） | 同面相交且穿透 ≥ 阈值 → `overlap` |
| PCB 焊盘 | pad 外形，仅同面 | 不同 footprint 焊盘相交 → `pad_overlap` |
| 原理图符号 | 库中 `rectangle`/`polyline`/`circle`/`arc`（**不含 pin**） | 同图页器件体相交 → `overlap` |
| 层级原理图 | 自动跟随 `Sheetfile` | 跨页不比较 |

两个关键设计：

- **相切不算重叠**：穿透 < `--touch-mm`（默认 0.02mm）判为 `touch`，只提示不判 FAIL。实测 JXBadge 有 6 处 7µm 相切，KiCad DRC 同样不报——这条容差是和 DRC 对齐的关键。
- **库解析失败不猜**：输出 `unresolved_symbol` 并退出几何判定，绝不估包围盒。

**confidence → gate_effect（工具自带，Gate 不再二次判断）**

| 几何来源 | confidence | gate_effect |
|---|---|---|
| 闭合 courtyard 多边形 | `exact` | `block` |
| 真实焊盘外形（rect） | `exact` | `block` |
| 凸包 fallback / Fab 包络替代 / 圆或异形焊盘近似 | `approx` | `review` |
| 库解析失败 | `none` | `incomplete` |

因此 `--fail-on-overlap` 只对 `block` 生效，`--fail-on-review` 才把 `review` 算失败。判定：block → `BLOCKED`；review/incomplete → `INCOMPLETE`；仅 info → `PASS`。

在 `CABadge/JXBadge_V1`（4 层、108 footprint、103 符号、4 图页）上的结果：

| 检查 | 结果 |
|---|---|
| PCB footprint 解析 | 108/108，`missing_courtyard=0` |
| PCB 重叠 | 0 处重叠，6 处 7µm 相切（U1 ↔ R1–R6） |
| 与 `run_drc` 对照 | 一致：DRC 无 courtyard 报错 |
| 原理图 | 103/103 解析成功，0 处重叠 |
| 判定 | `PASS`（block=0 / review=0 / incomplete=0 / info=6） |
| 单元测试 | 16 个用例全通过（正例/分离/异面/相切/45°/退出码/Fab 降级/pad/符号/层级/几何） |

### 6.3 MCP 形态

Python 3 stdlib + stdio JSON-RPC，工具名 `pcb_*`，与 Konnect 并存；无 MCP 时技能降级为调用脚本。MCP 只做 transport，判定逻辑仍由可测试的脚本函数提供。

---

## 7. `.kicad_dru` 专项

### 7.1 文件所有权

`.kicad_dru` 是 **KiCad 管理的文件**，官方建议通过 Custom Rules / Design Rule Editor 修改。因此：

- **不允许** LLM 直接覆盖项目里的 `.kicad_dru`。
- `set_layer_constraints` 是 Konnect 提供的受控写入路径，继续使用。
- 本套件的 `gen_dru` 只产出 **proposal**（文本 + AST + 说明），由人确认后经 KiCad/Konnect 应用。

### 7.2 流水线

```
Design Intent ──► gen_dru（proposal 文本/AST）
                      │
                      ▼
                  lint_dru（语法 + 约束名 + 条件 + 优先级）
                      │
                      ▼
           用户/Konnect 导入 .kicad_dru
                      │
                      ▼
            kicad-cli 语法校验 + run_drc
                      │
                      ▼
                  证据入 Gate
```

v1 的 `gen_dru` 输出带 `status: PROPOSAL`，不写文件；写文件必须由用户显式确认或走 Konnect。

### 7.3 优先级是一等概念（v0.3 修正方向）

**v0.2 的定义有方向性错误。** 它写"前面有同 constraint 且条件为其超集的规则 → unreachable"，但同一节又说规则逆序求值——两句话互相矛盾。

正确模型：

```
eval_order = reverse(file_order)      # 文件靠后的规则先求值
effective(C, x) = first r in eval_order where defines(r, C) and cond(r, x)
```

由此得出：

| 写法（文件顺序） | 结果 |
|---|---|
| 窄在前、宽在后 | **危险**：宽规则后写 → 先求值 → 吃掉窄规则 |
| 宽在前、窄在后 | **正确**：窄规则更具体，应该后写 |

形式化定义（`earlier(r1, r2)` 指 r1 在求值顺序中更早，即文件中更靠后）：

| 判定 | 定义 | lint 码 |
|---|---|---|
| `shadowed(r, C)` | ∃ r' : `earlier(r', r)` ∧ `cond(r') ⊇ cond(r)` ∧ `defines(r', C)` | L004 |
| `unreachable(r)` | r 定义的每个 C 都被 shadow | L005 |
| `overlap_conflict(r1, r2, C)` | 条件可同时为真 ∧ 对 C 取值不同 ∧ 顺序决定结果 | L006 |
| `specificity_order_violation(r_sp, r_br, C)` | `cond(r_sp) ⊂ cond(r_br)` ∧ `earlier(r_br, r_sp)` | L007 |
| `ignore_shadow(victim, C)` | ∃ blocker: `earlier(blocker, victim)` ∧ `cond(blocker) ⊇ cond(victim)` ∧ `defines(blocker, C)` ∧ `blocker.severity == ignore` | L008 |

约束：

- 只对**能静态证明**的包含关系给 `block` 结论；其余一律 `review`（对应 core-semantics §4 的 confidence 规则）。
- `ignore` 规则参与匹配，被遮蔽时会让违规永久沉默——这是最隐蔽的一类，必须由 lint 而非常人眼发现。
- 顺序错误不产生语法错误，只产生"规则看起来生效、实际没生效"；最终以 `kicad-cli pcb drc` 实跑为准。

完整定义、lint 编号与静态分析边界见 core-semantics §7。

---

## 8. 复用、引用与许可

**复用**：Konnect（IO/几何/导出/DRC 封装）；KiCad 官方文档（规则语法、ERC 引脚矩阵、PCB Calculator 模型）；社区实践（`kicad-harness` 的"眼与手"思路、公开 `.kicad_dru` 文件的语法样例、`kicad-tools` 的 DRC 符合性测试思路）。

**许可**：IPC-2221 / IPC-7351 是版权标准，不逐字复制表格，只写公式与"依据 IPC-2221 方法"的引用；引用第三方规则保留出处与许可；板厂能力值必须带 URL + 日期。每个技能根目录放 `SOURCES.md`。

---

## 9. 实施计划与验收

### 9.1 里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| M0 | `pcb_overlap` + 测试 + 真板验证 + confidence/gate 语义 | ✅ 完成 |
| M1.0 | Core semantics：判定状态机、域化权威解析、证据置信、假设生命周期、单位、DRU 求值模型 | ✅ 完成 |
| M1.1 | Design Intent：数据模型 → schema → validator → 共享夹具 → 文档 | ✅ 完成（80 tests） |
| M1.2 | DRU parser + AST（真实夹具 + 畸形输入 + 诊断 + 未知子树隔离） | ✅ 完成（21 tests） |
| M1.3 | `lint_dru`：条件解析 + 三值包含判定 + 遮蔽/优先级/ignore 报告 | ✅ 完成（40 tests） |
| M1.4 | `gen_dru`：Intent → PROPOSAL + 精确往返核对 + lint 门槛 | ✅ 完成（32 tests，Codex 复审通过） |
| M1.5 | 统一 evidence + Gate 五态判定（intent/drc/erc/overlap/lint/gen + waiver + assumption） | ✅ 完成（57 tests） |
| M1.6 | `pcb-flow` / `pcb-verification` SKILL.md 接入 gate.py | ✅ 完成 |
| M2 | `pcb-schematic` + `pcb-components` | ✅ 完成 |
| M3 | `pcb-layout` + `pcb-routing` | ✅ 完成 |
| M4 | `pcb-manufacturing` + 全套资产与挂载脚本 | ✅ 完成 |
| M5 | `pcb-calc` / `pcb-analysis` 其余工具 + MCP 封装 | ✅ 完成 |

M1 先做"观察 → 判断 → 修改 → 验证 → Gate"的闭环，领域知识随后往骨架里填。

### 9.2 验收标准

1. **路由**：20 条中英文请求，**Primary Skill 准确率 ≥95%**，不得出现错误主路由；Supporting Skills 允许多选（如"USB 差分怎么布" = `pcb-routing` + `domain-mcu-digital` + `pcb-verification`）。
2. **端到端**：真实工程跑完 P0–P10，每个 Gate 有可检查产物。
3. **算术**：`trace_width` 与 KiCad Calculator 偏差 ≤5%；阻抗模型回归偏差 ≤3%（仅证明模型一致，不证明成品阻抗）。
4. **规则**：生成的 `.kicad_dru` 被 `kicad-cli pcb drc` 接受；shadow/precedence 用例集全部通过。
5. **重叠**：真板 0 误报（与 DRC 一致）+ 合成夹具 100% 检出；16 个测试保持绿色。
6. **可维护**：每个数值有唯一出处；`SOURCES.md` 完整；技能间无重复定义。

### 9.3 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 板厂能力值过期 | 规则过松/过严 | profile 带日期；投板前复核 |
| 技能过长挤占上下文 | 触发后变慢 | SKILL.md ≤450 行，细则下沉 references |
| 与 Konnect 技能漂移 | 两套说法冲突 | 分工 + SSOT + 按域解析（core-semantics §2） |
| `.kicad_dru` 语法/求值随版本变化 | 规则不生效 | lint + 实跑 DRC；标注适用版本 |
| LLM 编造数值 | 设计错误 | 可追溯记录；无来源即登记假设，无法登记则 `INCOMPLETE` |
| 凸包近似高估重叠 | 误报 | 标记 `confidence=low`；闭合失败单独统计 |

---

## 10. 已确认 / 仍开放

**已确认**：本次只交付方案（+ 已实现的 overlap 能力）；覆盖全品类；默认板厂嘉立创 2/4 层，PCBWay/OSHPark 并行。

**仍开放**：界面语言（推荐中文正文 + 英文标识符）；MCP 封装时机（推荐脚本先行）；M1 启动时间。
