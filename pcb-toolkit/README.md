# pcb-toolkit

确定性工具层。目标：把算术、几何判定和格式校验从 LLM 手里拿走，让技能层只做判断。

**当前状态：v0.1 —— 已实现 1 个工具，其余为规划。** 未实现的部分不提供占位实现，避免技能引用到不存在的工具。

| 分组 | 工具 | 状态 |
|---|---|---|
| 几何 | `pcb_overlap.py` 元件重叠检测（原理图 / PCB） | ✅ 已实现 |
| Intent | `validate_intent.py` Design Intent 语义校验 + resolver | ✅ 已实现 |
| 计算 | `trace_width` / `via_current` / `impedance` / `stackup` / `circuit_calc` | 规划 |
| 规则 | `dru_ast.py` `.kicad_dru` 结构解析 | ✅ 已实现 |
| 规则 | `lint_dru.py` 遮蔽 / 优先级 / ignore 分析 | ✅ 已实现 |
| 规则 | `gen_dru.py` Design Intent → proposal | ✅ 已实现 |
| 计算 | `pcb_calc.py` 线宽/过孔/阻抗/叠层/电路 | ✅ 已实现 |
| 分析 | `pcb_analysis.py` DRC 分诊 / BOM 本地检查 / 规则汇总 | ✅ 已实现 |
| MCP | `pcb_mcp.py` stdio JSON-RPC，暴露 `pcb_*` | ✅ 已实现 |
| Gate | `gate.py` 统一 evidence + 五态判定 | ✅ 已实现 |
| 分析 | `triage_drc` / `audit_bom` | 规划（`audit_bom` 依赖外部器件数据库，不是纯计算） |

---

## pcb_overlap.py

只读解析 `.kicad_pcb` / `.kicad_sch`，不修改任何 KiCad 文件，不需要 KiCad 运行，只依赖 Python 3 标准库。

```powershell
python scripts\pcb_overlap.py board.kicad_pcb
python scripts\pcb_overlap.py root.kicad_sch
python scripts\pcb_overlap.py project.kicad_pro        # PCB + 原理图一起查

# 报告与可视化
python scripts\pcb_overlap.py board.kicad_pcb --json r.json --svg r.svg
# 门禁用：block 级重叠退出码 1；review 级需再加 --fail-on-review
python scripts\pcb_overlap.py board.kicad_pcb --fail-on-overlap
python scripts\pcb_overlap.py board.kicad_pcb --fail-on-review
```

### 判定口径

| 对象 | 几何来源 | 判定 |
|---|---|---|
| PCB footprint | `F.CrtYd` / `B.CrtYd` 多边形（缺省回退 `F.Fab`，`confidence=low`） | 同面相交且穿透深度 ≥ 阈值 → `overlap` |
| PCB 焊盘 | 每个 footprint 的 pad 外形，仅同面 | 不同 footprint 的焊盘相交 → `pad_overlap`（短路风险） |
| 原理图符号 | 符号库中的 `rectangle`/`polyline`/`circle`/`arc`（**不含 pin**） | 同一图页内器件体相交 → `overlap` |
| 层级原理图 | 自动跟随 `Sheetfile`，逐页独立判定 | 跨页不比较（本来就允许重叠） |

### 关键设计

- **相切不算重叠**：穿透深度 < `--touch-mm`（默认 0.02mm）判为 `touch`，只提示不判 FAIL。理由是 courtyard 本身就是余量，亚 0.02mm 的相交属于网格/制造噪声。这是与 KiCad DRC 对齐的关键——实测 JXBadge 板有 6 处 7µm 相切，KiCad DRC 同样不报错。
- **背面不互撞**：`F.Cu` 与 `B.Cu` 分组，只在同面内比较。
- **库解析失败不猜**：原理图符号库找不到时输出 `unresolved_symbol`，不参与几何判定，绝不估一个包围盒。
- **凸包近似**：courtyard 无法闭合成环时退回凸包并标 `confidence=low`；凹形包络可能高估，报告里保留该标记。

### 已验证

在 `CABadge/JXBadge_V1`（4 层，108 个 footprint / 103 个符号，4 张图页）上：

