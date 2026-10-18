# DRU fixtures — provenance

## jxbadge_v1.kicad_dru

| 项 | 值 |
|---|---|
| 来源 | `C:\Users\YunaCelisse\Desktop\Software\CABadge\hardware\JXBadge_V1.kicad_dru` |
| 复制日期 | 2026-10-19 |
| 字节数 | 1085 |
| SHA-256 | `98fe6bc7ca3c450788f6dd1d989ca62c0e319d30cdf4e5ec9094dd901fe5b173` |
| 用途 | parser 真实语法夹具（只读） |

原始文件未修改；本目录副本仅用于测试。复制后哈希与原件一致（`Get-FileHash -Algorithm SHA256`）。

该文件包含 5 条规则，覆盖：`track_angle`、`disallow track via`、`(layer "In1.Cu")`、`intersectsArea` 条件、`clearance` 与 `hole_clearance` 双约束、跨行 condition、`#` 注释。

## 其他夹具

| 文件 | 用途 |
|---|---|
| `unclosed_paren.kicad_dru` | 括号未闭合 |
| `extra_close.kicad_dru` | 多余 `)` |
| `unterminated_string.kicad_dru` | 字符串未闭合 |
| `escapes.kicad_dru` | 字符串转义 + 字符串内 `#` |
| `comments.kicad_dru` | 整行/行尾注释 |
| `unknown_nodes.kicad_dru` | 未知顶层节点、未知 constraint、未知 rule 子节点 |
| `unknown_constraint_child.kicad_dru` | constraint 内未知子形式（`future_value`） |
| `hidden_rule.kicad_dru` | 未知容器内的 rule：保留但不得计入有效规则 |
