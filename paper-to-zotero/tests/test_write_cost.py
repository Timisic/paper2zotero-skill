"""What a resume costs when nothing has changed.

Every recovery path in this skill re-runs the same command, so the price of
re-verifying an already-finished paper is paid over and over. On a slow link
it is the number of round trips that hurts, and re-downloading an attachment
only to hash bytes we already hashed hurts twice.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from http_fixture import server
from test_full_chain import confirmed_run, variant_pdf, write_summaries
from test_acquisition import PROBE, scripted
from test_process_run import payload, process
from zotero_peer import ZoteroLibrary
from mineru_peer import MineruService


@contextmanager
def finished_run(tmp_path: Path):
    """Two papers with every artifact written, read back and synced.

    Yields with the library still served, because a run is bound to the
    library URL it first wrote to — a second server on a new port is a
    different library as far as the writer is concerned, and rightly refused.
    """
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
                  "--storage-root", str(storage), *browser]
        first = process(run, "--stages", "acquire,convert,ingest", *common, env=env)
        write_summaries(run, payload(first)["pending_summaries"])
        assert payload(process(run, "--stages", "ingest", *common, env=env))["status"] == "complete"
        # Measure only the no-op pass.
        zotero.requests.clear()
        zotero.downloaded = 0
        again = process(run, "--stages", "ingest", *common, env=env)
        yield run, zotero, payload(again), zotero_base


def test_a_no_op_reverify_stays_cheap(tmp_path: Path) -> None:  # noqa: D103
    """16.5 requests per paper before this budget existed; 6.5 after.

    What is left is one read per piece of evidence — the parent still exists,
    each attachment's bytes still hash to the source, the note reads back, the
    collection membership held — plus one children listing. Going lower means
    trusting something instead of checking it.
    """
    with finished_run(tmp_path) as (_, zotero, body, _base):
        assert body["status"] == "complete", body
    counts = Counter(zotero.requests)
    per_paper = len(zotero.requests) / 2
    assert per_paper <= 7, f"{per_paper} requests per paper: {counts}"
    assert counts[("GET", "items/{key}/file")] == 4, "one download per attachment, not two"
    # Nothing changed, so nothing may be written.
    assert not [entry for entry in zotero.requests if entry[0] in ("POST", "PATCH")], counts


def test_a_no_op_reverify_downloads_each_attachment_once(tmp_path: Path) -> None:
    with finished_run(tmp_path) as (run, zotero, _body, _base):
        pass
    # Every artifact actually written, not one paper's sizes doubled: the two
    # papers' files differ, and the bound must mean what it says.
    attached = sum(path.stat().st_size for path in (run / "papers").rglob("*")
                   if path.is_file() and path.name in ("source.pdf", "paper.md"))
    assert attached > 0
    assert zotero.downloaded <= attached, (zotero.downloaded, attached)


def test_the_children_of_a_paper_are_listed_once_per_pass(tmp_path: Path) -> None:
    with finished_run(tmp_path) as (_run, zotero, _body, _base):
        pass
    listings = [entry for entry in zotero.requests if entry[1].endswith("children")]
    assert len(listings) <= 2, listings  # one per paper


def test_a_content_type_fix_survives_the_object_moving_meanwhile(tmp_path: Path) -> None:
    """The listing decides whether to write; only a fresh read may gate it.

    Downloading a multi-megabyte attachment takes long enough for Zotero
    Desktop to bump the object's version, and a precondition captured before
    that download would turn a correction into a 412 that fails the paper.
    """
    with finished_run(tmp_path) as (run, zotero, _body, base):
        attachments = [item for item in zotero.items.values()
                       if item["data"].get("itemType") == "attachment"]
        assert attachments
        for item in attachments:
            item["data"]["contentType"] = "application/octet-stream"  # needs correcting
        # The object moves while its file is being downloaded, which is the
        # whole window between the cached listing and the write below.
        zotero.bump_on_download = True
        again = process(run, "--stages", "ingest", "--api-base", base,
                        "--storage-root", str(tmp_path / "Zotero"))
    assert payload(again)["status"] == "complete", payload(again)
    assert zotero.conflicts == 0, "a stale precondition would have 412'd here"
    assert all(item["data"]["contentType"] in ("application/pdf", "text/markdown")
               for item in attachments)
