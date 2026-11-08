# 安装与使用帮助

## Windows

- 使用普通 PowerShell 或双击下载目录中的 `install/setup.cmd`，无需安装 WSL，也不需要手动改系统路径。安装路径可以包含中文和空格。
- 安装过程中可能出现系统的安装许可窗口。完成后会打开标题含 **Windows 图形向导 v2** 的窗口。
- 在输入框按 **Ctrl+V**，或点击 **粘贴** 按钮。输入以圆点遮蔽。点击 **验证并保存**，连接成功后才保存；失败会留在当前页供你修改、重试。“暂时跳过”保留原有配置。
- 个人文库 ID 自动识别，不需要填写。点击“打开授权页面”会调用默认浏览器；若没有打开，旁边的网址可以选中复制。
- 如果看到旧的 `Stage 2/4` 终端界面，说明仍在运行旧下载。重新运行首页的在线安装命令获取新版。`setup.cmd` 只运行当前下载的版本，不会自动更新。
- 系统提示缺少“应用安装程序”时，按打开的 Microsoft Store 页面安装或更新，然后重跑原入口。网络下载失败时，网络恢复后重跑；已经填写的配置会保留。
- 通过在线命令安装后，可按 Win+R，输入 `%LOCALAPPDATA%\paper2zotero-source\install\setup.cmd` 继续配置。软件装好后仍提示找不到工具时，关闭旧窗口再运行安装入口。

## 更多配置

默认配置完成后即可使用。下面的项目可以等需要时再设置，每项都可跳过，跳过会保留之前的配置。打开方式：Windows 完成页的 **更多配置（可选）** 按钮或双击 `install/setup-more.cmd`；macOS/Linux 运行 `bash install/setup.sh --advanced`；也可以请助手“打开文献工具的更多设置”。

- **Zotero Web API**：群组文库，或电脑上的 Zotero 没开时的备用写入。
- **MinerU 云端 Token**：把 PDF 转成 Markdown 的云端服务。没有它时用本机 markitdown 转换。
- **Kimi WebBridge**：从学校或机构的已登录浏览器检索和获取全文。按官网“搭配本地 Agent”安装连接服务和扩展，然后点击“启动并检查”。
- **Semantic Scholar**、**Crossref**、**Unpaywall**：补充题录和开放全文。Crossref 和 Unpaywall 只需联系邮箱，不需要邮箱密码。Semantic Scholar 的“已保存”不代表已验证，实际检索时才报告是否可用。
- **OpenAlex**：只在你改用 OpenAlex 检索时出现。

自建或实验室的 MinerU 服务不在向导里：在 `~/.config/literature-to-zotero/env` 写一行 `MINERU_API_BASE=<服务地址>`。

写入本机 Zotero 时保持 Zotero 桌面应用打开。第一次写入时 Zotero 会弹出授权框，选“始终允许”，以后就不再询问。

## 没有账号或授权码

直接回车暂时跳过。向导会说明哪些功能还不能使用。基础检查不需要这些授权；群组文库或云端转换需要时再补齐。

## 更换总结提示词

可以保留默认分析方式，也可以换成自己的提示词。setup 最后会询问是否查看修改位置；这一步只显示说明，不编辑文件。

修改**当前助手实际加载的 skill** 中的 `references/paper-summary.md`。官方安装器的默认位置如下，自定义安装目录以 setup 显示的绝对路径为准：

| 安装方式 | 要修改的文件 |
| --- | --- |
| macOS / Linux | `~/.local/share/paper-to-zotero/skill/references/paper-summary.md` |
| Windows · Codex | `%USERPROFILE%\.codex\skills\paper-to-zotero\references\paper-summary.md` |
| Windows · Claude Code | `%USERPROFILE%\.claude\skills\paper-to-zotero\references\paper-summary.md` |
| Windows · Pi | `%USERPROFILE%\.pi\agent\skills\paper-to-zotero\references\paper-summary.md` |

用文本编辑器打开它，把前半部分的阅读分析要求替换为自己的提示词，保留 **`## Save and continue` 及之后**的保存／续跑说明。保存后在新文献任务中生效；已经生成的笔记不会自动重写。更新或重装可能覆盖这个文件，请自己保留一份副本。

## 助手里找不到技能

新开一个助手会话再试。仍找不到时，让助手“检查六个文献 skill 是否安装到了当前助手”。安装器支持 Claude Code、Codex 和 Pi，所选助手会同时安装全部 skill；需要全部助手时选择 `all`。各 skill 的用途和许可见仓库根目录的 `THIRD_PARTY.md`。

账号配置保存在 `~/.config/literature-to-zotero/`，重装或更新后继续使用，无需重填密钥。

写作 skill 需要当前助手已连接 Zotero MCP。安装成功或 Zotero Web API 检查通过，都不能证明 MCP 已连接。打开 Zotero 后，先让助手只读查看指定集合，再开始写作。

## 论文和数据会发送到哪里

- 找论文时，检索词、题名或论文编号会发送给学术搜索服务。
- 你确认保存后，论文和阅读笔记会写入你的 Zotero；已有条目会先按论文身份检查是否可复用。
- 转成 Markdown 时，如果配置了自建 MinerU 或 MinerU 云端，会上传 PDF，助手会先取得你的许可。你不允许上传时，用本机 markitdown 转换，不上传。
- 使用机构访问时，浏览器会用已有登录状态访问出版社或数据库。交给 AI 阅读的论文文本也会进入当前助手的处理流程。

账号授权码保存在本机配置中。任务目录会保留 PDF、阅读材料和处理进度，方便继续；不要把含授权码的配置或任务资料提交到公开仓库。

## 使用中的常见问题

| 遇到什么 | 怎么继续 |
| --- | --- |
| Zotero 有条目，但电脑上打不开附件 | 打开 Zotero 的同步设置，确认附件同步和自动下载已开启，再点同步。仍打不开时让助手检查该附件的下载状态，先不要重复导入。 |
| 某篇论文获取失败、要求登录或出现人机验证 | 在实际打开的网页上完成登录或手动点击验证，然后让助手继续原任务。多篇失败不一定是同一种原因。 |
| 全文转换授权失效，或转换一直失败 | 重跑向导检查授权；确实失效时再更新。已下载的 PDF 会保留。 |
| 阅读材料中的表格或文字不对 | 以原始 PDF 为准，让助手核对具体页面。转换和总结都可能出错。 |
| 任务中断，只处理了一部分 | 说“继续上次的任务”；保留原任务目录，助手会读取已完成的步骤。 |
