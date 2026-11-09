# 快速上手

开始前请确认两件事：已安装 Zotero 7，正在用 Claude Code / Codex / Psyclaw 中的一个助手。

安装分模块进行。每个模块装完立刻检查，确认成功后再装下一个。

## 模块清单

| 模块 | 作用 | 是否必需 | 成功时显示 |
| --- | --- | --- | --- |
| ① 运行环境 | Python、scansci-pdf（检索和下载 PDF）、markitdown（PDF 转 Markdown） | 必需 | ✓ 运行工具、✓ 论文检索（ScanSci）、✓ 全文转换 |
| ② 文献 skill | 把 6 个 skill 装进你的助手 | 必需 | ✓ 连接 AI 助手：6 个 skill |
| ③ Zotero 本地 API | 让助手写入 Zotero，写作 skill 也从这里读取 | 必需 | ✓ Zotero 本地 API：127.0.0.1:23119 可写入 |
| ④ MinerU | 更好的 PDF 转换，不配置就用本机 markitdown | 可选 | 全文转换一行出现“MinerU” |
| ⑤ Kimi WebBridge | 用学校或机构的浏览器登录下载全文，是下载失败时的备用通道 | 可选 | ✓ Kimi WebBridge |

## 四步装好

### 1. 拿到安装包

- **能上 GitHub：** 在 https://github.com/Timisic/paper2zotero-skill 点 **Code → Download ZIP**，或运行 `git clone https://github.com/Timisic/paper2zotero-skill.git`。
- **不能上网（离线安装）：** 用别人拷给你的离线安装包 `paper2zotero-<版本>-macos-arm64.zip`（Apple 芯片）、`-macos-x64.zip`（Intel 芯片）或 `-windows-x64.zip`。包里自带 Python 和全部依赖，安装时不联网。

解压到一个固定位置，路径可以有中文和空格。

### 2. 逐个安装模块

在解压后的文件夹里运行：

- **macOS / Linux：** 打开终端，进入这个文件夹，运行

  ```bash
  bash install/setup.sh --modules
  ```

- **Windows：** 双击 `install\setup-modules.cmd`。

脚本按 ① 到 ⑤ 的顺序处理，每个模块后面打印检查结果：

- `✓` 已就绪，自动进入下一个模块。
- `待完成` 必需模块没通过，下面一行“下一步”写明怎么做。做完输入 `r` 重试。
- `○` 可选模块没配，不影响使用，直接回车跳过。

到 ③ 时，打开 Zotero，进入 **设置 → 高级**，勾选 **允许此计算机上的其他应用程序与 Zotero 通讯**，回到终端按回车。以后找论文、写作时都保持 Zotero 打开。

<img src="https://timisic.oss-cn-hangzhou.aliyuncs.com/pic/image-20261109092032294.png" alt="image-20261109092032294" style="zoom:30%;" />

<!-- 图 1：Zotero 设置 → 高级，勾选本地接口 -->

到 ④ 时，输入 `1` 粘贴 MinerU 云端 Token（在 https://mineru.net/apiManage/token 创建），或输入 `2` 填自建 MinerU 服务的地址，例如 `192.168.1.20:8000`。

⑤ 需要你先按 https://www.kimi.com/products/kimi-webbridge 安装本地服务和浏览器扩展，脚本只检查。

最后看到“必需模块全部就绪”，就装好了。

### 3. 验证

随时可以重新检查整套环境：

```bash
bash install/setup.sh --check
```

Windows 运行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File install\setup.ps1 -Check`。

必需项前面都是 ✓，并且看到“环境已就绪”，就可以用了。

<img src="https://timisic.oss-cn-hangzhou.aliyuncs.com/pic/image-20261109100926469.png" alt="image-20261109100926469" style="zoom:50%;" />

<!-- 图 2：检查结果，全部 ✓ 和“环境已就绪” -->

装好后可以删除解压的文件夹，运行环境和 skill 已经复制到用户目录。离线指的是安装过程，实际检索论文、下载 PDF 和 MinerU 云端转换仍然要联网。

### 4. 新开一个会话，说出你要找什么

新开会话是为了让助手加载刚装好的技能。然后直接用自然语言提需求，下面的示例就是一次完整的使用过程。

## 一次完整的使用示例

### ① 提出需求

> 帮我找 2024 年以来 AI 支持自我调节学习的研究，优先有真人干预实验的，先给我一份候选清单。

### ② 选论文，一次回复

助手检索后给出一份 10 到 15 篇的候选清单，包括编号、题目、年份和期刊、入选理由、引用数和来源。同一条消息里，它会问你两件事：选哪几篇，存到 Zotero 的哪个集合。

一句话回答这两件事：

> 选 1、2、4、7，保存到 Zotero 的“AI 与学习”

### ③ 等它处理

接下来不需要你操作。助手会依次完成这些事：

1. 下载 PDF，并核对是不是同一篇论文。
2. 把 PDF 转成 Markdown。配置了 MinerU 就上传给 MinerU 转换，没配置就用本机 markitdown，不用你回复。
3. 按论文语种写阅读笔记，分为任务、挑战、洞见与启发、创新、潜在缺陷和研究动机。
4. 把论文、PDF、Markdown 和笔记写入 Zotero，再读回来核对。

第一次写入时，Zotero 会弹出“本地 API 授权”窗口，选 **始终允许**。以后就不再询问。

如果浏览器打开了需要登录或人机验证的页面，在那个页面完成，再对助手说“继续”。

### ④ 看结果

助手最后给出一张表，每篇论文一行，列出 PDF、Markdown、阅读笔记、Zotero 回读的状态。没完成的项会写明原因。

打开 Zotero 的“AI 与学习”集合，每篇论文下面都有 PDF、Markdown 和阅读笔记。

<img src="https://timisic.oss-cn-hangzhou.aliyuncs.com/pic/image-20261109092343454.png" alt="image-20261109092343454" style="zoom:20%;" />

<!-- 图 3：Zotero 集合里的条目、附件和笔记 -->

### ⑤ 用这些文献写作

写作只引用这个集合里的文献。例如写讨论：

> 使用 discussion-drafter。研究背景是……，核心发现是……；只使用 Zotero 中“AI 与学习”集合的文献。

写文献综述用 `academic-paper` 的 lit-review 模式，写引言用 `nature-writing`，提法相同。
