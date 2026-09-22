"""One question, one source, one classified answer.

These drive `sources.Sources` against a local peer, so the credential rules,
the failure classification and the cache are exercised as the real code paths
rather than described. Provider-format knowledge (`normalize`, `locations`) is
pure and tested directly.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

from http_fixture import server

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sources  # noqa: E402
from sources import Query, Sources  # noqa: E402


def test_an_api_failure_never_silently_opens_the_browser(monkeypatch, tmp_path: Path) -> None:
    import browser_pdf
    def forbidden(*args, **kwargs):
        raise AssertionError("API-only discovery must not open a browser")
    monkeypatch.setattr(browser_pdf, "fetch_text", forbidden)
    with server(lambda *args: (503, {}, {})) as base:
        client = Sources(bases={"openalex": base}, budget=0.2, attempts=1,
                         throttle_dir=tmp_path, setting=lambda _: "")
        answer = client.search("openalex", Query(text="mental health"), budget=0.2)
    assert answer.status == "unavailable"


S2_PAPER = {
    "paperId": "abc123",
    "title": "Large language models for mental state detection",
    "abstract": "We evaluate LLMs on clinical text.",
    "year": 2024,
    "publicationDate": "2024-03-01",
    "venue": "CHI",
    "publicationVenue": {"name": "CHI Conference", "type": "conference"},
    "publicationTypes": ["Conference"],
    "externalIds": {"DOI": "10.1145/3643540", "ArXiv": "2401.00001", "CorpusId": 99},
    "authors": [{"name": "Ada Lovelace"}],
    "citationCount": 42,
    "openAccessPdf": {"url": "https://oa.example.org/s2.pdf", "status": "GREEN"},
    "isOpenAccess": True,
}

OPENALEX_WORK = {
    "id": "https://openalex.org/W123",
    "doi": "https://doi.org/10.1145/3643540",
    "title": "Large Language Models for Mental State Detection",
    "publication_year": 2024,
    "publication_date": "2024-03-02",
    "type": "article",
    "language": "en",
    "cited_by_count": 40,
    "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
    "abstract_inverted_index": {"We": [0], "evaluate": [1]},
    "open_access": {"is_oa": True, "oa_status": "green"},
    "primary_location": {"landing_page_url": "https://dl.acm.org/doi/10.1145/3643540",
                         "pdf_url": None, "version": "publishedVersion",
                         "source": {"display_name": "CHI", "type": "conference"}},
    "best_oa_location": {"pdf_url": "https://oa.example.org/openalex.pdf",
                         "landing_page_url": "https://oa.example.org/abs",
                         "version": "acceptedVersion", "source": {"type": "repository"}},
}


def peer_for(payload, seen: list | None = None, status: int = 200):
    def respond(method, path, body, headers):
        if seen is not None:
            seen.append({"path": path, "x-api-key": headers.get("x-api-key")})
        return (status, payload, {})
    return respond


def sources_at(tmp_path: Path, **bases) -> Sources:
    """A Sources whose bases point at local peers and which never opens a browser."""
    return Sources(bases=bases, throttle_dir=tmp_path, browser=None,
                   setting=lambda name: {"semantic_scholar": "s2-secret",
                                         "unpaywall": "person@example.org",
                                         "crossref": "person@example.org"}.get(name, ""))


# ── Credentials reach exactly one host ─────────────────────────────────────

def test_a_key_travels_only_to_the_source_that_issued_it(tmp_path: Path) -> None:
    s2_seen: list = []
    openalex_seen: list = []
    with server(peer_for({"data": [S2_PAPER]}, s2_seen)) as s2:
        with server(peer_for({"results": [OPENALEX_WORK]}, openalex_seen)) as openalex:
            client = sources_at(tmp_path, semantic_scholar=s2, openalex=openalex)
            assert client.search("semantic_scholar", Query("llm mental health")).status == "ok"
            assert client.search("openalex", Query("llm mental health")).status == "ok"
    assert s2_seen[0]["x-api-key"] == "s2-secret"
    # OpenAlex is a different host: it sees no key at all, its own or anyone's.
    assert openalex_seen[0]["x-api-key"] is None
    assert "api_key" not in openalex_seen[0]["path"]


def test_a_url_off_the_source_base_carries_no_key(tmp_path: Path) -> None:
    """A record's own link is not the API, so it never collects the API key."""
    elsewhere: list = []
    with server(peer_for({"data": []}, elsewhere)) as publisher:
        with server(peer_for({"data": []})) as s2:
            client = sources_at(tmp_path, semantic_scholar=s2)
            params, headers = client._auth("semantic_scholar", publisher + "/paper.pdf", {})
    assert headers == {} and params == {}


