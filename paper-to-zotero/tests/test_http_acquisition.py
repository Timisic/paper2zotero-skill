"""HTTP first: a known open PDF is fetched without opening a browser.

The whole point of the change these cover is that the common case — an open
access PDF whose URL is already in the candidate record — costs one HTTPS GET
and needs no daemon, no extension and no live tab. So the browser here is a
program that records being called and then fails: if it ever runs, the test
has caught the old behaviour.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

from http_fixture import server
from test_cli import ROOT, run_script
from test_process_run import payload, process
from test_workflow_resume import selected_run

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import acquire  # noqa: E402
from sources import Sources  # noqa: E402

PROBE = ROOT / "tests/fixtures/probe.pdf"
PROBE_TITLE = "Zotero MCP Write Probe"
ALPHA = "doi:10.1000/alpha"
DOI = "10.1000/alpha"


def refusing_browser(tmp_path: Path) -> tuple[list[str], Path]:
    """A browser adapter that records being called, then fails.

    Its marker file is the assertion: an HTTP-acquirable paper must finish
    without this program ever starting.
    """
    marker = tmp_path / "browser-was-called"
    program = tmp_path / "recording_browser.py"
    program.write_text(
        "import json, pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text(' '.join(sys.argv[1:]))\n"
        "print(json.dumps({'status': 'failed', 'kind': 'error', 'reason': 'browser refused'}))\n"
        "raise SystemExit(2)\n",
        encoding="utf-8",
    )
    tokens = [sys.executable, str(program)]
    return [flag for token in tokens for flag in ("--browser-command", token)], marker


def serving(files: dict[str, bytes], seen: list | None = None):
    def respond(method, path, body, headers):
        if seen is not None:
            seen.append(path)
        route = path.split("?", 1)[0]
        if route in files:
            return (200, files[route], {"Content-Type": "application/pdf"})
        if route.startswith("/json/"):
            return (200, json.loads(files[route + ".json"]), {})
        return (404, {"error": "not here"}, {})
    return respond


def run_with_link(tmp_path: Path, url: str, *, title: str = PROBE_TITLE,
                  landing: str | None = None) -> Path:
    """A confirmed paper whose open PDF link is `url`."""
    run = selected_run(tmp_path)
    candidates = json.loads((run / "candidates.json").read_text())
    candidates[0].update({"title": title, "doi": DOI, "oa_pdf_url": url,
                          "landing_page_url": landing})
    (run / "candidates.json").write_text(json.dumps(candidates))
    return run


# ── The common case ────────────────────────────────────────────────────────

def test_a_known_open_pdf_is_fetched_without_the_browser(tmp_path: Path) -> None:
    browser, marker = refusing_browser(tmp_path)
    with server(serving({"/alpha.pdf": PROBE.read_bytes()})) as base:
        run = run_with_link(tmp_path, base + "/alpha.pdf")
        body = payload(process(run, "--stages", "acquire", "--no-source-lookup", *browser))

    assert body["acquire"]["acquired"] == [ALPHA]
    assert not marker.exists(), "the browser was opened for a plain HTTP download"
    status = json.loads(run_script("workflow.py", "status", "--run-dir", str(run)).stdout)
    paper = status["papers"][ALPHA]
    assert paper["state"] == "pdf_acquired"
    assert Path(paper["artifacts"]["pdf"]).read_bytes() == PROBE.read_bytes()

    trail = json.loads((run / "papers" / "doi-10.1000-alpha" / "acquisition.json").read_text())[-1]
    assert trail["ok"] is True and trail["channel"] == "http"
    assert trail["verification"] == "verified"
    assert trail["sha256"] and trail["bytes"] == PROBE.stat().st_size
    assert [entry["channel"] for entry in trail["attempts"]] == ["http"]


def test_a_paper_is_acquired_with_no_browser_channel_at_all(tmp_path: Path) -> None:
    """Kimi being absent removes a route; it does not stop an HTTP paper."""
    with server(serving({"/alpha.pdf": PROBE.read_bytes()})) as base:
        candidate = {"id": ALPHA, "doi": DOI, "title": PROBE_TITLE,
                     "oa_pdf_url": base + "/alpha.pdf"}
        result = acquire.acquire(acquire.AcquireRequest(
            candidate=candidate, output=tmp_path / "source.pdf", browser=None, lookup=False))
    assert result["ok"] is True and result["channel"] == "http"
    assert (tmp_path / "source.pdf").read_bytes() == PROBE.read_bytes()


def test_the_browser_is_reached_only_after_http_has_failed(tmp_path: Path) -> None:
    browser, marker = refusing_browser(tmp_path)
    run = run_with_link(tmp_path, "http://127.0.0.1:9/alpha.pdf")
    body = payload(process(run, "--stages", "acquire", "--no-source-lookup", *browser))
    assert list(body["acquire"]["failed"]) == [ALPHA]
    assert marker.exists()
    assert "--url" in marker.read_text()


# ── What must never be accepted ────────────────────────────────────────────

def test_an_html_page_served_as_a_pdf_is_not_a_source_pdf(tmp_path: Path) -> None:
    page = b"<html><head><title>Sign in</title></head><body>Please log in</body></html>"
    with server(serving({"/alpha.pdf": page})) as base:
        run = run_with_link(tmp_path, base + "/alpha.pdf")
        body = payload(process(run, "--stages", "acquire", "--no-source-lookup"))
    assert list(body["acquire"]["failed"]) == [ALPHA]
    assert not (run / "papers" / "doi-10.1000-alpha" / "source.pdf").exists()
    trail = json.loads((run / "papers" / "doi-10.1000-alpha" / "acquisition.json").read_text())[-1]
    assert trail["attempts"][0]["kind"] == "not_a_pdf"
    assert trail["walls"] == ["not_a_pdf"]


def test_a_challenge_page_is_named_apart_from_an_ordinary_html_page(tmp_path: Path) -> None:
    """The three acquisition walls have different fixes, so they stay apart."""
    challenge = b"<html><body>Just a moment... Checking your browser before access</body></html>"
    with server(serving({"/alpha.pdf": challenge})) as base:
        candidate = {"id": ALPHA, "doi": DOI, "title": PROBE_TITLE, "oa_pdf_url": base + "/alpha.pdf"}
        result = acquire.acquire(acquire.AcquireRequest(
            candidate=candidate, output=tmp_path / "source.pdf", browser=None, lookup=False))
    assert result["walls"] == ["challenge"]


def test_a_valid_pdf_of_the_wrong_paper_leaves_nothing_behind(tmp_path: Path) -> None:
    with server(serving({"/alpha.pdf": PROBE.read_bytes()})) as base:
        run = run_with_link(tmp_path, base + "/alpha.pdf",
                            title="Coral reef bleaching under marine heatwaves")
        body = payload(process(run, "--stages", "acquire", "--no-source-lookup"))
    assert body["acquire"]["failed"] == {ALPHA: "no verified source PDF"}
    paper_dir = run / "papers" / "doi-10.1000-alpha"
    assert not (paper_dir / "source.pdf").exists()
    assert not list(paper_dir.glob("*.part"))
    trail = json.loads((paper_dir / "acquisition.json").read_text())[-1]
    assert trail["attempts"][0]["verification"] == "rejected"
    assert trail["attempts"][0]["kind"] == "identity_mismatch"


def test_a_dropped_transfer_never_becomes_a_source_pdf(tmp_path: Path) -> None:
    """A connection that dies mid-answer leaves no artifact at all."""
    with server(lambda *args: None) as base:
        run = run_with_link(tmp_path, base + "/alpha.pdf")
        body = payload(process(run, "--stages", "acquire", "--no-source-lookup"))
    assert list(body["acquire"]["failed"]) == [ALPHA]
    paper_dir = run / "papers" / "doi-10.1000-alpha"
    assert not (paper_dir / "source.pdf").exists()
    assert not list(paper_dir.glob("*.part"))


def test_an_unreadable_pdf_is_kept_for_a_human(tmp_path: Path) -> None:
    scanned = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    with server(serving({"/alpha.pdf": scanned})) as base:
        run = run_with_link(tmp_path, base + "/alpha.pdf")
        body = payload(process(run, "--stages", "acquire", "--no-source-lookup"))
    assert body["acquire"]["failed"] == {ALPHA: "pdf_unverified"}
    status = json.loads(run_script("workflow.py", "status", "--run-dir", str(run)).stdout)
    artifacts = status["papers"][ALPHA]["artifacts"]
    assert "pdf" not in artifacts
    assert Path(artifacts["pdf_unverified"]).read_bytes() == scanned


def test_an_oversized_response_is_refused_rather_than_written(tmp_path: Path) -> None:
    with server(serving({"/alpha.pdf": b"%PDF-" + b"0" * 40_000})) as base:
        candidate = {"id": ALPHA, "doi": DOI, "title": PROBE_TITLE, "oa_pdf_url": base + "/alpha.pdf"}
        result = acquire.acquire(acquire.AcquireRequest(
            candidate=candidate, output=tmp_path / "source.pdf", browser=None, lookup=False,
            limits=acquire.Limits(max_bytes=1000)))
    assert result["ok"] is False
    assert result["trail"][0]["kind"] == "too_large"
    assert not (tmp_path / "source.pdf").exists()


def test_an_attempt_never_overwrites_an_already_verified_artifact(tmp_path: Path) -> None:
    output = tmp_path / "source.pdf"
    output.write_bytes(PROBE.read_bytes())
    wrong = b"%PDF-1.4\nfake\n%%EOF\n"
    with server(serving({"/alpha.pdf": wrong})) as base:
        candidate = {"id": ALPHA, "doi": DOI, "title": PROBE_TITLE, "oa_pdf_url": base + "/alpha.pdf"}
        acquire.acquire(acquire.AcquireRequest(candidate=candidate, output=output,
                                               browser=None, lookup=False))
    assert output.read_bytes() == PROBE.read_bytes()


def test_a_resumed_run_does_not_download_the_paper_again(tmp_path: Path) -> None:
    downloads: list = []
    with server(serving({"/alpha.pdf": PROBE.read_bytes()}, downloads)) as base:
        run = run_with_link(tmp_path, base + "/alpha.pdf")
        assert payload(process(run, "--stages", "acquire", "--no-source-lookup"))["acquire"]["acquired"] == [ALPHA]
        again = payload(process(run, "--stages", "acquire", "--no-source-lookup"))
    assert again["acquire"]["attempted"] == []
    assert len(downloads) == 1


# ── Asking where else the full text lives ──────────────────────────────────

def test_a_failed_pdf_repeated_by_one_api_does_not_hide_the_next_copy(tmp_path: Path) -> None:
    holder: dict = {}
    seen: list[str] = []
    def respond(method, path, body, headers):
        route = path.split("?", 1)[0]
        seen.append(route)
        if route == "/blocked.pdf":
            return (403, {}, {})
        if route == "/real.pdf":
            return (200, PROBE.read_bytes(), {"Content-Type": "application/pdf"})
        if route == "/v2/" + DOI:
            return (200, {"doi": DOI, "best_oa_location": {"url_for_pdf": holder["base"] + "/blocked.pdf"}}, {})
        if route.startswith("/works/doi:"):
            return (200, {"id": "https://openalex.org/W1", "locations": [{"pdf_url": holder["base"] + "/real.pdf"}]}, {})
        return (404, {}, {})
    with server(respond) as base:
        holder["base"] = base
        client = Sources(bases={name: base for name in ("unpaywall", "openalex", "semantic_scholar", "crossref", "arxiv")},
                         throttle_dir=tmp_path, browser=None, setting=lambda _: "x@example.org")
        result = acquire.acquire(acquire.AcquireRequest(
            candidate={"id": ALPHA, "doi": DOI, "title": PROBE_TITLE, "oa_pdf_url": base + "/blocked.pdf"},
            output=tmp_path / "source.pdf", client=client))
    assert result["ok"] is True, "the next API's repository copy should beat the browser fallback"
    assert seen.count("/blocked.pdf") == 1
    assert "/real.pdf" in seen

def test_a_candidate_with_no_link_is_looked_up_then_downloaded(tmp_path: Path) -> None:
    seen: list = []
    files = {"/repo/alpha.pdf": PROBE.read_bytes()}
    # The peer answers with its own address, which it only learns once it is up.
    holder: dict = {}

    def respond(method, path, body, headers):
        seen.append(path)
        route = path.split("?", 1)[0]
        if route in files:
            return (200, files[route], {"Content-Type": "application/pdf"})
        if route == "/v2/" + DOI:
            return (200, {"doi": DOI, "best_oa_location": {
                "url_for_pdf": holder["base"] + "/repo/alpha.pdf",
                "version": "publishedVersion", "host_type": "repository"}}, {})
        return (404, {"error": "not here"}, {})

    with server(respond) as base:
        holder["base"] = base
        candidate = {"id": ALPHA, "doi": DOI, "title": PROBE_TITLE}
        client = Sources(bases={name: base for name in ("unpaywall", "openalex",
                                                        "semantic_scholar", "crossref", "arxiv")},
                         throttle_dir=tmp_path, browser=None,
                         setting=lambda name: "person@example.org")
        result = acquire.acquire(acquire.AcquireRequest(
            candidate=candidate, output=tmp_path / "source.pdf", browser=None, client=client))

    assert result["ok"] is True
    assert result["source"] == "Unpaywall" and result["version"] == "published"
    assert any(entry.get("lookup") == "Unpaywall" for entry in result["trail"])
    assert "/repo/alpha.pdf" in seen


def test_pmc_official_file_avoids_the_blocked_publisher_and_browser(tmp_path: Path) -> None:
    seen: list[str] = []
    holder: dict = {}
    def respond(method, path, body, headers):
        route = path.split("?", 1)[0]
        seen.append(route)
        if route == "/blocked.pdf":
            return (403, {}, {})
        if route == "/":
            return (200, b'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><CommonPrefixes><Prefix>PMC123.2/</Prefix></CommonPrefixes></ListBucketResult>', {"Content-Type": "application/xml"})
        if route == "/metadata/PMC123.2.json":
            return (200, {"doi": DOI, "pdf_url": holder["base"] + "/official.pdf", "is_manuscript": "yes"}, {})
        if route == "/official.pdf":
            return (200, PROBE.read_bytes(), {"Content-Type": "application/pdf"})
        return (404, {}, {})
    with server(respond) as base:
        holder["base"] = base
        client = Sources(bases={"pmc": base}, throttle_dir=tmp_path, browser=None)
        result = acquire.acquire(acquire.AcquireRequest(
            candidate={"id": ALPHA, "doi": DOI, "title": PROBE_TITLE, "identifiers": {"pmcid": "PMC123"}, "oa_pdf_url": base + "/blocked.pdf"},
            output=tmp_path / "source.pdf", client=client))
    assert result["ok"] and result["channel"] == "http" and result["source"] == "PMC"
    assert result["version"] == "accepted"
    assert seen == ["/blocked.pdf", "/", "/metadata/PMC123.2.json", "/official.pdf"]


def test_an_arxiv_title_lead_that_does_not_check_out_is_not_followed(tmp_path: Path) -> None:
    """Eight shared words is a lead. Without the author it stays one."""
    feed = ("""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"
             xmlns:arxiv="http://arxiv.org/schemas/atom"><entry>
             <id>http://arxiv.org/abs/2401.00002v1</id>
             <title>Zotero MCP Write Probe</title>
             <published>2024-01-05T00:00:00Z</published>
             <author><name>Someone Else Entirely</name></author>
             </entry></feed>""").encode()

    def respond(method, path, body, headers):
        route = path.split("?", 1)[0]
        if route == "/api/query":
            return (200, feed, {"Content-Type": "application/atom+xml"})
        return (404, {"error": "not here"}, {})

    with server(respond) as base:
        candidate = {"id": ALPHA, "doi": DOI, "title": PROBE_TITLE,
                     "authors": ["Ada Lovelace"], "year": 2024}
        client = Sources(bases={name: base for name in ("unpaywall", "openalex",
                                                        "semantic_scholar", "crossref", "arxiv")},
                         throttle_dir=tmp_path, browser=None, setting=lambda name: "x@example.org")
        result = acquire.acquire(acquire.AcquireRequest(
            candidate=candidate, output=tmp_path / "source.pdf", browser=None, client=client))

    assert result["ok"] is False
    unconfirmed = [entry for entry in result["trail"] if entry.get("status") == "unconfirmed"]
    assert unconfirmed and "no shared author" in unconfirmed[0]["detail"]
    # Nothing from arxiv.org was even attempted.
    assert not any("arxiv.org" in str(entry.get("url", "")) for entry in result["trail"])


def test_a_recorded_url_never_carries_a_key_or_a_signed_token() -> None:
    """Trails and query logs are read by people; a URL is redacted first."""
    redacted = acquire.redact(
        "https://api.example.org/v2/10.1/x?email=person@example.org&api_key=secret&format=json")
    assert "secret" not in redacted and "person@example.org" not in redacted
    assert redacted.endswith("format=json")
    signed = acquire.redact("https://files.example.org/a.pdf?token=abc123&signature=deadbeef")
    assert "abc123" not in signed and "deadbeef" not in signed
    assert acquire.redact("https://user:pw@example.org/a.pdf") == "https://example.org/a.pdf"


def test_a_document_that_reprints_the_title_does_not_end_the_search(tmp_path: Path) -> None:
    """An erratum or a comment can carry a paper's whole title verbatim.

    It is kept as a fallback, never claimed — and, crucially, the remaining
    links are still tried, so the real paper on the second link still wins.
    """
    comment = (b"%PDF-1.4\n" + b"Comment on Zotero MCP Write Probe\n"
               b"https://doi.org/10.9999/comment\n" + b"the and of for with in " * 40 + b"\n%%EOF\n")
    with server(serving({"/comment.pdf": comment, "/real.pdf": PROBE.read_bytes()})) as base:
        candidate = {"id": ALPHA, "doi": DOI, "title": PROBE_TITLE,
                     "locations": [
                         {"url": base + "/comment.pdf", "kind": "pdf", "source": "OpenAlex",
                          "version": "published"},
                         {"url": base + "/real.pdf", "kind": "pdf", "source": "Unpaywall",
                          "version": "published"}]}
        result = acquire.acquire(acquire.AcquireRequest(
            candidate=candidate, output=tmp_path / "source.pdf", browser=None, lookup=False))
    assert result["ok"] is True
    assert result["source"] == "Unpaywall"
    assert (tmp_path / "source.pdf").read_bytes() == PROBE.read_bytes()


def test_an_unreadable_first_link_still_lets_a_later_link_win(tmp_path: Path) -> None:
    scanned = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    with server(serving({"/scan.pdf": scanned, "/real.pdf": PROBE.read_bytes()})) as base:
        candidate = {"id": ALPHA, "doi": DOI, "title": PROBE_TITLE,
                     "locations": [{"url": base + "/scan.pdf", "kind": "pdf", "source": "OpenAlex"},
                                   {"url": base + "/real.pdf", "kind": "pdf", "source": "arXiv"}]}
        result = acquire.acquire(acquire.AcquireRequest(
            candidate=candidate, output=tmp_path / "source.pdf", browser=None, lookup=False))
    assert result["ok"] is True
    assert (tmp_path / "source.pdf").read_bytes() == PROBE.read_bytes()


def test_a_resume_reports_the_kept_file_it_already_had(tmp_path: Path) -> None:
    """A second pass must never diagnose less than the first one did."""
    scanned = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    output = tmp_path / "source.pdf"
    output.write_bytes(scanned)
    candidate = {"id": ALPHA, "doi": DOI, "title": PROBE_TITLE,
                 "oa_pdf_url": "http://127.0.0.1:9/gone.pdf"}
    result = acquire.acquire(acquire.AcquireRequest(
        candidate=candidate, output=output, browser=None, lookup=False))
    assert result["ok"] is False
    assert result["reason"] == "pdf_unverified"
    assert result["kept"] == str(output)
    assert output.read_bytes() == scanned
