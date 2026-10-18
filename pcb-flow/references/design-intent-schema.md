# Design Intent Schema（M1.1）

- 版本：0.1 · 对应 Core Semantics 0.2.3
- 结构文件：[`../assets/design-intent.schema.json`](../assets/design-intent.schema.json)（JSON Schema 2020-12）
- 语义实现：[`../../pcb-toolkit/scripts/validate_intent.py`](../../pcb-toolkit/scripts/validate_intent.py)
- 共享夹具：[`../../pcb-toolkit/tests/fixtures/intent/`](../../pcb-toolkit/tests/fixtures/intent/)

本文档描述**已经被测试固定住的行为**，不是待实现的规格。

---

## 1. 为什么要分两份规则

Design Intent 同时承担两件事：**声明意图**（谁要求什么）和**记录解析结果**（resolver 算出了什么）。这两件事的形状可以完全用 JSON Schema 描述；但下面这些不能：

- `source` / `candidate` / `assumption` 的跨引用是否存在；
- `basis` 是否属于当前 requirement；
- resolver 重算结果是否与 `derived` 一致；
- 数值是否有限、容差是否非负、`min <= max`；
- `equal` 与数值方向的 `value` 类型差异。

因此分工是：

| 规则 | JSON Schema | validator |
|---|---|---|
| 类型、枚举、必填字段 | ✅ | ✅（双保险） |
| candidate 形状随 `direction` 变化 | ✅（按 direction 展开 `oneOf`） | ✅（`E019`） |
| `value` / `range` / `tolerance_pct` 互斥 | ✅ | ✅ |
| 非负容差 | ✅（`minimum: 0`） | ✅ |
| source / candidate / assumption 回指 | ❌ | ✅ |
| derived 与 resolver 一致（含 level） | ❌ | ✅（`E018`） |
| 有限数、`min <= max` | ❌ | ✅ |
| 空骨架的 Gate 覆盖 | ❌ | ❌（属于 Gate，不属于数据校验） |

**共同覆盖的部分用共享夹具锁定**：同一份 intent 同时喂给 schema 和 validator，两边分别断言各自的预期，而不是互相比较。

---

## 2. 顶层结构

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | `const 1` | 整数；`true` 不是合法版本 |
| `project_id` | string | 非空 |
| `revision` | integer ≥1 | 每次冻结递增 |
| `units` | object | 六个核心单位固定，见 §5 |
| `sources` | map `S-###` → source | 全局引用表 |
| `requirements` | map key → requirement | **输入**：候选主张 |
| `assumptions` | map `A-###` → assumption | 全局 |
| `derived` | object | **输出**：resolver 结果与 provenance |

`waivers` 尚未进入 schema（M1.5 随 Gate 一起定义）。

---

## 3. Requirement 与 Candidate

`requirements` 的每个条目按 `direction` 选一种形状。JSON Schema 无法把子对象的形状与父对象的 `direction` 关联，所以 schema 在 **requirement 层**展开 `oneOf`（`req_at_least` / `req_at_most` / `req_exact` / `req_equal`），而不是在 candidate 层猜。

| direction | candidate 形状 |
|---|---|
| `at_least` / `at_most` | 必填数值 `value`；禁止 `range`、`tolerance_pct` |
| `exact` | 二选一：`value`（可选 `tolerance_pct ≥ 0`）或 `range {min,max}`；禁止混用 |
| `equal` | 必填 `value`，字符串或数值；禁止 `range` / `tolerance_pct` |

公共字段：`id`（requirement 内唯一）、`authority`、`level`、`source`。

requirement 公共字段：`domain`、`direction`、`level`、`waiver_policy`、`candidates`，可选 `assumptions: [A-###]`。

**层次语义**：`requirement.level` 是"这项要求对项目多重要"；`candidate.level` 是"来源措辞的强度"（must / shall → `MUST`，recommended → `SHOULD`，typical → `INFO`）。resolver 只把 `candidate.level == MUST` 且 authority 在域 hard 集合里的候选当作硬约束。

