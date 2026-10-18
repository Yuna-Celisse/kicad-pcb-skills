# Core Semantics — 规范层定义（M1.0）

- 版本：**0.2.3**
- 状态：**normative（规范性）**。所有技能、工具、Gate 输出必须遵守；改动需升版本并在文末记迁移说明。
- 适用范围：判定词、约束权威解析、证据与置信、假设生命周期、单位规范、约束求值模型。
- 非目标：不含任何工程数值、板厂参数或具体流程。那些属于 `references/` 下的领域文档。

> 这份文档存在的唯一理由：让 `lint_dru`、`gen_dru`、`pcb-verification`、`pcb-flow` 在 M2/M3 时不需要再返工。任何技能自行发明状态词、单位或权威顺序，都属于违反本规范。

---

## 1. 术语

| 术语 | 定义 |
|---|---|
| **Requirement** | 一条可判定的要求：`{key, domain, direction, level}`，例如“最小间距 ≥ 0.15mm”。 |
| **Candidate** | 某个来源对该 requirement 给出的取值主张：`{id, value, authority, level, source}`；`id` 只在所属 requirement 内唯一。 |
| **Constraint** | 解析后的有效边界：`{min | max | nominal ± tol, 依据 candidate, 域}`。 |
| **Finding** | 一次检查产生的观察结果：把 observed 与 constraint 比较。 |
| **Evidence** | 支撑 finding 的来源与方法：`{source, method, geometry}`。 |
| **Waiver** | 对某条 finding 的显式豁免记录，必须带补偿措施与批准人。 |
| **Assumption** | 因信息缺失而采用的显式假设，必须带影响面与关闭期限。 |
| **Gate** | 阶段出口检查，输出唯一 Verdict。 |
| **Verdict** | 五态之一（§3），不得扩展。 |
| **Confidence** | 证据可信度（§4），决定该 finding 能否单独阻断 Gate。 |
| **Authority** | 取值主张的来源等级（§2.2）。 |
| **Domain** | 约束所属的规则域（§2.1），决定谁有硬否决权。 |

---

## 2. 约束域与权威解析

### 2.1 域（Domain）

| domain | 管什么 | 硬约束来源 |
|---|---|---|
| `safety` | 安规、隔离、爬电/电气间隙、认证 | `STANDARD` |
| `manufacturing` | 板厂可制造硬下限（线宽/间距/孔径/环宽） | `FAB` |
| `component` | 器件电气与布局要求（耐压、结温、去耦、热焊盘） | `DATASHEET`、`STANDARD` |
| `signal_integrity` | 阻抗、长度、skew、回流、串扰 | `STANDARD`、`DATASHEET` |
| `project` | 行为、架构、机械、成本、接口约定 | `PROJECT` |
| `practice` | 通用经验（3W、20H、去耦距离、摆件习惯） | 无 |

### 2.2 权威等级（Authority）

`PROJECT` / `DATASHEET` / `STANDARD` / `FAB` / `DOMAIN` / `GENERIC`

等级 + 域共同决定效力，**不存在全局 total order**。

### 2.3 域策略与解析（替代"取更严格者"）

```yaml
DOMAIN_POLICY:
  safety:           {hard: [STANDARD],            soft: [STANDARD, PROJECT, DOMAIN, GENERIC]}
  manufacturing:    {hard: [FAB],                 soft: [FAB, PROJECT, DOMAIN, GENERIC]}
  component:        {hard: [DATASHEET, STANDARD], soft: [DATASHEET, STANDARD, PROJECT, DOMAIN, GENERIC]}
  signal_integrity: {hard: [STANDARD, DATASHEET], soft: [STANDARD, DATASHEET, PROJECT, DOMAIN, GENERIC]}
  project:          {hard: [PROJECT],             soft: [PROJECT, DOMAIN, GENERIC]}
  practice:         {hard: [],                    soft: [DOMAIN, GENERIC]}
```

