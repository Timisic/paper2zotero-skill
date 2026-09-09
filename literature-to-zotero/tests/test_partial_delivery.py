"""P2: PDF, Markdown and summary are written independently of one another."""
from __future__ import annotations

import json
from pathlib import Path

from http_fixture import server
from test_cli import ROOT, run_script
from test_zotero_ingest import ingest
from test_workflow_resume import selected_run
from zotero_peer import ZoteroLibrary

SUMMARY = (
    "# Core Summary\n\n- provider: `agent-default`\n- template_version: `1`\n"
    "- source_basis: `pdf`\n\nVerified probe summary.\n"
)


def run_with_pdf(tmp_path: Path) -> tuple[Path, Path]:
    """A selected paper whose verified source PDF is on disk, nothing else."""
    run = selected_run(tmp_path)
    source = run / "source.pdf"
    source.write_bytes((ROOT / "tests/fixtures/probe.pdf").read_bytes())
    candidates = json.loads((run / "candidates.json").read_text())
    candidates[0]["title"] = "Zotero MCP Write Probe"
    (run / "candidates.json").write_text(json.dumps(candidates))
    run_script("workflow.py", "record-paper", "--run-dir", str(run),
               "--id", "doi:10.1000/alpha", "--state", "metadata_verified")
    run_script("workflow.py", "record-paper", "--run-dir", str(run),
               "--id", "doi:10.1000/alpha", "--state", "pdf_acquired", "--artifact", "pdf=" + str(source))
    return run, source


def serve(peer: ZoteroLibrary):
    return server(peer.respond)


def test_dry_run_accepts_a_verified_pdf_with_no_summary(tmp_path: Path) -> None:
    run, _ = run_with_pdf(tmp_path)
    result = ingest(run, "http://127.0.0.1:1", "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "planned"


def test_verified_pdf_is_saved_before_any_summary_exists(tmp_path: Path) -> None:
    run, source = run_with_pdf(tmp_path)
    storage = tmp_path / "Zotero"
    peer = ZoteroLibrary(storage=storage)
    with serve(peer) as base:
        peer.base = base
        result = ingest(run, base, "--storage-root", str(storage))
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "partial"
    paper = payload["papers"]["doi:10.1000/alpha"]
    assert paper["state"] == "partial"
    assert "summary pending" in paper["pending"]
    assert paper["markdown_status"] == "markdown_unavailable"
    assert paper["cloud_verified_at"]
    assert peer.files, "the PDF attachment binary must be uploaded"
    assert not any(item["data"].get("itemType") == "note" for item in peer.items.values())

    row = json.loads(run_script("workflow.py", "report", "--run-dir", str(run)).stdout)["papers"][0]
    assert (row["pdf"], row["markdown"], row["summary"]) == (True, False, False)
    assert row["cloud_verified_at"]
    assert "summary pending" in row["pending"]


def test_a_later_summary_reuses_the_parent_and_uploaded_pdf(tmp_path: Path) -> None:
    run, source = run_with_pdf(tmp_path)
    storage = tmp_path / "Zotero"
    peer = ZoteroLibrary(storage=storage)
    with serve(peer) as base:
        peer.base = base
        ingest(run, base, "--storage-root", str(storage))
        creations_after_pdf, uploads_after_pdf = peer.creations, peer.uploads

        summary = run / "summary.md"
        summary.write_text(SUMMARY)
        run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/alpha",
                   "--state", "summary_generated", "--artifact", "summary=" + str(summary))
        second = ingest(run, base, "--storage-root", str(storage))

    assert second.returncode == 0, second.stdout + second.stderr
    payload = json.loads(second.stdout)
    assert payload["status"] == "complete"
    assert payload["papers"]["doi:10.1000/alpha"]["state"] == "read_back_verified"
    # One new object: the summary note. No second parent, no re-upload.
    assert peer.creations == creations_after_pdf + 1
    assert peer.uploads == uploads_after_pdf
    assert sum(item["data"]["itemType"] == "attachment" for item in peer.items.values()) == 1
    status = json.loads(run_script("workflow.py", "status", "--run-dir", str(run)).stdout)
    assert status["paper_states"] == {"read_back_verified": 1}


def test_cloud_verified_paper_is_delivered_while_desktop_lags(tmp_path: Path) -> None:
    run, source = run_with_pdf(tmp_path)
    summary = run / "summary.md"
    summary.write_text(SUMMARY)
    run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/alpha",
               "--state", "summary_generated", "--artifact", "summary=" + str(summary))
    # No storage mirror: the cloud has the file, Zotero Desktop does not yet.
    peer = ZoteroLibrary(storage=None)
    with serve(peer) as base:
        peer.base = base
        result = ingest(run, base, "--storage-root", str(tmp_path / "Zotero"))
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "partial"
    paper = payload["papers"]["doi:10.1000/alpha"]
    assert paper["state"] == "sync_pending"
    assert paper["pending"] == ["markdown_unavailable", "local sync pending"]
    assert paper["cloud_verified_at"]
    row = json.loads(run_script("workflow.py", "report", "--run-dir", str(run)).stdout)["papers"][0]
    assert row["local_synced"] is False
    assert row["cloud_verified_at"]


