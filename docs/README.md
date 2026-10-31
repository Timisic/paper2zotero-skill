# 维护文档

这些文档供开发者和维护 Agent 使用。普通用户从[项目首页](../README.md)开始；安装和使用中的问题见[帮助页](../install/HELP.md)。

## 按任务阅读

- 帮用户安装或修复配置：[Agent 安装说明](../install/AGENT_SETUP.md)。
- 修改安装器或向导：[安装架构](setup-architecture.md)。
- 修改论文处理流程：[架构与工作约定](../CONTEXT.md)。
- 执行文献任务：[SKILL.md](../paper-to-zotero/SKILL.md)及其按需引用的 `references/`。
- 根据库内文献写讨论：[discussion-drafter](../discussion-drafter/SKILL.md)。

## Architecture decisions

以下记录保留设计取舍，不作为平台或服务的验收报告。

- [ADR-0001](adr/0001-capability-judgement-and-credentials.md)：统一能力判断与凭据读取。
- [ADR-0002](adr/0002-browser-acquisition-channel.md)：浏览器作为全文获取通道；调用顺序由 ADR-0004 更新。
- [ADR-0003](adr/0003-one-confirmation-and-independent-artifacts.md)：一次确认、同一任务续跑、独立交付产物。
- [ADR-0004](adr/0004-http-first-discovery-and-acquisition.md)：HTTP 优先，浏览器按需介入。

## 检查与打包

在仓库根目录运行：

```bash
python3 -m pytest paper-to-zotero/tests -q
python3 -m mypy paper-to-zotero/scripts
python3 scripts/build-distribution.py --output <新的输出目录>
```

打包包含首页、`install/`、`paper-to-zotero/` 和 `discussion-drafter/`；本目录、测试和本地运行数据不进入安装包。`paper-to-zotero/references/` 是 Agent 执行所需的材料，随 skill 分发。

文献流程的夹具验收是 [verify-paper2zotero](../.agents/skills/verify-paper2zotero/SKILL.md)。上面的 pytest 是全套回归，不是另一份手测清单。默认实验室路径是 scansci 检索与 PDF 下载、`MINERU_API_BASE=http://192.168.8.167:8000`、本机 Zotero。灰色来源默认开启，`--legal-only` 或 `SCANSCI_LEGAL_ONLY=1` 改为只要合法来源。Kimi 仍是 `SEARCH_BACKEND=kimi`。