`soft` 是**域内**顺序，不是全局顺序；只有 `hard` 里的权威拥有否决权。

```
resolve(requirement):
    policy = DOMAIN_POLICY[requirement.domain]     # 未知域 -> ERROR，不得默认
    cands  = requirement.candidates

    # 1) 硬约束
    hard = [c for c in cands if c.level == MUST and c.authority in policy.hard]
    if hard:
        bound = combine(hard, requirement.direction)       # 可能 CONFLICT
        if is_conflict(bound): return bound
        proj = combine([c for c in cands
                        if c.authority == PROJECT and c.level in (MUST, SHOULD)],
                       requirement.direction)              # 可能 CONFLICT
        if is_conflict(proj): return proj
        if proj and loosens(proj, bound, requirement.direction):
            return CONFLICT(hard=bound, project=proj,
                            waiver_policy=requirement.waiver_policy)
        return ADOPT(tighten(bound, proj), basis=hard + (proj or []))

    # 2) 域内软顺序
    for auth in policy.soft:
        group = [c for c in cands
                 if c.authority == auth and c.level in (MUST, SHOULD)]
        if group:
            r = combine(group, requirement.direction)
            return r if is_conflict(r) else ADOPT(r, basis=group)

    # 3) 只剩经验值
    r = combine([c for c in cands if c.level == HEURISTIC], requirement.direction)
    return r if is_conflict(r) else ADOPT(r, level=HEURISTIC)
```

关键规则：

1. **硬约束不可放宽**：项目值可以更严格，不能更宽松。更宽松 → `CONFLICT`。
2. **安全/制造/器件域里，项目不是最高权威**。"项目 0.5mm 爬电"不能覆盖 IEC；"项目 0.10mm 间距"不能覆盖板厂 0.15mm。
3. **`FAB` 必须出现在 manufacturing 的 soft 里**：板厂没有 MUST 级声明时，`FAB` 的 SHOULD 仍优先于 `PROJECT`，不能被 fallback 忽略。
4. **同权威才比严格**：只有同域、同 authority 的多个候选冲突时，才按 §2.4 合并。
5. **HEURISTIC / INFO 不参与绑定**：hard 只收 `MUST`；项目收紧与 soft 只收 `MUST` / `SHOULD`。经验值只能填空，不能改判，也不能触发 `CONFLICT`；经验值之间彼此矛盾时结果为 `unresolved / heuristic_disagreement`。
6. **解析必须留痕**：每个 constraint 记录 `basis`（胜出候选）与 `overridden`（被压制候选）。

### 2.4 方向（direction）与合并

| direction | 含义 | combine | loosens(project, bound) |
|---|---|---|---|
| `at_least` | 不得小于（间距、线宽、裕量、电流能力） | 取 max | project.value < bound.value |
| `at_most` | 不得大于（长度、skew、压降、结温） | 取 min | project.value > bound.value |
| `exact` | 必须落在区间（阻抗 ± tol、频率） | 取交集 | 项目区间超出硬区间 |
| `equal` | 必须相等（引脚映射、极性） | 不一致即冲突 | 值不同 |

`combine` 是**部分函数**，可能失败：

```
combine(candidates, direction) -> Constraint | CONFLICT | None
```

| 情况 | 结果 |
|---|---|
| 候选为空 | `None`（"无约束"），不是 0 或默认值 |
| `exact` 区间交集为空 | `CONFLICT(empty_intersection)` |
| `equal` 值不一致 | `CONFLICT(value_mismatch)` |
| 多个 `PROJECT` 候选互相冲突 | `CONFLICT(project_conflict)` |

**不得**在冲突时返回一个"大致有效"的 Constraint；调用方必须先处理 `CONFLICT`。多个项目来源（机械规格 / design brief / 用户覆盖）必须先合并，再与硬约束比较。

### 2.4.1 候选表示由 direction 决定

