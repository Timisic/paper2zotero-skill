#!/usr/bin/env python3
"""Per-stage verification helpers for the setup wizard and humans.

Each command prints one JSON line: {"ok": bool, "detail": "..."}. Every
command is a thin caller of scripts/capability.py (probe + pure judgement),
the same records preflight uses — so the wizard can
never report "done" while the skill would refuse to run, and vice versa.

Commands:
  skill-links     - all skills ready in the selected agent runtime
  zotero-local    - Zotero Desktop local API answers on 127.0.0.1:23119
  zotero-sync     - Desktop attachment file sync enabled (absent pref =
                    Zotero 7 default ON) and auto-download not disabled
  kimi            - Kimi daemon running and browser extension connected
  zotero-key      - credentials resolve and match the current library (needs
                    ZOTERO_API_KEY / ZOTERO_LIBRARY_ID in the environment)
  self-id         - print the numeric Zotero user id for the provided API key
  mineru          - one conversion hop is ready (lab, cloud token, or markitdown)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capability  # noqa: E402
import credentials  # noqa: E402
import agent_installation  # noqa: E402


def print_record(record: dict[str, str | bool]) -> int:
    detail = record.get("detail") or ""
    print(json.dumps({"ok": bool(record["ok"]), "detail": detail}, ensure_ascii=False))
    return 0 if record["ok"] else 1


def cmd_skill_links() -> int:
    agent = os.environ.get('PAPER2ZOTERO_AGENT', 'auto')
    paths = [path for name in agent_installation.SKILL_NAMES
             for path in agent_installation.installed_paths(agent=agent, skill_name=name)]
    return print_record({'ok': agent_installation.installation_ok(agent), 'detail': ', '.join(paths)})


def cmd_zotero_local() -> int:
    return print_record(capability.zotero_local(capability.probe_zotero_local()))


def cmd_zotero_sync() -> int:
    return print_record(capability.zotero_sync(capability.zotero_prefs()))


def cmd_kimi() -> int:
    return print_record(capability.kimi(capability.probe_kimi()))


def cmd_zotero_key() -> int:
    account = credentials.zotero_credentials()
    if not account["api_key"] or not account["library_id"]:
        return print_record(capability.zotero_key(False, None))
    access = capability.zotero_key_access(
        account["api_key"], account["library_id"], account["library_type"]
    )
    return print_record(capability.zotero_key(True, access))


def cmd_self_id() -> int:
    key = os.environ.get("ZOTERO_API_KEY", "")
    if not credentials.usable_secret(key) or any(ord(c) < 32 or ord(c) == 127 for c in key):
        print('授权码没有正确填入，请重新复制并粘贴完整授权码。', file=sys.stderr)
        return 1
    try:
        user_id = capability.zotero_personal_id(capability.zotero_key_info(key))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(user_id)
    return 0


def cmd_mineru() -> int:
    import mineru_parse
    plan = mineru_parse.converter_plan(live=True)
    return print_record(capability.converter_ready(plan))


COMMANDS = {
    "skill-links": cmd_skill_links,
    "zotero-local": cmd_zotero_local,
    "zotero-sync": cmd_zotero_sync,
    "kimi": cmd_kimi,
    "zotero-key": cmd_zotero_key,
    "self-id": cmd_self_id,
    "mineru": cmd_mineru,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    args = parser.parse_args(argv)
    return COMMANDS[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
