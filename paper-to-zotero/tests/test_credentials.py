"""Credential discovery is runtime-neutral and env wins."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "credentials", Path(__file__).resolve().parent.parent / "scripts" / "credentials.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_env_wins_over_config_files(tmp_path: Path, monkeypatch: object) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(MODULE, "SKILL_ENV_FILE", tmp_path / "no-such-env")
    monkeypatch.setenv("ZOTERO_API_KEY", "env-key")
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "999")
    codex = tmp_path / "config.toml"
    codex.write_text(
        '[mcp_servers.zotero]\ncommand = "/bin/true"\n'
        '[mcp_servers.zotero.env]\nZOTERO_API_KEY = "codex-key"\nZOTERO_LIBRARY_ID = "1"\n'
    )
    creds = MODULE.zotero_credentials(codex)
    assert creds["api_key"] == "env-key"
    assert creds["library_id"] == "999"
    assert creds["library_type"] == "user"


def test_codex_config_supplies_when_env_empty(tmp_path: Path, monkeypatch: object) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(MODULE, "SKILL_ENV_FILE", tmp_path / "no-such-env")
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.delenv("ZOTERO_LIBRARY_ID", raising=False)
    codex = tmp_path / "config.toml"
    codex.write_text(
        '[mcp_servers.zotero]\ncommand = "/bin/true"\n'
        '[mcp_servers.zotero.env]\nZOTERO_API_KEY = "codex-key"\nZOTERO_LIBRARY_ID = "42"\n'
        'ZOTERO_LIBRARY_TYPE = "group"\n'
    )
    creds = MODULE.zotero_credentials(codex)
    assert creds == {"api_key": "codex-key", "library_id": "42", "library_type": "group"}


def test_skill_env_and_claude_are_fallback_sources(tmp_path: Path, monkeypatch: object) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.delenv("ZOTERO_LIBRARY_ID", raising=False)
    skill_env = tmp_path / "env"
    skill_env.write_text('ZOTERO_API_KEY=skill-key\nZOTERO_LIBRARY_ID=7\n')
    monkeypatch.setattr(MODULE, "SKILL_ENV_FILE", skill_env)
    monkeypatch.setattr(MODULE, "CODEX_CONFIG", tmp_path / "missing.toml")
    claude = tmp_path / "claude.json"
    claude.write_text(json.dumps({"mcpServers": {"zotero": {"env": {"ZOTERO_API_KEY": "x", "ZOTERO_LIBRARY_ID": "1"}}}}))
    monkeypatch.setattr(MODULE, "CLAUDE_JSON", claude)
    monkeypatch.setattr(MODULE, "CLAUDE_SETTINGS", tmp_path / "settings.json")
    creds = MODULE.zotero_credentials()
    assert creds["api_key"] == "skill-key"
    assert creds["library_id"] == "7"


def test_mineru_token_prefers_env_then_skill_config_then_token_file(tmp_path: Path, monkeypatch: object) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    monkeypatch.setattr(MODULE, "SKILL_ENV_FILE", tmp_path / "no-such-env")
    token_file = tmp_path / "mineru" / "token"
    monkeypatch.setattr(MODULE, "MINERU_TOKEN_FILE", token_file)
    assert MODULE.mineru_token() == ""
    token_file.parent.mkdir(parents=True)
    token_file.write_text("sk-example\n")
    assert MODULE.mineru_token() == "sk-example"
    monkeypatch.setenv("MINERU_TOKEN", "sk-env")
    assert MODULE.mineru_token() == "sk-env"


def test_zotero_mcp_config_exposes_only_non_secret_block_facts(tmp_path: Path) -> None:
    codex = tmp_path / "config.toml"
    codex.write_text(
        '[mcp_servers.zotero]\ncommand = "/opt/zotero-mcp"\n'
        '[mcp_servers.zotero.env]\nZOTERO_LOCAL = "true"\n'
        'ZOTERO_API_KEY = "super-secret"\nZOTERO_LIBRARY_ID = "123"\n'
    )
    facts = MODULE.zotero_mcp_config(codex)
    assert facts["command"] == "/opt/zotero-mcp"
    assert facts["env_present"] is True
    assert facts["zotero_local"] is True
    assert set(facts) == {"command", "env_present", "zotero_local"}
    assert "super-secret" not in str(facts)

    missing = MODULE.zotero_mcp_config(tmp_path / "missing.toml")
    assert missing == {"command": "", "env_present": False, "zotero_local": False}


def test_zotero_mcp_config_reads_zotero_local_flag_only(tmp_path: Path) -> None:
    codex = tmp_path / "config.toml"
    codex.write_text(
        '[mcp_servers.zotero]\ncommand = "/opt/zotero-mcp"\n'
        '[mcp_servers.zotero.env]\nZOTERO_LOCAL = "false"\nZOTERO_API_KEY = "k"\n'
    )
    facts = MODULE.zotero_mcp_config(codex)
    assert facts["zotero_local"] is False
    assert facts["env_present"] is True


def test_a_source_setting_prefers_env_then_the_skill_dotenv(tmp_path: Path, monkeypatch: object) -> None:  # type: ignore[no-untyped-def]
    dotenv = tmp_path / "env"
    dotenv.write_text("SEMANTIC_SCHOLAR_API_KEY=from-file\nUNPAYWALL_EMAIL=person@example.org\n")
    monkeypatch.setattr(MODULE, "SKILL_ENV_FILE", dotenv)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("S2_API_KEY", raising=False)
    assert MODULE.source_setting("semantic_scholar") == "from-file"
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "from-env")
    assert MODULE.source_setting("semantic_scholar") == "from-env"
    assert MODULE.source_setting("unpaywall") == "person@example.org"


def test_a_source_that_needs_nothing_is_configured(tmp_path: Path, monkeypatch: object) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(MODULE, "SKILL_ENV_FILE", tmp_path / "missing")
    for name in ("SEMANTIC_SCHOLAR_API_KEY", "S2_API_KEY", "OPENALEX_API_KEY",
                 "CROSSREF_MAILTO", "UNPAYWALL_EMAIL"):
        monkeypatch.delenv(name, raising=False)
    configured = MODULE.configured_sources()
    assert configured["arxiv"] is True
    assert configured["semantic_scholar"] is False
    assert MODULE.source_setting("arxiv") == ""


def test_an_unknown_source_is_a_mistake_not_an_empty_string() -> None:
    try:
        MODULE.source_setting("scopus")
    except KeyError:
        return
    raise AssertionError("an unknown source must not silently read as unconfigured")
