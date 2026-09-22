"""Setup doctor renders a complete, secret-free action checklist."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "setup.py"


def test_setup_doctor_reports_missing_items_without_secrets(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[mcp_servers.zotero]\ncommand = "/opt/zotero-mcp"\n'
        '[mcp_servers.zotero.env]\nZOTERO_LOCAL = "true"\n'
        'ZOTERO_API_KEY = "super-secret"\nZOTERO_LIBRARY_ID = "123"\n'
    )
    env = dict(os.environ)
    env.pop("MINERU_TOKEN", None)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--codex-config", str(config), "--json", "--skip-live"],
        text=True,
        capture_output=True,
        timeout=60,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload) == {"status", "ready", "notes", "items", "external_sources", "sources"}
    # Reachability is advisory: it is reported beside the checklist, never as
    # one of its items, so it cannot turn a usable machine into NOT READY.
    assert "external_sources" not in {item["name"] for item in payload["items"]}
    assert "ok" not in payload["external_sources"]
    names = {item["name"] for item in payload["items"]}
    assert "MinerU token（Markdown 解析）" in names
    assert "Zotero MCP 已配置" in names
    assert all(item["status"] in {"ok", "missing"} for item in payload["items"])
    assert "super-secret" not in result.stdout
    assert "super-secret" not in result.stderr

    # Source rows say whether a setting exists and never what it is: the name
    # of the variable is reported, its value never leaves credentials.py.
    assert {row["source"] for row in payload["sources"]} == {
        "OpenAlex", "SemanticScholar", "Crossref", "Unpaywall", "arXiv", "PMC"}
    for row in payload["sources"]:
        assert set(row) == {"source", "role", "setting", "configured", "usable",
                            "degrades_to", "requests_per_second"}
        assert isinstance(row["configured"], bool) and isinstance(row["usable"], bool)
    # A missing optional key narrows coverage; it never makes the machine
    # NOT READY, which is what keeps a search from being blocked on it.
    sources_item = next(item for item in payload["items"] if item["name"].startswith("文献检索来源"))
    assert sources_item["status"] == "ok"
