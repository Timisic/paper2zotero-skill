# Agent 安装执行说明

目标：为用户当前使用的助手安装此 skill，打开可操作的向导，完成本地账号配置后进行检查。README 是给人的入口；平台分支、参数和完成条件以本文为准。

## 1. 确定系统与安装目标

从当前运行环境确定操作系统和助手，不让用户选择 Python 版本、目录或服务参数。安装目标参数是 `codex`、`claude-code` 或 `pi`；明确知道当前助手时必须传入。以下示例以 Claude Code 为例，按当前助手替换这个值。`auto` 只安装到已经存在的助手配置目录；无法识别时，交互向导会询问使用哪一个助手。只有用户要求所有助手时才使用 `all`。

安装与验证共用 `scripts/agent_installation.py`。Codex 使用 `~/.codex/skills`（尊重 `CODEX_HOME`）；Claude Code 使用 `~/.claude/skills`（尊重 `CLAUDE_CONFIG_DIR`）；Pi 使用 `~/.pi/agent/skills`。共享目录中的已有安装可以被识别，但不会被默认改写。

普通配置是四步：准备工具、连接 Zotero、启用全文阅读、检查结果。首次使用默认走这条路径。用户要求更多设置时加 `--advanced` / `-Advanced`；群组文库加 `--group` / `-Group`（使用本地 setup 入口）。

## 2. 准备依赖并打开向导

### Windows 原生环境

下载官方安装器并运行。它会准备原生 Python、PDF 工具和 Git Bash，然后打开独立终端。不要自行拼接 mintty 启动命令，也不用 WSL。

```powershell
$installer = Join-Path $env:TEMP 'paper2zotero-install.ps1'
Invoke-WebRequest 'https://raw.githubusercontent.com/Timisic/paper2zotero-skill/main/install/install.ps1' -OutFile $installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -Agent claude-code -LaunchWizard
```

已有仓库时，使用当前仓库的绝对路径，避免重新下载旧的公开版本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<仓库绝对路径>\install\setup.ps1' -Agent claude-code -LaunchWizard
```

`-LaunchWizard` 等待终端就绪后返回；`-DependenciesOnly` 只准备依赖和 skill。向导窗口标题为 `literature-to-zotero`，授权码可右键粘贴或 Shift+Insert，隐藏输入不显示字符。WinGet 缺失时按安装器打开的 Microsoft Store 页面补齐“应用安装程序”。后续重跑同一入口，已有有效依赖和配置会被复用。

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

完成条件：运行工具、PDF 工具、选定助手的 `SKILL.md`、Zotero 身份与读写权限、全文阅读授权，以及此前启用的可选功能，均按实际探测通过。报告缺失项及一个继续配置入口。终端就绪、文件安装成功或演示检查通过，均不等于账号配置完成；总检也不证明论文已处理或桌面附件已下载。

最后请当前助手确认可以发现 `literature-to-zotero`。Claude Code 可用 `/literature-to-zotero`，Codex 可用 `$literature-to-zotero`；必要时新开会话。报告文件安装、服务检查和实际发现这三个状态，未验证的如实说明。

## 通过其他 skill 分发工具安装

本仓库保留标准 `literature-to-zotero/SKILL.md` 布局。例如已有 Node.js 的用户可用：

```bash
npx skills add Timisic/paper2zotero-skill --skill literature-to-zotero --agent claude-code --global
```

这类工具安装 skill 文件，不安装运行依赖或连接服务。继续按本文启动 setup。若外部管理器已占用同名目录，本安装器会保留它并报冲突；由用户选择保留外部管理或先移走该目录后改用本安装器。不要自动覆盖独立安装。

Claude Code 读取标准 `SKILL.md`，没有必须添加 `agents/claude.yaml` 的要求。`agents/openai.yaml` 只保存 Codex 的界面元数据。两者共用同一套脚本、配置与恢复逻辑。

分发方式参考：[Claude Code 官方 Skills 文档](https://code.claude.com/docs/en/skills)、[OpenAI Skills 文档](https://learn.chatgpt.com/docs/build-skills)、[Vercel skills](https://github.com/vercel-labs/skills)和 [Anthropic skills](https://github.com/anthropics/skills)。
