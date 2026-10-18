---
name: pcb-verification
description: "KiCad 验证全流程：采集 DRC/ERC/overlap/lint/gen 报告，调用 gate.py 得到五态结论，管理 waiver 与报告归档。触发：DRC、ERC、重叠、规则 lint、能不能投板、验证报告、违规怎么修。English: DRC, ERC, design rule check, verification, sign-off report."
metadata: { version: 0.3, requires: "konnect>=0.13, kicad>=10" }
---

# PCB 验证（pcb-verification）

本技能负责**采证与判定**。判定只来自 `pcb-toolkit/scripts/gate.py`；
本技能不会、也不允许根据单项检查自行给出 `PASS`。

## 何时用 / 何时不用

用：

- 布局后、布线后、出图前的 DRC/ERC/overlap 检查。
- `.kicad_dru` 规则体检（lint）与由 Intent 生成规则提案（gen）。
- "现在能不能投板""这些违规要不要修""报告怎么写"。

不用：

- 只问某个违规的电气根因/改法 → 先看本文 §违规处置，再按域转 `pcb-layout` / `pcb-routing`。
- 只问选型/降额 → `pcb-components`。
- 阶段推进与最终签核 → `pcb-flow`。

## 前置条件

| 项 | 要求 |
|---|---|
| KiCad | 10.x；`kicad-cli` 可用（报告落盘优先用它） |
| Konnect | 已加载；需要 ERC 时 `load_toolset("sch_export")` |
| Intent | 已冻结（P5 后）；未冻结时验证结论只能算 `INCOMPLETE` |
| 目录 | 报告统一放 `reports/`；文件名带阶段，如 `drc_P8.json` |
| 工具 | `pcb-toolkit/scripts/` 可执行 |

## 证据链

```
原理图/PCB
   ├─ kicad-cli / Konnect → drc.json / erc.json
   ├─ pcb_overlap.py      → overlap.json
   ├─ lint_dru.py         → lint.json
   └─ gen_dru.py          → gen.json
                ↓
        gate.py --phase Pn --json gate_Pn.json
                ↓
   verdict + evidence + counts + findings + waivers/reasons（原样归档）
```

缺任何一项都不要伪造空报告：不传该参数，gate 会记 `CHECK_MISSING`。

## 采集

### DRC

优先落盘完整报告：

```bash
kicad-cli pcb drc --format json --output reports/drc_P8.json board.kicad_pcb
```

或 Konnect（记得同时写文件）：

```text
mcp__konnect__run_drc(board="board.kicad_pcb", severity="warning",
                      output="reports/drc_P8.json", limit=1000)
```

要点：

- 报告必须含 `violations`（列表）；`unconnected_items`、`schematic_parity` 可以是列表或整数。
- `severity` 只认 `error / warning / info`；未知值会让 gate 记 `DRC_UNKNOWN_SEVERITY`。
- `unconnected_items > 0` 或 `schematic_parity > 0` 都会被 gate 当作 block。
- 截断的报告（`truncated: true`）不是完整证据；重跑到完整或直接判 `INCOMPLETE`。

### ERC

```bash
kicad-cli sch erc --format json --output reports/erc_P8.json board.kicad_sch
```

Konnect 路径（先加载 toolset）：

```text
mcp__konnect__load_toolset("sch_export")
mcp__konnect__run_erc(schematic="board.kicad_sch", severity="warning",
                      output="reports/erc_P8.json")
```

`output` 写的是工具响应（含 `violations` 与坐标来源），gate 只取 `violations`，其余键忽略。
不要改字段名，不要补造 `violations` 元素。

层次化设计必须覆盖全部 sheet；只跑根 sheet 视为覆盖不足 → `INCOMPLETE`。

### 重叠（布局后与投板前必跑）

```bash
python pcb-toolkit/scripts/pcb_overlap.py board.kicad_pcb --json reports/overlap_P8.json
python pcb-toolkit/scripts/pcb_overlap.py board.kicad_sch --json reports/overlap_sch_P8.json
```

- `gate_effect` 为 `block` 的必须修；`review` 需人工确认（gate 会判 `INCOMPLETE`）。
- 贴边相切（`touch`）只是 `info`，不应被说成重叠。
- 需要焊盘互检时加 `--include-pads`，并在报告中注明。

### 规则 lint

```bash
python pcb-toolkit/scripts/lint_dru.py board.kicad_dru --json reports/lint_P8.json
```

- 语法错误会让报告 `coverage=partial`，gate 判 `INCOMPLETE`。
- `L010`（潜在规则重叠）是 review 项，需要确认是否真的冲突。
- `severity ignore` 的规则**仍参与匹配**：命中后该 constraint 即被"处理"，可能让后续（文件中更靠前）的规则永远看不到。需按 `L008` 检查 ignore 遮蔽，不能把 ignore 当"规则已移除"。

### 规则生成

```bash
python pcb-toolkit/scripts/gen_dru.py design-intent.json --json reports/gen_P9.json
```

- 只产出 **PROPOSAL**；`applicable=false` 或 `coverage.complete=false` 都会让 gate 判 `INCOMPLETE`。
- conflict 会直接 block；必须由新的 authoritative source 替代并重解析，不能靠 waiver 绕过。

## Gate 调用

按阶段选择参数，缺项不要补空文件：

