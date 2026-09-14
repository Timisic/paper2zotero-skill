"""The whole machine-executable chain in one invocation.

Confirmed selection → acquire → identity-verify → convert → write → read back
→ summary handoff → re-run → complete. Only the two agent judgements are
outside it: understanding the request, and writing each summary. Everything
else runs its real code against scripted peers.

This is the shape a live run takes, and the gap that let a MinerU failure
strand a real run undetected.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from http_fixture import server
from mineru_peer import MineruService
from test_acquisition import PROBE, PROBE_TITLE, scripted
from test_cli import ROOT, run_script
from test_process_run import payload, process
from test_workflow_resume import selected_run
from zotero_peer import ZoteroLibrary


def variant_pdf(tmp_path: Path) -> Path:
    """A second, distinct source PDF that still identifies as the same title.

    Distinct bytes matter: MinerU parses identical content once, and the two
    papers must exercise two real conversions.
    """
    path = tmp_path / "variant.pdf"
    path.write_bytes(PROBE.read_bytes() + b"\n%% variant copy\n")
    return path


def confirmed_run(tmp_path: Path) -> Path:
    """Two confirmed papers with MinerU consent and no artifacts yet."""
    run = selected_run(tmp_path)
    candidates = json.loads((run / "candidates.json").read_text())
    # The candidate id is the identity: a `doi` field contradicting it is
    # refused by the writer, which is exactly right.
    candidates[0].update({"title": PROBE_TITLE, "doi": "10.1000/alpha",
                          "oa_pdf_url": "http://127.0.0.1:9/p0.pdf"})
    candidates[1].update({"title": PROBE_TITLE, "oa_pdf_url": "http://127.0.0.1:9/p1.pdf",
                          "authors": ["Ada Lovelace"], "year": 2024})
    candidates[1].pop("doi", None)
    (run / "candidates.json").write_text(json.dumps(candidates))
    run_script("workflow.py", "import-candidates", "--run-dir", str(run), "--file", str(run / "candidates.json"))
    run_script("workflow.py", "approve-candidates", "--run-dir", str(run),
               "--ids", "doi:10.1000/alpha,openalex:W3", "--source", "message:1", "--rule", "explicit IDs")
    run_script("workflow.py", "consent", "--run-dir", str(run), "--service", "mineru",
               "--decision", "approved", "--source", "message:1")
    return run


def write_summaries(run: Path, handoff: list[dict]) -> None:
    """Stand in for the agent: one summary per paper, from its own source."""
    for entry in handoff:
        body = run / f"body-{entry['id'].replace('/', '-')}.md"
        body.write_text(f"研究问题、方法、结果、关联与限制（{entry['id']}）。", encoding="utf-8")
        run_script("summary_artifact.py", "--content-file", str(body), "--output", entry["output"],
                   "--provider", "test-agent", "--template-version", "1",
                   "--source-basis", entry["source_basis"])
        run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", entry["id"],
                   "--state", "summary_generated", "--artifact", "summary=" + entry["output"])


@pytest.mark.parametrize('deep_directory,attachment_directory', [(False, False), (True, False), (False, True)],
                         ids=['ordinary-path', 'deep-path', 'storage-directory'])
def test_one_invocation_carries_a_confirmed_selection_to_read_back(
        tmp_path: Path, deep_directory: bool, attachment_directory: bool) -> None:
    if deep_directory:
        # A normal Documents/project layout can exceed MAX_PATH only after
        # the selection hash, conversion assets or summary filename is added.
        tmp_path = tmp_path / ('project-' + 'a' * max(12, 185 - len(str(tmp_path))))
        tmp_path.mkdir()
    run = confirmed_run(tmp_path)
    storage = tmp_path / "Zotero"
    zotero, mineru = ZoteroLibrary(storage=storage), MineruService()
    browser = scripted(tmp_path, {
        "capture": {
            "http://127.0.0.1:9/p0.pdf": {"result": "captured", "source": str(PROBE)},
            "http://127.0.0.1:9/p1.pdf": {"result": "captured", "source": str(variant_pdf(tmp_path))},
        },
    })
    env = {"MINERU_TOKEN": "test-token"}
    with server(zotero.respond) as zotero_base, server(mineru.respond) as mineru_base:
        zotero.base, mineru.base = zotero_base, mineru_base
        common = ["--api-base", zotero_base, "--mineru-api-base", mineru_base,
                  "--storage-root", str(storage / 'storage' if attachment_directory else storage), *browser]
        first = process(run, "--stages", "acquire,convert,ingest", *common, env=env)
        body = payload(first)
        assert body["status"] == "awaiting_summaries", body
        assert body["acquire"]["acquired"] == ["doi:10.1000/alpha", "openalex:W3"]
        assert set(body["convert"]["converted"]) == {"doi:10.1000/alpha", "openalex:W3"}
        for row in body["papers"]:
            assert (row["pdf"], row["markdown"], row["summary"]) == (True, True, False)
            assert row["cloud_verified_at"], "the PDF and Markdown are written before any summary exists"

        write_summaries(run, body["pending_summaries"])
        second = process(run, "--stages", "acquire,convert,ingest", *common, env=env)

    final = payload(second)
    assert final["status"] == "complete", final
    assert all(row["complete"] for row in final["papers"])
    # Nothing was re-fetched or re-converted on the second pass.
    assert final["acquire"] == {"attempted": [], "acquired": [], "failed": {}}
    assert final["convert"]["converted"] == []
    assert len(mineru.submissions) == 1
    # One parent, one PDF, one Markdown and one summary note per paper.
    parents = [item for item in zotero.items.values()
               if item["data"].get("itemType") not in ("attachment", "note")]
    assert len(parents) == 2
    for parent in parents:
        kinds = [child["data"]["itemType"] for child in zotero.children(parent["key"])]
        assert sorted(kinds) == ["attachment", "attachment", "note"]
    assert len(zotero.files) == 4  # two PDFs, two Markdown files


def test_a_conversion_failure_still_delivers_the_pdf(tmp_path: Path) -> None:
    """Markdown fails for every paper; the PDFs are written regardless."""
    run = confirmed_run(tmp_path)
    storage = tmp_path / "Zotero"
    zotero, mineru = ZoteroLibrary(storage=storage), MineruService(fail_all=True)
    browser = scripted(tmp_path, {
        "capture": {
            "http://127.0.0.1:9/p0.pdf": {"result": "captured", "source": str(PROBE)},
            "http://127.0.0.1:9/p1.pdf": {"result": "captured", "source": str(variant_pdf(tmp_path))},
        },
    })
    env = {"MINERU_TOKEN": "test-token"}
    with server(zotero.respond) as zotero_base, server(mineru.respond) as mineru_base:
        zotero.base, mineru.base = zotero_base, mineru_base
        body = payload(process(run, "--stages", "acquire,convert,ingest",
                               "--api-base", zotero_base, "--mineru-api-base", mineru_base,
                               "--storage-root", str(storage), *browser, env=env))
    assert body["convert"]["converted"] == []
    assert set(body["convert"]["failed"]) == {"doi:10.1000/alpha", "openalex:W3"}
    assert body["status"] == "awaiting_summaries"
    for row in body["papers"]:
        assert (row["pdf"], row["markdown"]) == (True, False)
        assert row["cloud_verified_at"], "a failed conversion must not hold back the PDF"
    # The full text is still readable, so the summary is offered from the PDF.
    assert {entry["source_basis"] for entry in body["pending_summaries"]} == {"pdf"}


def test_a_lost_mineru_submission_does_not_strand_the_chain(tmp_path: Path) -> None:
    """The live failure: the batch POST got no answer and every retry refused.

    Nothing was uploaded, so nothing exists at MinerU to collide with; the run
    must reconcile and carry on rather than needing its files hand-edited.
    """
    run = confirmed_run(tmp_path)
    storage = tmp_path / "Zotero"
    zotero = ZoteroLibrary(storage=storage)
    mineru = MineruService(lose_first_submission=True)
    browser = scripted(tmp_path, {
        "capture": {
            "http://127.0.0.1:9/p0.pdf": {"result": "captured", "source": str(PROBE)},
            "http://127.0.0.1:9/p1.pdf": {"result": "captured", "source": str(variant_pdf(tmp_path))},
        },
    })
    env = {"MINERU_TOKEN": "test-token"}
    with server(zotero.respond) as zotero_base, server(mineru.respond) as mineru_base:
        zotero.base, mineru.base = zotero_base, mineru_base
        common = ["--api-base", zotero_base, "--mineru-api-base", mineru_base,
                  "--storage-root", str(storage), "--retry-budget", "1", *browser]
        stranded = payload(process(run, "--stages", "acquire,convert,ingest", *common, env=env))
        assert stranded["convert"]["converted"] == []
        # The PDFs were still acquired and written while conversion failed.
        assert all(row["pdf"] for row in stranded["papers"])

        recovered = payload(process(run, "--stages", "convert,ingest", *common, env=env))

    assert set(recovered["convert"]["converted"]) == {"doi:10.1000/alpha", "openalex:W3"}
    assert all(row["markdown"] for row in recovered["papers"])
    assert len(mineru.submissions) == 2, "one lost, one that took"
    journal = json.loads(next(run.glob("mineru-*.json")).read_text())
    assert journal["reconciliations"][0]["action"] == "resubmitted as a new batch"
