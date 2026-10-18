# Evidence 契约（gate.py 输入/输出）

本文件是 `pcb-verification` 与 `pcb-flow` 调用 `gate.py` 时的字段契约。
实现以 `pcb-toolkit/scripts/gate.py` 为准；本文件只描述**可接受/不可接受**的形状。

## 总则

- 所有报告是 UTF-8 JSON；允许 BOM（gate 用 `utf-8-sig` 读取）。
- 缺少关键字段 ≠ 空报告；gate 会归一化为 `coverage=none` + incomplete。
- 任何 `coverage` 不在 `full / partial / none` 内都视为 `none`。
- 任何计数必须是**有限的非负整数**；`0.5`、`"202"`、`-1` 都非法。
- `status` 为 `FAILED / ERROR / ABORTED` 的报告按未完成处理。

## DRC

```json
{
  "violations": [
    {"severity": "error", "rule": "clearance", "description": "…", "uuid": "…"}
  ],
  "unconnected_items": [],
  "schematic_parity": []
}
```

| 字段 | 要求 |
|---|---|
| `violations` | **必需**，列表；元素含 `severity` ∈ error/warning/info |
| `unconnected_items` | **必需**（完整报告），列表或整数；缺失 → `DRC_INVALID_COUNT` |
| `schematic_parity` | **必需**（完整报告），列表或整数；缺失 → `DRC_INVALID_COUNT` |
| `coverage` | 可选，full/partial/none |
| `truncated` | 可选，bool；字段缺失=未截断，**显式 `null` 或非 bool 非法** |
| `status` | 可选；FAILED/ERROR/ABORTED → incomplete |

- `severity=error` → block；`warning` → review；`info` → info。
- `unconnected_items>0`、`schematic_parity>0` 各产生一个 block。
- 缺 `violations` → `DRC_INVALID_REPORT`，coverage=none。
- finding 的 `ref` 按报告结构生成：顶层 `uuid` → `items[].uuid`（多对象按字母序用 `+` 连接）
  → `sheet@x,y`。真实 kicad-cli/Konnect 报告通常只有 `items[].uuid`。
- 缺失 `unconnected_items` / `schematic_parity` **不解释为 0**：报告不完整，gate 记
  `DRC_INVALID_COUNT` 并判 `INCOMPLETE`。生成报告时两个字段都要写出（可为空列表）。
- `truncated=true` 表示列表被截断，不是完整证据；gate 记 `DRC_TRUNCATED` 并降为 partial。
- 显式 `truncated: null` 不是“未截断”，而是非法值：gate 记 `DRC_INVALID_TRUNCATED` 并降为 partial；字段缺失才是未截断。

## ERC

```json
{"violations": [
  {"type": "pin", "severity": "error", "description": "…", "uuid": "…",
   "waiver_policy": "prohibited"}
]}
```

- 结构与 DRC 相同（`violations` 必需）。
- `type` 可选；缺省用 `rule`，再缺省为 `unknown`。
- `ref` 同样取 `items[].uuid`；多个对象用 `+` 连接（如 `A+B`），单独豁免其中一个不会生效。
- `truncated=true` → coverage=partial + `ERC_TRUNCATED`（不完整证据）。
- `waiver_policy` 会保留；未知值 → `ERC_INVALID_POLICY` + incomplete。

## 重叠（pcb_overlap）

```json
{"findings": [
  {"kind": "overlap", "gate_effect": "block",
   "ref_a": "U1", "ref_b": "C3", "detail": "…",
   "waiver_policy": "authority_required"}
]}
```

| 字段 | 要求 |
|---|---|
| `findings` | **必需**，列表 |
| `gate_effect` | block/review/incomplete/info；其它 → incomplete |
| `ref_a` / `ref_b` | 用于 waiver 的 `ref` 匹配 |
| `waiver_policy` | 可选，prohibited/authority_required/project_acceptance |

- 报告级 `coverage` 可选；`none` 表示未完成。
- `summary.verdict` 不被 gate 采用（gate 自己算），不要依赖它。

## 规则 lint（lint_dru）

```json
{"findings": [
  {"code": "L007", "effect": "block", "rule": "…", "constraint": "clearance",
   "message": "…"}
],
 "errors": []}
```

- `findings` **必需**；`errors` 可选（语法错误列表）。
- 语法错误 → coverage=partial + `LINT_SYNTAX`。
- `summary.aborted=true` → coverage=none + `LINT_ABORTED`。
- `effect` 只认 block/review/incomplete/info。