- PCB：108 个 footprint 全部解析到 courtyard（`missing_courtyard=0`），0 处重叠，6 处 7µm 相切（U1 与 R1–R6）；与 `run_drc` 结果一致（DRC 无 courtyard 报错）。
- 原理图：103 个符号全部从库解析成功，0 处重叠。
- 16 个单元测试覆盖：正例、分离、异面、相切、45° 旋转、退出码、Fab 降级为 review、pad 相交、符号重叠、图页层级、几何工具。

### 输出契约

每个 finding 自带 `geometry` / `confidence` / `gate_effect`，Gate 不再二次猜测：

```json
{
  "tool": "pcb_overlap",
  "summary": {"blocks": 0, "reviews": 0, "incomplete": 0, "touches": 6,
              "overlaps": 0, "pad_overlaps": 0, "unresolved": 0, "verdict": "PASS"},
  "findings": [
    {"kind": "touch", "ref_a": "U1", "ref_b": "R1", "area_mm2": 0.0091,
     "penetration_mm": 0.007, "where": "F",
     "geometry": "courtyard_polygon", "confidence": "exact", "gate_effect": "info"}
  ]
}
```

| 几何 | confidence | gate_effect |
|---|---|---|
| 闭合 courtyard 多边形 | `exact` | `block` |
| 真实焊盘外形（rect） | `exact` | `block` |
| 凸包 fallback / Fab 包络 / 圆或异形焊盘近似 | `approx` | `review` |
| 库解析失败 | `none` | `incomplete` |

`verdict` 遵循 core-semantics §3：

- 任一 `block` → `BLOCKED`
- 否则任一 `review` / `incomplete` → `INCOMPLETE`
- 仅 `info` → `PASS`

`--fail-on-overlap` 只对 `block` 生效；`--fail-on-review` 把 `review` 也算失败。近似几何**不能**单独阻断 Gate，这是刻意的：圆形、椭圆、圆角矩形与 custom pad 的外接矩形近似会产生 false positive。

### 与技能的接口

- `pcb-verification` G6（布局后）与 G8（投板前）把本工具作为必跑项，判定写入 Gate 证据。
- `pcb-schematic` 的图面评审用它查符号重叠。
- 未来封装为 MCP 工具 `pcb_overlap_audit`，参数与 CLI 一致。

## 测试

```powershell
cd pcb-toolkit
python -m unittest discover -s tests -v
```

---

## validate_intent.py（M1.1）

Design Intent 的语义校验器，同时内置 `core-semantics.md` §2 的 resolver。只依赖标准库；`.json` 开箱可用，`.yaml` 需要 PyYAML。

```powershell
python scripts\validate_intent.py intent.json
python scripts\validate_intent.py intent.json --json report.json
python scripts\validate_intent.py intent.json --print-derived   # 打印重算结果
```

退出码：`0` PASS，`1` FAIL / INCOMPLETE，`2` 解析错误。

### 首批 invariant

| 码 | 检查 |
|---|---|
| `E001` | `schema_version` 不支持 |
| `E002` | 顶层必填缺失 / 类型错误 |
| `E003` | `units` 缺核心单位，或不是 canonical 值 |
| `E004` | 字段名带单位后缀（`_mm/_v/_a/_hz/_s`） |
| `E005` | 未知 source type / 缺 `ref` |
| `E006` | 未知 `domain` |
| `E007` | 未知 `direction` / `level` / `waiver_policy` |
| `E008` | candidate 结构错误、`id` 重复 |
| `E009` | candidate 引用不存在的 source |
| `E010` | `derived.constraints` 指向未知 requirement |
| `E011` | `status` 非法 |
| `E012` | `adopted` 缺 value/range 或缺 basis |
| `E013` | basis/overridden 引用不属于该 requirement 的 candidate |
| `E014` | `conflict` 带 value，或 `adopted` 带 conflict |
| `E015` | `unresolved` 缺 reason 或带 value |
| `E016` | assumption 字段/阶段/状态非法 |
| `E017` | requirement 引用不存在的 assumption |
| `E018` | derived 与 resolver 重算不一致（状态 / 数值 / 候选引用 / 冲突策略） |
| `E019` | candidate 表示/容差与 `direction` 不匹配（value+range 混用、非法 tolerance_pct、非有限数） |
| `E020` | basis/overridden 内部有重复 candidate id |
| `E021` | `adopted.value` 类型与 direction 不符 |
| `E022` | `adopted.range` 端点非有限，或 `min > max` |
| `E099` | 内部校验异常（安全网，正常不应出现） |
| `I001` | requirement 既无 candidate 也无 assumption |
| `I002` | derived 缺条目（resolver 未运行） |

