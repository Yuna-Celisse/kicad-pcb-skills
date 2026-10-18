# 供货与生命周期（sourcing-and-lifecycle）

## JLCPCB 基础库 vs 扩展库

| 类型 | 优点 | 代价 |
|---|---|---|
| Basic | 库存稳、上料费低/免 | 品类有限 |
| Extended | 品类全 | 上料费、MOQ、备货 |

- 优先 Basic；Extended 需确认库存与上料费。
- 同一 BOM 不要混太多 Extended，装配成本上升。
- 价格/库存是快照，投板前复核。

## 库存与 MOQ

- 库存深度 ≥ 本次用量 × 1.2 + 安全库存。
- MOQ 大于用量时，确认余料处理。
- 交期与项目排期匹配；长交期料提前锁定。
- 替代料也要查库存，不能只写型号。

## 生命周期

| 状态 | 处理 |
|---|---|
| Active | 正常 |
| NRND | 评估替代，避免新设计 |
| EOL | 必须替代或最后一次采购（LTB） |
| Obsolete | 禁止新设计 |

- 关键料至少一个 pin-compatible 替代。
- 替代料核对：封装、引脚、极性、电压/电流、时序、温度等级。
- 替代料不得降低降额余量。

## 供应链风险矩阵

| 风险 | 迹象 | 缓解 |
|---|---|---|
| 单一来源 | 只有一家/一个封装 | 第二来源 |
| 长交期 | 交期 > 项目周期 | 提前采购/替代 |
| 价格波动 | 现货价差大 | 锁价/多源 |
| 停产 | NRND/EOL 通知 | LTB + 替代设计 |
| 假货 | 非授权渠道 | 授权渠道/来料检 |

## 选型记录

每个关键料记录：

```
MPN, 厂家, LCSC, 封装, 关键参数, 降额核算,
库存(日期), 交期, 生命周期, 替代料, 结论
```

- 数据手册链接与抓取日期。
- 替代料单独列，不覆盖主料。
- 结论写"可选/需确认/禁用"，不要只写"OK"。

## BOM 审查要点

1. 每个料有 MPN/LCSC/封装；DNP 显式标注。
2. 值收敛：同值不要多种封装/精度无理由。
3. 关键料有替代；替代同封装同引脚。
4. 生命周期无 EOL/Obsolete；NRND 有说明。
5. 库存/MOQ/交期满足本次生产。
6. 价格与上料费在预算内。

## 工具

```text
mcp__konnect__search_jlcpcb_parts(query="...", basic_only=true)
mcp__konnect__get_jlcpcb_part(lcsc_id="C...")
mcp__konnect__suggest_jlcpcb_alternatives(value="...", footprint="...")
mcp__konnect__check_bom_health(schematic="board.kicad_sch")
mcp__konnect__get_datasheet_url(mpn="...")
```

工具结果是参考，最终以订单页面/授权渠道为准。
