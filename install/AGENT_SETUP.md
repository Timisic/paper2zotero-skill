# Agent 安装执行说明

目标：为用户当前使用的助手安装 `paper-to-zotero` 和 `discussion-drafter` 两个 skills，打开可操作的向导，完成本地账号配置后进行检查。README 是给人的入口；平台分支、参数和完成条件以本文为准。

## 1. 确定系统与安装目标

从当前运行环境确定操作系统和助手，不让用户选择 Python 版本、目录或服务参数。安装目标参数是 `codex`、`claude-code` 或 `pi`；明确知道当前助手时必须传入。以下示例以 Claude Code 为例，按当前助手替换这个值。`auto` 只安装到已经存在的助手配置目录；无法识别时，交互向导会询问使用哪一个助手。只有用户要求所有助手时才使用 `all`。

安装与验证共用 `paper-to-zotero/scripts/agent_installation.py`。Codex 使用 `~/.codex/skills`（尊重 `CODEX_HOME`）；Claude Code 使用 `~/.claude/skills`（尊重 `CLAUDE_CONFIG_DIR`）；Pi 使用 `~/.pi/agent/skills`。所选助手同时获得两个 skills。已有本安装器管理的其他助手副本也会更新；旧 `literature-to-zotero` 名称在两项技能安装成功后移至可恢复备份。独立安装保留，不自动覆盖。

普通配置依次为：准备工具、连接 Zotero、连接 OpenAlex（必配）、启用全文阅读、检查结果、更多配置（可选）。OpenAlex 必须填写授权码并通过小型检索验证，才能通过基础配置检查。首次使用默认走这条路径。用户要求更多设置时加 `--advanced` / `-Advanced`；群组文库加 `--group` / `-Group`（使用本地 setup 入口）。

Windows 完成页提供“更多配置（可选）”，`-Advanced` 也可直接打开原生进阶页，不会重复要求填写基础账号。所有可选项目直接展开，包括 Kimi WebBridge、Semantic Scholar、Crossref、Unpaywall 和 Zotero Desktop；Semantic Scholar“已保存”不代表在线验证成功。macOS/Linux 和 Windows 备用终端在最后依次展示相同项目，`--advanced` 直接跳过基础账号步骤。两种界面共享服务说明、验证和保存逻辑。需要 Windows 备用终端进阶入口时使用 `-Terminal -Advanced`。

## 2. 准备依赖并打开向导

### Windows 原生环境

下载官方安装器并运行。它会准备原生 Python、PDF 工具和 Git Bash，然后打开 Windows 图形配置窗口。不要自行拼接 mintty 启动命令，也不用 WSL。

```powershell
$installer = Join-Path $env:TEMP 'paper2zotero-install.ps1'
Invoke-WebRequest 'https://raw.githubusercontent.com/Timisic/paper2zotero-skill/main/install/install.ps1' -OutFile $installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -Agent claude-code -LaunchWizard
```

已有仓库时，使用当前仓库的绝对路径，避免重新下载旧的公开版本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<仓库绝对路径>\install\setup.ps1' -Agent claude-code -LaunchWizard
```

`-LaunchWizard` 等待图形窗口就绪后返回；`-DependenciesOnly` 只准备依赖和 skill。标题必须包含 `Windows 图形向导 v2`。输入框支持 Ctrl+V 和“粘贴”按钮，以圆点隐藏内容；点击“验证并保存”后检查授权和读写权限，成功才原子保存整个账号。个人文库 ID 自动识别，错误留在当前页，用户可以重试或跳过。`-Terminal` 保留备用终端向导；`-Advanced` 打开更多配置；与 `-Terminal` 合用时打开终端更多配置。WinGet 缺失时按安装器打开的 Microsoft Store 页面补齐“应用安装程序”。

发布 GitHub 不会自动更新本机已有下载或助手目录。用户报告旧文案时，检查实际启动文件、安装缓存及目标助手副本；`setup.cmd` 不负责拉取更新。更新官方干净缓存应运行 `install.ps1`；缓存有本地改动时先保留备份，不要 reset/clean 覆盖。依赖安装后确认目标助手里的 `scripts/setup_gui.py` 存在且与当前来源一致，再报告本机已更新。保留一条指向明确来源的继续配置入口。

### macOS / Debian / Ubuntu

在用户能够操作的终端中运行：

```bash
curl -fsSL https://raw.githubusercontent.com/Timisic/paper2zotero-skill/main/install/install.sh | bash -s -- --agent claude-code
```

已有仓库时运行 `bash '<仓库绝对路径>/install/setup.sh' --agent claude-code`。

Agent 命令工具没有用户可操作的终端时，先下载上述安装器到临时文件，以 `bash '<安装器绝对路径>' --dependencies-only --agent claude-code` 准备依赖，然后在用户终端打开：

```bash
bash "$HOME/.local/share/paper2zotero-source/install/setup.sh" --agent claude-code
```

不能操作用户终端时，明确说明限制并提供这一条命令。不要把 Agent 自己的伪终端当作用户可操作的窗口，不要声称尚未打开的向导已启动。

## 3. 用户填写账号

说明实际打开的窗口及下一步操作。注册、登录和复制授权码由用户在本机完成；不索取聊天中的密钥，不读取或回显配置文件内容。无需让用户提前了解 MinerU、Semantic Scholar 或 API；用途和网页步骤由向导说明。

复用既有授权，不重复申请账号。打开向导不授权上传论文；实际处理论文时，仍沿用 skill 的上传许可规则。额外来源、浏览器及电脑附件同步默认不要求配置。跳过保留旧值，曾经启用的可选功能仍会参加总检。

## 4. 检查并交付

用户完成后，在同一目标上运行只读检查；自定义仓库目录用实际路径替换：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\paper2zotero-source\install\setup.ps1" -Agent claude-code -Check
```

