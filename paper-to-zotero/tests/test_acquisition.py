"""The browser fallback, driven through a scripted second adapter.

HTTP is tried first now (see `test_http_acquisition.py`), so every paper here
starts with links that no HTTP route can fetch — a closed local port — and the
browser channel is what has to finish the job. That ordering is the point:
these exercise the real identity checking and per-paper isolation in
`process_run` with only the browser itself replaced (see `fake_browser.py`).
"""
from __future__ import annotations

import json
from pathlib import Path

from http_fixture import server
from test_cli import ROOT, run_script
from test_process_run import payload, process
from test_workflow_resume import selected_run
from zotero_peer import ZoteroLibrary

PROBE = ROOT / "tests/fixtures/probe.pdf"
PROBE_TITLE = "Zotero MCP Write Probe"
FAKE_BROWSER = Path(__file__).with_name("fake_browser.py")
# Port 9 (discard) refuses instantly: an HTTP route that cannot work, without
# a DNS lookup or a proxy dial to wait for.
UNREACHABLE_PDF = "http://127.0.0.1:9/alpha.pdf"
UNREACHABLE_LANDING = "http://127.0.0.1:9/alpha"
SECOND_PDF = "http://127.0.0.1:9/second/alpha.pdf"
UNREACHABLE_W3 = "http://127.0.0.1:9/w3.pdf"


def scripted(tmp_path: Path, scenario: dict) -> list[str]:
    """`--browser-command` flags running the scripted adapter over this scenario.

    Paired with `--no-source-lookup`: these tests fix the set of links up
    front, so asking metadata services for more would only add latency.
    """
    import sys

    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")
    tokens = [sys.executable, str(FAKE_BROWSER), str(path)]
    return ["--no-source-lookup",
            *[flag for token in tokens for flag in ("--browser-command", token)]]


def run_awaiting_acquisition(tmp_path: Path, title: str = PROBE_TITLE, doi: str = "10.1000/alpha") -> Path:
    """A confirmed paper with no PDF yet — the state the default flow reaches."""
    run = selected_run(tmp_path)
    candidates = json.loads((run / "candidates.json").read_text())
    candidates[0].update({"title": title, "doi": doi, "oa_pdf_url": UNREACHABLE_PDF,
                          "landing_page_url": UNREACHABLE_LANDING})
    (run / "candidates.json").write_text(json.dumps(candidates))
    return run


def test_an_open_access_pdf_is_tried_first_and_recorded(tmp_path: Path) -> None:
    run = run_awaiting_acquisition(tmp_path)
    command = scripted(tmp_path, {
        "capture": {UNREACHABLE_PDF: {"result": "captured", "source": str(PROBE)}},
    })
    result = process(run, "--stages", "acquire", *command)
    body = payload(result)
    assert body["acquire"]["acquired"] == ["doi:10.1000/alpha"]
    status = json.loads(run_script("workflow.py", "status", "--run-dir", str(run)).stdout)
    paper = status["papers"]["doi:10.1000/alpha"]
    assert paper["state"] == "pdf_acquired"
    assert Path(paper["artifacts"]["pdf"]).read_bytes() == PROBE.read_bytes()


def test_a_blocked_publisher_hands_other_sources_to_the_agent(tmp_path: Path) -> None:
    run = run_awaiting_acquisition(tmp_path)
    candidates = json.loads((run / "candidates.json").read_text())
    candidates[0]["locations"] = [
        {"url": UNREACHABLE_PDF, "kind": "pdf", "source": "OpenAlex", "version": "published"},
        {"url": SECOND_PDF, "kind": "pdf", "source": "Unpaywall", "version": "accepted"},
    ]
    (run / "candidates.json").write_text(json.dumps(candidates))
    command = scripted(tmp_path, {
        "capture": {
            UNREACHABLE_PDF: {"result": "blocked"},
            SECOND_PDF: {"result": "captured", "source": str(PROBE)},
        },
    })
    body = payload(process(run, "--stages", "acquire", *command))
    assert body["acquire"]["acquired"] == []
    handoff = body["acquire"]["browser_handoff"][0]
    assert handoff["id"] == "doi:10.1000/alpha"
    assert SECOND_PDF in handoff["urls"]
    assert body["papers"][0]["pdf"] is False
    trail = json.loads((run / "papers" / "doi-10.1000-alpha" / "acquisition.json").read_text())[-1]
    # The wall that stopped the first link is named, not folded into "failed".
    assert [entry["kind"] for entry in trail["attempts"] if entry.get("channel") == "browser"] == [
        "reachability"]
    assert trail["ok"] is False


