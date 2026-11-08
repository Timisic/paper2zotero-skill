# Agent 安装执行说明

目标：为用户当前使用的助手安装 `paper-to-zotero` 和随附的写作 skill，打开可操作的向导，用户完成本地账号配置后进行检查。README 是给人的入口；平台分支、参数和完成条件以本文为准。六个 skill 的用途、来源和许可见 [THIRD_PARTY.md](../THIRD_PARTY.md)。

## 1. 确定系统与安装目标

从当前运行环境确定操作系统和助手，不让用户选择 Python 版本、目录或服务参数。安装目标参数是 `codex`、`claude-code` 或 `pi`；明确知道当前助手时必须传入。以下示例以 Claude Code 为例，按当前助手替换这个值。`auto` 只安装到已经存在的助手配置目录；无法识别时，交互向导会询问。只有用户要求所有助手时才使用 `all`。

安装与验证共用 `paper-to-zotero/scripts/agent_installation.py`。Codex 使用 `~/.codex/skills`（尊重 `CODEX_HOME`）；Claude Code 使用 `~/.claude/skills`（尊重 `CLAUDE_CONFIG_DIR`）；Pi 使用 `~/.pi/agent/skills`。所选助手同时获得全部六个 skill 目录。已有本安装器管理的其他助手副本也会更新；旧 `literature-to-zotero` 名称在全部 skill 安装成功后移至可恢复备份。独立安装保留，不自动覆盖。

