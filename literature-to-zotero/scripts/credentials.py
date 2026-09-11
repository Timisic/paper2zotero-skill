"""Runtime-neutral credential discovery.

The skill is read and executed by multiple agent runtimes (Codex, Claude
Code, Hermes, pi, ...). Credentials therefore must not be tied to one
runtime's config file. Resolution order per service (first hit wins):

  1. environment variables (the most portable channel; also how tests inject)
  2. this skill's own config file: ~/.config/literature-to-zotero/env
     (flat KEY=VALUE dotenv written by the setup wizard)
  3. Zotero MCP env blocks found in common runtime configs:
       ~/.codex/config.toml            ([mcp_servers.zotero.env])
       ~/.claude.json / settings.json  (mcpServers.zotero.env)

Values are returned to callers but never printed or logged. Every script
reads configuration through this module only, so a new runtime or config
format is a change in one place. Non-secret MCP block facts (command,
ZOTERO_LOCAL flag, env presence) are exposed via zotero_mcp_config().
"""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Any

HOME = Path.home()
# Flat KEY=VALUE dotenv written by the setup wizard (same format as .env).
SKILL_ENV_FILE = HOME / ".config" / "literature-to-zotero" / "env"
MINERU_TOKEN_FILE = HOME / ".config" / "mineru" / "token"
CODEX_CONFIG = HOME / ".codex" / "config.toml"
CLAUDE_JSON = HOME / ".claude.json"
CLAUDE_SETTINGS = HOME / ".claude" / "settings.json"


def _dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def _codex_zotero_block(path: Path) -> dict[str, Any]:
    """Parse one Codex config file's zotero MCP block: command + env values.

    Returns {"command": str, "env": {KEY: value}}. The env values may hold
    secrets; only code inside this module should carry them around.
    """
    if not path.is_file():
        return {"command": "", "env": {}}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {"command": "", "env": {}}
    block = (data.get("mcp_servers") or {}).get("zotero") or {}
    env = {
        str(k): str(v)
        for k, v in (block.get("env") or {}).items()
        if isinstance(v, (str, int, bool))
    }
    return {"command": str(block.get("command") or ""), "env": env}


def zotero_mcp_config(
    explicit_codex_config: str | Path | None = None,
) -> dict[str, Any]:
    """Non-secret facts about the zotero MCP block in a Codex config.

    Returns {"command": str, "env_present": bool, "zotero_local": bool}.
    Secrets inside the env block are never returned here; scripts that only
    need to know whether a block exists / where its command points use this
    instead of parsing config files themselves.
    """
    path = Path(explicit_codex_config) if explicit_codex_config is not None else CODEX_CONFIG
    block = _codex_zotero_block(path)
    env = block["env"]
    return {
        "command": block["command"],
        "env_present": bool(env),
        "zotero_local": str(env.get("ZOTERO_LOCAL", "")).lower() == "true",
    }


def _skill_env() -> dict[str, str]:
    return _dotenv(SKILL_ENV_FILE)


def _codex_zotero_env() -> dict[str, str]:
    return _codex_zotero_block(CODEX_CONFIG)["env"]


def _claude_zotero_env() -> dict[str, str]:
    def read(path: Path) -> dict[str, str]:
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        block = (data.get("mcpServers") or {}).get("zotero") or {}
        env = block.get("env") or {}
        return {str(k): str(v) for k, v in env.items() if isinstance(v, str)}

    merged: dict[str, str] = {}
    for path in (CLAUDE_JSON, CLAUDE_SETTINGS):
        merged.update(read(path))
    return merged


def usable_secret(value: str) -> bool:
    """Reject empty/redacted setup values without prescribing a token format."""
    token = value.strip()
    return bool(token and not (len(token) <= 3 and not token.isalnum())
                and set(token) - set("*xX.•…") and token.casefold() not in {
        "<redacted>", "[redacted]", "redacted", "your-api-key", "your_api_key",
        "replace-me", "replace_me", "changeme", "<api_key>", "<api-key>",
    })