`E018` 是这一层最关键的检查：它让"手写的 derived"和"resolver 实际会算出的结果"不能再偷偷分叉。

### resolver 行为

按 `core-semantics.md` §2 的 `DOMAIN_POLICY`：

- 硬约束 = `candidate.level == MUST` 且 `authority ∈ policy.hard`
- 项目收紧与 soft 只收 `MUST` / `SHOULD`；`HEURISTIC` / `INFO` 不参与
- 经验值之间彼此矛盾 → `unresolved / heuristic_disagreement`，不是 `conflict`
- 项目值只能收紧，宽松 → `conflict.project_loosen_hard_bound`
- 无 MUST 时按 `policy.soft` 取第一组；`manufacturing` 的 `FAB` 在 `PROJECT` 之前
- `exact` 求交集，空集 → `conflict.empty_intersection`；零容差也输出 `{min: v, max: v}`
- `value` / `range` / `tolerance_pct` 互斥；数值必须有限，容差必须非负
- `equal` 接受字符串或数值，且比对用**精确相等**
- 无候选 → `unresolved: no_candidate`，**不是**静默省略

入口契约：`resolve_requirement()` 对任意畸形输入都不抛异常，返回 `unresolved`（`invalid_requirement` / `unknown_domain` / `unknown_direction` / `no_candidate` / `heuristic_disagreement`）；结构诊断由 validator 负责。

本组 80 个（intent 59 + schema 5 + overlap 16）。Robustness 组覆盖：畸形输入（`direction: []`、`candidates: 1`、`value: 10**400`）不抛异常；`1e-13`/`0`、`1e9`/`1e9+1`、`2^53`/`2^53+1` 都能被 stale 检查抓到；`exact` 的 1e308 + 1000% 容差返回 `unresolved / non_finite_result` 而不是无穷区间；assumption 的 `value` 必须是字符串或有限数值、`impact` 必须是非空字符串列表。

### JSON Schema 与共享夹具

结构契约在 [`../pcb-flow/assets/design-intent.schema.json`](../pcb-flow/assets/design-intent.schema.json)，说明见 [`../pcb-flow/references/design-intent-schema.md`](../pcb-flow/references/design-intent-schema.md)。

`tests/fixtures/intent/case_*.json` 每份都带 `expect: {schema, codes}`，`test_intent_schema.py` 让 **JSON Schema 与 validator 分别断言同一预期**，而不是互相比较。validator 侧放在独立测试类里，`jsonschema` 缺失时仍然运行。Schema 侧需要 `jsonschema`：已 vendor 到 `tests/vendor/`（仅测试用，可随时删除重装）：

```powershell
python -m pip install --target tests/vendor jsonschema
```

未安装时 schema 测试整体 skip，validator 仍照常运行。

---

## dru_ast.py（M1.2）

`.kicad_dru` 的**结构**解析：tokenize → AST。只做语法，不做规则遮蔽/优先级/约束效力（后续 `lint_dru`）。

```powershell
python scripts\dru_ast.py board.kicad_dru
python scripts\dru_ast.py board.kicad_dru --json ast.json
```

退出码：`0` 无语法错误，`1` 有错误，`2` 文件不可读。

### 保真规则

- **顺序与位置**：每个节点带 `line` / `col` / `offset`（1-based 行列），子节点保持源码顺序。
- **未知节点保留**：未知顶层节点、未知 constraint、未知 rule 子节点全部进入 AST，标 `known: false`，**不静默丢弃**。
- **未知子树隔离**：一旦进入未知容器，其子树标 `unparsed` 且不进入 rules / constraints 统计——lint 只能对它报 review，不能基于未理解的语法得结论。
- **字符串内的 `#` 不是注释**；注释只在字符串外生效，且记录到 `comments[]`。
- **转义**：`\"` `\\` `\n` `\r` `\t` 反转义，未知转义原样保留；`raw` 保留带引号的原文。
- **错误恢复**：括号未闭合、多余 `)`、字符串未闭合、嵌套过深都返回**部分 AST + 诊断**，不抛裸异常。

### 诊断码

| 码 | 含义 |
|---|---|
| `E_UNCLOSED` | 列表未闭合（位置指向对应的 `(`） |
| `E_UNEXPECTED_CLOSE` | 多余的 `)` |
| `E_UNTERMINATED_STRING` | 字符串未闭合（位置指向起始引号） |
| `E_DEPTH` | 嵌套超过 256 层 |
| `E_UNEXPECTED_EOF` | 表达式位置遇到 EOF |