```bash
bash "$HOME/.local/share/paper2zotero-source/install/setup.sh" --agent claude-code --check
```

需要结构化诊断时，通过安装好的 `scripts/run-python.sh`（Bash）或 `scripts/run-python.ps1`（PowerShell）运行 `scripts/configure.py --check --json`。将 `PAPER2ZOTERO_AGENT` 设为已选目标，才能检查该目标，而不是其他已安装助手。`scripts/setup.py` 是开发诊断入口，会展示更多可选集成；它的整机结果不代替上述面向用户的完成检查。

完成条件：运行工具、PDF 工具、选定助手的 `SKILL.md`、Zotero 身份与读写权限、OpenAlex 授权检索、全文阅读授权，以及此前启用的可选功能，均按实际探测通过。报告缺失项及一个继续配置入口。终端就绪、文件安装成功或演示检查通过，均不等于账号配置完成；总检也不证明论文已处理或桌面附件已下载。

最后请当前助手确认可以发现 `paper-to-zotero` 和 `discussion-drafter`。Claude Code 可用 `/paper-to-zotero`、`/discussion-drafter`，Codex 可用 `$paper-to-zotero`、`$discussion-drafter`；必要时新开会话。报告文件安装、服务检查和实际发现这三个状态，未验证的如实说明。`discussion-drafter` 另需当前助手连接 Zotero MCP：发现实际工具并只读验证目标集合访问。Web API 配置检查通过不等于 MCP 已连接；缺少连接时明确列为讨论写作的未完成项，不重复申请已有账号。

交付时简短询问用户是否想换用自己熟悉的总结提示词。若向导已询问，复用该选择，不再重复询问。需要时只给出当前助手实际加载的 skill 下 `references/paper-summary.md` 的绝对路径，以及“修改前半部分的阅读分析要求，保留 `## Save and continue` 及之后的保存／续跑说明”的方法；不打开编辑器、不修改提示词，也不新增配置项。通过 `agent_installation.installed_paths(agent=已选目标)` 定位安装目录，避免把下载仓库里的文件误报为生效文件；自定义配置目录以实际路径为准。已有笔记不自动重写；托管安装会保留自定义总结提示词，仍建议用户保留自己的副本。

## 通过其他 skill 分发工具安装

本仓库保留两个标准 skill 目录。例如已有 Node.js 的用户可分别安装：

```bash
npx skills add Timisic/paper2zotero-skill --skill paper-to-zotero --agent claude-code --global
npx skills add Timisic/paper2zotero-skill --skill discussion-drafter --agent claude-code --global
```

这类工具安装 skill 文件，不安装运行依赖或连接服务。继续按本文启动 setup。若外部管理器已占用同名目录，本安装器会保留它并报冲突；由用户选择保留外部管理或先移走该目录后改用本安装器。不要自动覆盖独立安装。

Claude Code 读取标准 `SKILL.md`，没有必须添加 `agents/claude.yaml` 的要求。`agents/openai.yaml` 只保存 Codex 的界面元数据。两者共用同一套脚本、配置与恢复逻辑。

分发方式参考：[Claude Code 官方 Skills 文档](https://code.claude.com/docs/en/skills)、[OpenAI Skills 文档](https://learn.chatgpt.com/docs/build-skills)、[Vercel skills](https://github.com/vercel-labs/skills)和 [Anthropic skills](https://github.com/anthropics/skills)。