## 规则生成（gen_dru）

```json
{
  "status": "PROPOSAL",
  "applicable": true,
  "coverage": {"conflict": 0, "unresolved": 1,
               "unsupported": 0, "complete": false},
  "lint": {"findings": []},
  "unsupported": [{"requirement": "usb_diff_impedance",
                   "kind": "unresolved", "reason": "…"}]
}
```

PROPOSAL 必须同时满足：

- `applicable` 是 bool；
- `coverage` 含 `conflict/unresolved/unsupported` 三个非负整数；
- `coverage.complete` 是 bool，且等于“三个计数都为 0”；
- `lint.findings` 是列表。

判定：

- `status=REJECTED` → block。
- `coverage.conflict>0` → block；`unsupported` 中 `kind=conflict` 的条目会按 requirement 生成 ref。
- `unresolved/unsupported` → incomplete（coverage 不完整）。
- `applicable=false` → incomplete。

## Design Intent

`--intent` 指向 intent JSON（不是 validator 报告）；gate 内部调用 `validate_intent.validate()`：

| validator 结果 | gate 效果 |
|---|---|
| error | block |
| incomplete | incomplete |
| warning | info |
| `derived.constraints.<name>.status=conflict` | block（`INTENT_CONFLICT`，ref=requirement） |
| `derived.constraints.<name>.status=unresolved` | incomplete（`INTENT_UNRESOLVED`） |

`sources` 与 `requirements` 同时用于 waiver 校验（authority 资格、替代关系）。

## Waiver

```json
[{"id": "W-1", "code": "DRC_clearance", "ref": "…",
  "reason": "…", "approved_by": "…", "review_by": "2026-11-01",
  "compensating": "…", "authority": "S-003"}]
```

- 六字段必填：`id / code / reason / approved_by / review_by / compensating`。
- `review_by` 必须 `YYYY-MM-DD` 且不早于今天。
- `policy` 由 finding/requirement 决定；waiver 自带 `policy` 记为无效。
- `authority_required`：`authority` 必须存在且类型属于
  `datasheet / standard / fab_profile / project_constraint`。
- 冲突类（`INTENT_CONFLICT` / `GEN_CONFLICT`）还要求 `replacement`：
  - 结构合法、含 `id`、`source == authority`、`level` ∈ MUST/SHOULD；
  - authority 在该 requirement 域内合格；
  - `replacement.id` 不得与保留候选重名；
  - 替代后重解析为 `adopted`，`basis` 非空、与 `overridden` 不相交、
    只引用存在的候选，且 replacement 进入 `basis`。
- 无效 waiver 不解除 block，并出现在 `waivers_rejected`。

## gate.py 输出

```json
{
  "tool": "gate", "version": "0.1", "phase": "P8",
  "verdict": "INCOMPLETE",
  "counts": {"checks": 4, "errors_total": 0, "errors_waived": 0,
             "errors_unwaived": 0, "reviews_open": 2,
             "incomplete_open": 1, "assumptions_open": 1,
             "assumptions_due": 0, "checks_missing": 0},
  "evidence": [{"check": "drc", "tool": "kicad-cli", "coverage": "full",
                "counts": {"block": 0, "review": 2, "incomplete": 0, "info": 0},
                "findings": []}],
  "findings": {"unwaived_blocks": [], "reviews": [], "incomplete": []},
  "waivers_applied": [], "waivers_rejected": [],
  "assumptions_open": [], "assumptions_due": [], "assumptions_invalid": [],
  "missing_checks": [], "reasons": ["…"]
}
```

- `verdict` 只有 `PASS / PASS_WITH_WAIVERS / PASS_WITH_ASSUMPTIONS / BLOCKED / INCOMPLETE`。
- 优先级：BLOCKED > INCOMPLETE > PASS_WITH_ASSUMPTIONS > PASS_WITH_WAIVERS > PASS。
- 退出码：0（PASS 家族）、1（BLOCKED）、2（INCOMPLETE/输入错误）。

## 阶段必需检查

| 阶段 | 必需 |
|---|---|
| P3 / P4 | `erc` |
| P6 | `drc` + `overlap` |
| P7 | `drc` |
| P8 | `drc` + `erc` + `overlap` + `lint` |
| P9 / P10 | 上述 + `gen` |

缺失即 `CHECK_MISSING` → `INCOMPLETE`；覆盖非 full 即 `CHECK_PARTIAL` → `INCOMPLETE`。
