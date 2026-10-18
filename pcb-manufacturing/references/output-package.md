# 输出包（output-package）

## 命名

`<project>_<rev>_<YYYYMMDD>/`，文件前缀一致，禁止"final_final"。

```
jxbadge_v1_20261019/
  gerber/
    jxbadge_v1-F_Cu.gbr
    jxbadge_v1-In1_Cu.gbr        # 4 层：内层 1
    jxbadge_v1-In2_Cu.gbr        # 4 层：内层 2
    jxbadge_v1-B_Cu.gbr
    jxbadge_v1-F_Mask.gbr
    jxbadge_v1-B_Mask.gbr
    jxbadge_v1-F_Silkscreen.gbr
    jxbadge_v1-B_Silkscreen.gbr
    jxbadge_v1-Edge_Cuts.gbr
    jxbadge_v1-F_Paste.gbr        # 需要钢网时
  drill/
    jxbadge_v1-PTH.drl
    jxbadge_v1-NPTH.drl
  jxbadge_v1-BOM.csv
  jxbadge_v1-CPL.csv
  jxbadge_v1-assembly-top.pdf
  jxbadge_v1-assembly-bottom.pdf
  jxbadge_v1-stackup.pdf
  manifest.md
  SHA256SUMS.txt
```

## Gerber 检查

- 铜层清单必须与声明层数一致：4 层 = `F_Cu + In1_Cu + In2_Cu + B_Cu`；
  6 层再加 `In3_Cu/In4_Cu`。少一层就是出包错误。
- 层清单与叠层一致；每层都有内容（空层确认是否应删）。
- 板框闭合；原点统一；单位 mm、格式一致。
- 阻焊开窗正确（不要大面积盖住测试点）。
- 丝印不压焊盘；位号可读。
- 用查看器看顶/底镜像与钻孔对齐。

## 钻孔

- PTH / NPTH 分开；槽孔单独标注。
- 孔径/数量与设计一致；最小孔满足 profile。
- 孔到铜/孔到孔间距满足 DFM。

## BOM

- 字段：Reference, Value, MPN, LCSC, Package, DNP, Notes。
- 与原理图/PCB 位号一致；DNP 显式。
- 一料一源；替代料单独列。
- 版本号与 Gerber 同版。

## CPL（位置文件）

- 字段：Designator, Mid X, Mid Y, Rotation, Layer。
- 原点与 Gerber 一致；旋转按板厂约定（常为逆时针）。
- 只含贴片件；DNP 是否包含按板厂要求，需在 manifest 说明。
- 首件前用装配图核对极性/方向。

## 装配图

- 顶/底分开；极性、pin1、DNP 标识清楚。
- 与 CPL 位号一致。
- 高器件/连接器方向可见。

## manifest

记录：

- 项目/版本/日期/作者。
- 文件清单 + SHA256。
- 板厂 profile id + retrieved。
- 叠层/阻抗/表面处理/颜色。
- BOM/CPL 的 DNP 约定。
- 已知偏差/EQ 结论。

模板：[output-manifest.template.md](../assets/output-manifest.template.md)。

## 出包后自检

1. Gerber 查看器逐层看一遍。
2. 钻孔与焊盘对齐。
3. BOM/CPL 位号与装配图一致。
4. 版本号/校验和齐全。
5. 改设计后重新出包，禁止手改 Gerber。
