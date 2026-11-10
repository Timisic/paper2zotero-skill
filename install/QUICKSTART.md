# paper2zotero 的安装及配置

paper2zotero 是一组 6 个 skill：根据研究需求找论文、下载全文、生成阅读笔记并保存到 Zotero，再用写作 skill 读取 Zotero 集合写综述、引言和讨论。下面逐项安装，每一项装完都有验证命令，以win命令为主。标有“(可选)”的部分可以跳过。

## 1. 准备安装包和 Python

**在线：** 在浏览器打开 https://github.com/Timisic/paper2zotero-skill ，点 **Code → Download ZIP**，下载后解压到本地，请记下文件夹路径。

**离线：** 直接使用资源包 agent-res 中的 paper2zotero 文件夹。Windows 上是 `c:\agent-res\paper2zotero`，Mac 上是 `~/agent-res/paper2zotero`。

打开命令窗口，进入这个文件夹，例如：

```bat
cd c:\agent-res\paper2zotero
```

Mac 上是 `cd ~/agent-res/paper2zotero`。

下文的命令都在这个文件夹里执行。需要 Python 3.11 及以上，Anaconda 自带的 Python 即可。检查版本：

```bat
python --version
```

显示 `Python 3.11` 或更高版本即可。

## 2. 安装 Python 依赖

scansci-pdf 用于检索和下载论文，markitdown 用于把 PDF 转成 Markdown。

在线安装：

```bat
python -m pip install "scansci-pdf==1.19.0" "markitdown[pdf]"
```

告诉 skill 使用这个 Python：

```bat
python -c "import sys, pathlib; p = pathlib.Path.home() / '.config/literature-to-zotero'; p.mkdir(parents=True, exist_ok=True); (p / 'python-path').write_text(sys.executable + '\n', encoding='utf-8')"
```

**验证：**

```bat
python -c "import importlib.metadata as m, markitdown; print('scansci-pdf', m.version('scansci-pdf'))"
```

打印出 `scansci-pdf 1.19.0`，说明依赖已正常安装。

## 3. 安装 skill

把 `paper-to-zotero` 文件夹，以及 `writing` 文件夹下的 5 个文件夹（academic-paper、academic-paper-reviewer、discussion-drafter、nature-shared、nature-writing），拷贝到当前用户的 `.claude\skills\` 文件夹下，即 `C:\Users\当前用户名\.claude\skills\`。可以在资源管理器里拷贝，也可以执行下面的命令。

**PowerShell**（Windows 11 的默认终端）中执行：

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
Copy-Item -Recurse -Force paper-to-zotero -Destination "$env:USERPROFILE\.claude\skills\"
Copy-Item -Recurse -Force writing\* -Destination "$env:USERPROFILE\.claude\skills\"
```

如果你的窗口是 **cmd.exe**（命令提示符），改用：

```bat
xcopy /E /I /Y paper-to-zotero %USERPROFILE%\.claude\skills\paper-to-zotero
xcopy /E /I /Y writing %USERPROFILE%\.claude\skills
```

Mac 上执行 `mkdir -p ~/.claude/skills && cp -R paper-to-zotero writing/* ~/.claude/skills/`。

使用 Codex 时拷贝到 `.codex\skills\`，使用 psyclaw 时拷贝到 `.psyclaw\agent\skills\`。

**验证：**

```bat
python paper-to-zotero\scripts\configure.py --verify skill-links
```

显示 `✓ 连接 AI 助手：6 个 skill`，说明 skill 已安装。也可以启动 claude，输入 `/skills`，列表里能看到这 6 个 skill。

## 4. Zotero 及其本地 API

安装 Zotero 并开启本地 API：参考本文档 7.2、7.3 节。关键是在 Zotero 的 **设置 → 高级** 中，勾选 **允许此计算机上的其他应用程序与 Zotero 通讯**。以后找论文、写作时都保持 Zotero 打开。

<img src="https://timisic.oss-cn-hangzhou.aliyuncs.com/pic/image-20261109092032294.png" alt="image-20261109092032294" style="zoom:30%;" />

<!-- 图 1：Zotero 设置 → 高级，勾选本地接口 -->

**验证：** 打开 Zotero，然后执行：

```bat
python paper-to-zotero\scripts\configure.py --verify zotero-local
```

显示 `✓ 连接电脑上的 Zotero：本地 API 应答 127.0.0.1:23119`，说明配置成功。

## 5. MinerU(可选)

MinerU 的 PDF 转换效果比本机 markitdown 更好，不配置也能用。

**云端 Token：** 在 https://mineru.net/apiManage/token 创建 Token，然后执行：

```bat
python paper-to-zotero\scripts\configure.py --extra mineru
```

粘贴 Token 后回车，再按 Ctrl+Z 并回车（Mac 按 Ctrl+D）。

**自建 MinerU 服务：** 执行下面的命令，输入服务地址，例如 `192.168.1.20:8000`，结束方式同上。

```bat
python paper-to-zotero\scripts\configure.py --extra mineru_api
```

**验证：** 显示 `设置已保存。` 即可。保存前会先连接 MinerU 验证。

## 6. Kimi WebBridge(可选)

Kimi WebBridge 用于通过学校或机构的浏览器登录下载全文，是下载失败时的备用通道。安装配置参考本文档 7.1 节。

**验证：**

```bat
python paper-to-zotero\scripts\configure.py --verify kimi
```

显示 `✓ Kimi WebBridge`，说明可以被调用。

## 7. 整体检查

```bat
python paper-to-zotero\scripts\configure.py --check
```

必需项前面都是 ✓，并且看到“环境已就绪”，就装好了。可选项未配置时显示 ○，不影响使用。

<img src="https://timisic.oss-cn-hangzhou.aliyuncs.com/pic/image-20261109100926469.png" alt="image-20261109100926469" style="zoom:50%;" />

<!-- 图 2：检查结果，全部 ✓ 和“环境已就绪” -->

装好后，新开一个会话，让助手加载刚装好的 skill，然后直接用自然语言提需求。

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
