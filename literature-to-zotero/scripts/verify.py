#!/usr/bin/env python3
"""Per-stage verification helpers for the setup wizard and humans.

Each command prints one JSON line: {"ok": bool, "detail": "..."}. Every
command is a thin caller of scripts/capability.py (probe + pure judgement),
the same records preflight and the setup doctor use — so the wizard can
never report "done" while the skill would refuse to run, and vice versa.

Commands:
  skill-links     - skill reachable from at least one agent runtime root
  zotero-local    - Zotero Desktop local API answers on 127.0.0.1:23119
  zotero-sync     - Desktop attachment file sync enabled (absent pref =
                    Zotero 7 default ON) and auto-download not disabled
  kimi            - Kimi daemon running and browser extension connected
  zotero-key      - credentials resolve and match the current library (needs
                    ZOTERO_API_KEY / ZOTERO_LIBRARY_ID in the environment)
  self-id         - print the numeric Zotero user id for the provided API key
  mineru          - MinerU token present and accepted (live probe)
  doctor          - full preflight readiness (live)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capability  # noqa: E402
import credentials  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_DIR / "scripts"


def print_record(record: dict[str, str | bool]) -> int:
    detail = record.get("detail") or ""
    print(json.dumps({"ok": bool(record["ok"]), "detail": detail}, ensure_ascii=False))
    return 0 if record["ok"] else 1


def cmd_skill_links() -> int:
    return print_record(capability.skill_links(capability.skill_link_roots()))


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
    token = credentials.mineru_token()
    if not token:
        return print_record(capability.mineru(False))
    return print_record(capability.mineru(True, capability.probe_mineru(token)))


def cmd_doctor() -> int:
    try:
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / "preflight.py"), "--json"],
            text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=60,
        )
        payload = json.loads(completed.stdout)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "detail": f"preflight failed: {type(exc).__name__}"}, ensure_ascii=False))
        return 1
    ok = payload.get("ready") is True
    print(json.dumps({"ok": ok, "detail": "see scripts/setup.py --json for missing items"}, ensure_ascii=False))
    return 0 if ok else 1


COMMANDS = {
    "skill-links": cmd_skill_links,
    "zotero-local": cmd_zotero_local,
    "zotero-sync": cmd_zotero_sync,
    "kimi": cmd_kimi,
    "zotero-key": cmd_zotero_key,
    "self-id": cmd_self_id,
    "mineru": cmd_mineru,
    "doctor": cmd_doctor,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    args = parser.parse_args(argv)
    return COMMANDS[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