def test_a_valid_pdf_of_the_wrong_paper_is_not_kept(tmp_path: Path) -> None:
    # The scenario hands back a real PDF that is a different paper entirely.
    run = run_awaiting_acquisition(tmp_path, title="Coral reef bleaching under marine heatwaves")
    command = scripted(tmp_path, {
        "capture": {UNREACHABLE_PDF: {"result": "captured", "source": str(PROBE)}},
    })
    body = payload(process(run, "--stages", "acquire", *command))
    assert body["acquire"]["failed"] == {"doi:10.1000/alpha": "no verified source PDF"}
    assert not (run / "papers" / "doi-10.1000-alpha" / "source.pdf").exists()
    status = json.loads(run_script("workflow.py", "status", "--run-dir", str(run)).stdout)
    paper = status["papers"]["doi:10.1000/alpha"]
    assert "pdf" not in paper["artifacts"]
    assert paper["warnings"] == ["acquisition: no verified source PDF"]


def test_a_title_too_thin_to_identify_is_kept_not_claimed_verified(tmp_path: Path) -> None:
    """A two-word title matching by luck must not pass as this paper."""
    run = run_awaiting_acquisition(tmp_path, title="Mental-LLM", doi="10.1145/3643540")
    command = scripted(tmp_path, {
        "capture": {UNREACHABLE_PDF: {"result": "captured", "source": str(PROBE)}},
    })
    body = payload(process(run, "--stages", "acquire", *command))
    assert body["acquire"]["failed"] == {"doi:10.1000/alpha": "pdf_unverified"}
    status = json.loads(run_script("workflow.py", "status", "--run-dir", str(run)).stdout)
    artifacts = status["papers"]["doi:10.1000/alpha"]["artifacts"]
    assert "pdf" not in artifacts
    assert Path(artifacts["pdf_unverified"]).is_file()


def test_an_unreadable_pdf_is_kept_for_a_human_not_ingested(tmp_path: Path) -> None:
    unreadable = tmp_path / "scanned.pdf"
    # A structurally valid PDF with no extractable text: identity is unknown,
    # which is not the same as wrong.
    unreadable.write_bytes(b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
    run = run_awaiting_acquisition(tmp_path)
    command = scripted(tmp_path, {
        "capture": {UNREACHABLE_PDF: {"result": "captured", "source": str(unreadable)}},
    })
    body = payload(process(run, "--stages", "acquire", *command))
    assert body["acquire"]["failed"] == {"doi:10.1000/alpha": "pdf_unverified"}
    status = json.loads(run_script("workflow.py", "status", "--run-dir", str(run)).stdout)
    artifacts = status["papers"]["doi:10.1000/alpha"]["artifacts"]
    assert "pdf" not in artifacts
    assert Path(artifacts["pdf_unverified"]).is_file()


def test_one_unreachable_paper_does_not_stop_the_batch(tmp_path: Path) -> None:
    run = run_awaiting_acquisition(tmp_path)
    candidates = json.loads((run / "candidates.json").read_text())
    candidates[1].update({"title": PROBE_TITLE, "oa_pdf_url": UNREACHABLE_W3,
                          "authors": ["Grace Hopper"]})
    (run / "candidates.json").write_text(json.dumps(candidates))
    run_script("workflow.py", "import-candidates", "--run-dir", str(run), "--file", str(run / "candidates.json"))
    run_script("workflow.py", "approve-candidates", "--run-dir", str(run),
               "--ids", "doi:10.1000/alpha,openalex:W3")
    command = scripted(tmp_path, {
        # alpha's only source is absent from the scenario: an unreachable host.
        "capture": {UNREACHABLE_W3: {"result": "captured", "source": str(PROBE)}},
    })
    storage = tmp_path / "Zotero"
    peer = ZoteroLibrary(storage=storage)
    with server(peer.respond) as base:
        peer.base = base
        result = process(run, "--stages", "acquire,ingest", *command,
                         "--api-base", base, "--storage-root", str(storage))
    body = payload(result)
    assert body["acquire"]["acquired"] == ["openalex:W3"]
    assert list(body["acquire"]["failed"]) == ["doi:10.1000/alpha"]
    rows = {row["id"]: row for row in body["papers"]}
    assert rows["openalex:W3"]["pdf"] is True and rows["openalex:W3"]["cloud_verified_at"]
    assert rows["doi:10.1000/alpha"]["pdf"] is False
    assert rows["doi:10.1000/alpha"]["pending"] == ["PDF pending"]


def test_acquisition_is_skipped_when_the_browser_channel_is_down(tmp_path: Path) -> None:
    run = run_awaiting_acquisition(tmp_path)
    # An adapter that cannot even start stands in for a dead channel.
    body = payload(process(run, "--stages", "acquire", "--no-source-lookup",
                           "--browser-command", "/nonexistent/adapter"))
    assert list(body["acquire"]["failed"]) == ["doi:10.1000/alpha"]
    assert body["papers"][0]["pdf"] is False