```bash
# P3/P4
python pcb-toolkit/scripts/gate.py --phase P4 --intent design-intent.json \
  --erc reports/erc_P4.json --json reports/gate_P4.json

# P6
python pcb-toolkit/scripts/gate.py --phase P6 --intent design-intent.json \
  --drc reports/drc_P6.json --overlap reports/overlap_P6.json \
  --json reports/gate_P6.json

# P8
python pcb-toolkit/scripts/gate.py --phase P8 --intent design-intent.json \
  --drc reports/drc_P8.json --erc reports/erc_P8.json \
  --overlap reports/overlap_P8.json --lint reports/lint_P8.json \
  --waivers reports/waivers.json --json reports/gate_P8.json

# P9/P10
python pcb-toolkit/scripts/gate.py --phase P9 --intent design-intent.json \
  --drc reports/drc_P9.json --erc reports/erc_P9.json \
  --overlap reports/overlap_P9.json --lint reports/lint_P9.json \
  --gen reports/gen_P9.json --waivers reports/waivers.json \
  --json reports/gate_P9.json
```

## 判定与处置

退出码：`0` PASS 家族、`1` BLOCKED、`2` INCOMPLETE 或输入错误。

| verdict | 动作 |
|---|---|
| `PASS` | 归档，进入下一阶段 |
| `PASS_WITH_WAIVERS` | 归档；确认 `waivers_applied` 与台账一致，复核日期未过期 |
| `PASS_WITH_ASSUMPTIONS` | 归档；列出未到期假设，下一阶段必须复核 |
| `INCOMPLETE` | 按 `missing_checks` / `findings.incomplete` / `reviews` 补证据或消项后重跑 |
| `BLOCKED` | 按 `findings.unwaived_blocks` 修复；或提交合规 waiver 后重跑 |

**不得**：

- 因为 "DRC errors=0" 就宣布通过——覆盖、假设、waiver、lint 都可能未过。
- 把 `gate.py` 的 `verdict` 改写成自己的措辞（如"基本通过"）。
- 隐藏 `waivers_rejected`、`missing_checks` 或 `reasons`。

## Waiver 流程

1. 只对 `block` finding 提交 waiver；`review`/`incomplete` 不是豁免对象。
2. 记录六字段：`id / code / reason / approved_by / review_by / compensating`。
3. 策略由 finding/requirement 决定：
   - `prohibited`：不可豁免。
   - `authority_required`：额外给 `authority`（必须是 `sources` 里类型合格的来源）。
   - 冲突类（`INTENT_CONFLICT` / `GEN_CONFLICT`）：还必须给 `replacement`，
     且替代后重解析必须通过；`replacement.id` 不得与保留候选重名。
4. `review_by` 用 `YYYY-MM-DD`，过期即无效。
5. 提交后重跑 `gate.py`；以新的 `waivers_applied` / `waivers_rejected` 为准。

## 违规处置速查

| 症状 | 先查 | 常见修法 |
|---|---|---|
| `clearance` | netclass / 规则优先级 / 板厂下限 | 调间距、改 netclass、修规则 |
| `unconnected` | 布线未完成 / zone 未填 | 补线、重填 zone、查网络名 |
| `silk_over_copper` | 丝印压焊盘 | 移丝印或开窗 |
| `courtyard_overlap` | 布局间距 | 移器件、改封装 |
| `lib_footprint_mismatch` | 库版本 | 更新封装或忽略并记录 |
| `schematic_parity` | 原理图/PCB 不同步 | 重新同步网络与位号 |
| `pin not driven` (ERC) | 电源标志/驱动 | 加 `PWR_FLAG` 或驱动源 |
| `L007/L010` | 规则遮蔽/重叠 | 拆分条件、显式优先级 |

## 报告模板

对外的验证报告必须包含（字段名与 gate JSON 一致）：

```json
{
  "phase": "P8",
  "verdict": "<原样>",
  "counts": { "...": "原样" },
  "evidence": [ "..." ],
  "findings": { "unwaived_blocks": [], "reviews": [], "incomplete": [] },
  "waivers_applied": [],
  "waivers_rejected": [],
  "missing_checks": [],
  "reasons": []
}
```

人读摘要可以另写，但必须同时给出 `gate_P8.json` 路径；摘要不得与 JSON 冲突。

## 反模式

- 只跑 DRC 就回答"可以投板"。
- ERC 只跑根 sheet（层次设计漏检）。
- 把 `run_erc` 的返回截断后当完整报告。
- 手改 `.kicad_dru` 而不 lint、不复核求值顺序。
- waiver 只写"已确认"而无批准人/补偿措施/复核日期。
- 用 `ignore` 让违规消失，却不进台账。

## 完成判据

1. 本阶段要求的每类报告都存在且非空（按 §阶段表）。
2. `gate.py` 已运行，`--json` 输出存在且字段完整。
3. `verdict` 为期望值；`BLOCKED/INCOMPLETE` 已按 findings 处理或明确记录未处理。
4. 报告与 waiver 台账一致；`waivers_rejected` 为空或逐条解释。
5. 设计日志记录报告路径与结论。

## 参考

- 证据契约：[evidence-contract.md](references/evidence-contract.md)（各报告字段与非法情形）
- 规范：[../pcb-flow/references/core-semantics.md](../pcb-flow/references/core-semantics.md)
- 工具说明：`pcb-toolkit/README.md`（gate/lint/gen/overlap）
- Konnect：`run_drc`、`run_erc`、`run_design_review`