def zotero_credentials(explicit_codex_config: str | Path | None = None) -> dict[str, str]:
    """Resolve Zotero Web API credentials across runtimes.

    Precedence: environment variables, then this skill's dotenv, then the
    Zotero MCP env block in the (optionally overridden) Codex config, then
    Claude Code's config. Every layer that exists contributes only missing
    keys, so env always wins.
    """
    resolved = {
        "api_key": os.environ.get("ZOTERO_API_KEY", ""),
        "library_id": os.environ.get("ZOTERO_LIBRARY_ID", ""),
        "library_type": os.environ.get("ZOTERO_LIBRARY_TYPE", ""),
    }
    # A redacted value is not a credential. Retain the selected account while
    # looking for a usable key, so fallback never borrows another library's key.
    if not usable_secret(resolved["api_key"]):
        resolved["api_key"] = ""
    layers: list[dict[str, str]] = []
    skill_env = _skill_env()
    skill_keys = {k: v for k, v in skill_env.items() if k.startswith("ZOTERO_")}
    if skill_keys:
        layers.append(skill_keys)
    if explicit_codex_config is not None:
        codex_path = Path(explicit_codex_config)
        layers.append(_read_codex_env(codex_path))
        if not codex_path.is_file():
            layers.append(_claude_zotero_env())
    else:
        layers.append(_codex_zotero_env())
        layers.append(_claude_zotero_env())
    env_names = {"api_key": "ZOTERO_API_KEY", "library_id": "ZOTERO_LIBRARY_ID", "library_type": "ZOTERO_LIBRARY_TYPE"}
    for layer in layers:
        layer_id = layer.get("ZOTERO_LIBRARY_ID", layer.get("library_id", ""))
        layer_type = layer.get("ZOTERO_LIBRARY_TYPE", layer.get("library_type", "")) or "user"
        account_matches = ((not resolved["library_id"] or layer_id == resolved["library_id"])
                           and (not resolved["library_type"] or layer_type == resolved["library_type"]))
        for key, env_name in env_names.items():
            if not resolved[key]:
                value = layer.get(key, "") or layer.get(env_name, "")
                if key == "api_key" and (not usable_secret(value) or not account_matches):
                    continue
                if key == "library_type" and not account_matches:
                    continue
                resolved[key] = value
    if resolved["library_type"] not in {"user", "group"}:
        resolved["library_type"] = "user"
    return resolved


def _read_codex_env(path: Path) -> dict[str, str]:
    return _codex_zotero_block(path)["env"]


# Bibliographic sources, and the configuration each one needs. Two of these
# are not secrets at all — Crossref and Unpaywall want a contact address so
# they can reach the operator of a busy client — but they are read here with
# everything else, so a new runtime or config format stays a change in one
# place. A source with no entry needs nothing and is always usable.
SOURCE_SETTINGS: dict[str, tuple[str, ...]] = {
    "semantic_scholar": ("SEMANTIC_SCHOLAR_API_KEY", "S2_API_KEY"),
    "openalex": ("OPENALEX_API_KEY",),
    "crossref": ("CROSSREF_MAILTO",),
    "unpaywall": ("UNPAYWALL_EMAIL",),
    "arxiv": (),
}


def source_setting(source: str) -> str:
    """The key or contact address configured for one bibliographic source.

    Environment first, then the skill dotenv — the same precedence as every
    other credential, so a shell export always wins over a stale file. An
    empty string means "not configured", which is a degraded source, never an
    error: only the source that needs it is affected.
    """
    names = SOURCE_SETTINGS.get(source)
    if names is None:
        raise KeyError(source)
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    skill_env = _skill_env()
    for name in names:
        value = skill_env.get(name, "").strip()
        if value:
            return value
    return ""


def configured_sources() -> dict[str, bool]:
    """Which sources are configured. Presence only — never the values."""
    return {
        source: True if not names else bool(source_setting(source))
        for source, names in SOURCE_SETTINGS.items()
    }


def mineru_token() -> str:
    token = os.environ.get("MINERU_TOKEN", "")
    if not token:
        token = _skill_env().get("MINERU_TOKEN", "")
    if not token and MINERU_TOKEN_FILE.is_file():
        token = MINERU_TOKEN_FILE.read_text(encoding="utf-8").strip()
    return token


def zotero_configured() -> bool:
    creds = zotero_credentials()
    return bool(creds["api_key"] and creds["library_id"])
