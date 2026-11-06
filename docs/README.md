# 维护文档

这些文档供开发者和维护 Agent 使用。普通用户从[项目首页](../README.md)开始。

- 帮用户安装或修复配置：[Agent 安装说明](../install/AGENT_SETUP.md)。修改安装器或向导：[安装架构](setup-architecture.md)。
- 修改论文处理流程：[架构与工作约定](../CONTEXT.md)；执行文献任务：[SKILL.md](../paper-to-zotero/SKILL.md) 及其 `references/`。
- 随附的第三方写作 skill：[THIRD_PARTY.md](../THIRD_PARTY.md)。文献流程的夹具验收：[verify-paper2zotero](../.agents/skills/verify-paper2zotero/SKILL.md)。

## Architecture decisions

- [ADR-0001](adr/0001-capability-judgement-and-credentials.md)：统一能力判断与凭据读取。
- [ADR-0003](adr/0003-one-confirmation-and-independent-artifacts.md)：一次确认、同一任务续跑、独立交付产物。
- [ADR-0005](adr/0005-ingest-existing-pdf-scansci-kimi.md)：入库顺序为已有 PDF → scansci → Kimi WebBridge。取代 [ADR-0002](adr/0002-browser-acquisition-channel.md) 和 [ADR-0004](adr/0004-http-first-discovery-and-acquisition.md)。

## 检查与打包

```bash
python3 -m pytest paper-to-zotero/tests -q
python3 -m mypy paper-to-zotero/scripts
python3 scripts/build-distribution.py --output <新的输出目录>
```

打包只含首页、`THIRD_PARTY.md`、`install/` 和六个 skill 目录，不含本目录与测试。
