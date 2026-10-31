# 配置说明

让助手完成一件事：找到你需要的论文，取得全文，整理阅读笔记，放进你的 Zotero。并且在需要的时候能够获得。

![flowchart-1](https://timisic.oss-cn-hangzhou.aliyuncs.com/pic/flowchart-1.png)


## 1. 哪些需要配置？

### 首次完整配置三个服务

| 配置项 | 解决什么问题 | 需要准备 |
| --- | --- | --- |
| Zotero 本地 API | 把论文和笔记写进本机文库 | Zotero 10 开着，并在授权框选「始终允许」 |
| scansci-pdf | 默认文献检索和 PDF 下载（灰色来源开启） | `pip install 'scansci-pdf==1.19.0'`，不要加浏览器扩展 |
| Kimi WebBridge | 可选检索，`SEARCH_BACKEND=kimi` | 浏览器扩展已连接 |
| 自建 MinerU | 将 PDF 转成 Markdown | 下面的 `MINERU_API_BASE` |

OpenAlex、MinerU 云端 Token、Zotero Web API 仍可用，都不是默认必配。向导里的对应步骤只在你改用这些可选通道时需要。

实验室环境变量（写在 `~/.config/literature-to-zotero/env`，也可临时放在进程环境里）：

```bash
# 不设置 SEARCH_BACKEND 时，检索和下载走 scansci，灰色来源开启。
# 只要合法来源：SCANSCI_LEGAL_ONLY=1，或 process_run.py --legal-only
# 改用 Kimi：SEARCH_BACKEND=kimi
MINERU_API_BASE=http://192.168.8.167:8000
```

`MINERU_API_BASE` 可以改成别的地址。Tailscale `http://100.92.231.38:8000` 仍可使用，但不是默认。把该项设成空字符串会关掉自建 MinerU。云端回退仍用 `MINERU_TOKEN`。本机回退：`pip install 'markitdown[pdf]'`。写入通道默认 `ZOTERO_WRITE_BACKEND=auto`（本机 API，失败再用 Web API）。`ZOTERO_LOCAL_API_KEY` 在选择「始终允许」后由程序写入。

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

### 可选通道

实验室默认不使用这些通道。向导里仍可能列出它们；只在改用该通道时填写。

- OpenAlex：<https://openalex.org/settings/api>
- MinerU 云端 Token：<https://mineru.net/apiManage/token>
- Zotero Web API：<https://www.zotero.org/settings/keys>
- Semantic Scholar、Crossref、Unpaywall：向导里的「更多配置」

本机写入时保持 Zotero 桌面应用打开。Kimi WebBridge 按已有扩展教程连接。

### 检查

向导结束即完成配置。文献流程的夹具验收用仓库里的 [verify-paper2zotero](../.agents/skills/verify-paper2zotero/SKILL.md)。默认路径仍是上一节的 scansci 检索与 PDF 下载、`MINERU_API_BASE=http://192.168.8.167:8000`、本机 Zotero。

## 4. 平时怎么用

每次只需要：**描述需求 → 确认论文、集合及上传许可 → 查看结果。** 

想长期更换总结格式，可按[更换总结提示词](HELP.md#更换总结提示词)修改，无需重新配置账号。注意，若遇见人机验证的情况，请手动点击。
