from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURES = Path(__file__).parent / "fixtures"


def run_script(name: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        text=True,
        capture_output=True,
        check=check,
    )


def test_processing_waits_only_for_the_selection_confirmation(tmp_path: Path) -> None:
    result = run_script(
        "workflow.py",
        "init",
        "--run-root",
        str(tmp_path),
        "--slug",
        "ai-mental-health",
        "--intent",
        "近三年 AI 与心理健康深度融合的干预研究",
        "--from-year",
        "2023",
        "--to-year",
        "2026",
    )
    run_dir = Path(json.loads(result.stdout)["run_dir"])

    run_script(
        "workflow.py", "import-candidates", "--run-dir", str(run_dir),
        "--file", str(FIXTURES / "normalized_candidates.json"),
    )

    blocked = run_script(
        "workflow.py", "record-paper", "--run-dir", str(run_dir),
        "--id", "doi:10.1000/alpha", "--state", "pdf_acquired", check=False,
    )
    assert blocked.returncode == 2
    assert "candidate selection is not approved" in blocked.stderr

    run_script(
        "workflow.py", "approve-candidates", "--run-dir", str(run_dir),
        "--ids", "doi:10.1000/alpha,openalex:W3",
    )
    run_script(
        "workflow.py", "record-paper", "--run-dir", str(run_dir),
        "--id", "doi:10.1000/alpha", "--state", "metadata_verified",
    )
    status = json.loads(run_script("workflow.py", "status", "--run-dir", str(run_dir)).stdout)
    assert status["gates"] == {"candidate_selection": "approved"}
    assert status["paper_states"]["metadata_verified"] == 1


def test_openalex_fixture_is_normalized_and_deduplicated(tmp_path: Path) -> None:
    output = tmp_path / "candidates.json"
    result = run_script(
        "discover_openalex.py",
        "--query", "AI mental health intervention",
        "--from-year", "2023",
        "--to-year", "2026",
        "--input-json", str(FIXTURES / "openalex.json"),
        "--output", str(output),
        "--run-dir", str(tmp_path),
    )
    summary = json.loads(result.stdout)
    candidates = json.loads(output.read_text())

    assert summary["returned"] == 2
    assert summary["duplicates_removed"] == 1
    assert candidates[0]["id"] == "doi:10.1000/alpha"
    assert candidates[0]["abstract"] == "AI mental health interventions improved outcomes"
    assert candidates[0]["venue"] == "Journal of Digital Mental Health"
    assert candidates[1]["id"] == "openalex:W3"
    assert candidates[1]["work_type"] == "proceedings-article"
    assert candidates[0]["citation_source"] == "OpenAlex"
    assert candidates[0]["citation_observed_at"]
    queries = json.loads((tmp_path / "queries.json").read_text())
    assert queries[0]["provider"] == "OpenAlex"
    assert queries[0]["query"] == "AI mental health intervention"
    assert queries[0]["filters"] == {"from_year": 2023, "to_year": 2026}
    assert queries[0]["sent_fields"] == ["search", "filter", "per-page", "sort"]
    help_text = run_script("discover_openalex.py", "--help").stdout
    assert "--api-key" not in help_text


def test_pdf_verification_rejects_html_and_accepts_matching_pdf(tmp_path: Path) -> None:
    fake = tmp_path / "login.pdf"
    fake.write_text("<html><title>Sign in</title></html>")
    rejected = run_script(
        "paper_artifacts.py", "verify", "--pdf", str(fake),
        "--title", "AI mental health interventions", check=False,
    )
    assert rejected.returncode == 2
    assert json.loads(rejected.stdout)["status"] == "rejected"

    source = ROOT / "tests" / "fixtures" / "probe.pdf"
    accepted = run_script(
        "paper_artifacts.py", "verify", "--pdf", str(source),
        "--title", "Zotero MCP Write Probe",
    )
    payload = json.loads(accepted.stdout)
    assert payload["status"] == "verified"
    assert len(payload["sha256"]) == 64
    assert payload["identity_evidence"]["title_token_overlap"] >= 0.75


def test_preflight_reports_capabilities_without_secrets(tmp_path: Path, monkeypatch) -> None:
    # Credential precedence has its own isolated tests. This subprocess must
    # not combine its fixture account with the developer's personal dotenv.
    monkeypatch.setenv('ZOTERO_API_KEY', 'super-secret')
    monkeypatch.setenv('ZOTERO_LIBRARY_ID', '123')
    monkeypatch.setenv('ZOTERO_LIBRARY_TYPE', 'user')
    config = tmp_path / "config.toml"
    config.write_text(
        '[mcp_servers.zotero]\ncommand = "/opt/zotero-mcp"\n'
        '[mcp_servers.zotero.env]\nZOTERO_LOCAL = "true"\n'
        'ZOTERO_API_KEY = "super-secret"\nZOTERO_LIBRARY_ID = "123"\n'
    )
    result = run_script(
        "preflight.py", "--codex-config", str(config), "--json", "--skip-live",
    )
    payload = json.loads(result.stdout)
    assert payload["zotero"]["configured"] is True
    assert payload["zotero"]["hybrid_write_configured"] is True
    assert payload["ready"] is False
    assert "super-secret" not in result.stdout


