# KiCad PCB 全流程技能套件

七个技能 + 一个确定性工具层，覆盖 P0–P10：

| 技能 | 职责 |
|---|---|
| [pcb-flow](pcb-flow/SKILL.md) | 总控、Design Intent、阶段 Gate |
| [pcb-schematic](pcb-schematic/SKILL.md) | 原理图规范、块级电路、ERC 裁决 |
| [pcb-components](pcb-components/SKILL.md) | 选型、降额、BOM、供货 |
| [pcb-layout](pcb-layout/SKILL.md) | 分区、摆放、热、叠层、禁布 |
| [pcb-routing](pcb-routing/SKILL.md) | netclass、载流、阻抗、差分、回流、铺铜 |
| [pcb-verification](pcb-verification/SKILL.md) | DRC/ERC/overlap/lint、waiver、报告 |
| [pcb-manufacturing](pcb-manufacturing/SKILL.md) | DFM、板厂 profile、出图、拼板、测试 |
| [pcb-toolkit](pcb-toolkit/README.md) | 确定性工具（overlap/intent/DRU/gate/calc/analysis）+ MCP |

## 规范

判定词、域内权威解析、证据/置信、单位、DRU 模型以
[core-semantics.md](pcb-flow/references/core-semantics.md) 为准。
**唯一有效的 Gate 结论来自 `pcb-toolkit/scripts/gate.py`**，技能入口不得自行重算。

## 快速开始

```powershell
# 1. 校验 Design Intent
python pcb-toolkit/scripts/validate_intent.py design-intent.json --json reports/intent.json

# 2. 采证（DRC/ERC/overlap/lint/gen）后跑 Gate
python pcb-toolkit/scripts/gate.py --phase P8 --intent design-intent.json `
  --drc reports/drc_P8.json --erc reports/erc_P8.json `
  --overlap reports/overlap_P8.json --lint reports/lint_P8.json `
  --json reports/gate_P8.json
```

## 安装到技能目录

```powershell
# 预览（默认不修改）
powershell -ExecutionPolicy Bypass -File .\mount-skills.ps1

# 创建 junction 到 ~/.dsh/skills
powershell -ExecutionPolicy Bypass -File .\mount-skills.ps1 -Apply
```

PowerShell 7 可用 `pwsh -File .\mount-skills.ps1`。脚本只创建 junction，不复制文件；
已存在且指向本仓库的链接会跳过，其他内容拒绝覆盖。

### 在 DeepSeek Harness 中启用 MCP

在 profile 的 `cordis.patch.yml` 追加（路径按本机替换）：

```yaml
- insert:
    - id: pcb-toolkit
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: pcb-toolkit
        transport: stdio
        command: '<python.exe 绝对路径>'
        args:
          - '<skills>/pcb-toolkit/scripts/pcb_mcp.py'
```

重载 profile 或重启 Harness 后，工具列表出现 `pcb_trace_width` 等 8 个 `pcb_*` 工具；
新会话的技能目录出现 `pcb-flow` 等 7 个技能。

## 测试

```powershell
python -m pip install -r requirements-dev.txt   # 可选，启用 schema 校验测试
cd pcb-toolkit
python -m unittest discover -s tests
```

未安装 `jsonschema` 时，schema 相关的少量用例会 skip；其余测试不受影响。
`tests/vendor/` 是本机测试用的 vendored 依赖，不纳入仓库。

## 目录

```
skills/
├── pcb-flow/            总控 + 规范
├── pcb-schematic/       原理图
├── pcb-components/      选型
├── pcb-layout/          布局
├── pcb-routing/         布线
├── pcb-verification/    验证
├── pcb-manufacturing/   制造
├── pcb-toolkit/         工具 + 测试
└── mount-skills.ps1     挂载脚本
```

## 边界

- 技能给方法与判据，不替代数据手册、板厂能力页与实测。
- `HEURISTIC` 值需项目确认；数据手册/标准更严时以它们为准。
- Gate 通过不代表具体板子可生产：还需 DFM、EQ 与首件确认。

## 许可

[MIT](LICENSE) © 2026 Yuna-Celisse

第三方工具（KiCad、Konnect）遵循其各自许可；本仓库只包含技能文档与独立实现。
