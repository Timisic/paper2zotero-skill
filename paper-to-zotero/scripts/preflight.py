#!/usr/bin/env python3
"""Report the machine's runtime capabilities without revealing credentials.

Probing and judgement semantics live in scripts/capability.py (one record
per capability: {ok, detail, remediation}). This CLI only runs the probes
against the real environment, then combines the capability records into a
report plus a single "ready" decision. It never modifies configuration and
never prints secrets.

Typical flow on a fresh machine:
    python "$SKILL_DIR/scripts/preflight.py" --skip-live --json   # offline facts
    python "$SKILL_DIR/scripts/preflight.py" --json               # live checks
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capability  # noqa: E402
import credentials  # noqa: E402
import mineru_parse  # noqa: E402
import sources  # noqa: E402


def search_report() -> dict[str, Any]:
    try:
        backend = credentials.search_backend()
        names = list(credentials.discovery_sources_for(backend))
    except ValueError as error:
        return {"backend": None, "sources": [], "error": str(error)}
    return {"backend": backend, "sources": names}


def converter_report(*, live: bool) -> dict[str, Any]:
    plan = mineru_parse.converter_plan(live=live)
    return {key: plan[key] for key in (
        "selected", "chain", "available", "api_base", "lab_default", "tailscale",
        "health", "markitdown", "markitdown_install")}


def stage_report(args: argparse.Namespace) -> dict[str, Any]:
    """Inspect only what the requested stage needs; other services stay untouched."""
    records: dict[str, capability.Record] = {}
    live = not args.skip_live
    extra: dict[str, Any] = {}
    if args.stage == "discovery":
        extra["search"] = search_report()
    elif args.stage == "conversion":
        plan = converter_report(live=live)
        records["mineru"] = capability.converter_ready(plan)
        extra["converter"] = plan
    elif args.stage == "ingestion":
        local_ok = capability.probe_zotero_local_write() if live else None
        account = credentials.zotero_credentials(args.codex_config)
        configured = bool(account["api_key"] and account["library_id"])
        access = capability.probe_zotero_key(account["api_key"], account["library_id"],
                                             account["library_type"], args.zotero_api_base_url) if live and configured and local_ok is not True else None
        records["zotero_write"] = capability.zotero_write(local_ok, capability.zotero_key(configured, access))
    elif args.stage == "browser_fallback":
        records["kimi"] = capability.kimi(capability.probe_kimi(live=live))
    elif args.stage == "local_sync":
        records["zotero_local"] = capability.zotero_local(capability.probe_zotero_local() if live else None)
        prefs = Path(args.zotero_prefs) if args.zotero_prefs else capability.default_zotero_prefs()
        records["zotero_sync"] = capability.zotero_sync(capability.zotero_prefs(prefs))
    missing = capability.stage_missing(args.stage, records)
    next_action = "run the requested stage" if not missing else (
        "continue independent PDF conversion/summaries; report this write-channel failure and let the ingestion command handle bounded recovery"
        if args.stage == "ingestion" else "report the missing capability; continue stages that do not require it")
    return {"next_action": next_action, "stage": args.stage, "stage_requirements": list(capability.STAGE_REQUIREMENTS[args.stage]),
            "stage_missing": missing, "stage_ready": not missing, "ready": not missing,
            "capabilities": records, **extra}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-config", default=str(Path.home() / ".codex" / "config.toml"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument("--mcp-tools-verified", action="store_true")
    parser.add_argument("--zotero-api-base-url", default=capability.ZOTERO_API_BASE)
    parser.add_argument("--zotero-prefs")
    parser.add_argument("--stage", choices=sorted(capability.STAGE_REQUIREMENTS),
                        help="report readiness for one stage instead of the whole run")
    args = parser.parse_args()

    if args.stage:
        stage_payload = stage_report(args)
        if not args.json:
            print("STAGE READY" if stage_payload["stage_ready"] else "STAGE NOT READY")
        print(json.dumps(stage_payload, ensure_ascii=False, indent=None if args.json else 2))
        return

    live = not args.skip_live
    mcp = credentials.zotero_mcp_config(Path(args.codex_config))
    command = mcp["command"]
    account = credentials.zotero_credentials(args.codex_config)
    creds_present = bool(account["api_key"] and account["library_id"])
    configured = bool(mcp["env_present"] or creds_present)
    command_ok = capability.command_available(command)
    mineru_configured = bool(credentials.mineru_token())
    converter = converter_report(live=live)

    storage_preferences = capability.zotero_prefs(Path(args.zotero_prefs) if args.zotero_prefs else capability.default_zotero_prefs())
    kimi_status = capability.probe_kimi(live=live)
    local_available = None if not live else capability.probe_zotero_local()
    local_write = None if not live else capability.probe_zotero_local_write()

    key_access: dict[str, bool | None] = {
        "reachable": None,
        "identity_match": None,
        "write_permission": None,
    }
    if live and creds_present and local_write is not True:
        key_access.update(
            capability.probe_zotero_key(
                account["api_key"],
                account["library_id"],
                account["library_type"],
                args.zotero_api_base_url,
                command=command if command_ok else None,
            )
        )

    key_record = capability.zotero_key(creds_present, key_access if live and creds_present else None)
    records = {
        "zotero_local": capability.zotero_local(local_available),
        "zotero_sync": capability.zotero_sync(storage_preferences),
        "zotero_mcp": capability.zotero_mcp(configured, command_ok),
        "zotero_key": key_record,
        "zotero_write": capability.zotero_write(local_write, key_record),
        "kimi": capability.kimi(kimi_status),
        "mineru": capability.converter_ready(converter),
        "skill_links": capability.skill_links(capability.skill_link_roots()),
        "discovery_sources": capability.discovery_sources(sources.usable_sources()),
    }
    ready = capability.ready({name: records[name] for name in ("zotero_local", "zotero_sync", "zotero_write", "kimi")})

    payload: dict[str, Any] = {
        "ready": ready,
        # Advisory only — deliberately outside `capabilities`, so it can never
        # reach `capability.ready`.
        "external_sources": capability.reachability_report(capability.probe_external_sources(live)),
        "kimi_webbridge": {
            "installed": kimi_status["installed"],
            "connected": kimi_status["extension_connected"],
        },
        "mineru": {
            "token_path": str(credentials.MINERU_TOKEN_FILE),
            "configured": mineru_configured,
            "authenticated": None,
            "reachable": None,
            "probe": "not_run",
            "required": False,
        },
        "zotero": {
            "configured": configured,
            "command_available": command_ok,
            "mcp_available": bool(command and command_ok),
            "scripted_writer_available": Path(__file__).with_name("zotero_ingest.py").is_file(),
            "write_channel": "mcp" if args.mcp_tools_verified else ("local_api" if local_write else "scripted_web_api"),
            "local_enabled": mcp["zotero_local"],
            "hybrid_write_configured": creds_present,
            "local_api_available": local_available,
            "web_api": key_access,
            "mcp_tools_verified": args.mcp_tools_verified,
            "desktop_storage": storage_preferences,
        },
        # Which source answers which question, and how fast it may be asked.
        # Configuration presence only: no key, address or token is ever shown.
        "sources": sources.source_report(),
        "search": search_report(),
        "converter": converter,
        "capabilities": records,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print("READY" if ready else "NOT READY")
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