### 真实夹具

`tests/fixtures/dru/jxbadge_v1.kicad_dru` 复制自 JXBadge 项目，来源、字节数与 SHA-256 记录在 `tests/fixtures/dru/SOURCE.md`；测试会校验哈希，副本与原件同哈希、原件未改动。

该夹具的解析结果：5 条规则、6 个 constraint、4 个 condition、1 个 `(layer ...)`、2 条注释，全部节点 `known: true`。

---

## lint_dru.py（M1.3）

在 AST 之上做**保守**的规则求值分析：逆序求值、完全/部分遮蔽、宽规则后写、ignore 遮蔽。

```powershell
python scripts\lint_dru.py board.kicad_dru
python scripts\lint_dru.py board.kicad_dru --json report.json
```

退出码：`0` 无 block，`1` 有 block，`2` 语法错误（此时跳过规则分析，不输出部分结论）。`--fail-on-review` 把 review 也算失败。

### 三值判定

`cond(sub) ⇒ cond(sup)` 返回 **True / False / None**，`None` 绝不当作 `False`。支持 `&&`、`||`、`!`、比较运算、属性路径、`A.intersectsArea('X')` 等方法调用；数值比较按区间包含（含开闭边界）。无法证明的一律 `None`。

### 分析资格（eligibility）

`known: true` 只表示节点形式已识别。规则还要满足：无 unknown/unparsed 子节点、constraint 名与取值形式已知、condition 可解析、layer/severity 可识别，才参与确定性推断。否则报 `L009`（review）。

存在 ineligible 规则时，不对其求值顺序之后的规则宣称"有效 / 不可达"——这些规则得到 `L009` review，而不是被静默忽略。

### 码表

| 码 | 含义 | effect |
|---|---|---|
| `L004` | 条件等价，被更早求值的规则完全遮蔽 | block |
| `L005` | 所有 constraint 都被遮蔽（规则永不生效） | block |
| `L006` | 条件等价但取值不同，先求值者生效 | block |
| `L007` | 窄规则写在宽规则之前，被宽规则先吃掉 | block |
| `L008` | 遮蔽者 `severity ignore`，让后面的规则永久沉默 | block |
| `L009` | 规则含未理解结构/条件，或结果受其影响无法确定 | review |
| `L010` | 未证明完全遮蔽、取值不同、且不能证明不相交（含部分重叠） | review |

每条 finding 带规则名、`line:col`、constraint、相关规则与 `proof`。

### 示例

```powershell
=== demo_lint.kicad_dru ===
rules=4 eligible=4 block=4 review=0
  L005 [block] vbus-specific @ 4:1
  L007 [block] vbus-specific @ 4:1 (clearance)
  L004 [block] dup-a @ 11:1 (track_width)
  L005 [block] dup-a @ 11:1
```

JXBadge 真实夹具的 5 条规则全部 eligible，0 block；两条 `clearance` 规则条件关系不可判定且取值不同（0.2 vs 0.11），产出 **1 条 L010 review**——这是刻意的保守输出，不是噪音。

### 测试

本组 41 个（条件解析 4 + 包含/不相交判定 14 + 排序/遮蔽 9 + 资格/未知关系/布尔/退出码 13 + 真实夹具 1）。

---

## gen_dru.py（M1.4）

Design Intent → `.kicad_dru` **PROPOSAL**（不自动应用）。

```powershell
python scripts\gen_dru.py intent.json
python scripts\gen_dru.py intent.json --json report.json --out proposal.kicad_dru
```

退出码：`0` 可应用，`1` 不可应用（block / 没有规则），`2` 被拒绝（校验失败）或 `--out` 被拒绝。

### 流程

1. `validate_intent` 校验并**重算** derived；结构错误或 stale → `REJECTED`，不输出 proposal。
2. 只从 `adopted` 结果生成；`conflict` / `unresolved` / 无映射 / 等级不支持进入 `unsupported` 并给出原因。
3. 生成 `PROPOSAL` 文本 + AST + 来源映射（requirement → rule → constraint → basis → sources）。
4. **重新解析并逐条核对**：规则数量、名称、constraint 数量与名称、取值集合（不得重复/多出）、severity；任何不一致 → `REJECTED`。
5. 跑 `lint_dru`：`lint_ok` 表示生成部分无 block；未解决 conflict 也会让 `applicable=false`。

