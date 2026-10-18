---
name: pcb-routing
description: "KiCad 布线经验与规则：netclass、载流线宽、过孔、阻抗、差分/等长、回流路径、串扰、铺铜与可制造性。触发：布线、走线、线宽、过孔、阻抗、差分、等长、铺铜、netclass、载流、回流。English: routing, trace width, via, impedance, differential pair, length matching, copper pour."
metadata: { version: 0.3, requires: "konnect>=0.13, kicad>=10" }
---

# PCB 布线（pcb-routing）

目标：在满足载流、阻抗、时序与可制造性的前提下，让每条信号都有**短、连续、
可控的回流路径**。规则先于走线；最终铺铜验收最后（参考平面可提前建立）。

## 何时用 / 何时不用

用：

- 布局冻结后布电源/地、关键信号、一般信号、差分/等长。
- 定 netclass、线宽、过孔、间距、阻抗目标。
- 评审回流路径、跨分割、串扰、铺铜。

不用：

- 布局/叠层 → `pcb-layout`。
- 规则文件语法/lint → `pcb-verification`。
- 器件选型 → `pcb-components`。

## 前置条件

| 项 | 要求 |
|---|---|
| 布局 | 已冻结；板框/叠层/阻抗目标确定 |
| 网表 | 与原理图一致，位号稳定 |
| 规则 | netclass 已定义；板厂能力（线宽/间距/孔径）已知 |
| 工具 | `pcb_routing`（traces/vias/zones）、`run_drc` |

## 布线顺序

1. **netclass**：先定义 Default/Power/HS/Diff/Analog，再套网络。
2. **电源与地**：大电流、低阻抗优先；参考平面可先建立，最终铺铜验收最后。
3. **关键信号**：时钟、复位、差分、模拟、高速总线。
4. **一般信号**：按最短路径。
5. **铺铜/收尾**：GND 双面、清孤岛、thermal relief。

详见 [routing-order.md](assets/routing-order.md)。

## netclass

| 类 | 典型 | 关键参数 |
|---|---|---|
| Default | 普通信号 | 0.2mm 线宽 / 0.2mm 间距 |
| Power | 电源 | 按载流算；多过孔 |
| HS | 高速单端 | 阻抗 50Ω；短、少过孔 |
| Diff90 / Diff100 | USB/CAN/以太网 | 差分宽/距按叠层 |
| Analog | 模拟 | 远离数字；包地/屏蔽 |

- netclass 只是起点；特殊网络用规则覆盖。
- 线宽/间距不要贴板厂下限，留 ~20% 余量。
- 规则要能指回 Design Intent；指不回去的规则可疑。

见 [netclass-strategy.md](references/netclass-strategy.md) 与
[netclass-presets.json](assets/netclass-presets.json)。

## 载流与线宽

IPC-2221 近似：

```
I = k · ΔT^0.44 · A^0.725      A 为截面积（mil²）
外层 k=0.048，内层 k=0.024
```

反解：`A = (I / (k · ΔT^0.44))^(1/0.725)`，`width(mil) = A / thickness(mil)`。
1oz 铜厚约 1.37mil（35µm）。

- 同时核压降与温升；大电流用铺铜/多过孔/多相。
- 过孔载流按孔径/镀铜厚度；电源地多孔并联。
- 经验值标 `HEURISTIC`，以实测温升为准。

算例与表格见 [current-and-width.md](references/current-and-width.md)。

## 过孔

- 电源/地：多孔并联，靠近电容/器件。
- 信号：少换层；换层旁放回流地过孔。
- 避免盘中孔（除非工艺支持）；环宽 ≥ 板厂下限。
- 过孔反焊盘/隔离区按阻抗与工艺。

## 阻抗

- 微带/带状线按**实际叠层**算；换层/换参考面重新核算。
- 参考平面不得开槽；跨分割是首要风险。
- 阻抗线尽量同层、短、少过孔；测试 coupon 随板。
- 公式是估算（±10–20%），以板厂/场求解器为准。

见 [impedance.md](references/impedance.md)。

## 差分与等长

- 等宽、等距、同层、少过孔；对内 skew 按协议。
- 差分对与其他信号保持间距（≥3W 或按串扰要求）。
- 不要求等长的总线不要盲目蛇形；蛇形会增加损耗/串扰。
- 长度匹配以**协议**为准（如 USB2 对内、DDR 组内）。

见 [differential-and-length.md](references/differential-and-length.md)。

## 回流路径

- 每条信号电流都有回流；回流走最近参考平面。
- 跨分割 → 回流绕行 → 环路大/辐射。能避免就避免；隔离边界不得桥接。
- 换层分三种：同参考加地孔；参考换电位需就近去耦转移（单个地孔不能连通）；隔离边界不默认桥接。
- 连接器/电缆：屏蔽/地针就近。

见 [return-path.md](references/return-path.md)。

## 串扰与 EMC

- 3W 规则（时钟/高速）；20H（电源平面内缩）。
- 平行走线过长要拉开或加地线；45° 折角。
- 包地/屏蔽腔按需；不要用包地代替回流设计。
- 时钟/复位远离接口与板边。

## 铺铜与过孔缝合

- GND 双面铺铜；thermal relief 按焊接要求。
- 清孤岛；板边留间距；不要用铺铜连接不同地。
- 缝合孔沿板边/地平面边界布置，间距按频率。
- 参考平面可提前建立；最终铺铜在布通后重填验收，改线后必须重填。

见 [pour-and-via.md](references/pour-and-via.md)。

## 可制造性

- 线宽/间距/孔径 ≥ 板厂能力 + 余量。
- 避免颈缩、酸角、细颈；焊盘连接用泪滴/加宽。
- 阻焊桥、丝印不要压焊盘。
- 拼板/V-cut 区域禁布。

## 验证衔接

```bash
python pcb-toolkit/scripts/gate.py --phase P7 --intent design-intent.json \
  --drc reports/drc_P7.json --json reports/gate_P7.json
```

- P7 要求 `drc`；P8 再加 `erc/overlap/lint`。
- 不在本技能宣布 PASS；结论由 `gate.py` 给出。
- unconnected 必须为 0；违规按 `pcb-verification` 处理。

## 反模式

| 反模式 | 后果 | 正确做法 |
|---|---|---|
| 用最终铺铜掩盖未布通 | 误以为已布通 | 布通后验收；参考 zone 可提前建并重填 |
| 改线后不重填 zone | 铜与走线不一致 | 每次改线后重填 |
| 线宽贴下限 | 良率/载流不足 | 留 20% 余量 |
| 跨分割 | 回流断裂/EMI | 换层/改参考 |
| 差分对换层多 | skew/阻抗突变 | 同层、少过孔 |
| 盲目等长蛇形 | 损耗/串扰 | 按协议要求 |
| 过孔太少 | 载流/接地阻抗 | 多孔并联 |

## 完成判据

1. 所有网络布通，unconnected=0。
2. netclass/线宽/间距/过孔满足载流与板厂能力。
3. 阻抗线参考完整，差分/等长符合协议。
4. 回流路径连续，无关键跨分割。
5. 铺铜/缝合完成，DRC 已跑；P7/P8 Gate 记录在案。

## 参考与来源

- IPC-2221（载流/通用设计）、IPC-2141（阻抗估算）。
- KiCad 10：Router、Board Setup、Net Classes、Zones。
- Konnect：`pcb_routing`、`run_drc`。
- 规范：`../pcb-flow/references/core-semantics.md`。