def test_markdown_arriving_late_attaches_without_touching_the_pdf(tmp_path: Path) -> None:
    run, source = run_with_pdf(tmp_path)
    storage = tmp_path / "Zotero"
    peer = ZoteroLibrary(storage=storage)
    with serve(peer) as base:
        peer.base = base
        ingest(run, base, "--storage-root", str(storage))
        pdf_keys = {key for key, item in peer.items.items() if item["data"].get("itemType") == "attachment"}
        markdown = run / "paper.md"
        markdown.write_text("# Derived paper\n")
        run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/alpha",
                   "--state", "markdown_derived", "--artifact", "markdown=" + str(markdown))
        second = ingest(run, base, "--storage-root", str(storage))
    payload = json.loads(second.stdout)
    paper = payload["papers"]["doi:10.1000/alpha"]
    assert paper["markdown_status"] == "available"
    assert paper["pending"] == ["summary pending"]
    attachments = {key for key, item in peer.items.items() if item["data"].get("itemType") == "attachment"}
    assert pdf_keys < attachments and len(attachments) == 2


def test_ingestion_can_be_narrowed_to_named_papers(tmp_path: Path) -> None:
    run, _ = run_with_pdf(tmp_path)
    run_script("workflow.py", "approve-candidates", "--run-dir", str(run),
               "--ids", "doi:10.1000/alpha,openalex:W3")
    storage = tmp_path / "Zotero"
    peer = ZoteroLibrary(storage=storage)
    with serve(peer) as base:
        peer.base = base
        result = ingest(run, base, "--storage-root", str(storage), "--ids", "doi:10.1000/alpha")
    payload = json.loads(result.stdout)
    assert payload["ids"] == ["doi:10.1000/alpha"]
    assert set(payload["papers"]) == {"doi:10.1000/alpha"}
    status = json.loads(run_script("workflow.py", "status", "--run-dir", str(run)).stdout)
    assert status["papers"]["openalex:W3"]["state"] == "selected"


def test_one_bad_paper_does_not_stop_the_others(tmp_path: Path) -> None:
    run, _ = run_with_pdf(tmp_path)
    summary = run / "summary.md"
    summary.write_text(SUMMARY)
    run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/alpha",
               "--state", "summary_generated", "--artifact", "summary=" + str(summary))
    # A third paper whose recorded PDF is a different paper entirely.
    candidates = json.loads((run / "candidates.json").read_text())
    candidates.append({"id": "doi:10.1000/gamma", "doi": "10.1000/gamma", "title": "A completely different study",
                       "year": 2024, "venue": "CHI", "authors": ["Ada Lovelace"]})
    (run / "candidates.json").write_text(json.dumps(candidates))
    run_script("workflow.py", "import-candidates", "--run-dir", str(run), "--file", str(run / "candidates.json"))
    run_script("workflow.py", "approve-candidates", "--run-dir", str(run),
               "--ids", "doi:10.1000/alpha,openalex:W3,doi:10.1000/gamma")
    run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "openalex:W3", "--state", "metadata_only")
    wrong = run / "wrong.pdf"
    wrong.write_bytes((ROOT / "tests/fixtures/probe.pdf").read_bytes())
    run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/gamma",
               "--state", "metadata_verified")
    run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/gamma",
               "--state", "pdf_acquired", "--artifact", "pdf=" + str(wrong))

    storage = tmp_path / "Zotero"
    peer = ZoteroLibrary(storage=storage)
    with serve(peer) as base:
        peer.base = base
        result = ingest(run, base, "--storage-root", str(storage))
        payload = json.loads(result.stdout)
        assert payload["status"] == "pending" and payload["errors"] == 1
        assert payload["papers"]["doi:10.1000/alpha"]["state"] == "read_back_verified"
        assert payload["papers"]["openalex:W3"]["state"] == "metadata_only"
        assert "identity not verified" in payload["papers"]["doi:10.1000/gamma"]["error"]
        # Retrying only the failed paper leaves the finished ones untouched.
        creations = peer.creations
        retry = ingest(run, base, "--storage-root", str(storage), "--ids", "doi:10.1000/gamma")
    assert set(json.loads(retry.stdout)["papers"]) == {"doi:10.1000/gamma"}
    assert peer.creations == creations


def test_an_unselected_paper_cannot_be_ingested(tmp_path: Path) -> None:
    run, _ = run_with_pdf(tmp_path)
    result = ingest(run, "http://127.0.0.1:1", "--ids", "openalex:W3", "--dry-run")
    assert result.returncode == 2
    assert "unselected papers cannot be ingested" in result.stdout
