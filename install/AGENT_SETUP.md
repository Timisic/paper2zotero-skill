# Agent 安装执行说明

请完成依赖安装和向导启动，不要只复制 skill 文件，也不要自行拼接 Git Bash/mintty 启动命令。

**Windows**：下载官方安装器，以 `-LaunchWizard` 运行。它会获取仓库、补齐依赖，并打开独立交互终端；确认终端就绪后返回，供用户在窗口中输入密钥：

```powershell
$installer = Join-Path $env:TEMP 'paper2zotero-install.ps1'
Invoke-WebRequest 'https://raw.githubusercontent.com/Timisic/paper2zotero-skill/main/install/install.ps1' -OutFile $installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -LaunchWizard
```

已有仓库时，直接运行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<仓库绝对路径>\install\setup.ps1" -LaunchWizard`。`-DependenciesOnly` 只准备依赖和 skill，不代表已经打开向导。

**macOS / Debian / Ubuntu**：在用户可以操作的交互终端中运行官方安装器：

```bash
curl -fsSL https://raw.githubusercontent.com/Timisic/paper2zotero-skill/main/install/install.sh | bash
```

如果 Agent 的命令工具没有交互终端，先从 `https://raw.githubusercontent.com/Timisic/paper2zotero-skill/main/install/install.sh` 下载安装器并保存为 `install.sh`，以 `bash install.sh --dependencies-only` 准备依赖，然后在用户终端执行 `bash "$HOME/.local/share/paper2zotero-source/install/setup.sh"`。不能操作用户终端时，明确告知这一限制，并提供该命令；不要声称向导已启动。

**向导打开后**：告知用户实际打开的终端（Windows 窗口名称为 `literature-to-zotero`）、安装位置和下一步操作。密钥只由用户在终端填写，不索取聊天中的密钥，不读取或回显配置文件内容。等待用户完成；终端就绪、依赖安装成功或返回码为 0，都不等于账号配置已经完成。

**用户完成后复查**：Windows 运行下面的只读检查；macOS/Linux 运行 `bash "$HOME/.local/share/paper2zotero-source/install/setup.sh" --check`。如果使用自定义仓库目录，请替换为实际目录。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\paper2zotero-source\install\setup.ps1" -Check
```

按实际结果分别说明 Python、Poppler、Skill、Zotero 凭据、MinerU 以及用户选择的可选功能是否通过；列出未完成项和继续配置的入口。不要把未选择的浏览器或 Desktop 功能说成安装失败，也不要用演示模式验证结果代替真实服务检查。
