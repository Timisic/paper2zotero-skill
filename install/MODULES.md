# 分模块安装与离线安装

这份说明把 paper2zotero 用到的模块逐个列出来。每个模块单独安装、单独检查，确认成功后再装下一个。哪一步失败，就只重做那一步。

## 模块清单

| 模块 | 作用 | 是否必需 | 谁来装 | 怎样算成功 |
| --- | --- | --- | --- | --- |
| Zotero 7 | 存论文、PDF 和阅读笔记 | 必需 | 你自己，用官网安装包 | 能打开 Zotero |
| AI 助手 | 执行找论文、整理、写作的流程 | 必需 | 你自己（Claude Code、Codex 或 Pi） | 能正常对话 |
| ① 运行环境 | Python 3.11+、scansci-pdf 1.19.0（检索和下载 PDF）、markitdown（PDF 转 Markdown） | 必需 | 脚本 | ✓ 运行工具、✓ 论文检索（ScanSci）、✓ 全文转换 |
| ② 文献 skill | 把 6 个 skill 装进你的 AI 助手 | 必需 | 脚本 | ✓ 连接 AI 助手：6 个 skill |
| ③ Zotero 本地 API | 让助手写入 Zotero，写作 skill 也从这里读取 | 必需 | 你在 Zotero 里勾选一个开关，脚本检查 | ✓ Zotero 本地 API：127.0.0.1:23119 可写入 |
| ④ MinerU | 更好的 PDF 转换。不配置就用本机 markitdown | 可选 | 你填云端 Token 或自建服务地址，脚本验证 | 全文转换一行出现“MinerU” |
| ⑤ Kimi WebBridge | 用学校或机构的浏览器登录下载全文，是下载失败时的备用通道 | 可选 | 你按官网安装本地服务和浏览器扩展，脚本检查 | ✓ Kimi WebBridge：已连接浏览器扩展 |

Zotero 和 AI 助手要先装好。① 到 ⑤ 由下面的脚本按顺序处理。

## 逐个安装

macOS / Linux 在终端运行：

```bash
bash install/setup.sh --modules
```

Windows 双击 `install\setup-modules.cmd`，或在 PowerShell 运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File install\setup.ps1 -Modules
```

脚本依次处理 ① 到 ⑤。每个模块先安装或配置，再立刻检查，并打印检查结果：

- `✓` 表示这个模块已就绪。
- `待完成` 表示必需模块没通过，下面一行“下一步”写明怎么处理。处理后输入 `r` 重试；直接回车会停在这里，后面的模块不再运行。
- `○` 表示可选模块未就绪，不影响使用，脚本继续下一个。

最后列出每个模块的结果。必需模块全部 ✓ 时显示“必需模块全部就绪”。

只装或只检查某一个模块，在命令后写上模块名，可以写多个：

```bash
bash install/setup.sh --modules zotero
bash install/setup.sh --modules mineru kimi
```

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File install\setup.ps1 -Modules -Module zotero
```

模块名：`runtime`（①）、`skills`（②）、`zotero`（③）、`mineru`（④）、`kimi`（⑤）。重复运行是安全的，已完成的模块会保留。

指定助手时加 `--agent codex`、`--agent claude-code` 或 `--agent pi`（Windows 用 `-Agent`）。不指定时，脚本自动找已安装的助手，找不到就询问。

### 每个模块做了什么

1. **运行环境。** 先找 Python 3.11+，没有就安装（macOS 用 Homebrew，Linux 用 apt，Windows 用 winget）。再在用户目录建一个独立环境，装 scansci-pdf 和 markitdown。PyPI 连不上时会改用清华镜像。离线安装包不联网，直接用包里的 Python 和依赖。
2. **文献 skill。** 把 `paper-to-zotero`、`discussion-drafter`、`academic-paper`、`academic-paper-reviewer`、`nature-writing`、`nature-shared` 复制到助手的 skill 目录。已有的同名独立安装会保留，不覆盖。
3. **Zotero 本地 API。** 打开 Zotero，进入 设置 → 高级，勾选“允许此计算机上的其他应用程序与 Zotero 通讯”，回到终端按回车检查。第一次写入时 Zotero 会弹出授权框，选“始终允许”。
4. **MinerU。** 输入 `1` 粘贴 MinerU 云端 Token（在 https://mineru.net/apiManage/token 创建），或输入 `2` 填自建 MinerU 服务的 IP 或域名，例如 `192.168.1.20:8000`。保存前会验证 Token 或服务的 `/v1/health`，不通过就不保存。回车跳过。
5. **Kimi WebBridge。** 脚本不替你安装，只检查。需要时按 https://www.kimi.com/products/kimi-webbridge 的说明安装本地服务和浏览器扩展，然后重跑 `--modules kimi`。

## 离线安装

适用于连不上 GitHub 或 PyPI 的电脑。离线安装包里有 Python 3.12 和全部 Python 依赖，安装过程不联网，也不需要 Git、Homebrew 或 winget。目前只有 Windows 和 macOS 版。

1. **在一台能上网的电脑上准备好文件，用 U 盘或网盘拷过去：**
   - 离线安装包 `paper2zotero-<版本>-windows-x64.zip`、`-macos-arm64.zip`（Apple 芯片）或 `-macos-x64.zip`（Intel 芯片）。从 GitHub Releases 下载，或在仓库里运行 `python3 scripts/build-distribution.py --platform all` 生成到 `dist/`。
   - Zotero 7 安装包，从 https://www.zotero.org/download 下载。
2. **装 Zotero 和 AI 助手。** 在目标电脑上安装并打开 Zotero。AI 助手按它自己的方式安装。
3. **解压离线安装包。** 解压到一个固定位置，路径可以有中文和空格。
4. **逐个安装模块。** 在解压后的文件夹里运行：
   - macOS：`bash install/setup.sh --modules`
   - Windows：双击 `install\setup-modules.cmd`
5. **确认结果。** 看到“必需模块全部就绪”就装好了。以后随时可以重新检查：
   - macOS：`bash install/setup.sh --check`
   - Windows：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File install\setup.ps1 -Check`

安装完成后可以删除解压的文件夹，运行环境和 skill 已经复制到用户目录。

离线指的是安装过程。实际使用时，检索论文、下载 PDF 和 MinerU 云端转换仍然要联网。
