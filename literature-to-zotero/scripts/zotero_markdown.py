#!/usr/bin/env python3
"""Attach Markdown through Zotero Web API when Zotero MCP rejects .md files."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import credentials  # noqa: E402


def fail(message: str) -> None:
    print(json.dumps({"status": "failed", "reason": message}, ensure_ascii=False))
    raise SystemExit(2)


def account(config_path: Path) -> dict[str, str]:
    """Resolve the hybrid-write account through the shared credentials layer.

    credentials.py already covers env → skill dotenv → runtime configs and
    never returns anything unless a layer supplies it; missing values are a
    hard failure here because a Web API write needs both key and library.
    """
    values = credentials.zotero_credentials(config_path)
    if not values["api_key"] or not values["library_id"]:
        fail("Zotero hybrid write credentials are not configured")
    if values["library_type"] not in {"user", "group"}:
        fail("ZOTERO_LIBRARY_TYPE must be user or group")
    return values


def attach_markdown(client: Any, source: Path, item_key: str) -> list[str]:
    response = client.attachment_simple([str(source)], parentid=item_key)
    if not isinstance(response, dict):
        raise RuntimeError("PyZotero returned an unexpected attachment response")
    failures = response.get("failure") or []
    if failures:
        raise RuntimeError(f"Zotero rejected the Markdown attachment: {failures}")
    records = (response.get("success") or []) + (response.get("unchanged") or [])
    keys = [record.get("key") for record in records if record.get("key")]
    if not keys:
        raise RuntimeError("Zotero returned no Markdown attachment key")
    for key in keys:
        attachment = client.item(key)
        attachment["data"]["contentType"] = "text/markdown"
        if client.update_item(attachment) is False:
            raise RuntimeError(f"Could not set text/markdown content type for attachment {key}")
    return keys


def load_pyzotero() -> Any:
    try:
        from pyzotero import zotero  # type: ignore[import-not-found]
        return zotero
    except ImportError:
        pass
    executable = shutil.which("zotero-mcp")
    if executable and os.environ.get("LITERATURE_ZOTERO_REEXEC") != "1":
        probe = subprocess.run(
            [executable, "setup-info"], text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=15
        )
        match = re.search(r"Python path:\s*(.+)", probe.stdout)
        if match and Path(match.group(1).strip()).is_file():
            environment = dict(os.environ)
            environment["LITERATURE_ZOTERO_REEXEC"] = "1"
            os.execve(match.group(1).strip(), [match.group(1).strip(), __file__, *sys.argv[1:]], environment)
    fail("PyZotero is unavailable and the zotero-mcp Python runtime could not be resolved")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item-key", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--codex-config", default=str(Path.home() / ".codex" / "config.toml"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = Path(args.file).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".md":
        fail("source must be an existing .md file")
    account_values = account(Path(args.codex_config))
    summary = {
        "status": "ready" if args.dry_run else "attached",
        "item_key": args.item_key,
        "filename": source.name,
        "library_type": account_values["library_type"],
        "library_id": account_values["library_id"],
    }
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False))
        return

    try:
        zotero = load_pyzotero()
        client = zotero.Zotero(account_values["library_id"], account_values["library_type"], account_values["api_key"])
        attachment_keys = attach_markdown(client, source, args.item_key)
    except Exception as error:
        fail(f"Markdown attachment upload failed: {type(error).__name__}: {error}")
    summary["attachment_keys"] = attachment_keys
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
