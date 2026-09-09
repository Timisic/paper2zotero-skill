# 故障排查

每条都按「症状 → 原因 → 处理」。多数来自真实运行中修过的问题。

## 转换出的 Markdown 质量差 / 出现伪表格、词粘连

- **症状**：Markdown 里满屏 `| 空单元格 |`、词被粘成 `alChina`、双栏内容交错。
- **原因**：使用了 MarkItDown 0.1.7 的旧路径（其无框表格探测器会误判学术双栏版式）。
- **处理**：本 skill 现只走 MinerU 精准解析（`vlm`）。确认 setup doctor 中 MinerU token 为 OK；若未配置 token，会记录 `markdown_unavailable` 而不是用低质量路径代跑。

## 多个出版社同时 `error`，但 JMIR / Google / Crossref 正常

- **症状**：`browser_pdf.py` 对 ScienceDirect、Springer、SAGE、Cambridge、Nature 一律返回 `kind: error`（浏览器里是 `ERR_CONNECTION_CLOSED`），可 shell 里 `curl -x http://127.0.0.1:7897 <同一地址>` 却是通的。
- **原因**：**MyLOFT 扩展的机构会话失效**，不是网络问题。失败集合恰好等于 MyLOFT 托管的出版社集合。决定性证据：mihomo 的 debug 日志里连一次 DNS 查询和 TCP 拨号都没有——请求在浏览器内部就被拦掉了，根本没到代理。
- **处理**：在浏览器里打开 `https://app.myloft.xyz/browse/home`，确认页首还显示机构名（如「中国科学院心理研究所」）；不显示就重新登录 MyLOFT 扩展，然后重跑。
- **别误判**：真正的代理/线路问题会在 mihomo 日志里留下 `[TCP] ... match ...` 记录。有记录才是路由问题，没记录就是浏览器侧。

## MinerU 上传返回 403

- **原因**：OSS 预签名 URL 的签名**不含 Content-Type**；请求带任何 Content-Type 头（curl `-d`、urllib 默认头）都会 403。
- **处理**：用 `scripts/mineru_parse.py`（内部用空 Content-Type 上传）；勿用 `curl -d` 手动传。

## 两篇不同论文解析出相同结果

- **原因**：MinerU 服务端按**文件名**缓存；两个文件都叫 `source.pdf` 时互相覆盖。
- **处理**：客户端已自动用 `父目录名-文件名` 命名；手写调用时务必给不同文件不同名字。

## MinerU 401 / “user authenticate failed”

- **原因**：token 无效（常见：从页面 DOM 误抓了别的长字符串；或 token 已过期 90 天）。
- **处理**：token 以 `sk-` 开头才是 API token。在 mineru.net `apiManage/token` 重新创建，用隐藏方式存入 `~/.config/mineru/token`；也可通过抓创建接口的响应（而非页面文本）确保拿到明文。

## MinerU 控制台提示 token 满（5/5）

- **原因**：每个账号最多 5 个 token；反复创建把槽位占满。
- **处理**：登录 mineru.net → API 管理 → 删除不用的 token。

## Zotero 报“无法找到附件 / 本地路径缺失”（如 storage/X7N63JD5/paper.md）

- **原因**：附件已上传到云端且元数据在库，但 Zotero Desktop **附件文件同步未开启**（`extensions.zotero.sync.storage.enabled=false`），本地永远不下文件。注意：该设置项在 Zotero 7 里默认开启（prefs.js 缺失该项 = 默认开启）；`downloadAssociatedFiles`（“下载其他设备添加的文件”）是更窄的开关，实测不影响 Web API 上传附件的落盘，只作参考，不构成门槛。
- **处理**：Zotero → 偏好设置 → 同步 → 设置：确认“同步附件文件”已勾选（若该项曾经被显式关闭，prefs 会写 `false`），点同步；等本地文件出现后重跑 `scripts/zotero_sync.py --kind attachment-file --key <KEY> --storage-root <Zotero数据目录> --expected-sha256 <哈希>`。状态机里 `sync_pending` 不是失败，但也不等于完整成功。

## Zotero Web API 偶发 SSL: UNEXPECTED_EOF_WHILE_READING

- **原因**：本机代理（VPN/MyLOFT）对 api.zotero.org / OSS 的 TLS 瞬断。
- **处理**：preflight 与客户端已内置“直连重试一次”；仍失败就如实报告外部状态，不伪称成功。

## Kimi `navigate` 卡住 / 不建标签页

- **原因**：daemon 让浏览器新建标签页的动作在某些版本会挂起（历史已知问题）。
- **处理**：改用“系统打开 URL + 借用当前标签页”：
  ```bash
  open -a "Google Chrome" "https://example.com"   # Arc 等 Chromium 同理
  # 然后 Kimi 侧：find_tab {url, active:true} → borrowed
  ```

## 本地 API 200 但 preflight 说 local_api_available=false

- **原因**：端口探测超时或代理串扰。
- **处理**：确认 Zotero 在运行；重试；必要时给脚本设 `NO_PROXY=127.0.0.1`。
