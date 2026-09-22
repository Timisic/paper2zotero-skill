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

Windows 原生测试需在装有 Python、Git 和 Poppler 的 Windows 上运行：`python paper-to-zotero/tests/test_windows_setup.py -v`。其他系统上的跳过结果不算 Windows 验收。新系统安装、账号授权、客户端发现技能和真实论文处理，需要分别验证。

`.github/workflows/runtime.yml` 在 Windows、macOS、Linux 上执行流水线、账号连接与托管安装回归。`test_windows_pipeline.py` 复现进程锁、私有文件清理、UTF-8、CRLF note 哈希、公开 PDF Cookie 重定向和多助手更新；`test_mineru_resume.py` 从公开转换入口检查空批次恢复；`test_managed_installation.py` 检查完整副本发布、损坏检测和中断恢复。测试默认使用临时 HOME/USERPROFILE，避免安装用例覆盖维护者的真实技能。Windows 私有文件检查 NTFS ACL；POSIX 检查 0600，不能用 POSIX 权限位冒充 Windows 验证。

批处理性能回归集中在 `tests/test_session_bottlenecks.py`：占位凭据及账号边界、PDF 包装页恢复、批内一次扫描、上传期间登记其他论文、总结批量交接与来源变化保护。配合 `test_write_cost.py` 保留附件读回与重试去重约束；请求数和本地模拟测试不等同于真实网络的十分钟完成保证。