### 数值与元数据

- `fmt_num()` 用最短往返十进制（`Decimal(str(float))`），不用指数、不截断：`1e-7 → 0.0000001`，`0.1500004 → 0.1500004`。
- 格式化后立即回读比较，精度无法保持的 requirement 直接列 unsupported。
- `project_id` 等元数据写进注释前会去掉换行与控制字符，防止注入额外规则；重解析后的规则数必须与来源映射逐条对应。

### 等级策略

requirement、basis 候选与结果 `level` 必须**一致**：

| 等级 | 生成 |
|---|---|
| `MUST` | 普通规则（默认 error） |
| `SHOULD` | `(severity warning)` |
| `HEURISTIC` / `INFO` | 不生成 |
| 混合（如 FAB/MUST + PROJECT/SHOULD） | 不生成，列 unsupported |

单条规则只能承载一个 severity：取最弱会把硬约束降级，取最强会把建议值升格，因此混合等级直接拒绝。

### 覆盖度与可应用性

| 字段 | 含义 |
|---|---|
| `lint_ok` | 生成部分 lint 无 block |
| `coverage.complete` | 无 conflict / unresolved / unsupported |
| `applicable` | `lint_ok` 且无未解决 conflict 且至少 1 条规则 |

`unresolved` 与无映射只让 `coverage.complete=false`，不单独阻止 applicability；未解决 conflict 必须阻止。

### 写盘保护

`--out` 拒绝覆盖已存在文件、拒绝与输入相同；`--json` 同样拒绝与输入或 `--out` 相同。写出使用独占创建（`open(..., "x")`）。

### requirement → constraint 映射

显式表（`REQUIREMENT_MAP`）：`min_clearance→clearance`、`min_track/track_width→track_width`、`min_via_diameter→via_diameter`、`min_via_drill→hole_size`、`min_hole_clearance→hole_clearance`、`edge_clearance→edge_clearance`、`max_skew→skew`、`diff_pair_gap→diff_pair_gap`。

未列出的 requirement 不会被静默忽略，而是列入 `unsupported`。

### 示例

```
=== gen_dru: intent_valid.json ===
status=PROPOSAL applicable=True lint_ok=True rules=1 unsupported=2
  + auto:min_clearance [clearance] level=MUST basis=['C-001'] sources=['S-001']
  - antenna_keepout (unresolved): resolver unresolved: no_candidate
  - usb_diff_impedance (unsupported): 没有 requirement→DRU 映射
  ! 1 个 requirement 未解析（coverage 不完整）
  ! 1 个 requirement 未生成（见 unsupported）
  lint: block=0 review=0
```

生成的 proposal：

```
# generated from jxbadge revision 4 — PROPOSAL, not applied
(version 1)

(rule "auto:min_clearance"
  (constraint clearance (min 0.15mm)))
```

### 测试

本组 32 个：确定性输出、规则排序、字符串转义、数值保真、元数据注入、未支持项、conflict/unresolved 不生成、等级策略（含混合等级）、stale/非法 intent 拒绝、生成后精确核对（多余取值/constraint/游离 atom/severity 参数）、block/conflict 阻止 applicability、路径保护与 `--out` 行为。

---

## gate.py（M1.5）

把各工具输出收敛成统一 evidence，按 core-semantics §3 判定。

```powershell
python scripts\gate.py --phase P8 --intent intent.json --drc drc.json --erc erc.json `
    --overlap overlap.json --lint lint.json --gen gen.json --waivers waivers.json