| direction | 允许的 candidate 表示 |
|---|---|
| `at_least` / `at_most` | 数值 `value`；不接受 `range` |
| `exact` | `value`（可带 `tolerance_pct`）或 `range: {min, max}`；零容差也解析为 `{min: v, max: v}` |
| `equal` | 字符串或数值（引脚映射、极性、枚举） |

表示与 direction 不匹配属于**结构错误**，不是解析结果；validator 必须报错而不是让 resolver 去猜。

额外约束：

- `value` 与 `range` 互斥；`range` 与 `tolerance_pct` 互斥；`tolerance_pct` 只用于 `exact`。
- `tolerance_pct` 必须是有限非负数；负容差不是"更严格的约束"，而是错误输入。
- 所有数值必须是有限数（拒绝 `inf` / `nan`）。

### 2.5 冲突记录

```yaml
conflict:
  requirement: min_clearance
  domain: manufacturing
  hard:    {value: 0.15, unit: mm, authority: FAB, source: jlcpcb-4l-2026-10}
  project: {value: 0.10, unit: mm, authority: PROJECT, source: design-brief}
  waiver_policy: authority_required
  resolution: BLOCKED
  remedy: 提高项目约束，或取得特殊工艺能力并登记为新的 authoritative source
```

`CONFLICT` 不是错误值，而是一种**必须先解决才能继续**的状态。禁止自动取"更宽松的那个"。

### 2.5.1 解析结果的三态表示

`resolve()` 的代数结果是 `Constraint | CONFLICT | None`，落到数据上必须是 tagged result，**不得用 `null` 兼表两义**：

| status | 含义 | 必填 | 禁止 |
|---|---|---|---|
| `adopted` | 解析出有效约束 | `value`（或 `range`）、非空 `basis` | `conflict` |
| `conflict` | 候选之间冲突 | `conflict.code` | `value` / `range` |
| `unresolved` | 无候选（`combine([]) → None`） | `reason` | `value` / `conflict` |

`basis` 与 `overridden` 记录的是 **Candidate id**，不是 source id——同一个 datasheet 完全可能给出"最小 0.2 / 推荐 0.3"两条主张，只记 source 无法指出实际选中了哪条。

**一致性校验的完整口径**：比较 `status`、`value` / `range`、`basis` / `overridden`（集合语义，忽略顺序与重复）、`conflict` 的 `code` + `hard`/`project` 引用 + `waiver_policy`，以及结果携带的 `level`（防止经验值结果被手工提升为 `MUST`）。

数值比较规则：`equal` 用**精确相等**；其余数值用相对误差（`rel_tol=1e-12`），**不设绝对下限**——否则 `1e-13` 与 `0` 会被判为一致，F/H/s 这类小量级会丢失分辨力。

只比 `code` 不足以发现候选引用或豁免策略被篡改。重复的 candidate id 单独诊断，不与"结果不一致"混为一谈。

### 2.6 豁免策略（waiver_policy）

不是所有约束都能被 waiver 放过。每个 requirement 声明 `waiver_policy`：

| 值 | 含义 | 典型 |
|---|---|---|
| `prohibited` | 不允许豁免 | 安规 MUST、法定认证 |
| `authority_required` | 必须由另一个 authoritative source 替代，不能仅凭"接受风险" | 板厂物理能力（应改为特殊工艺能力） |
| `project_acceptance` | 项目负责人书面接受即可 | 内部实践、成本权衡 |

规则：

- `prohibited`：waiver 无效，finding 永远 `block`，Gate 不得出现 `PASS_WITH_WAIVERS`。
- `authority_required`：waiver 必须引用一个**新的 authoritative source**（如 `JLCPCB-0.08mm-special`），否则视为无效。
- `project_acceptance`：允许 `PASS_WITH_WAIVERS`，但必须记录批准人、补偿措施与复核日期。

