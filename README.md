# 把论文和阅读笔记放进 Zotero

告诉 AI 你想研究什么，它会帮你找论文、整理候选清单。你选好后，它会获取全文、按论文语种生成结构化阅读笔记，并保存到 Zotero。已有的 PDF 也能直接处理。

支持 **Claude Code、Codex 和 Pi**；可在 Windows、macOS 和 Debian / Ubuntu 上安装。

## 一句话开始

把下面这句话复制给你正在使用的 AI 助手：

> 请按照 https://github.com/Timisic/paper2zotero-skill/blob/main/install/AGENT_SETUP.md ，帮我安装并配置这个文献工具，安装到我当前使用的助手中。

它会准备需要的工具，再打开配置向导。你只需按提示登录 Zotero 和全文阅读服务，复制网页上的授权码；已有配置会保留，暂时没有的可以跳过。**授权码只填在本机向导中。**

## 装好后怎么用

> 帮我找近三年 AI 心理健康干预的研究，先给我一份候选清单。

或者：

> 把这些 PDF 整理到 Zotero 的“AI 心理健康”文件夹，按论文语种分析每篇的问题、挑战、洞见、创新、潜在缺陷和研究动机。

助手会在需要时确认论文选择、保存位置和全文上传许可。中断后说“继续上次的任务”即可。部分论文暂时处理不了，也会先交付已完成的部分，并说明还缺什么。

<details>
<summary>自己安装，或继续上次的配置</summary>

**Windows 10/11**：打开 PowerShell，粘贴：

```powershell
irm https://raw.githubusercontent.com/Timisic/paper2zotero-skill/main/install/install.ps1 | iex
```

**macOS / Debian / Ubuntu**：打开终端，粘贴：

```bash
curl -fsSL https://raw.githubusercontent.com/Timisic/paper2zotero-skill/main/install/install.sh | bash
```

已经下载仓库：Windows 双击 `install/setup.cmd`；macOS/Linux 运行 `bash install/setup.sh`。

以后可让助手“继续文献工具的配置”或“打开文献工具的更多设置”。[安装与使用帮助](install/HELP.md)包含 Windows 操作说明、数据流向和常见问题。

</details>

<!-- repository-only -->

[开发与验证说明](docs/README.md) · [Agent 安装说明](install/AGENT_SETUP.md)
