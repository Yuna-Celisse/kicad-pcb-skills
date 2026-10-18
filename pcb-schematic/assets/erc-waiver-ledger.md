# ERC waiver 台账（模板）

只登记**已判定为误报且无法通过改图消除**的项。真错不得进台账。

字段与 `gate.py` 的 waiver 契约一致：

| 字段 | 要求 |
|---|---|
| `id` | `W-ERC-001` 递增 |
| `code` | 与 ERC finding 的 code/rule 一致 |
| `ref` | 网络/位号/页，便于定位 |
| `reason` | 为什么是误报 |
| `compensating` | 补偿/验证措施 |
| `approved_by` | 批准人 |
| `review_by` | `YYYY-MM-DD`，到期前复核 |
| `status` | `open / accepted / expired` |

## 台账

| id | code | ref | reason | compensating | approved_by | review_by | status |
|---|---|---|---|---|---|---|---|
| W-ERC-001 | `ERC_power_pin_not_driven` | `3c2ee8e4-f859-43c0-82c1-65155fddb138` | 电源由外部连接器提供 | 连接器规格书 + 上电测试 | 张三 | 2026-11-01 | accepted |
| W-ERC-002 | `ERC_pin_not_driven` | `<gate finding ref>` | 外部主控驱动，本板不提供 | 系统联调覆盖 | 李四 | 2026-11-01 | open |

## 使用规则

1. **从 Gate 复制 code/ref**：先跑 `pcb-verification`/`gate.py`，在
   `findings.unwaived_blocks` 里复制 `code` 与 `ref` 到台账，不要手写规则名。
   - `code` 形如 `ERC_power_pin_not_driven`（归一化时加了 `ERC_` 前缀）。
   - `ref` 是归一化报告的标识：优先 `items[].uuid`（真实 ERC 报告通常只有这一层），
     多对象违规用 `+` 连接（如 `A+B`）；只写其中一个不会豁免整条。
   - 手写的 `power_pin_not_driven` 或网络名不会匹配，waiver 不生效。
2. 先尝试改图（`PWR_FLAG`、NC、固定电平）；改不了才登记。
3. `compensating` 必须可验证（测试/评审/计算），不能写"已确认"。
4. 到期未复核 → `expired`，Gate 会按无效 waiver 处理。
5. `prohibited` 的规则不可豁免；安全相关项升级给 `pcb-flow`。
6. 台账随验证报告一起归档；`gate.py` 的 `waivers_applied` 必须与这里对应。

## 与 Gate 的关系

- `pcb-verification` 把台账转成 `reports/waivers.json`（字段名一致）。
- `gate.py` 校验：六字段、策略、authority（如需要）、`review_by` 未过期。
- 台账里存在但 gate 未应用 → 检查 `code`/`ref` 是否匹配，或策略是否 `prohibited`。
