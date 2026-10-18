---
name: pcb-flow
description: "KiCad PCB 全流程总控：建立/冻结 Design Intent、维护假设登记、按 P0–P10 推进、用 gate.py 判定 PASS/BLOCKED/INCOMPLETE 并决定能否投板。触发：开始新板、继续项目、下一步做什么、能不能投板、冻结约束、生成规则、签核。English: PCB flow, stage gate, sign-off, design intent."
metadata: { version: 0.3, requires: "konnect>=0.13, kicad>=10" }
---

# PCB 全流程总控（pcb-flow）

本技能负责**编排与判定**，不负责具体绘制/选型/布线细节。阶段技能各自给建议，
但**唯一有效的 Gate 结论来自 `pcb-toolkit/scripts/gate.py`**。

## 何时用 / 何时不用

用：

- 新板立项、从 brief 到投板的阶段推进。
- "下一步做什么""现在能不能投板""这版能不能冻结"。
- 建立、修改、冻结 Design Intent；登记/关闭假设。
- 需要给出 `PASS / PASS_WITH_WAIVERS / PASS_WITH_ASSUMPTIONS / BLOCKED / INCOMPLETE`。

不用：

- 只问某个器件怎么选 → `pcb-components`。
- 只问 DRC/ERC 怎么跑、某条违规怎么修 → `pcb-verification`。
- 只问布线规则/阻抗/差分 → `pcb-routing`。

## 前置条件

| 项 | 要求 |
|---|---|
| KiCad 操作 | 已加载 `konnect` 纪律；任何 `.kicad_*` 变更走 MCP，不手改文件 |
| 工具层 | 仓库内 `pcb-toolkit/scripts/` 可执行；Python 3.9+ |
| Design Intent | P1 起存在 `design-intent.json`，且通过 `validate_intent.py`（无 E 级错误） |
| 阶段 | 明确当前阶段 `P0–P10`；不确定时先按 §阶段表 对齐产物 |

## 决策流程

每一步只做一件事，产物落盘后再进下一步：

1. **对齐阶段**：读取设计日志/现有产物，确定当前阶段与上一 Gate 的结论。
2. **补齐本阶段产物**：按 §阶段表 产出该阶段要求的文件/报告。
3. **采集证据**：调用对应工具生成 JSON 报告（DRC/ERC/overlap/lint/gen）。
4. **调用 Gate**：用 `gate.py` 计算结论（见 §Gate 协议）。
5. **按结论行动**：
   - `BLOCKED`：停止推进；修复或走 waiver（waiver 也由 gate 校验）。
   - `INCOMPLETE`：补检查/补覆盖/消 review/关假设，然后重跑。
   - `PASS_WITH_*`：允许推进，但把假设/豁免写入日志并在下一阶段复核。
   - `PASS`：推进。
6. **记录**：把 Gate JSON 原样存档，日志只引用文件路径与结论。

## Gate 协议（唯一判定入口）

### 调用

```bash
python pcb-toolkit/scripts/gate.py \
  --phase P8 \
  --intent design-intent.json \
  --drc reports/drc.json \
  --erc reports/erc.json \
  --overlap reports/overlap.json \
  --lint reports/lint.json \
  --gen reports/gen.json \
  --waivers reports/waivers.json \
  --json reports/gate_P8.json
```

- 只传**当前阶段实际产生**的报告；缺失项不要用空文件补，`gate.py` 会给出 `CHECK_MISSING`。
- 阶段与必需检查的对应关系见 §阶段表；`gate.py` 内置同一张表。
- 退出码：`0` = PASS 家族，`1` = BLOCKED，`2` = INCOMPLETE 或输入错误。

### 结果契约（不得改写）

`--json` 文件的以下字段必须**原样保留**并随阶段产物提交：

| 字段 | 含义 |
|---|---|
| `verdict` | 唯一结论；不得由其他字段重新推导 |
| `counts` | `errors_total / errors_waived / errors_unwaived / reviews_open / incomplete_open / assumptions_open / assumptions_due / checks_missing` |
| `evidence` | 每个检查的 `coverage`、`counts`、`findings` |
| `findings.unwaived_blocks` | 未豁免的阻断项 |
| `findings.reviews` / `findings.incomplete` | 待复核 / 未完成项 |
| `waivers_applied` / `waivers_rejected` | 生效与无效的豁免及原因 |
| `assumptions_open` / `assumptions_due` / `assumptions_invalid` | 假设状态 |
| `missing_checks` | 本阶段缺失的必需检查 |
| `reasons` | 判定理由 |

**禁止**：

- 根据 "DRC 0 error"、"overlap 0 block" 自行宣布 PASS。
- 把 `INCOMPLETE` 或 `BLOCKED` 改写成"基本通过"。
- 删除 `waivers_rejected` 或 `reasons` 后再汇报。
- 在 `gate.py` 不可用时默认通过；应报 `INCOMPLETE`（无法验证 ≠ 通过）。

### 判定优先级

```
BLOCKED > INCOMPLETE > PASS_WITH_ASSUMPTIONS > PASS_WITH_WAIVERS > PASS
```

- P8 起任何未关闭假设（proposed/active/expired）直接 `BLOCKED`。
- 未豁免 block、到期假设 → `BLOCKED`。
- 必需检查缺失/覆盖不足、review 未消解、引用不完整 → `INCOMPLETE`。

## Design Intent 生命周期

