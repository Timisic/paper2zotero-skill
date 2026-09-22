# 配置说明

让助手完成一件事：找到你需要的论文，取得全文，整理阅读笔记，放进你的 Zotero。并且在需要的时候能够获得。

![flowchart-1](https://timisic.oss-cn-hangzhou.aliyuncs.com/pic/flowchart-1.png)


## 1. 哪些需要配置？

### 首次完整配置三个服务

| 配置项 | 解决什么问题 | 需要准备 |
| --- | --- | --- |
| Zotero Web API | 把论文和笔记保存到你的文库 | Zotero 账号和文库读写 API Key |
| OpenAlex | 根据研究问题找到候选论文 | OpenAlex 账号和 API Key |
| MinerU | 将PDF转成Markdown，方便AI读取 | MinerU 账号和 Token |

### 有需要时再补充

| 你的需要 | 配置什么 | 需要提供什么 |
| --- | --- | --- |
| 增加一个学术检索来源 | Semantic Scholar | 申请得到的 API Key |
| 按 DOI 寻找开放获取的全文 | Unpaywall | 可收信的联系邮箱 |
| 为 DOI 题录查询提供联系信息 | Crossref | 可收信的联系邮箱；不填也不等于完全停用 Crossref 查询 |
| 通过已登录的学校、机构或出版社网页获取全文 | Kimi WebBridge | 按已有教程连接扩展，并登录有访问权限的账号 |

## 2. 开始配置

### 第一步：让助手准备工具

将下面这句话复制给你正在使用的 AI 助手：

> 请按照 https://github.com/Timisic/paper2zotero-skill/blob/main/install/AGENT_SETUP.md ，帮我安装并配置这个文献工具，安装到我当前使用的助手中。

助手会安装技能和运行工具，再打开配置向导。Python 和 PDF 工具由安装流程准备。API KEY从官网复制，直接粘贴到本机配置向导。**windows上配置向导为可视化界面。

### 第二步：连接 OpenAlex

1. 打开 [OpenAlex API 设置页](https://openalex.org/settings/api)，注册登录。
2. 找到 API Key，复制完整内容。
3. 回到向导的「连接 OpenAlex（必配）」，粘贴并验证。

<img src="https://timisic.oss-cn-hangzhou.aliyuncs.com/pic/image-20260921204702998.png" alt="image-20260921204702998" style="zoom:20%;" />

### 第三步：连接 MinerU

1. 打开 [MinerU API 管理页](https://mineru.net/apiManage/token)，注册登录。
2. 在 API 管理中创建 Token，复制完整内容。
3. 回到向导的「启用全文阅读」（MinerU）步骤，粘贴并验证。

<img src="https://timisic.oss-cn-hangzhou.aliyuncs.com/pic/image-20260921205059443.png" alt="image-20260921205059443" style="zoom:20%;" />

### 第四步：Zotero 连接与可选项目

已有 Zotero 和 MCP 配置可以沿用，重点检查以下三项：

1. **Web API：允许工具保存论文。** 在 [Zotero 授权页](https://www.zotero.org/settings/keys)创建 API Key，允许目标文库读取、笔记访问和写入，再粘贴到文献工具向导的 Zotero 步骤并验证。

<img src="https://timisic.oss-cn-hangzhou.aliyuncs.com/pic/image-20260921210120747.png" alt="image-20260921210120747" style="zoom:20%;" />

<img src="https://timisic.oss-cn-hangzhou.aliyuncs.com/pic/image-20260921210344722.png" alt="image-20260921210344722" style="zoom:25%;" />

1. **MCP：让助手访问已有文库。** 云端模式使用 Web API 凭据；本地模式需要桌面应用运行并开启本地 API。配置后，让助手实际查询一条已有文献，确认能读到正确文库。MCP保证后续智能体能够直接读取论文数据及笔记，可以直接插入预设文献引用格式。
2. **桌面应用：开启本地连接与附件同步。** 在「设置 → 同步」登录同一账号，开启自动同步和附件文件同步，将「下载文件」设为「同步时」。使用本机联动时保持 Zotero 运行。

<img src="https://timisic.oss-cn-hangzhou.aliyuncs.com/pic/image-20260921210453347.png" alt="image-20260921210453347" style="zoom:25%;" />

<div style="page-break-after: always;"></div>

### 第五步：可选项目：按需要补充

打开向导中的「更多配置（可选）」

| 项目 | 操作 | 完成后如何判断 |
| --- | --- | --- |
| Semantic Scholar | 在 [官方 API 页面](https://www.semanticscholar.org/product/api)申请 Key，收到后粘贴到对应项目并保存；等待期间可跳过 | 已保存不等于检索成功，实际检索时会报告该来源是否可用 |
| Unpaywall | 在对应项目填写可收信的邮箱并保存，无需邮箱密码或单独的 API Key | 获取全文时检查是否找到开放副本；配置后也不保证每篇都有全文 |
| Crossref | 在对应项目填写可收信的邮箱并保存，无需邮箱密码或单独的 API Key | 实际查询时判断来源是否可用 |

Zotero MCP 和 Kimi WebBridge 的完整安装操作沿用已有教程。

### 第六步：检查，并试跑一篇论文

> 帮我找与「你的研究主题」相关的论文，先给候选清单。

> 选第 1 篇，存到 Zotero 的「配置测试」集合，允许上传这篇论文到 MinerU，并生成阅读笔记。

最后确认三件事：Zotero 中能找到条目；原始 PDF 能打开；Markdown 和阅读笔记已生成。若要在本机阅读，再确认电脑上的 Zotero 已下载附件。

## 4. 平时怎么用

每次只需要：**描述需求 → 确认论文、集合及上传许可 → 查看结果。** 

想长期更换总结格式，可按[更换总结提示词](HELP.md#更换总结提示词)修改，无需重新配置账号。注意，若遇见人机验证的情况，请手动点击。
