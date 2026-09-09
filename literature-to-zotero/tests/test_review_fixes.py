"""Regressions for the review findings on the simplification work.

Each test names the failure it prevents; all of them describe paths the
documented default flow actually takes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from http_fixture import server
from test_cli import FIXTURES, ROOT, run_script
from test_partial_delivery import SUMMARY, run_with_pdf
from test_process_run import payload, process
from test_workflow_resume import selected_run
from zotero_peer import ZoteroLibrary

sys.path.insert(0, str(ROOT / "scripts"))
import workflow  # noqa: E402


def test_a_confirmed_paper_can_go_straight_to_an_acquired_pdf(tmp_path: Path) -> None:
    """The default flow never records `metadata_verified` before acquisition."""
    run = selected_run(tmp_path)
    source = run / "source.pdf"
    source.write_bytes((ROOT / "tests/fixtures/probe.pdf").read_bytes())
    paper = workflow.Run.record(run, "doi:10.1000/alpha", "pdf_acquired", artifact="pdf=" + str(source))
    assert paper.state == "pdf_acquired"
    assert paper.pdf == source.resolve()


def test_markdown_can_arrive_after_the_paper_was_read_back(tmp_path: Path) -> None:
    """A token added between runs must not throw away the conversion."""
    run, _ = run_with_pdf(tmp_path)
    summary = run / "summary.md"
    summary.write_text(SUMMARY)
    run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/alpha",
               "--state", "summary_generated", "--artifact", "summary=" + str(summary))
    storage = tmp_path / "Zotero"
    peer = ZoteroLibrary(storage=storage)
    with server(peer.respond) as base:
        peer.base = base
        first = process(run, "--stages", "ingest", "--api-base", base, "--storage-root", str(storage))
        assert payload(first)["papers"][0]["state"] == "read_back_verified"
        markdown = run / "paper.md"
        markdown.write_text("# Derived paper\n")
        late = workflow.Run.record(run, "doi:10.1000/alpha", "markdown_derived",
                                   artifact="markdown=" + str(markdown))
        assert late.state == "markdown_derived"
        second = process(run, "--stages", "ingest", "--api-base", base, "--storage-root", str(storage))
    body = payload(second)
    assert body["status"] == "complete", body
    assert body["papers"][0]["markdown"] is True


def test_a_warning_from_a_failed_attempt_does_not_outlive_the_fix(tmp_path: Path) -> None:
    """Otherwise a recovered run reports "partial" forever."""
    run, _ = run_with_pdf(tmp_path)
    workflow.Run.record(run, "doi:10.1000/alpha", warning="markdown_unavailable: no MinerU token")
    markdown = run / "paper.md"
    markdown.write_text("# Derived paper\n")
    workflow.Run.record(run, "doi:10.1000/alpha", "markdown_derived", artifact="markdown=" + str(markdown))
    summary = run / "summary.md"
    summary.write_text(SUMMARY)
    workflow.Run.record(run, "doi:10.1000/alpha", "summary_generated", artifact="summary=" + str(summary))
    storage = tmp_path / "Zotero"
    peer = ZoteroLibrary(storage=storage)
    with server(peer.respond) as base:
        peer.base = base
        result = process(run, "--stages", "ingest", "--api-base", base, "--storage-root", str(storage))
    body = payload(result)
    row = body["papers"][0]
    assert row["pending"] == []
    assert row["complete"] is True
    assert body["status"] == "complete", body
    # The history is still recorded, just not mistaken for outstanding work.
    assert "markdown_unavailable: no MinerU token" in row["notes"]


def test_dry_run_never_downloads_or_uploads(tmp_path: Path) -> None:
    run, _ = run_with_pdf(tmp_path)
    result = process(run, "--dry-run", "--api-base", "http://127.0.0.1:1")
    body = payload(result)
    assert body["stages"] == ["ingest"]
    assert body["dry_run"] is True
    assert "acquire" not in body and "convert" not in body


def test_a_paper_with_no_full_text_is_finished_not_actionable(tmp_path: Path) -> None:
    run = selected_run(tmp_path)
    run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/alpha",
               "--state", "metadata_only")
    row = json.loads(run_script("workflow.py", "report", "--run-dir", str(run)).stdout)["papers"][0]
    assert row["pending"] == ["no full text"]
    assert row["actionable"] is False


def test_a_selected_paper_missing_from_the_candidate_file_is_reported(tmp_path: Path) -> None:
    run, _ = run_with_pdf(tmp_path)
    (run / "candidates.json").write_text(json.dumps(
        [item for item in json.loads((run / "candidates.json").read_text()) if item["id"] != "doi:10.1000/alpha"]))
    result = process(run, "--stages", "ingest", "--api-base", "http://127.0.0.1:1")
    assert result.returncode == 2
    assert "missing from candidates.json" in payload(result)["reason"]


def test_a_supplementary_round_without_a_run_is_refused(tmp_path: Path) -> None:
    result = run_script(
        "discover_openalex.py", "--query", "q", "--round", "supplementary", "--reason", "more",
        "--input-json", str(FIXTURES / "openalex.json"), "--output", str(tmp_path / "out.json"), check=False,
    )
    assert result.returncode == 2
    assert "needs --run-dir" in result.stderr


def test_local_sync_unchecked_is_distinct_from_not_synced(tmp_path: Path) -> None:
    run, _ = run_with_pdf(tmp_path)
    summary = run / "summary.md"
    summary.write_text(SUMMARY)
    run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/alpha",
               "--state", "summary_generated", "--artifact", "summary=" + str(summary))
    peer = ZoteroLibrary(storage=None)
    with server(peer.respond) as base:
        peer.base = base
        # No --storage-root: the local copy was never looked at.
        result = process(run, "--stages", "ingest", "--api-base", base)
    row = payload(result)["papers"][0]
    assert row["pending"] == ["markdown_unavailable", "local sync not checked"]
    assert row["state"] == "sync_pending"


def test_a_mistyped_request_field_fails_at_the_call_not_mid_batch() -> None:
    """The request types are the seam's contract; a typo cannot slip past it.

    An argparse.Namespace accepted any attribute name, so a caller's typo went
    unnoticed by the type checker and surfaced as an AttributeError partway
    through writing a batch.
    """
    import pytest

    import mineru_parse  # noqa: PLC0415
    import zotero_ingest  # noqa: PLC0415

    with pytest.raises(TypeError):
        zotero_ingest.IngestRequest(run_dir=Path("/tmp/x"), storagexroot=None)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        mineru_parse.ParseRequest(pdfs=[], run_directory=Path("/tmp/x"))  # type: ignore[call-arg]
    # run_dir is the one field with no sensible default.
    with pytest.raises(TypeError):
        zotero_ingest.IngestRequest()  # type: ignore[call-arg]
