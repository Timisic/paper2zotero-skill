"""P3: one entry point runs the confirmed selection and resumes it."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from http_fixture import server
from test_cli import ROOT, SCRIPTS, run_script
from test_partial_delivery import SUMMARY, run_with_pdf
from zotero_peer import ZoteroLibrary

sys.path.insert(0, str(SCRIPTS))


def process(run: Path, *extra: str, check: bool = False,
            env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "ZOTERO_API_KEY": "test-secret", "ZOTERO_LIBRARY_ID": "123",
           "ZOTERO_LIBRARY_TYPE": "user", **(env or {})}
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "process_run.py"), "--run-dir", str(run),
         "--collection-key", "COLLECT1", "--retry-budget", "5", *extra],
        env=env, capture_output=True, text=True, check=check,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_browser_disabled_never_probes_or_drives_the_installed_daemon(monkeypatch, tmp_path: Path) -> None:
    import process_run
    monkeypatch.setenv("LITERATURE_BROWSER_DISABLED", "1")
    def forbidden(*args, **kwargs):
        raise AssertionError("isolated execution must not touch the user's browser")
    monkeypatch.setattr(process_run.capability, "probe_kimi", forbidden)
    channel, missing = process_run.browser_channel(process_run.ProcessRequest(run_dir=tmp_path))
    assert channel is None and missing == ["browser_disabled"]


def test_a_timed_out_browser_is_not_restarted_for_the_next_paper(monkeypatch, tmp_path: Path) -> None:
    import process_run
    calls = []
    def timeout(*args):
        calls.append(args)
        raise subprocess.TimeoutExpired("fixture", 1)
    monkeypatch.setattr(process_run, "browser", timeout)
    channel, _ = process_run.browser_channel(process_run.ProcessRequest(run_dir=tmp_path, browser_command=["fixture"]))
    assert channel("capture", "--url", "https://example.org/first")[1]["kind"] == "browser_error"
    assert channel("capture", "--url", "https://example.org/second")[1]["kind"] == "browser_error"
    assert len(calls) == 1


def test_a_paper_without_a_summary_comes_back_as_an_agent_handoff(tmp_path: Path) -> None:
    run, _ = run_with_pdf(tmp_path)
    storage = tmp_path / "Zotero"
    peer = ZoteroLibrary(storage=storage)
    with server(peer.respond) as base:
        peer.base = base
        result = process(run, "--stages", "ingest", "--api-base", base, "--storage-root", str(storage))
    assert result.returncode == 0, result.stdout + result.stderr
    body = payload(result)
    assert body["status"] == "awaiting_summaries"
    handoff = body["pending_summaries"]
    assert [entry["id"] for entry in handoff] == ["doi:10.1000/alpha"]
    assert handoff[0]["source_basis"] == "pdf"
    assert handoff[0]["source"].endswith("source.pdf")
    assert Path(handoff[0]["instructions"]).is_file()
    assert handoff[0]["template_version"] == "3"
    assert "resume_command" in body["next_action"]
    # The PDF was still written and read back while the summary is outstanding.
    assert body["papers"][0]["pdf"] is True
    assert body["papers"][0]["cloud_verified_at"]


def test_rerunning_after_the_summary_completes_without_repeating_work(tmp_path: Path) -> None:
    run, _ = run_with_pdf(tmp_path)
    storage = tmp_path / "Zotero"
    peer = ZoteroLibrary(storage=storage)
    with server(peer.respond) as base:
        peer.base = base
        first = process(run, "--stages", "ingest", "--api-base", base, "--storage-root", str(storage))
        handoff = payload(first)["pending_summaries"][0]

        body_file = tmp_path / "body.md"
        body_file.write_text("研究问题、方法、结果、关联与限制。")
        run_script("summary_artifact.py", "--content-file", str(body_file), "--output", handoff["output"],
                   "--provider", "agent-default", "--template-version", "1",
                   "--source-basis", handoff["source_basis"])
        run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", handoff["id"],
                   "--state", "summary_generated", "--artifact", "summary=" + handoff["output"])
        assert payload(first)["ingest"]["papers"]["doi:10.1000/alpha"]["attachments"]["source.pdf"]["file_action"] == "uploaded"
        creations, uploads = peer.creations, peer.uploads
        second = process(run, "--stages", "ingest", "--api-base", base, "--storage-root", str(storage))

    body = payload(second)
    assert body["ingest"]["papers"]["doi:10.1000/alpha"]["attachments"]["source.pdf"]["file_action"] == "reused"
    # The paper is written and read back; the run stays "partial" because the
    # user declined MinerU, so this paper genuinely has no Markdown.
    assert body["status"] == "partial", body
    assert body["pending_summaries"] == []
    assert body["papers"][0]["state"] == "read_back_verified"
    assert body["papers"][0]["pending"] == ["markdown_unavailable"]
    assert body["papers"][0]["summary"] is True
    assert peer.uploads == uploads
    assert peer.creations == creations + 1  # the summary note only
    assert "Paper | PDF | Markdown | Summary" in body["table"]


def test_every_artifact_present_reports_a_complete_run(tmp_path: Path) -> None:
    run, _ = run_with_pdf(tmp_path)
    markdown = run / "paper.md"
    markdown.write_text("# Derived paper\n")
    run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/alpha",
               "--state", "markdown_derived", "--artifact", "markdown=" + str(markdown))
    summary = run / "summary.md"
    summary.write_text(SUMMARY)
    run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/alpha",
               "--state", "summary_generated", "--artifact", "summary=" + str(summary))
    storage = tmp_path / "Zotero"
    peer = ZoteroLibrary(storage=storage)
    with server(peer.respond) as base:
        peer.base = base
        result = process(run, "--stages", "ingest", "--api-base", base, "--storage-root", str(storage))
    body = payload(result)
    assert body["status"] == "complete", body
    assert body["papers"][0]["complete"] is True
    assert body["papers"][0]["pending"] == []


def test_an_already_acquired_pdf_is_never_fetched_again(tmp_path: Path) -> None:
    run, source = run_with_pdf(tmp_path)
    before = source.stat().st_mtime_ns
    storage = tmp_path / "Zotero"
    peer = ZoteroLibrary(storage=storage)
    with server(peer.respond) as base:
        peer.base = base
        # The browser channel is never reached: nothing needs acquiring.
        result = process(run, "--stages", "acquire,ingest", "--api-base", base,
                         "--storage-root", str(storage))
    body = payload(result)
    assert body["acquire"] == {"attempted": [], "acquired": [], "failed": {}}
    assert source.stat().st_mtime_ns == before


def test_conversion_without_consent_is_recorded_and_never_blocks_the_pdf(tmp_path: Path) -> None:
    run, _ = run_with_pdf(tmp_path)
    storage = tmp_path / "Zotero"
    peer = ZoteroLibrary(storage=storage)
    with server(peer.respond) as base:
        peer.base = base
        result = process(run, "--stages", "convert,ingest", "--api-base", base, "--storage-root", str(storage))
    body = payload(result)
    assert body["convert"] == {"converted": [], "failed": {},
                               "skipped": {"doi:10.1000/alpha": "markdown_unavailable: no upload consent"}}
    assert body["papers"][0]["pdf"] is True
    assert "markdown_unavailable" in " ".join(body["papers"][0]["pending"])
    assert result.returncode == 0


def test_a_service_failure_is_pending_not_a_lost_run(tmp_path: Path) -> None:
    run, _ = run_with_pdf(tmp_path)
    # Nothing is listening on this port: the write channel is down.
    result = process(run, "--stages", "ingest", "--api-base", "http://127.0.0.1:1", "--retry-budget", "0.2")
    body = payload(result)
    assert result.returncode == 2
    assert body["status"] == "pending"
    assert body["ingest"]["status"] == "pending"
    assert body["papers"][0]["pdf"] is True


def test_processing_refuses_before_the_user_confirms_the_list(tmp_path: Path) -> None:
    result = run_script("workflow.py", "init", "--run-root", str(tmp_path), "--slug", "unconfirmed",
                        "--intent", "test")
    run = Path(json.loads(result.stdout)["run_dir"])
    run_script("workflow.py", "import-candidates", "--run-dir", str(run),
               "--file", str(ROOT / "tests/fixtures/normalized_candidates.json"))
    blocked = process(run, "--stages", "ingest")
    assert blocked.returncode == 2
    assert "candidate selection is not approved" in payload(blocked)["reason"]


def test_unselected_papers_are_never_processed(tmp_path: Path) -> None:
    run, _ = run_with_pdf(tmp_path)
    blocked = process(run, "--ids", "openalex:W3", "--stages", "ingest")
    assert blocked.returncode == 2
    assert "unselected papers cannot be ingested" in payload(blocked)["reason"]


def test_metadata_only_paper_is_delivered_beside_a_full_text_paper(tmp_path: Path) -> None:
    run, _ = run_with_pdf(tmp_path)
    summary = run / "summary.md"
    summary.write_text(SUMMARY)
    run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/alpha",
               "--state", "summary_generated", "--artifact", "summary=" + str(summary))
    run_script("workflow.py", "approve-candidates", "--run-dir", str(run),
               "--ids", "doi:10.1000/alpha,openalex:W3")
    run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "openalex:W3",
               "--state", "metadata_only")
    storage = tmp_path / "Zotero"
    peer = ZoteroLibrary(storage=storage)
    with server(peer.respond) as base:
        peer.base = base
        result = process(run, "--stages", "ingest", "--api-base", base, "--storage-root", str(storage))
    body = payload(result)
    states = {row["id"]: row["state"] for row in body["papers"]}
    assert states["doi:10.1000/alpha"] == "read_back_verified"
    assert states["openalex:W3"] == "metadata_only"
    assert body["status"] == "partial"
    assert "no full text" in " ".join(dict(zip(states, body["papers"]))["openalex:W3"]["pending"])


def test_split_pass_carries_collection_and_storage_into_executable_handoff(tmp_path: Path) -> None:
    import process_run
    import shlex
    run, _ = run_with_pdf(tmp_path)
    markdown = run / 'paper.md'
    markdown.write_text('Verified full text.')
    run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha',
               '--state', 'markdown_derived', '--artifact', 'markdown=' + str(markdown))
    storage = tmp_path / 'storage with spaces'
    peer = ZoteroLibrary(storage=storage)
    def respond(method, path, body, headers):
        if method == 'GET' and '/collections/' in path:
            key = path.rsplit('/', 1)[1]
            item = peer.items.get('collection:' + key)
            return (200, item, {}) if item else (404, {}, {})
        return peer.respond(method, path, body, headers)
    with server(respond) as base:
        peer.base = base
        first = process_run.process(process_run.ProcessRequest(
            run_dir=run, stages=['convert'], collection_name="Reading ' batch",
            storage_root=storage, api_base=base, retry_budget=5))
        assert peer.requests == []
        command = first['resume_command']
        assert shlex.split(first['resume_shell']) == command
        resumed = process_run.ProcessRequest.from_args(process_run.build_parser().parse_args(command[2:]))
        assert resumed.stages == ['ingest']
        assert resumed.collection_name == "Reading ' batch"
        assert resumed.ids == ['doi:10.1000/alpha']
        assert resumed.storage_root == storage
        summary = Path(first['pending_summaries'][0]['output'])
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text(SUMMARY)
        run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha',
                   '--state', 'summary_generated', '--artifact', 'summary=' + str(summary))
        env = {**os.environ, 'ZOTERO_API_KEY': 'test-secret', 'ZOTERO_LIBRARY_ID': '123',
               'ZOTERO_LIBRARY_TYPE': 'user'}
        result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert payload(result)['status'] == 'complete'
    collection = peer.items['collection:' + payload(result)['collection']]
    assert collection['data']['name'] == "Reading ' batch"
