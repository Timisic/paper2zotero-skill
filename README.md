# literature-to-zotero

让 Agent 从研究问题或已有 DOI、题名、PDF 出发，找到文献、取得全文、生成阅读材料，并保存到 Zotero。

## 功能与流程

```text
研究问题 → 候选清单 → 确认论文、目标集合和上传许可
                         ↓
已有 PDF ───────────→ 身份核验 → MinerU Markdown → 中文总结 → Zotero 写入与回读
```

- 检索使用 OpenAlex、Semantic Scholar 等来源，按 DOI 去重；PDF 优先直接下载，需要机构访问时再用浏览器。
- 总结基于全文，默认约1000字，包含主要发现、关键局限和一两个有依据的启发。
- Zotero 中保存论文条目、PDF、Markdown 附件及总结笔记；复用已有条目，保留原有内容。
- 已有 PDF 可批量导入并自动核验；每次运行保留本地进度，支持中断后继续。结果分别列出 PDF、Markdown、总结、云端核验和本地同步状态；缺少一个产物时仍可交付其余部分。

## 安装

**Windows 10/11**：打开 PowerShell，粘贴：

```powershell
irm https://raw.githubusercontent.com/Timisic/paper2zotero-skill/main/install/install.ps1 | iex
```

**macOS / Debian / Ubuntu**：打开终端，粘贴：

```bash
curl -fsSL https://raw.githubusercontent.com/Timisic/paper2zotero-skill/main/install/install.sh | bash
```

安装器自动获取仓库，识别系统，补齐缺少的工具，再进入 Wizard。已有依赖跳过；默认个人 Zotero 文库，ID 自动获取；可选配置回车跳过。账号授权和密钥由你在终端填写，中断后重跑即可。

也可以让 Agent 安装：

> 请读取 https://github.com/Timisic/paper2zotero-skill 的 README，按当前操作系统安装。密钥由我在终端填写，完成后检查并说明未完成项。

已克隆仓库的用户可运行 `install/setup.cmd`（Windows）或 `bash install/setup.sh`（macOS/Linux）。想预览界面，使用 `install/setup-demo.cmd` 或 `bash install/setup.sh --demo`；Windows 预览需要已有 Git Bash。

Windows 会打开独立的 Git Bash 八步向导窗口；密钥在该窗口填写。已在 Windows 真机验证依赖检查、向导终端和重复安装；全新系统的软件下载与账号授权仍需实际完成。浏览器与 Desktop 同步按需配置。

技能安装在 `%USERPROFILE%\.codex\skills\literature-to-zotero`，配置保存在 `%USERPROFILE%\.config\literature-to-zotero`；在线安装器的仓库入口在 `%LOCALAPPDATA%\paper2zotero-source\install\setup.cmd`。以后双击该入口即可继续配置。

## 使用

直接向 Agent 提出需求，例如：

> 帮我找近三年 AI 心理健康干预研究，英文优先。

或：

> 处理这些 PDF，放入 Zotero 的“AI心理健康”集合，允许上传 MinerU；每篇约1000字总结并给一两个启发。Zotero 数据目录是……

检索任务会先给一张候选清单，再确认选哪些论文、放入哪个集合、是否允许上传。已明确提供这些信息的任务可直接处理。中断后让 Agent **继续同一个 run**，它会复用已完成的步骤。

<!-- repository-only -->

开发、测试和验收记录见[文档索引](docs/README.md)。安装入口统一位于 `install/`，运行 skill 位于 `literature-to-zotero/`；`scripts/` 为维护工具。可选离线打包命令为 `python3 scripts/build-distribution.py`。
