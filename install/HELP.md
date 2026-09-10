# 安装帮助

第一次配置只有四步：准备工具 → 连接 Zotero → 启用全文阅读 → 检查结果。

Zotero 保存你的论文和笔记；全文阅读使用 MinerU，将 PDF 转成便于阅读和总结的文字。两个服务各有自己的账号。向导会打开对应网页并逐步说明如何取得授权码，不需要学习编程。

## Windows

- 使用普通 PowerShell 或双击下载目录中的 `install/setup.cmd`，无需安装 WSL，也不需要手动改系统路径。
- 安装过程中可能出现系统的安装许可窗口。完成后会打开标题为 `literature-to-zotero` 的配置窗口。
- 在配置窗口里可右键粘贴或按 **Shift+Insert**。输入授权码时不会显示字符，粘贴后按回车即可。
- 如果系统提示缺少“应用安装程序”，按打开的 Microsoft Store 页面安装或更新，然后重跑原入口。
- 若网络下载失败，网络恢复后重跑；已经填写的账号配置会保留。
- 通过在线命令安装后，可按 Win+R，输入 `%LOCALAPPDATA%\paper2zotero-source\install\setup.cmd`，继续配置。
- 安装路径可以包含中文和空格。软件安装完成后仍提示找不到工具时，关闭旧窗口，再运行安装入口。

## 更多设置

默认配置完成后，即可开始使用。额外文献来源、电脑上的 Zotero 附件下载，以及通过学校或机构浏览器访问全文，可以等需要时再设置。

请 AI 助手“打开文献工具的更多设置”。也可以自己运行：

- Windows：双击 `install/setup-more.cmd`。
- macOS/Linux：`bash install/setup.sh --advanced`。

更多设置里的每项都可跳过。跳过会保留之前的配置；之前已经启用的功能仍会在最后检查。

## 没有账号或授权码

直接回车暂时跳过。向导会说明哪些功能还不能使用，可以先尝试找论文；服务是否可用还取决于网络和对应服务的访问额度。需要保存到 Zotero 或生成全文阅读材料时，再补齐对应账号。

## 预览界面

Windows 双击 `install/setup-demo.cmd`，macOS/Linux 运行 `bash install/setup.sh --demo`。这只是演示，不安装软件、不连接账号、不上传论文，也不会改变真实配置。Windows 预览需要已经安装 Git Bash。

## 助手里找不到技能

新开一个助手会话再试。仍找不到时，让助手“检查 literature-to-zotero 是否安装到了当前助手”。同一份技能支持 Claude Code、Codex 和 Pi；安装到一个助手不会自动使所有助手都能使用。