```

退出码：`0` PASS 家族，`1` BLOCKED，`2` INCOMPLETE / 输入错误。

### 判定优先级

```
BLOCKED > INCOMPLETE > PASS_WITH_ASSUMPTIONS > PASS_WITH_WAIVERS > PASS
```

| 条件 | verdict |
|---|---|
| 存在未豁免 block | `BLOCKED` |
| 假设到期（`must_resolve_before <= phase`） | `BLOCKED` |
| 必需检查缺失 / 覆盖不足 / review 未消解 | `INCOMPLETE` |
| 仅有未到期假设 | `PASS_WITH_ASSUMPTIONS` |
| 仅有已豁免 block | `PASS_WITH_WAIVERS` |
| 其余 | `PASS` |

### 阶段必需检查

| 阶段 | 必需 |
|---|---|
| P3 / P4 | erc |
| P6 | drc, overlap |
| P7 | drc |
| P8 | drc, erc, overlap, lint |
| P9 / P10 | drc, erc, overlap, lint, gen |

### 归一化

| 输入 | 映射 |
|---|---|
| `pcb_overlap` | `gate_effect` → block/review/incomplete/info；未知 effect 或 `coverage` 异常 → incomplete |
| `lint_dru` | `effect`；语法错误 → 覆盖 partial + incomplete；未知 effect → incomplete |
| `run_drc` | severity → effect；`unconnected_items` / `schematic_parity`（列表或计数）→ block |
| `run_erc` | severity → effect |
| `gen_dru` | REJECTED / conflict → block；coverage 不完整 → incomplete；lint findings 透传 |
| `validate_intent` | error → block；incomplete → incomplete；warning → info；**derived conflict → block** |
| `--waivers` | 必须含 id/code/reason/approved_by/review_by/compensating；policy 由 finding 决定 |

**缺字段不等于"检查通过"**：报告缺少 `findings` / `violations` / `status` 时归一化为 `coverage=none` + incomplete，绝不默认 full。DRC/ERC 的 report-level `coverage` 与 `status`（`FAILED`/`ABORTED`）同样会降级；计数必须是**有限非负整数**（`0.5`、"202"、负数都非法）。lint 的 `summary.aborted` 视为未完成；gen 的 `PROPOSAL` 必须含 `applicable`(bool) / `coverage` / `lint`，且 `coverage.complete` 必须是 bool 并与分类计数一致。finding 上的 `waiver_policy` 会被保留并校验，归一化不降级。

### waiver 有效性

```json
{"id": "W-1", "code": "DRC_SCHEMATIC_PARITY", "ref": "…",
 "reason": "…", "approved_by": "…", "review_by": "2026-11-01",
 "compensating": "…"}
```

- 六个字段缺一即无效，block 不会因此解除。
- `policy` 写在 finding / requirement 上，waiver 自带的 `policy` 不算数（并记为无效）。
- `prohibited` 的 finding 不可豁免；`authority_required` 必须额外提供 `authority`，且该来源必须存在并具备 authoritative 资格（`datasheet` / `standard` / `fab_profile` / `project_constraint`）；`heuristic` 等无效。
- 冲突类 finding（`INTENT_CONFLICT` / `GEN_CONFLICT`）还要求 `replacement`：新来源对该 requirement 的替代主张。replacement 必须通过 candidate 结构校验（含 `id`）、`source == authority`、`level` 为 MUST/SHOULD 且 authority 在域内合格，`replacement.id` 不得与保留候选重名；替代后重解析必须为 `adopted`，`basis` 非空、与 `overridden` 不相交、只引用存在的候选，且 replacement 进入 `basis`。`GEN_CONFLICT` 同样强制此路径，缺 intent/requirement 时保持 BLOCKED。
- `review_by` 必须是 ISO 日期且未过期（`YYYY-MM-DD`），否则无效。

### 假设

| 阶段 | 行为 |
|---|---|
| P0–P7 | 未到期 → `PASS_WITH_ASSUMPTIONS`；到期（含 `expired`）→ `BLOCKED` |
| P8 起 | 任何未关闭假设（proposed/active/expired）→ `BLOCKED` |

`assumptions_open` 统计全部未关闭项，`assumptions_due` 只统计到期项；状态或期限非法 → incomplete。

### 示例

真实 JXBadge（DRC 报告 + overlap 报告）：

```
=== Gate P6 ===
verdict: BLOCKED
checks=2 total=1 waived=0 unwaived=1 reviews=10 incomplete=0 assumptions=0
  ! 1 条未豁免 block
  BLOCK drc/DRC_SCHEMATIC_PARITY: 202 条原理图/PCB 不一致