这只改变"豁免是否有效"，不改变 §2.3 的解析：`prohibited` 的硬约束依然不能被项目值放宽。

**waiver 记录的最小字段**：`id` / `code` / `reason` / `approved_by` / `review_by` / `compensating`。缺任一字段即无效。

`policy` 由 requirement（或产生 finding 的组件）决定，**waiver 不得自声明 policy**；`authority_required` 必须同时给出替代的 authoritative source（`authority` 字段），且该来源必须能在项目 `sources` 中解析、`type` 属于 authoritative 类别（`datasheet` / `standard` / `fab_profile` / `project_constraint`）。`heuristic`、`calculation` 等不具备资格；存在但资格不足时 waiver 无效。

`review_by` 必须是 ISO 日期（`YYYY-MM-DD`）且不得早于当前日期；过期或格式非法的 waiver 无效。归一化时必须保留 finding 上声明的 `waiver_policy`，不得降级为默认值。

对**冲突类 finding**（`INTENT_CONFLICT` / `GEN_CONFLICT`），"替代"必须可验证：waiver 需提供 `replacement`（该 requirement 的替代 candidate），replacement 必须通过 candidate 结构校验、`source` 等于 `authority`、`level` 为 MUST/SHOULD 且该 authority 在 requirement 域内具备对应资格；`replacement.id` 不得与替换后保留的候选重名。替代后重新解析必须得到 `adopted`，且结果的 `basis` 非空、`basis`/`overridden` 不相交、只引用存在的候选，replacement 必须出现在 `basis` 中。引用冲突原主张的来源、缺 candidate id、经验值替代或无法提供替代主张时，waiver 无效。

---

## 3. 判定状态机

### 3.1 五态（唯一合法集合）

| Verdict | 条件 |
|---|---|
| `BLOCKED` | 存在未豁免的 `gate_effect=block` finding；或存在未解决 `CONFLICT`；或自 P8 起存在到期未关闭的 assumption；或被跳过的 MUST 检查无有效 waiver |
| `INCOMPLETE` | 无 block，但存在：必需检查未运行、覆盖不全、`gate_effect=review` 未确认、证据 `confidence=none` |
| `PASS_WITH_ASSUMPTIONS` | 无 block/incomplete，且存在 `must_resolve_before > 当前阶段` 的活跃 assumption |
| `PASS_WITH_WAIVERS` | 无 block/incomplete/assumption，且存在生效 waiver |
| `PASS` | 以上皆无 |

**不存在 `ASSUMPTION` 这个 verdict。** 假设到期未关闭就是"无法签核"，落到 `BLOCKED`。

### 3.2 组合优先级（多条件同时成立时）

```
BLOCKED > INCOMPLETE > PASS_WITH_ASSUMPTIONS > PASS_WITH_WAIVERS > PASS
```

理由：已经确认的硬伤不会被覆盖缺口改变；而覆盖缺口不能被"带假设通过"掩盖。

### 3.3 阶段合法性

| 阶段 | 允许的 Verdict |
|---|---|
| P0–P7 | 全部五态 |
| P8 起（含 P8/P9/P10） | 不允许 `PASS_WITH_ASSUMPTIONS`；到期假设一律转 `BLOCKED` |

### 3.4 Gate 输出契约

```yaml
gate: P8
verdict: PASS_WITH_WAIVERS
counts:
  errors_total: 3
  errors_waived: 3
  errors_unwaived: 0
  reviews_open: 0
  assumptions_open: 0
evidence:
  - {check: drc, source: kicad-cli, coverage: full}
  - {check: overlap, source: pcb_overlap, coverage: full}
waivers: [W-004, W-007]
assumptions: []
```

Gate 判据一律用**计数**表达，不用文字。`DRC 0 error` 改为 `errors_unwaived == 0`。

---

## 4. 要求依据 与 验证证据（两轴）