| 阶段 | 动作 |
|---|---|
| P1 | 从 brief 建 `design-intent.json`；每条约束带 candidate + source；不确定项登记为 assumption |
| P2–P4 | 随选型更新 candidates；每次变更 `revision += 1` |
| P5 | **冻结**：`validate_intent.py` 无 E 级错误，`derived` 无 conflict/unresolved |
| P6–P10 | 变更必须开新 revision 并重跑受影响的 Gate |

校验与生成：

```bash
python pcb-toolkit/scripts/validate_intent.py design-intent.json --json reports/intent.json
python pcb-toolkit/scripts/gen_dru.py design-intent.json --json reports/gen.json
```

- `gen_dru` 只产出 **PROPOSAL**，永不自动应用；应用前必须人审并另行落盘。
- conflict 的 requirement 不会被生成；`coverage.complete=false` 时 Gate 为 `INCOMPLETE`。
- conflict 不能用项目值自行放宽；需要新的 authoritative source 替代，并由 gate 重解析验证。

## 假设登记

assumption 必须可直接放进 `assumptions` 映射，并通过 validator（E016 要求
`item`、`assumed_value{value,unit}`、`must_resolve_before`、`impact`、`status` 齐全）：

```json
{
  "assumptions": {
    "A-001": {
      "status": "active",
      "must_resolve_before": "P6",
      "item": "USB VBUS 实际最大电流",
      "assumed_value": {"value": 0.5, "unit": "A"},
      "impact": ["USB 输入保护选型", "VBUS 走线载流"],
      "owner": "hw",
      "fallback": "按 500mA 设计"
    }
  }
}
```

- `status`：`proposed / active / resolved / refuted / expired`。
- `must_resolve_before` 必须是 `P0–P10`；非法值会让 Gate 记 `ASSUMPTION_INVALID` 并 `INCOMPLETE`。
- P8 之前必须全部关闭；P8 之前允许 `PASS_WITH_ASSUMPTIONS`，但要在日志中列出。

## 阶段表

| 阶段 | 主产物 | Gate 必需检查 |
|---|---|---|
| P0 | brief、初始 intent、假设登记 | 无 |
| P1 | 电源树、电流预算 | 无 |
| P2 | BOM v0、选型记录 | 无 |
| P3 | 原理图草案 | `erc` |
| P4 | 原理图评审、ERC 清零 | `erc` |
| P5 | **intent 冻结**、netclass 草案 | 无 |
| P6 | 布局、叠层、overlap 报告 | `drc` + `overlap` |
| P7 | 布线完成、unconnected=0 | `drc` |
| P8 | 全量验证、waiver 台账 | `drc` + `erc` + `overlap` + `lint` |
| P9 | 制造文件、DFM 报告 | 上述 + `gen` |
| P10 | 投板签核、归档 | 上述 + `gen` |

## 速查

- 规范定义：[core-semantics.md](references/core-semantics.md)（判定词、域解析、证据、置信、DRU 模型）
- Intent 数据模型：[design-intent-schema.md](references/design-intent-schema.md)
- 结构契约：[design-intent.schema.json](assets/design-intent.schema.json)
- Gate 实现与 CLI：`pcb-toolkit/README.md` 的 `gate.py` 段
- 验证流程与报告契约：`pcb-verification/SKILL.md`

## 反模式

| 反模式 | 后果 | 正确做法 |
|---|---|---|
| 用 DRC/ERC 单项结果自行判 PASS | 绕过覆盖/假设/豁免规则 | 只认 `gate.py` 的 `verdict` |
| 缺报告就跳过检查 | 误放行 | 让 gate 记 `CHECK_MISSING` → `INCOMPLETE` |
| 把 `INCOMPLETE` 说成"基本没问题" | 掩盖未验证项 | 原样报告并列出缺口 |
| 自动应用 gen_dru proposal | 规则未经人审 | 只提交 PROPOSAL，人工确认后落盘 |
| waiver 只写理由 | 无法审计 | 六个字段齐全 + 策略允许 + 复核日期 |
| 用项目值放宽 FAB/MUST | 违反域解析 | 走 conflict + authoritative replacement |
| 手改 `.kicad_dru`/`.kicad_pcb` | 文件损坏/漂移 | 通过 Konnect MCP 或生成后人工应用 |

## 完成判据

一个阶段结束必须同时满足：

1. `reports/gate_<phase>.json` 存在，`verdict` 属于期望集合。
2. 该文件包含完整 `evidence`、`counts`、`findings`、`waivers_*`、`reasons`（未被裁剪）。
3. 设计日志记录了阶段、gate 文件路径、结论与未关闭项。
4. 本阶段产物齐备（原理图/PCB/报告/BOM 等）。
5. 若存在 waiver：`waivers_applied` 与台账一致，`waivers_rejected` 为空或已解释。

投板前（P9/P10）额外要求：`verdict` 为 `PASS`，或 `PASS_WITH_WAIVERS` 且所有豁免已批准、
复核日期未过期、且不存在 `prohibited` 策略项。

## 参考与来源

- KiCad 10 文档：Design Rules、DRC/ERC、Board Setup。
- Konnect 0.13 toolset 文档（`mcp__konnect__*`）。
- 本套件规范：`references/core-semantics.md`（版本化，冲突时以其为准）。
- 工具实现：`pcb-toolkit/scripts/gate.py`、`validate_intent.py`、`gen_dru.py`。
