"""P1: retrieval is bounded at the run level, and stages check only what they use."""
from __future__ import annotations

import json
from pathlib import Path

from test_cli import FIXTURES, run_script


def init_run(tmp_path: Path) -> Path:
    result = run_script(
        "workflow.py", "init", "--run-root", str(tmp_path), "--slug", "budget", "--intent", "test",
    )
    return Path(json.loads(result.stdout)["run_dir"])


def discover(run: Path, output: Path, *extra: str, check: bool = True):
    return run_script(
        "discover_openalex.py", "--query", "AI mental health intervention",
        "--input-json", str(FIXTURES / "openalex.json"), "--output", str(output),
        "--run-dir", str(run), *extra, check=check,
    )


def test_discovery_records_its_round_against_the_run_budget(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    first = discover(run, tmp_path / "a.json")
    assert json.loads(first.stdout)["search"]["supplementary_remaining"] == 1
    second = discover(run, tmp_path / "b.json", "--round", "supplementary",
                      "--reason", "initial list had four reliable candidates")
    assert json.loads(second.stdout)["search"]["supplementary_remaining"] == 0

    blocked = discover(run, tmp_path / "c.json", "--round", "supplementary",
                       "--reason", "one more source", check=False)
    assert blocked.returncode == 2
    assert "supplementary search budget" in blocked.stderr

    queries = json.loads((run / "queries.json").read_text())
    assert [entry["round"] for entry in queries] == ["initial", "supplementary"]


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
    assert payload["stage_requirements"] == ["zotero_key"]
    assert payload["stage_ready"] is False
    assert payload["stage_missing"] == ["zotero_key"]