普通配置依次为：准备工具、Zotero Desktop 本机写入、检查结果、更多配置。首次使用走这条路径。用户要求更多设置时加 `--advanced` / `-Advanced`，它直接打开更多配置，不重复基础账号；群组文库加 `--group` / `-Group`（使用本地 setup 入口）。更多配置的项目见 [HELP.md](HELP.md#更多配置)。

## 2. 准备依赖并打开向导

### Windows 原生环境

下载官方安装器并运行。它会准备原生 Python 和 PDF 工具，然后打开 Windows 图形配置窗口；Git Bash 只在 `-Terminal` 时需要。不要自行拼接 mintty 启动命令，也不用 WSL。

```powershell
$installer = Join-Path $env:TEMP 'paper2zotero-install.ps1'
Invoke-WebRequest 'https://raw.githubusercontent.com/Timisic/paper2zotero-skill/main/install/install.ps1' -OutFile $installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -Agent claude-code -LaunchWizard
```

已有仓库时，把最后一行的 `$installer` 换成 `'<仓库绝对路径>\install\setup.ps1'`，避免重新下载旧的公开版本。

`-LaunchWizard` 等待图形窗口就绪后返回；`-DependenciesOnly` 只准备依赖和 skill。窗口标题必须包含 `Windows 图形向导 v2`。“验证并保存”检查授权和读写权限，成功才原子保存整个账号。`-Terminal` 打开备用终端向导，与 `-Advanced` 合用时打开终端更多配置。WinGet 缺失时按安装器打开的 Microsoft Store 页面补齐“应用安装程序”。

发布 GitHub 不会自动更新本机已有下载或助手目录。用户报告旧文案时，检查实际启动文件、安装缓存及目标助手副本；`setup.cmd` 不负责拉取更新。更新官方干净缓存应运行 `install.ps1`；缓存有本地改动时先保留备份，不要 reset/clean 覆盖。依赖安装后确认目标助手里的 `scripts/setup_gui.py` 存在且与当前来源一致，再报告本机已更新。

### macOS / Debian / Ubuntu

在用户能够操作的终端中运行：

```bash
curl -fsSL https://raw.githubusercontent.com/Timisic/paper2zotero-skill/main/install/install.sh | bash -s -- --agent claude-code
```

已有仓库时运行 `bash '<仓库绝对路径>/install/setup.sh' --agent claude-code`。

Agent 命令工具没有用户可操作的终端时，先下载上述安装器到临时文件，以 `bash '<安装器绝对路径>' --dependencies-only --agent claude-code` 准备依赖，然后请用户在自己的终端运行 `bash "$HOME/.local/share/paper2zotero-source/install/setup.sh" --agent claude-code`。不要把 Agent 自己的伪终端当作用户可操作的窗口，不要声称尚未打开的向导已启动。

## 3. 用户填写账号

说明实际打开的窗口及下一步操作。注册、登录和复制授权码由用户在本机完成；不索取聊天中的密钥，不读取或回显配置文件内容。用途和网页步骤由向导说明。复用既有授权，不重复申请账号。打开向导不授权上传论文。跳过保留旧值，曾经启用的可选功能仍会参加总检。

## 4. 检查并交付

用户完成后，在同一目标上运行只读检查；自定义仓库目录用实际路径替换：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\paper2zotero-source\install\setup.ps1" -Agent claude-code -Check
```

```bash
bash "$HOME/.local/share/paper2zotero-source/install/setup.sh" --agent claude-code --check
```

需要结构化结果时，通过安装好的 `scripts/run-python.sh` 或 `scripts/run-python.ps1` 运行 `scripts/configure.py --check --json`，并把 `PAPER2ZOTERO_AGENT` 设为已选目标。

完成条件按检查顺序：运行工具、连接 AI 助手、当前检索后端（未设置 `SEARCH_BACKEND` 时是 scansci-pdf 1.19.0）、全文转换（任一路可用：设置了 `MINERU_API_BASE` 的自建 MinerU、MinerU 云端 Token 或本机 markitdown）、Zotero Desktop 本机写入。群组文库再加 Zotero Web API 行。此前启用的可选功能，例如 `SETUP_BROWSER=1` 的 Kimi，仍按实际探测。云端 Token 和 OpenAlex 不是完成条件。报告缺失项及一个继续配置入口。终端就绪或文件安装成功不等于账号配置完成；总检也不证明论文已处理或桌面附件已下载。

最后请当前助手确认可以发现 `paper-to-zotero`、`academic-paper`、`nature-writing` 和 `discussion-drafter`（Claude Code 用 `/名称`，Codex 用 `$名称`）；必要时新开会话。报告文件安装、服务检查和实际发现这三个状态，未验证的如实说明。写作 skill 另需当前助手连接 Zotero MCP：发现实际工具并只读验证目标集合。缺少连接时列为写作的未完成项。

交付时简短询问用户是否想换用自己的总结提示词；向导已问过则复用该选择。需要时通过 `agent_installation.installed_paths(agent=已选目标)` 给出生效的 `references/paper-summary.md` 绝对路径，修改方法见 [HELP.md](HELP.md#更换总结提示词)。不打开编辑器，不修改提示词。

## 离线安装包

解压后的文件夹根目录同时有 `runtime/` 和 `VERSION` 时，它是离线安装包：随附 Python 3.12 和全部 Python 依赖，安装不联网，不需要 Git、Homebrew 或 WinGet。离线安装包只有 Windows 和 macOS 版；Linux 按第 2 节在线安装。只有 `开始.md`、没有 `runtime/` 时，按第 2 节“已有仓库时”的命令在线安装，仓库路径就是这个文件夹。

`<安装包>` 是解压后文件夹的绝对路径，助手参数同第 1 节。先准备依赖和 skill，再只读检查：

```bash
bash '<安装包>/install/setup.sh' --dependencies-only --agent claude-code
bash '<安装包>/install/setup.sh' --agent claude-code --check
```

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<安装包>\install\setup.ps1' -Agent claude-code -DependenciesOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<安装包>\install\setup.ps1' -Agent claude-code -Check
```

依赖装进用户目录下的独立运行环境，之后删除解压文件夹不影响使用。`开始.md` 列出只有用户能做的事：安装 Zotero 7 并开启本地 API、可选的 Kimi WebBridge 和 MinerU 云端 Token。逐项询问是否已完成，不代为操作。然后按第 3 节打开向导：Windows 用 `-LaunchWizard`，macOS 请用户在自己的终端运行 `bash '<安装包>/install/setup.sh' --agent claude-code`。最后按第 4 节交付，检查命令用上面的 `--check` / `-Check`。缺少 Poppler 不影响安装。

## 通过其他 skill 分发工具安装

本仓库保留六个标准 skill 目录。已有 Node.js 的用户可对每个 skill 运行一次下面的命令；`nature-writing` 必须与 `nature-shared` 一起安装，`academic-paper` 应与 `academic-paper-reviewer` 一起安装：

```bash
npx skills add Timisic/paper2zotero-skill --skill <skill 名称> --agent claude-code --global
```

这类工具只安装 skill 文件，不安装运行依赖或连接服务。继续按本文启动 setup。外部管理器已占用同名目录时，本安装器会保留它并报冲突，由用户选择保留外部管理或先移走该目录。Claude Code 读取标准 `SKILL.md`；`agents/openai.yaml` 只保存 Codex 的界面元数据。

分发方式参考：[Claude Code 官方 Skills 文档](https://code.claude.com/docs/en/skills)、[OpenAI Skills 文档](https://learn.chatgpt.com/docs/build-skills)、[Vercel skills](https://github.com/vercel-labs/skills)和 [Anthropic skills](https://github.com/anthropics/skills)。