def test_workflow_rejects_skipped_paper_states(tmp_path: Path) -> None:
    result = run_script(
        "workflow.py", "init", "--run-root", str(tmp_path), "--slug", "state-test",
        "--intent", "AI mental health interventions",
    )
    run_dir = Path(json.loads(result.stdout)["run_dir"])
    run_script(
        "workflow.py", "import-candidates", "--run-dir", str(run_dir),
        "--file", str(FIXTURES / "normalized_candidates.json"),
    )
    run_script(
        "workflow.py", "approve-candidates", "--run-dir", str(run_dir),
        "--ids", "doi:10.1000/alpha",
    )
    result = run_script(
        "workflow.py", "record-paper", "--run-dir", str(run_dir),
        "--id", "doi:10.1000/alpha", "--state", "read_back_verified", check=False,
    )
    assert result.returncode == 2
    assert "invalid paper state transition" in result.stderr
    run_script(
        "workflow.py", "record-paper", "--run-dir", str(run_dir),
        "--id", "doi:10.1000/alpha", "--state", "metadata_only",
    )
    recovered = run_script(
        "workflow.py", "record-paper", "--run-dir", str(run_dir),
        "--id", "doi:10.1000/alpha", "--state", "pdf_acquired",
    )
    assert json.loads(recovered.stdout)["state"] == "pdf_acquired"


def test_summary_artifact_records_provider_version_and_source_basis(tmp_path: Path) -> None:
    body = tmp_path / "body.md"
    body.write_text("研究问题、方法、结果、关联与限制。")
    output = tmp_path / "summary.md"
    result = run_script(
        "summary_artifact.py", "--content-file", str(body), "--output", str(output),
        "--provider", "agent-default", "--template-version", "1", "--source-basis", "markdown",
    )
    payload = json.loads(result.stdout)
    assert payload["status"] == "summary_generated"
    text = output.read_text()
    assert "provider: `agent-default`" in text
    assert "template_version: `1`" in text
    assert "source_basis: `markdown`" in text


def test_candidate_table_is_compact_and_selection_ready(tmp_path: Path) -> None:
    normalized = tmp_path / "normalized.json"
    run_script(
        "discover_openalex.py",
        "--query", "AI mental health intervention",
        "--input-json", str(FIXTURES / "openalex.json"),
        "--output", str(normalized),
    )
    candidates = json.loads(normalized.read_text())
    candidates[0]["candidate_set"] = "core"
    candidates[0]["hit_reason"] = "Tests an AI intervention against mental-health outcomes."
    candidates[1]["candidate_set"] = "expansion"
    candidates[1]["hit_reason"] = "Adds an HCI perspective on psychological support."
    normalized.write_text(json.dumps(candidates))

    output = tmp_path / "candidate-table.md"
    run_script("candidate_table.py", "--input", str(normalized), "--output", str(output))
    table = output.read_text()
    assert "ID | Paper | Year / venue | Why relevant | Citations | Source | Set" in table
    assert "doi:10.1000/alpha" in table
    assert "OpenAlex, observed" in table
    assert "Abstract:" not in table


def test_candidate_table_rejects_unscreened_candidates(tmp_path: Path) -> None:
    result = run_script(
        "candidate_table.py",
        "--input", str(FIXTURES / "normalized_candidates.json"),
        "--output", str(tmp_path / "candidate-table.md"),
        check=False,
    )
    assert result.returncode == 2
    assert "candidate screening is incomplete" in result.stderr


def test_markdown_attachment_dry_run_uses_zotero_account_without_leaking_key(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[mcp_servers.zotero]\ncommand = "/opt/zotero-mcp"\n'
        '[mcp_servers.zotero.env]\nZOTERO_LOCAL = "true"\n'
        'ZOTERO_API_KEY = "super-secret"\nZOTERO_LIBRARY_ID = "123"\n'
        'ZOTERO_LIBRARY_TYPE = "user"\n'
    )
    markdown = tmp_path / "paper.md"
    markdown.write_text("# Derived paper\n")
    # Credential discovery is env-first; pin env so the host dotenv can never
    # shadow the deterministic account this test expects.
    env = dict(os.environ)
    env.pop("ZOTERO_LIBRARY_TYPE", None)
    env["ZOTERO_API_KEY"] = "super-secret"
    env["ZOTERO_LIBRARY_ID"] = "123"
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "zotero_markdown.py"), "--item-key", "ABCD1234",
         "--file", str(markdown), "--codex-config", str(config), "--dry-run"],
        text=True, capture_output=True, check=False, env=env,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "status": "ready",
        "item_key": "ABCD1234",
        "filename": "paper.md",
        "library_type": "user",
        "library_id": "123",
    }
    assert "super-secret" not in result.stdout
    assert "super-secret" not in result.stderr


def test_preflight_treats_absent_storage_sync_pref_as_default_on(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[mcp_servers.zotero]\ncommand = "/opt/zotero-mcp"\n'
        '[mcp_servers.zotero.env]\nZOTERO_LOCAL = "true"\n'
        'ZOTERO_API_KEY = "super-secret"\nZOTERO_LIBRARY_ID = "123"\n'
    )
    prefs = tmp_path / "prefs.js"
    prefs.write_text('user_pref("extensions.zotero.dataDir", "/tmp/Zotero");\n')
    result = run_script(
        "preflight.py", "--codex-config", str(config), "--json", "--skip-live",
        "--zotero-prefs", str(prefs),
    )
    payload = json.loads(result.stdout)
    assert payload["zotero"]["desktop_storage"]["storage_sync_enabled"] is None
    assert payload["capabilities"]["zotero_sync"]["ok"] is True

    prefs.write_text('user_pref("extensions.zotero.sync.storage.enabled", false);\n')
    payload = json.loads(run_script(
        "preflight.py", "--codex-config", str(config), "--json", "--skip-live",
        "--zotero-prefs", str(prefs),
    ).stdout)
    assert payload["capabilities"]["zotero_sync"]["ok"] is False
    assert payload["ready"] is False