v0.1 把 datasheet 与 DRC 放进同一条"证据优先级"，这是概念错误：前者回答"要求是什么"，后者回答"设计是否满足"。两者不可比较，也不能互相替代。

```
Requirement ──basis──► Constraint
Implementation ──verification──► Finding
```

### 4.1 约束依据（constraint basis）

回答"为什么是这个值"。取值即 §2.2 的 authority：`STANDARD` / `DATASHEET` / `FAB` / `PROJECT` / `DOMAIN` / `GENERIC`。

- 每条 constraint 必须带 `basis`，且能追溯到一个 `sources` 条目。
- `basis` 只决定"要求的合法性"，**不能**用来证明"当前设计符合要求"。

### 4.2 验证证据（verification evidence）

回答"凭什么说它满足了"：

| 值 | 含义 |
|---|---|
| `native_rule_engine` | KiCad ERC/DRC 等原生规则引擎 |
| `exact_geometry` | 精确几何（闭合多边形、真实焊盘外形） |
| `direct_read` | 直接读取工程数据（网络表、坐标、叠层） |
| `derived_model` | 由模型计算（线宽、阻抗、热） |
| `approx_geometry` | 近似几何（AABB、凸包、Fab 包络） |
| `manual_review` | 人工确认并记录 |
| `none` | 未验证 |

### 4.3 confidence

| 值 | 含义 |
|---|---|
| `exact` | 精确几何 / 直接读取 / 规则引擎 |
| `derived` | 模型计算，**必须附 `model_status`** |
| `approx` | 近似几何或估算 |
| `none` | 无法取得 |

`derived` 必须带 `model_status`：

- `validated`：模型已与参考实现或实测对齐（如线宽对 KiCad Calculator）
- `candidate`：模型可用但输入未确认（如叠层候选、阻抗估算）

**`derived` 本身不代表足以阻断**——"算得很精确，但叠层是猜的"不能判 block。

### 4.4 gate_effect 映射

| level | confidence | model_status | gate_effect |
|---|---|---|---|
| MUST | `exact` | — | `block` |
| MUST | `derived` | `validated` | `block` |
| MUST | `derived` | `candidate` | `review` |
| MUST | `approx` | — | `review` |
| SHOULD | 任意 | — | `review` |
| HEURISTIC / INFO | 任意 | — | `info` |
| 任意 | `none` | — | `incomplete` |

工具必须自带该判定，Gate 不再二次猜测。

### 4.5 组合

- 任一 `block` → Gate `BLOCKED`
- 否则任一 `review` / `incomplete` → Gate `INCOMPLETE`
- `info` 不影响判定，但必须出现在报告里

**`review` 不能被静默升级为 `block`，也不能被静默忽略。** 解除方式只有两种：用更精确的验证复核，或由人确认并以 `manual_review` evidence 记录。

### 4.6 跨轴规则

- 不同轴不比较强弱：`DATASHEET` 不能证明 PCB 间距合格，DRC 也不能证明要求值正确。
- 要求缺依据（无 `basis`）→ `INCOMPLETE`；实现未验证（`verification = none`）→ `INCOMPLETE`。
- 强验证证据可以否定弱验证证据；弱验证证据不能否定强验证证据。

---

## 5. Assumption 生命周期

### 5.1 记录

```yaml
A-017:
  item: ambient_temperature
  assumed_value: {value: 25, unit: C}
  impact: [trace_width, thermal_margin]
  confidence: low
  must_resolve_before: P8
  owner: user
  status: active        # proposed | active | resolved | refuted | expired
  resolution: null
```

### 5.2 规则

