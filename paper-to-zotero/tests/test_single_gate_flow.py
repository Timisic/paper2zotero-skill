"""P1: one confirmation, one list, a bounded search ledger."""
from __future__ import annotations

import json
from pathlib import Path

from test_cli import FIXTURES, run_script


def init_run(tmp_path: Path, slug: str = "single-gate") -> Path:
    result = run_script(
        "workflow.py", "init", "--run-root", str(tmp_path), "--slug", slug,
        "--intent", "近三年 AI 与心理健康的干预研究",
    )
    return Path(json.loads(result.stdout)["run_dir"])


def test_clear_intent_reaches_candidates_without_a_plan_gate(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    manifest = json.loads((run / "manifest.json").read_text())
    assert "search_plan" not in manifest["gates"]

    imported = run_script(
        "workflow.py", "import-candidates", "--run-dir", str(run),
        "--file", str(FIXTURES / "normalized_candidates.json"),
    )
    assert json.loads(imported.stdout)["imported"] == 2
    selected = run_script(
        "workflow.py", "approve-candidates", "--run-dir", str(run),
        "--ids", "doi:10.1000/alpha", "--source", "message:12", "--rule", "explicit IDs",
    )
    assert json.loads(selected.stdout)["selected"] == ["doi:10.1000/alpha"]
    status = json.loads(run_script("workflow.py", "status", "--run-dir", str(run)).stdout)
    assert status["gates"] == {"candidate_selection": "approved"}


def test_recorded_scope_is_evidence_not_a_gate(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    run_script(
        "workflow.py", "record-scope", "--run-dir", str(run),
        "--scope", "AI mental-health interventions; 2023-2026; English preferred",
    )
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["search_scope"] == "AI mental-health interventions; 2023-2026; English preferred"
    assert manifest["gates"] == {"candidate_selection": "pending"}
    assert [event["event"] for event in manifest["events"] if event["event"] == "search_scope_recorded"]
    # The retired `approve-plan` spelling still records scope for older callers.
    run_script("workflow.py", "approve-plan", "--run-dir", str(run), "--plan", "same scope, older flag")
    assert json.loads((run / "manifest.json").read_text())["search_scope"] == "same scope, older flag"


def test_one_supplementary_search_is_the_default_ceiling(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    first = run_script(
        "workflow.py", "record-search", "--run-dir", str(run), "--round", "initial",
        "--provider", "OpenAlex", "--query", "AI mental health intervention",
        "--reason", "primary query", "--elapsed-seconds", "31",
    )
    assert json.loads(first.stdout)["supplementary_remaining"] == 1
    second = run_script(
        "workflow.py", "record-search", "--run-dir", str(run), "--round", "supplementary",
        "--provider", "Semantic Scholar", "--query", "seed expansion",
        "--reason", "only 4 reliable candidates", "--elapsed-seconds", "44",
    )
    payload = json.loads(second.stdout)
    assert payload["supplementary_remaining"] == 0
    assert payload["elapsed_seconds"] == 75

    blocked = run_script(
        "workflow.py", "record-search", "--run-dir", str(run), "--round", "supplementary",
        "--provider", "Crossref", "--query", "third try", "--reason", "still thin", check=False,
    )
    assert blocked.returncode == 2
    assert "supplementary search budget" in blocked.stderr

    allowed = run_script(
        "workflow.py", "record-search", "--run-dir", str(run), "--round", "supplementary",
        "--provider", "Crossref", "--query", "third try", "--reason", "user asked to widen",
        "--user-requested",
    )
    assert json.loads(allowed.stdout)["rounds"] == 3


def test_search_status_reports_the_time_budget(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    run_script(
        "workflow.py", "record-search", "--run-dir", str(run), "--round", "initial",
        "--provider", "OpenAlex", "--query", "q", "--reason", "primary", "--elapsed-seconds", "310",
    )
    status = json.loads(run_script("workflow.py", "status", "--run-dir", str(run)).stdout)
    assert status["search"]["budget_seconds"] == 300
    assert status["search"]["elapsed_seconds"] == 310
    assert status["search"]["over_budget"] is True


def test_a_note_recorded_without_a_state_never_rewinds_the_paper(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import workflow  # noqa: PLC0415

    run = init_run(tmp_path, "notes")
    run_script("workflow.py", "import-candidates", "--run-dir", str(run),
               "--file", str(FIXTURES / "normalized_candidates.json"))
    run_script("workflow.py", "approve-candidates", "--run-dir", str(run), "--ids", "doi:10.1000/alpha")
    run_script("workflow.py", "record-paper", "--run-dir", str(run),
               "--id", "doi:10.1000/alpha", "--state", "metadata_verified")

    paper = workflow.Run.record(run, "doi:10.1000/alpha", warning="acquisition: no verified source PDF")
    assert paper.state == "metadata_verified"
    # The same observation twice is one warning, not a growing list.
    paper = workflow.Run.record(run, "doi:10.1000/alpha", warning="acquisition: no verified source PDF")
    assert paper.warnings == ["acquisition: no verified source PDF"]


def test_legacy_run_with_a_plan_gate_still_advances(tmp_path: Path) -> None:
    run = init_run(tmp_path, "legacy")
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["schema_version"] = 1
    manifest["gates"] = {"search_plan": "pending", "candidate_selection": "pending"}
    manifest.pop("search", None)
    (run / "manifest.json").write_text(json.dumps(manifest))
    run_script(
        "workflow.py", "import-candidates", "--run-dir", str(run),
        "--file", str(FIXTURES / "normalized_candidates.json"),
    )
    run_script(
        "workflow.py", "approve-candidates", "--run-dir", str(run), "--ids", "doi:10.1000/alpha",
    )
    status = json.loads(run_script("workflow.py", "status", "--run-dir", str(run)).stdout)
    assert status["gates"]["candidate_selection"] == "approved"