# ── Saying nothing, in three different ways ────────────────────────────────

def test_a_genuine_empty_result_is_an_answer_and_is_remembered(tmp_path: Path) -> None:
    calls: list = []
    with server(peer_for({"data": []}, calls)) as s2:
        client = sources_at(tmp_path, semantic_scholar=s2)
        first = client.search("semantic_scholar", Query("nothing matches this"))
        second = client.search("semantic_scholar", Query("nothing matches this"))
    assert first.status == "empty" and first.ok
    assert second.status == "empty" and second.cached and second.requests == 0
    assert len(calls) == 1


def test_an_authentication_failure_is_never_remembered_as_no_papers(tmp_path: Path) -> None:
    calls: list = []
    with server(peer_for({"error": "unauthorized"}, calls, status=401)) as s2:
        client = sources_at(tmp_path, semantic_scholar=s2)
        first = client.search("semantic_scholar", Query("llm"))
        second = client.search("semantic_scholar", Query("llm"))
    assert first.status == "authentication_required" and not first.ok
    assert first.records == []
    # Asked again, it asks again: nothing was learned about the literature.
    assert second.status == "authentication_required" and not second.cached
    assert len(calls) == 2


def test_a_rate_limit_is_distinguishable_from_an_empty_shelf(tmp_path: Path) -> None:
    with server(lambda *args: (429, {}, {"Retry-After": "30"})) as s2:
        answer = sources_at(tmp_path, semantic_scholar=s2).search(
            "semantic_scholar", Query("llm"), budget=0.2)
    assert answer.status == "rate_limited"
    assert answer.records == []


def test_a_missing_key_is_reported_before_the_budget_is_spent(tmp_path: Path) -> None:
    with server(peer_for({"data": [S2_PAPER]})) as s2:
        client = Sources(bases={"semantic_scholar": s2}, throttle_dir=tmp_path,
                         browser=None, setting=lambda name: "")
        answer = client.search("semantic_scholar", Query("llm"))
    assert answer.status == "not_configured"
    assert answer.requests == 0


def test_a_doi_a_source_does_not_have_is_not_found_not_a_failure(tmp_path: Path) -> None:
    with server(lambda *args: (404, {"error": "not found"}, {})) as crossref:
        answer = sources_at(tmp_path, crossref=crossref).work("crossref", "10.0000/missing")
    assert answer.status == "not_found"
    assert answer.ok is False


# ── Provider formats ───────────────────────────────────────────────────────

def test_semantic_scholar_normalizes_into_a_candidate_with_its_provenance() -> None:
    candidate = sources.normalize("semantic_scholar", S2_PAPER, "2026-09-06T00:00:00+00:00")
    assert candidate["id"] == "doi:10.1145/3643540"
    assert candidate["sources"] == ["SemanticScholar"]
    assert candidate["abstract_source"] == "SemanticScholar"
    assert candidate["citations"] == [
        {"source": "SemanticScholar", "count": 42, "observed_at": "2026-09-06T00:00:00+00:00"}]
    assert candidate["identifiers"]["arxiv"] == "2401.00001"
    assert candidate["identifiers"]["semantic_scholar"] == "abc123"
    assert candidate["venue"] == "CHI Conference"
    assert candidate["hit_reason"] is None


def test_openalex_normalizes_into_the_same_shape() -> None:
    candidate = sources.normalize("openalex", OPENALEX_WORK, "2026-09-06T00:00:00+00:00")
    assert candidate["id"] == "doi:10.1145/3643540"
    assert candidate["sources"] == ["OpenAlex"]
    assert candidate["oa_pdf_url"] == "https://oa.example.org/openalex.pdf"
    assert candidate["cited_by_count"] == 40
    assert candidate["citation_source"] == "OpenAlex"
    assert candidate["abstract"] == "We evaluate"


def test_a_candidate_without_a_doi_keeps_its_own_source_identity() -> None:
    record = {**S2_PAPER, "externalIds": {"CorpusId": 7}}
    assert sources.normalize("semantic_scholar", record, "t")["id"] == "s2:abc123"


def test_locations_carry_their_source_and_version() -> None:
    found = sources.locations("openalex", OPENALEX_WORK)
    by_url = {entry["url"]: entry for entry in found}
    assert by_url["https://oa.example.org/openalex.pdf"]["version"] == "accepted"
    assert by_url["https://oa.example.org/openalex.pdf"]["kind"] == "pdf"
    assert by_url["https://dl.acm.org/doi/10.1145/3643540"]["version"] == "published"
    assert all(entry["source"] == "OpenAlex" for entry in found)