1. 缺参数不得直接 `BLOCKED`；先登记 assumption 并推进（P0–P7）。
2. `assumed_value` 必须带单位（`{value, unit}`）——假设也是数值，同样受 §6 约束；`value` 必须是字符串或有限数值，`impact` 是非空字符串列表。
3. `must_resolve_before` 必须是阶段编号；到期阶段起，该假设自动视为 `expired`。
4. `refuted`（假设被推翻）时，重跑 `impact` 中列出的全部计算与 Gate，并在报告列出受影响条目。
5. 自 P8 起，存在 `active`/`expired` 且 `must_resolve_before <= P8` 的假设 → `BLOCKED`。
6. Assumption 不等于 waiver：假设是"我不知道"，waiver 是"我知道且接受"。

---

## 6. 单位规范

### 6.1 规范单位（canonical）

| 量 | 单位 | 备注 |
|---|---|---|
| 长度 | `mm` | 禁止存储 `mil`；导入时转换并保留 `origin` |
| 电压 | `V` | |
| 电流 | `A` | 禁止 `mA` 直接存储 |
| 阻抗 | `ohm` | |
| 频率 | `Hz` | 禁止 `MHz` 直接存储 |
| 温度 | `C` | 摄氏；温升用 `K` |
| 功率 | `W` | |
| 时间 | `s` | 传播延迟显示可换算 ps/ns |
| 电容 / 电感 | `F` / `H` | |
| 角度 | `deg` | |
| 相对量 | `pct` | 容差、偏差 |

### 6.2 规则

1. 存储值一律用规范单位，**不做隐式换算**；换算只发生在展示层。
2. **字段名不带单位后缀**：用 `max_skew` + `units.length: mm`，不用 `max_skew_mm`。validator 拒绝 `_mm`/`_v`/`_a`/`_hz`/`_s` 这类物理量后缀；比例字段可用 `_pct`。
3. 容差用 `{nominal, tol_pct}` 或 `{min, max}`，禁止两者混用同一字段。
4. 同一 requirement 内不得混用单位；发现混用 → `INCOMPLETE`。
5. 外部导入（板厂表、器件手册）保留原始值与单位：`origin: {value: 6, unit: mil}`。

---

## 7. 约束求值模型（`.kicad_dru`）

### 7.1 求值顺序

KiCad 逆序求值：**文件中靠后的规则先匹配**；某 constraint 一旦被匹配就不再继续。

```
eval_order = reverse(file_order)

effective(constraint C, point x) =
    first r in eval_order
    where defines(r, C) and eval(r.condition, x) == true
```

注意：`severity ignore` 的规则**也参与匹配**，命中后该 constraint 即被"处理"，可能让后面（文件中更靠前）的规则永远看不到它。

### 7.2 形式化定义（lint 的判定基础）

设 `earlier(r1, r2) := r1 在 eval_order 中位于 r2 之前`（即 r1 在文件中更靠后）。

| 判定 | 定义 |
|---|---|
| `shadowed(r, C)` | ∃ r' : `earlier(r', r)` ∧ `cond(r') ⊇ cond(r)` ∧ `defines(r', C)` |
| `unreachable(r)` | 对 r 定义的每个 C 都 `shadowed(r, C)` |
| `partial_shadow(r)` | 只对部分 C 成立 |
| `overlap_conflict(r1, r2, C)` | `cond(r1) ∩ cond(r2) ≠ ∅` ∧ 两者对 C 取值不同 ∧ 顺序决定结果 |
| `specificity_order_violation(r_sp, r_br, C)` | `cond(r_sp) ⊂ cond(r_br)` ∧ `earlier(r_br, r_sp)` → 宽规则先求值，窄规则永远不生效 |
| `ignore_shadow(victim, C)` | ∃ blocker : `earlier(blocker, victim)` ∧ `cond(blocker) ⊇ cond(victim)` ∧ `defines(blocker, C)` ∧ `blocker.severity == ignore` |

**方向易错点（0.2 修正）**：

- 危险写法是"**窄在前、宽在后**"（文件中）：宽规则后写 → 先求值 → 吃掉窄规则。
- 正确写法是"**宽在前、窄在后**"：窄规则更具体，应该在文件中靠后。
- 因此"前面有超集规则"本身不是问题；**只有当那条超集规则在求值顺序里更早（文件里更靠后）时**才构成 shadow。
- `ignore_shadow` 的主语是**遮蔽者**，不是被遮蔽者：危险的是宽泛的 `ignore` 规则排在求值前面，让后面的具体规则永远沉默。被遮蔽的规则本身是 ignore 并无危害。

### 7.3 静态分析的边界

condition 表达式无法一般性地判定包含关系。lint 采取：

1. 能静态证明的（同一 `intersectsArea` / `NetName` 谓词的子集关系）→ 直接给结论；
   `NetClass` 是**成员判断**，一个网络可属于多个类，不同类的 `==` 不证明互斥 → 未知。
2. 不能证明的 → `review`，**不得**给 `block`。
3. 关键规则最终以 `kicad-cli pcb drc` 实跑为准，lint 只是前置筛查。

### 7.4 lint 输出

```yaml
- id: L005
  rule: "RF coplanar ground gap 0.2mm"
  constraint: clearance
  finding: unreachable
  cause: "被后写的 'QFN fine pitch escape clearance' 在求值顺序中先命中"
  action: 将具体规则移到文件末尾
  gate_effect: block

