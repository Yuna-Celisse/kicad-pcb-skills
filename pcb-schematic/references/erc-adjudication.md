# ERC 裁决（erc-adjudication）

ERC 检查的是**引脚类型与连接关系**，不是电路功能。每条违规都要分类：
真错 / 误报 / 需登记。

## 引脚类型冲突矩阵

| 驱动 → | Input | Output | Bidir | Power In | Power Out | Passive | Open |
|---|---|---|---|---|---|---|---|
| Output | OK | **冲突** | 视情况 | OK | 视情况 | OK | **警告** |
| Bidir | OK | 视情况 | 视情况 | OK | 视情况 | OK | 警告 |
| Power Out | OK | 视情况 | 视情况 | OK | **冲突** | OK | 警告 |
| Passive | OK | OK | OK | OK | OK | OK | 无 |
| Open | 警告 | 警告 | 警告 | 警告 | 警告 | 无 | 无 |

规则细节以 KiCad 10 ERC 为准；矩阵用于快速判断"是否可能真错"。

## 常见违规与裁决

| 违规 | 常见原因 | 真错？ | 处理 |
|---|---|---|---|
| `Power input not driven` | 电源由连接器/外部提供 | 多为误报 | 加 `PWR_FLAG` 到该网络 |
| `Input pin not driven` | 只接了被动件/连接器，或符号引脚类型选错 | 视情况 | 查真实驱动、接口方向与引脚类型；**普通信号不能用 `PWR_FLAG` 消项**，必要时补驱动或改符号引脚类型 |
| `Output pin connected to output` | 两个输出并接 | **真错** | 加隔离/只保留一个驱动 |
| `Pin connected to other pins but not driven` | 悬空/只接测试点 | 视情况 | 明确 NC 或加驱动 |
| `No connect pin connected` | 标了 NC 又连线 | **真错** | 去掉 NC 或去掉连线 |
| `Symbol pin not connected` | 必需脚悬空 | 视情况 | 按手册接固定电平 |
| `Duplicate reference` | 复制未重标注 | **真错** | 重新 annotate |
| `Hierarchical label mismatch` | 标签与 sheet pin 不一致 | **真错** | 统一命名 |
| `Different footprint assigned` | 符号/封装不一致 | **真错** | 修正封装 |
| `Unresolved text variable` | 变量未定义 | 多为误报 | 补定义或改文本 |

## `PWR_FLAG` 用法

- 只加在"电源来源"网络：连接器输入、LDO 输出、电池、DCDC 输出。
- 不要给每个电源脚都加；一个网络一个即可。
- `PWR_FLAG` 本质是 **Power Output** 引脚，只用于声明"这个电源网络有来源"；
  它不是普通信号输入的消项工具。普通输入报"未驱动"应查驱动/方向/引脚类型。
- `PWR_FLAG` 不是电源符号，不产生网络名；它只告诉 ERC "这里由外部驱动"。
- 加完后重跑 ERC，确认 `Power input not driven` 消失。

## NC 与合法悬空

- 真不用的脚：放 `no_connect`（X），并在评审记录里写明。
- 测试点/跳线造成的悬空：加说明，必要时用 0Ω 连接。
- 多单元器件的未用单元：输入接固定电平，输出悬空并 NC。
- 不要用 NC 掩盖"忘记连接"。

## 层次化 ERC

- 必须整树跑（`schematic_scope: hierarchy` 或 kicad-cli 对根图）。
- 只跑根页会漏掉子页的引脚冲突。
- 层次标签与 sheet pin 不匹配会同时出现在父子页，按父页修。
- 跨页电源网络在 power 页统一定义。

## 处理流程

1. 读报告：记 `rule`、`severity`、位置、涉及引脚。
2. 分类：真错 / 误报 / 需登记（不确定）。
3. 真错：改图，重跑。
4. 误报：加 `PWR_FLAG`/NC/说明，重跑。
5. 不确定：登记为 assumption 或 waiver，写清理由与复核日期。
6. 记录：把 ERC 报告路径与结论交给 `pcb-verification`，由 `gate.py` 判定。

## waiver 台账

误报若无法通过改图消除，按 [erc-waiver-ledger.md](../assets/erc-waiver-ledger.md) 记录：

- 规则、位置、理由、补偿措施、批准人、复核日期。
- 没有补偿措施/批准人的"忽略"不算处理。

## 禁止

- 用 `ignore` 全局压制 ERC 规则而不记录。
- 把"ERC 0 error"当作电路正确——ERC 不检查取值、时序、热。
- 在原理图阶段宣布 PASS；最终由 `gate.py` 判。