def test_unpaywall_and_crossref_locations_keep_the_version_apart() -> None:
    unpaywall = sources.locations("unpaywall", {
        "best_oa_location": {"url_for_pdf": "https://repo.example.org/a.pdf",
                             "version": "submittedVersion", "host_type": "repository"},
        "oa_locations": [{"url_for_pdf": "https://publisher.example.org/final.pdf",
                          "version": "publishedVersion", "host_type": "publisher"}],
    })
    assert {entry["url"]: entry["version"] for entry in unpaywall} == {
        "https://repo.example.org/a.pdf": "preprint",
        "https://publisher.example.org/final.pdf": "published",
    }
    crossref = sources.locations("crossref", {
        "link": [{"content-type": "application/pdf", "URL": "https://publisher.example.org/x.pdf",
                  "content-version": "vor"}],
        "resource": {"primary": {"URL": "https://publisher.example.org/x"}},
        "alternative-id": ["S0747563223001234"],
    })
    urls = [entry["url"] for entry in crossref]
    assert "https://publisher.example.org/x.pdf" in urls
    assert "https://www.sciencedirect.com/science/article/pii/S0747563223001234" in urls


def test_a_doi_org_link_is_never_offered_as_a_full_text_location() -> None:
    """doi.org is unreachable on this network and is not a copy of anything."""
    found = sources.locations("crossref", {"resource": {"primary": {"URL": "https://doi.org/10.1/x"}}})
    assert found == []


def test_arxiv_answers_from_its_atom_feed(tmp_path: Path) -> None:
    feed = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry><id>http://arxiv.org/abs/2401.00001v1</id>
        <title>Large language models for mental state detection</title>
        <arxiv:doi>10.1145/3643540</arxiv:doi></entry>
    </feed>"""
    with server(lambda *args: (200, feed.encode(), {"Content-Type": "application/atom+xml"})) as arxiv:
        answer = Sources(bases={"arxiv": arxiv}, throttle_dir=tmp_path, browser=None,
                         setting=lambda name: "").arxiv("10.1145/3643540")
    assert answer.status == "ok"
    assert answer.records[0]["match"] == "doi"
    assert answer.records[0]["arxiv_id"] == "2401.00001v1"
    assert sources.locations("arxiv", answer.records[0])[0]["version"] == "preprint"


# ── The key is paced, and never written down ───────────────────────────────

def test_the_semantic_scholar_key_is_paced_once_per_second_everywhere(tmp_path: Path) -> None:
    """One key, one queue: the documented quota covers every endpoint."""
    first = Sources(throttle_dir=tmp_path, browser=None, setting=lambda name: "k")
    second = Sources(throttle_dir=tmp_path, browser=None, setting=lambda name: "k")
    assert sources.INTERVALS["semantic_scholar"] == 1.0
    # Search, per-DOI lookup and a second command all take the same slot file.
    assert first.throttles["semantic_scholar"].path == second.throttles["semantic_scholar"].path
    assert first.throttles["semantic_scholar"].interval == 1.0
    # arXiv publishes one request per three seconds; OpenAlex is only spaced.
    assert first.throttles["arxiv"].interval == 3.0
    assert first.throttles["openalex"].path != first.throttles["semantic_scholar"].path


def test_a_failure_is_reported_without_the_url_that_carried_the_key(tmp_path: Path) -> None:
    with server(lambda *args: (401, {"error": "bad key"}, {})) as s2:
        client = sources_at(tmp_path, semantic_scholar=s2)
        answer = client.search("semantic_scholar", Query("llm"))
    report = json.dumps(answer.report())
    assert "s2-secret" not in report
    # The report names the source and what went wrong, not the request.
    assert "url" not in answer.report()
    assert answer.report()["status"] == "authentication_required"


def test_a_feed_that_is_not_xml_is_an_unavailable_source_not_a_crash(tmp_path: Path) -> None:
    """`ParseError` is a `SyntaxError`; unhandled it would end a whole batch."""
    with server(lambda *args: (200, b"<html>gateway timeout", {"Content-Type": "text/html"})) as arxiv:
        answer = Sources(bases={"arxiv": arxiv}, throttle_dir=tmp_path, browser=None,
                         setting=lambda name: "").arxiv("10.1000/x")
    assert answer.status == "unavailable"
    assert "unreadable feed" in answer.detail