- id: L008
  kind: ignore_shadow
  shadowing_rule: "Broad ignore (test only)"     # 遮蔽者
  shadowed_rule: "RF coplanar ground gap 0.2mm"  # 受害者
  constraint: clearance
  gate_effect: block
```

编号约定：`L001` 语法、`L002` 未知 constraint、`L003` 引用未定义（area/netclass）、`L004` shadowed、`L005` unreachable、`L006` overlap-conflict、`L007` specificity-order、`L008` ignore-shadow、`L009` 不可理解规则 / 未知子树、`L010` 关系不可判定（review）。

### 7.5 分析资格（eligibility）

`known: true` 只表示**节点形式**已识别，不表示整条规则已被完整理解。一条规则只有同时满足下列条件才 eligible：

- 结构：rule 子树内没有 `unknown` / `unparsed` 节点；
- constraint：名字已知，且每个取值形式（`min`/`max`/`opt`/`disallow` 原子）可识别；
- condition：能解析进支持的条件子集；
- layer / severity：取值可识别。

不满足 → `L009`（review），不得进入确定性推断。并且：

- 存在 ineligible 规则时，**不得**对其求值顺序之后的规则宣称"有效"或"不可达"；
- 包含关系是 `True / False / None` 三值，`None` 不得当作 `False`；
- `implies=False` 只证明"不包含"，不能排除**部分重叠**：共享 constraint、取值不同、且无法证明不相交时，仍必须留下 `L010` review，不得静默跳过；
  例外：若反向包含成立（`blocker` 比当前规则更窄），说明是刻意让后写的窄规则覆盖先写的宽规则，这种情况不报 `L010`，通常也不产生 L007/L005；
- 语法不完整（存在 parse error）时不得输出规则结论，工具必须以失败退出（`lint_dru` 用 `2`）；
- 每条确定性 finding 必须附规则位置、涉及的 constraint 与证明依据。

### 7.6 从 Intent 生成规则（gen_dru）

- 生成前必须先用 `validate_intent` 校验并**重算** derived；结构错误或 stale 一律拒绝，不输出 proposal。
- 只从 `adopted` 结果生成规则；`conflict`、`unresolved`、无映射、等级不支持必须列入 unsupported 并给出原因，不得静默遗漏。
- requirement → constraint 的映射必须是显式的。
- **数值保真**：格式化必须往返精确（解析回来与 resolver 值完全相等）；生成后重新解析，逐条核对规则数量、名称、constraint、数值与 severity，不一致即拒绝。
- **往返核对必须精确**：重新解析后的规则数量、名称、constraint 数量与名称、取值集合（不得重复、不得多出 `max`/`opt` 等未生成项）、severity 必须与生成记录**完全一致**；多出的 constraint、取值或未预期节点都视为失败。
- **元数据安全**：写进注释的字段必须先单行化，防止换行注入额外规则。
- **等级策略**：requirement、basis 候选与结果 `level` 必须一致；混合等级无法用单条规则同时表达强制边界与建议边界，一律列入 unsupported。`MUST` → 默认规则，`SHOULD` → `(severity warning)`，`HEURISTIC`/`INFO` → 不生成默认规则。
- 输出是 `PROPOSAL`：文本 + AST + 来源映射 + lint 报告，**不自动应用**。
- 生成后跑 `lint_dru`：block 或**未解决 conflict** → `applicable=false`；`unresolved` / 无映射只记录在 `coverage` 中（`complete=false`），不单独阻止 applicability。
- 写盘保护：拒绝覆盖已存在目标，拒绝与输入或其它输出同路径。

---

## 8. 一致性要求（conformance）

任何技能 / 工具 / Gate 输出：

1. 只使用 §3.1 的五态，不得新增状态词。
2. 任何影响判定的数值必须带 §2 的 source 记录；缺来源时：能建立显式假设就创建 Assumption record（**不是新的 Verdict**），否则 Gate = `INCOMPLETE`。
3. 任何 finding 必须带 `confidence` 与 `gate_effect`，且由产生它的组件判定，不由下游猜测。
4. Gate 只接受计数式判据（`errors_unwaived == 0`），不接受"看起来没问题"。
5. 约束解析必须记录 `basis` 与 `overridden`，保证可审计。
6. 单位必须符合 §6；违反即为 `INCOMPLETE`。
7. 约束依据（basis）与验证证据（verification）分属两轴，不得混用或互相替代（§4）。
8. **数据校验 ≠ Gate 覆盖**：`requirements: {}` + `derived: {}` 可以通过数据校验（空设计不违规），但 Gate 必须独立检查阶段要求的需求覆盖，不能把空骨架当作 PASS 证据。

---

## 9. 版本与迁移

| 版本 | 变更 | 迁移 |
|---|---|---|
| 0.1 | 初版；域化权威解析、五态判定、confidence→gate_effect、assumption 生命周期、单位规范、DRU 求值模型 | — |
| 0.2 | 修正 `specificity_order_violation` 方向与 `ignore_shadow` 主语；`DOMAIN_POLICY` 取代全局 fallback（补 `FAB`）；`combine` 失败形式化；新增 `waiver_policy`；证据拆 basis / verification 两轴；`derived` 增加 `model_status`；单位去后缀；P8 起统一禁止假设 | 新增必填 `model_status`（derived）与 `waiver_policy`（requirement）；字段名去单位后缀 |
| 0.2.1 | 补充 Candidate 局部 `id`；新增 §2.5.1 三态解析结果（adopted / conflict / unresolved）；`basis`/`overridden` 明确引用 candidate id | 无破坏性变更；`derived` 结果不得再用 `null` 表示失败 |
| 0.2.2 | `HEURISTIC`/`INFO` 明确不参与绑定、不触发 `CONFLICT`；新增 §2.4.1 候选表示按 `direction` 限定；§2.5.1 补 derived 完整性校验口径（含 conflict 引用与 waiver_policy） | 无字段变更；经验值不再能造成冲突 |
| 0.2.3 | 修正 hard/binding 集合表述（hard 只收 MUST）；`exact` 表示互斥与容差/有限数约束；`equal` 精确比较、其余用相对误差不设下限；derived 比较纳入 `level`；经验值互相矛盾 → `unresolved / heuristic_disagreement` | 无字段变更；非法容差从"静默按零容差"变为错误 |

升级规则：新增 verdict 词或改变 §3.2 优先级属于 breaking change，必须升主版本并同步所有 Gate 输出。
