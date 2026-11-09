# Paper to Zotero

告诉 AI 你想研究什么，它会帮你找论文、整理候选清单。你选好后，它会获取全文、按论文语种生成结构化阅读笔记，并保存到 Zotero。已有的 PDF 也能直接处理。

## 一句话开始

把下面这句话复制给你正在使用的 AI 助手：

> 请按照 https://github.com/Timisic/paper2zotero-skill/blob/main/install/AGENT_SETUP.md ，帮我安装并配置这个文献工具，安装到我当前使用的助手中。

它会准备需要的工具，再打开配置向导。第一次使用，按[快速上手](install/QUICKSTART.md)的三步和完整示例操作即可。

文献流程分三段：**ScanSci 检索与下载 PDF（失败时改用 Kimi WebBridge）→ 写入本机 Zotero → 写作 skill 读取 Zotero**。

## 装好后怎么用

平时就在 Claude Code、Codex 的对话里使用。你负责提出需求、选择论文，助手负责后续处理。

1. **告诉助手你想读什么。** 例如：“帮我找 2024 年以来 AI 支持自我调节学习的研究，优先有真人干预实验，筛选 5 篇。”助手会给出题目、来源和入选理由。
2. **一次确认。** 例如：“选 1、2、4，保存到 Zotero 的‘AI 与学习’。”
3. **查看结果。** 助手会列出每篇的 PDF、Markdown、阅读笔记、Zotero 入库和本地同步状态，以及未完成的原因。

已有 DOI、论文链接或 PDF 时，直接提供给助手即可。转 Markdown 时默认上传 MinerU，不再询问；没有配置 MinerU 时用本机 markitdown。不想上传时，告诉助手“不上传”。例如：

> 把这些 PDF 整理到 Zotero 的“AI 心理健康”文件夹，按论文语种分析每篇的问题、挑战、洞见、创新、潜在缺陷和研究动机。

阅读笔记由当前 AI 助手撰写。想换用自己的总结提示词，见[更换总结提示词](install/HELP.md#更换总结提示词)。

## 用库内文献写作

本仓库一起安装六个 skill。入库后，写作只引用 Zotero 集合里的文献：文献综述用 `academic-paper` 的 lit-review 模式，引言用 `nature-writing`，讨论用 [`discussion-drafter`](writing/discussion-drafter/SKILL.md)。写作时保持 Zotero 打开即可。

> 使用 discussion-drafter。研究背景是……，核心发现是……；只使用 Zotero 中“AI 与学习”集合及子集合的文献，撰写中文讨论。

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

想逐个安装并确认每个模块都成功，或者网络受限（无法访问 GitHub 或 PyPI），按[快速上手](install/QUICKSTART.md)操作，同一套步骤也适用于离线安装包。

已经下载仓库：Windows 双击 `install/setup.cmd`；macOS/Linux 运行 `bash install/setup.sh`。以后可让助手“继续文献工具的配置”或“打开文献工具的更多设置”。[安装与使用帮助](install/HELP.md)包含 Windows 操作说明、数据流向和常见问题。

</details>

<!-- repository-only -->

[开发与验证说明](docs/README.md) · [Agent 安装说明](install/AGENT_SETUP.md)
