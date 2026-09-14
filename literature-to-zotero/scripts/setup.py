#!/usr/bin/env python3
"""Setup doctor: turn a capability report into a human action checklist.

Detection and remediation text live in scripts/capability.py (one record per
capability: {ok, detail, remediation}); preflight runs the probes and this
doctor renders the records as the "so what do I do next" layer. For every
missing capability it prints the exact remediation (commands, UI paths,
hidden-input steps). It never modifies configuration and never reveals
credentials.

Typical flow on a fresh machine:
    python "$SKILL_DIR/scripts/setup.py" --skip-live   # first look
    python "$SKILL_DIR/scripts/setup.py"               # live checks (Zotero running)
Then follow the printed ACTION items top to bottom; re-run after each step.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capability  # noqa: E402


def run_preflight(codex_config: Path, skip_live: bool) -> dict[str, Any]:
    command = [sys.executable, str(SKILL_DIR / "scripts" / "preflight.py"),
               "--codex-config", str(codex_config), "--json"]
    if skip_live:
        command.append("--skip-live")
    completed = subprocess.run(command, text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=60)
    if completed.returncode != 0:
        print(json.dumps({"status": "failed", "reason": completed.stderr.strip() or "preflight failed"},
                         ensure_ascii=False))
        raise SystemExit(2)
    return json.loads(completed.stdout)


# Doctor checklist: (human label, record name in report["capabilities"]).
# Records are the single source for ok/detail/remediation (capability.py).
CHECKLIST = [
    ("Zotero Desktop 本地 API（应用已安装并运行）", "zotero_local"),
    ("Zotero 附件文件同步", "zotero_sync"),
    ("Zotero MCP 已配置", "zotero_mcp"),
    ("Zotero Web API key（hybrid 写入：身份与写权限）", "zotero_key"),
    ("Kimi WebBridge（浏览器自动化）", "kimi"),
    ("MinerU token（Markdown 解析）", "mineru"),
    ("文献检索来源（OpenAlex 必备，其余可选）", "discovery_sources"),
]


def checklist(report: dict[str, Any]) -> list[dict[str, str]]:
    records = report.get("capabilities") or {}
    items: list[dict[str, str]] = []

    def add(name: str, record: dict[str, Any]) -> None:
        ok = record.get("ok") is True
        items.append({
            "name": name,
            "status": "ok" if ok else "missing",
            "action": str(record.get("remediation") or ""),
            "detail": str(record.get("detail") or ""),
        })

    for name, record_name in CHECKLIST:
        record = records.get(record_name)
        if isinstance(record, dict):
            add(name, record)
    return items


ACTIONS = {
    "codex_config_path": "~/.codex/config.toml（本 skill 的 zotero MCP env 默认放在这里）",
    "mineru_token_path": "~/.config/mineru/token（0600）",
    "zotero_prefs": f"{capability.zotero_profiles_dirs()[0]}/*/prefs.js（由 Zotero 设置页修改，勿手改运行中文件）",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-config", default=str(Path.home() / ".codex" / "config.toml"))
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run_preflight(Path(args.codex_config), args.skip_live)
    items = checklist(report)
    ready = report.get("ready") is True

    if args.json:
        print(json.dumps({
            "status": "ready" if ready else "incomplete",
            "ready": ready,
            "notes": ACTIONS,
            "items": items,
            "external_sources": report.get("external_sources", {}),
            "sources": report.get("sources", []),
        }, ensure_ascii=False))
        return 0

    print("== literature-to-zotero setup doctor ==")
    print("ready:", "READY" if ready else "NOT READY (见下方缺失项)\n")
    for it in items:
        mark = "OK " if it["status"] == "ok" else "MISSING"
        print(f"[{mark}] {it['name']}")
        if it["status"] != "ok":
            print(f"       行动: {it['action']}")
            if it.get("detail"):
                print(f"       详情: {it['detail']}")
    external = report.get("external_sources") or {}
    if external.get("measured"):
        print(f"\n== 外部数据源可达性（参考，不影响 ready）{external['reachable']}/{external['measured']} ==")
        for name, value in external["sources"].items():
            print(f"- {name}: {'OK' if value else ('未探测' if value is None else '不可达')}")
        print(f"  {external['note']}")

    configured = report.get("sources") or []
    if configured:
        print("\n== 检索来源（配置存在与否，不显示任何密钥）==")
        for row in configured:
            mark = "可用" if row["usable"] else "跳过"
            setting = (f"{row['setting']}{'（已配置）' if row['configured'] else '（未配置）'}"
                       if row["setting"] else "无需配置")
            print(f"- [{mark}] {row['source']}（{row['role']}）: {setting}，"
                  f"限速 {row['requests_per_second']} 次/秒")

    print("\n== 关键路径 ==")
    for key, value in ACTIONS.items():
        print(f"- {key}: {value}")
    if not ready:
        print("\n提示: 逐项修复后重跑本命令；MCP 工具的实际调用验证需在装有 zotero MCP 的运行时进行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
