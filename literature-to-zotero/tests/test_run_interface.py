"""The Run interface: one home for the manifest schema.

Callers ask a Run and its Papers what exists; nothing outside `workflow.py`
navigates manifest keys or re-derives where an artifact lives.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from test_cli import ROOT, run_script
from test_workflow_resume import selected_run

sys.path.insert(0, str(ROOT / "scripts"))
from workflow import Paper, Run  # noqa: E402


def test_a_recorded_artifact_that_vanished_is_recorded_but_not_present(tmp_path: Path) -> None:
    """`path` is what was recorded; `artifact` is what is actually there."""
    run = selected_run(tmp_path)
    source = run / "source.pdf"
    source.write_bytes((ROOT / "tests/fixtures/probe.pdf").read_bytes())
    Run.record(run, "doi:10.1000/alpha", "pdf_acquired", artifact="pdf=" + str(source))

    paper = Run.open(run).paper("doi:10.1000/alpha")
    assert paper.pdf == source.resolve()
    source.unlink()
    paper = Run.open(run).paper("doi:10.1000/alpha")
    assert paper.pdf is None
    assert paper.path("pdf") == source.resolve()


def test_a_run_relative_artifact_resolves_against_its_run(tmp_path: Path) -> None:
    run = selected_run(tmp_path)
    (run / "papers").mkdir(exist_ok=True)
    relative = Path("papers") / "source.pdf"
    (run / relative).write_bytes((ROOT / "tests/fixtures/probe.pdf").read_bytes())
    Run.record(run, "doi:10.1000/alpha", "pdf_acquired", artifact="pdf=" + str(relative))
    assert Run.open(run).paper("doi:10.1000/alpha").pdf == (run / relative).resolve()


def test_the_run_answers_selection_consent_and_candidates(tmp_path: Path) -> None:
    run = selected_run(tmp_path)
    package = Run.open(run)
    assert package.confirmed is True
    assert package.selected == ["doi:10.1000/alpha"]
    assert package.consented("mineru", ["doi:10.1000/alpha"]) is False
    with pytest.raises(ValueError, match="consent missing"):
        package.require_consent("mineru", ["doi:10.1000/alpha"])

    run_script("workflow.py", "consent", "--run-dir", str(run), "--service", "mineru",
               "--decision", "approved", "--source", "message:7")
    package = Run.open(run)
    assert package.consented("mineru", ["doi:10.1000/alpha"]) is True
    assert package.consent_source("mineru", "doi:10.1000/alpha") == "message:7"
    assert package.candidates()["doi:10.1000/alpha"]["title"]

    with pytest.raises(ValueError, match="unselected papers"):
        package.resolve_ids(["openalex:W3"])
    with pytest.raises(ValueError, match="not in this run"):
        package.paper("doi:10.1000/nope")


def test_an_unconfirmed_run_refuses_before_any_work(tmp_path: Path) -> None:
    result = run_script("workflow.py", "init", "--run-root", str(tmp_path),
                        "--slug", "unconfirmed", "--intent", "test")
    run = Path(json.loads(result.stdout)["run_dir"])
    package = Run.open(run)
    assert package.confirmed is False
    with pytest.raises(ValueError, match="not approved"):
        package.require_confirmed()


def test_paper_reports_itself_without_the_caller_reading_the_manifest(tmp_path: Path) -> None:
    run = selected_run(tmp_path)
    Run.record(run, "doi:10.1000/alpha", "metadata_only")
    row = Run.open(run).report()[0]
    assert row["id"] == "doi:10.1000/alpha"
    assert row["pending"] == ["no full text"]
    assert row["actionable"] is False
    assert "Paper | PDF | Markdown" in Run.open(run).table()
    assert set(Paper.ARTIFACTS) == {"pdf", "markdown", "summary"}