```

同一 overlap 报告 + 清洁 DRC：

```
=== Gate P6 ===
verdict: PASS
checks=2 total=0 waived=0 unwaived=0 reviews=0 incomplete=0 assumptions=0
```

### 测试

本组 70 个：五态与优先级、必需检查、覆盖不足、报告结构性校验（空报告/失败状态/aborted/截断含 null/非法计数含小数/非法 effect/覆盖异常）、intent 与 gen 的 conflict、gen coverage 一致性、waiver 字段有效性 / prohibited / authority 资格 / replacement 结构与 id 冲突 / 结果引用不变量 / 复核日期 / 台账到 waiver 的 code-ref 匹配 / ERC 真实 `items[].uuid` ref 与多对象 ref / DRC-ERC-overlap 的策略保留、假设期限与 P8 规则、CLI 退出码。

技能入口与文档 31 个：`pcb-flow` / `pcb-verification` 必须调用 `gate.py` 并保留完整字段；假设示例必须能通过 validator；ignore 语义与截断契约必须与实现一致；M2/M3 入口的章节结构、本地链接、BOM 模板与工程内容（结温 θJC/ΨJT、Buck 换流回路、散热焊盘电位、PWR_FLAG 边界、BOM 参数一致性、netclass 多成员、叠层求和、参考面换层三情形、铺铜阶段、失配处补偿、IPC-2221/阻抗公式常量），以及“换层/铺铜”旧捷径不得残留；M4 的 fab profile schema 使用真实日期/URL 与完整必填字段、manifest 章节齐全、铜层清单与层数一致、孔能力区分 PTH/NPTH、挂载脚本安全且幂等。

全套 **328 个**。

---

## pcb_calc.py（M5）

纯函数 + CLI，无外部数据；每个结果带 `model` 与 `warnings`，是估算而非实测。

```powershell
'{"op":"trace_width","params":{"current_a":3,"delta_t_c":10,"copper_oz":1,"layer":"external"}}' |
  python scripts\pcb_calc.py
```

| op | 参数 | 结果 |
|---|---|---|
| `trace_width` | current_a, delta_t_c, copper_oz, layer | width_mm、area_mil2 |
| `via_current` | drill_mm, plating_um, delta_t_c, layer | current_a |
| `impedance` | kind, er, h_mm, w_mm, t_mm, b_mm/s_mm | z0_ohm / zdiff_ohm |
| `stackup` | layers[], target_mm | total_mm、delta_mm |
| `circuit` | op=divider/rc/led_resistor/ldo_power/crystal_load/i2c_pullup | 对应结果 |

示例：3A/10°C/1oz 外层 → 1.375mm；0.3mm 钻刀/25µm 铜 → 0.84A（成品孔 0.25mm）；微带 0.35/0.2/4.3 → 48.6Ω。
物理前置条件会报错：LDO 必须 Vin>Vout、微带几何越界、结果溢出/NaN、I²C 无可行区间（`feasible=false`）。
`warnings` 会明确“估算/以板厂或实测为准”。

## pcb_analysis.py（M5）

只读汇总，不重新判 DRC：

```powershell
python scripts\pcb_analysis.py --op triage_drc --input drc.json --json triage.json
python scripts\pcb_analysis.py --op audit_bom --input bom.json --json bom_report.json
python scripts\pcb_analysis.py --op rule_audit --input lint.json --json audit.json
```

- `triage_drc`：按 severity/rule 分组，保留样例；unconnected/parity 单独列。
- `audit_bom` 的 MCP 参数是对象 `{"rows": [...]}`（与 CLI 的列表输入区分）。
- 两个 CLI 都拒绝 `--input/--request` 与 `--json` 指向同一文件，避免覆盖原始报告。
- `pcb_audit_bom`：Reference 唯一、Value/Package/MPN/LCSC、DNP 取值；null 视为缺失；
  输出 `not_checked` 与 `requires: external_datasource`——**不伪造供应链结论**。
- `rule_audit`：规则数/资格、findings 按 code、block/review 计数。

## pcb_mcp.py（M5）

stdio JSON-RPC（每行一条消息），只做 transport：

```json
{
  "mcpServers": {
    "pcb-toolkit": {
      "command": "python",
      "args": ["<skills>/pcb-toolkit/scripts/pcb_mcp.py"]
    }
  }
}
```

工具：`pcb_trace_width`、`pcb_via_current`、`pcb_impedance`、`pcb_stackup`、
`pcb_circuit`、`pcb_triage_drc`、`pcb_audit_bom`、`pcb_rule_audit`。
计算类工具统一经过 `compute()`（有限性/物理校验），响应序列化使用
`allow_nan=False`；溢出/NaN 返回 `isError=true`。MCP 不改变判定：Gate 仍只由 `gate.py` 给出。

### 测试

calc 30 + analysis 8 + mcp 15，共 53 个；全套 **328 个**。

