"""P1: retrieval is bounded at the run level, and stages check only what they use."""
from __future__ import annotations

import json
from pathlib import Path

from test_cli import FIXTURES, run_script


def test_normalized_candidates_carry_no_forced_classification(tmp_path: Path) -> None:
    output = tmp_path / "candidates.json"
    run_script(
        "discover_openalex.py", "--query", "q", "--input-json", str(FIXTURES / "openalex.json"),
        "--output", str(output),
    )
    candidates = json.loads(output.read_text())
    assert all("candidate_set" not in candidate for candidate in candidates)
    assert all(candidate["hit_reason"] is None for candidate in candidates)


def test_discovery_stage_is_not_gated_on_zotero_desktop(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[mcp_servers.zotero]\ncommand = "/opt/zotero-mcp"\n')
    payload = json.loads(run_script(
        "preflight.py", "--codex-config", str(config), "--json", "--skip-live", "--stage", "discovery",
    ).stdout)
    assert payload["stage"] == "discovery"
    assert payload["stage_ready"] is True
    assert payload["stage_requirements"] == []


def test_ingestion_stage_requires_the_write_channel_only(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[mcp_servers.zotero]\ncommand = "/opt/zotero-mcp"\n')
    payload = json.loads(run_script(
        "preflight.py", "--codex-config", str(config), "--json", "--skip-live", "--stage", "ingestion",
    ).stdout)
    assert payload["stage_requirements"] == ["zotero_write"]
    assert payload["stage_ready"] is False
    assert payload["stage_missing"] == ["zotero_write"]