---

## 4. derived 的三态

`derived.constraints.<key>` 必须是下列之一：

```json
{"status": "adopted", "value": 0.15, "basis": ["C-001"], "overridden": []}
{"status": "adopted", "range": {"min": 81, "max": 99}, "basis": ["C-001"]}
{"status": "conflict", "conflict": {"code": "project_loosen_hard_bound",
                                    "hard": ["C-001"], "project": ["C-002"],
                                    "waiver_policy": "authority_required"}}
{"status": "unresolved", "reason": "no_candidate"}
```

- `adopted`：必须有 `value` **或** `range`（互斥）、非空 `basis`；不得出现 `conflict` 字段（哪怕是 `null`）。
- `conflict`：必须有 `conflict.code`；不得有 `value`/`range`。
- `unresolved`：必须有 `reason`；不得有 `value`/`range`/`conflict`。
- 可选 `level`：仅当 resolver 降级到经验值时出现（`HEURISTIC`），且必须与重算结果一致。

---

## 5. 单位与假设

`units` 固定六个核心键（`length: mm`、`voltage: V`、`current: A`、`impedance: ohm`、`frequency: Hz`、`temperature: C`），可选扩展键也必须是 canonical 值。**字段名不得带单位后缀**。

`assumed_value` 必须是 `{value, unit}` 对象——假设也是数值，同样受单位规范约束。`must_resolve_before` 限定 `P0`–`P10`。

---

## 6. 共享夹具约定

路径：`pcb-toolkit/tests/fixtures/intent/case_*.json`

```json
{
  "name": "exact_value_and_range",
  "note": "exact 同时给 value 与 range：两者都应拒绝",
  "expect": {"schema": false, "codes": ["E019"]},
  "intent": { ... }
}
```

测试 `test_intent_schema.py` 对每个 case 做两次独立断言：

1. `jsonschema` 的判定 == `expect.schema`
2. validator 的诊断码包含 `expect.codes`

**禁止**写成"两边结果一致即可"——那会让 schema 和 validator 一起接受同一份错误输入。

当前夹具：

| 文件 | schema | validator |
|---|---|---|
| `case_valid_min` | valid | — |
| `case_at_least_range` | invalid | `E019` |
| `case_at_least_tolerance` | invalid | `E019` |
| `case_at_most_tolerance` | invalid | `E019` |
| `case_exact_value_and_range` | invalid | `E019` |
| `case_conflict_with_value` | invalid | `E014` |
| `case_equal_string` | valid | — |
| `case_missing_units` | invalid | `E003` |
| `case_large_int_equal` | valid | `E018` |
| `case_assumption_bad_value` | invalid | `E016` |
| `case_impact_non_string` | invalid | `E016` |

最后一条是刻意保留的：Schema 只能看出两个数是 `number`，`9007199254740992 ≠ 9007199254740993` 只有 validator 能判。

---

## 7. 已知表达边界

| 边界 | 原因 | 由谁处理 |
|---|---|---|
| `Infinity` / `NaN` | JSON 数字本身不允许，但 Python `json` 接受 | validator（`E019`/`E022`） |
| `range.min <= max` | JSON Schema 无跨字段比较 | validator（`E008`/`E022`） |
| `equal` 与数值方向的 `value` 类型差异 | 需要父级 `direction` | validator（`E021`） |
| 同 requirement 内 candidate `id` 唯一 | JSON Schema 无唯一性约束（`uniqueItems` 不按键） | validator（`E008`） |
| 空 `requirements` + 空 `derived` | 结构合法 | 允许；Gate 另查覆盖 |

---

## 8. 版本

| 版本 | 变更 |
|---|---|
| 0.1 | 首版：requirements/candidates、derived 三态、units、assumptions；共享夹具 7 例 |

改结构必须同时更新 schema、validator 与夹具。共享夹具覆盖的规则若只改一边，测试会变红；但新增而**未进夹具**的规则不会被自动发现——所以每条新规则都要配套正反夹具。
