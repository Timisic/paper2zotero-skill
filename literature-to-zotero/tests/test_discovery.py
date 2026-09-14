"""One list from two sources: identity, provenance, budget, partial delivery.

The merge rules are pure and tested directly. The retrieval behaviour goes
through `discovery.discover` with a `Sources` pointed at local peers, so the
budget accounting and the failure classification are the real ones.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

from http_fixture import server
from test_cli import FIXTURES, run_script

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import discovery  # noqa: E402
import sources as source_module  # noqa: E402
from discovery import DiscoveryRequest  # noqa: E402
from sources import Query, Sources  # noqa: E402


def init_run(tmp_path: Path, slug: str = "cross-source") -> Path:
    result = run_script("workflow.py", "init", "--run-root", str(tmp_path),
                        "--slug", slug, "--intent", "test")
    return Path(json.loads(result.stdout)["run_dir"])


def both_sources(run: Path, output: Path, *extra: str, check: bool = True):
    return run_script(
        "discovery.py", "--query", "AI mental health intervention",
        "--sources", "openalex,semantic_scholar",
        "--input-json", "openalex=" + str(FIXTURES / "openalex.json"),
        "--input-json", "semantic_scholar=" + str(FIXTURES / "semantic_scholar.json"),
        "--output", str(output), "--run-dir", str(run), *extra, check=check,
    )


# ── Identity across sources ────────────────────────────────────────────────

def test_one_paper_found_twice_becomes_one_candidate_with_both_accounts(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    output = tmp_path / "candidates.json"
    summary = json.loads(both_sources(run, output).stdout)
    candidates = {candidate["id"]: candidate for candidate in json.loads(output.read_text())}

    alpha = candidates["doi:10.1000/alpha"]
    assert alpha["sources"] == ["OpenAlex", "SemanticScholar"]
    # Both counts survive with their own date; neither is presented as "the" number.
    assert [entry["source"] for entry in alpha["citations"]] == ["OpenAlex", "SemanticScholar"]
    assert {entry["count"] for entry in alpha["citations"]} == {12, 19}
    assert all(entry["observed_at"] for entry in alpha["citations"])
    # A DOI written in a different case is the same DOI.
    assert alpha["identifiers"]["doi"] == "10.1000/alpha"
    assert alpha["identifiers"]["arxiv"] == "2501.00001"
    assert summary["duplicates_removed"] >= 1
    assert "doi:10.1000/gamma" in candidates


def test_the_abstract_says_which_source_wrote_it(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    output = tmp_path / "candidates.json"
    both_sources(run, output)
    candidates = {candidate["id"]: candidate for candidate in json.loads(output.read_text())}
    alpha = candidates["doi:10.1000/alpha"]
    assert alpha["abstract"] == "AI mental health interventions improved outcomes"
    assert alpha["abstract_source"] == "OpenAlex"
    assert candidates["doi:10.1000/gamma"]["abstract_source"] == "SemanticScholar"


def test_the_same_title_in_a_different_year_stays_two_candidates(tmp_path: Path) -> None:
    """Neither record has a DOI, so only a strict match may merge them."""
    run = init_run(tmp_path)
    output = tmp_path / "candidates.json"
    both_sources(run, output)
    titles = [candidate for candidate in json.loads(output.read_text())
              if candidate["title"].lower().startswith("conversational agents")]
    assert len(titles) == 2
    assert {candidate["year"] for candidate in titles} == {2024, 2019}


def test_two_sources_disagreeing_is_recorded_not_overwritten() -> None:
    first = source_module.normalize("openalex", {
        "id": "https://openalex.org/W1", "doi": "10.1/x", "title": "A study of things",
        "publication_year": 2024, "authorships": [], "primary_location": {},
    }, "t")
    second = source_module.normalize("semantic_scholar", {
        "paperId": "p1", "title": "A study of things", "year": 2023,
        "externalIds": {"DOI": "10.1/x"}, "authors": [],
    }, "t")
    merged, count = discovery.merge([[first], [second]])
    assert count == 1
    assert merged[0]["year"] == 2024
    assert merged[0]["conflicts"] == [
        {"field": "year", "kept": 2024, "reported": 2023, "source": "SemanticScholar"}]


def test_a_preprint_and_its_version_of_record_are_related_not_collapsed(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    output = tmp_path / "candidates.json"
    both_sources(run, output)
    alpha = next(candidate for candidate in json.loads(output.read_text())
                 if candidate["id"] == "doi:10.1000/alpha")
    assert {entry["version"] for entry in alpha["versions"]} >= {"preprint", "published"}
    locations = {entry["url"]: entry for entry in alpha["locations"]}
    # The arXiv id proves a preprint; the green OA link only proves a repository.
    assert locations["https://arxiv.org/pdf/2501.00001"]["version"] == "preprint"
    assert locations["https://repo.example.org/alpha-preprint.pdf"]["version"] == "unknown"
    assert locations["https://repo.example.org/alpha-preprint.pdf"]["host_type"] == "repository"


# ── Budget and partial delivery ────────────────────────────────────────────

def peer(payload, status=200):
    return lambda *args: (status, payload, {})


def test_a_failed_source_never_looks_like_an_empty_shelf(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    output = tmp_path / "candidates.json"
    with server(peer({"results": [json.loads((FIXTURES / "openalex.json").read_text())["results"][0]]})) as openalex:
        with server(peer({}, status=429)) as s2:
            client = Sources(bases={"openalex": openalex, "semantic_scholar": s2},
                             throttle_dir=tmp_path, browser=None, budget=0.3,
                             setting=lambda name: "s2-key" if name == "semantic_scholar" else "")
            result = discovery.discover(DiscoveryRequest(
                query=Query("ai mental health"), output=output, run_dir=run), client)

    statuses = {entry["source"]: entry["status"] for entry in result["sources"]}
    assert statuses["OpenAlex"] == "ok"
    assert statuses["SemanticScholar"] == "rate_limited"
    assert result["partial"] is True
    assert result["failed_sources"] == ["SemanticScholar"]
    # The usable half is delivered rather than held back.
    assert len(json.loads(output.read_text())) == 1


def test_every_round_spends_the_one_run_budget_including_its_failures(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    def delayed_failure(*args):
        # Cross the older Windows monotonic clock's ~15 ms resolution.
        time.sleep(0.03)
        return peer({}, status=500)(*args)
    with server(delayed_failure) as broken:
        client = Sources(bases={"openalex": broken}, throttle_dir=tmp_path, browser=None, budget=0.4,
                         setting=lambda name: "")
        discovery.discover(DiscoveryRequest(query=Query("q"), output=tmp_path / "a.json",
                                            sources=["openalex"], run_dir=run), client)
    spent = json.loads(run_script("workflow.py", "status", "--run-dir", str(run)).stdout)["search"]
    # A round that failed still cost the user time, and the ledger says so.
    assert spent["rounds"] == 1
    assert spent["elapsed_seconds"] > 0


def test_a_restart_continues_the_budget_instead_of_resetting_it(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    run_script("workflow.py", "record-search", "--run-dir", str(run), "--round", "initial",
               "--provider", "OpenAlex", "--query", "q", "--reason", "first round",
               "--elapsed-seconds", "400")
    output = tmp_path / "candidates.json"
    with server(peer({"results": []})) as openalex:
        client = Sources(bases={"openalex": openalex}, throttle_dir=tmp_path, browser=None,
                         setting=lambda name: "")
        result = discovery.discover(DiscoveryRequest(
            query=Query("q"), output=output, sources=["openalex"], run_dir=run,
            round="supplementary", reason="coverage"), client)
    # 400 s of a 300 s budget is already gone, so this round asks nobody —
    # and a round that asked nobody writes nothing.
    assert [entry["status"] for entry in result["sources"]] == ["skipped"]
    assert result["sources"][0]["detail"] == "retrieval budget spent"
    assert result["wrote_output"] is False
    assert not output.exists()


def test_the_supplementary_ceiling_covers_every_source(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    output = tmp_path / "candidates.json"
    assert json.loads(both_sources(run, output).stdout)["search"]["supplementary_remaining"] == 1
    second = both_sources(run, output, "--round", "supplementary", "--reason", "too few")
    assert json.loads(second.stdout)["search"]["supplementary_remaining"] == 0
    blocked = both_sources(run, output, "--round", "supplementary", "--reason", "again", check=False)
    assert blocked.returncode == 2
    assert "supplementary search budget" in blocked.stderr


def test_the_query_log_records_every_source_and_no_credentials(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    both_sources(run, tmp_path / "candidates.json")
    entry = json.loads((run / "queries.json").read_text())[0]
    assert entry["provider"] == "OpenAlex+SemanticScholar"
    assert entry["sent_fields"] == ["search", "filter", "per-page", "sort", "query", "year", "limit", "fields"]
    assert [item["source"] for item in entry["sources"]] == ["OpenAlex", "SemanticScholar"]
    assert "key" not in json.dumps(entry).lower()


def test_an_unknown_source_is_refused_before_anything_runs(tmp_path: Path) -> None:
    result = run_script("discovery.py", "--query", "q", "--sources", "scopus",
                        "--output", str(tmp_path / "out.json"), check=False)
    assert result.returncode == 2
    assert "unknown discovery source" in result.stderr


def test_an_arxiv_doi_is_a_preprint_not_a_version_of_record() -> None:
    """arXiv mints a DOI for the preprint, so that DOI proves no published version."""
    preprint = discovery.versions({"doi": "10.48550/arXiv.2309.15461",
                                   "identifiers": {"arxiv": "2309.15461"}})
    assert [entry["version"] for entry in preprint] == ["preprint"]

    published = discovery.versions({"doi": "10.1145/3643540", "identifiers": {"arxiv": "2401.00001"}})
    assert [entry["version"] for entry in published] == ["preprint", "published"]


def test_a_round_where_nobody_answered_is_not_an_empty_shelf(tmp_path: Path) -> None:
    """Zero candidates from zero answers must not read as zero papers."""
    run = init_run(tmp_path)
    output = tmp_path / "candidates.json"
    with server(peer({}, status=503)) as broken:
        client = Sources(bases={"openalex": broken, "semantic_scholar": broken},
                         throttle_dir=tmp_path, browser=None, budget=0.4,
                         setting=lambda name: "s2-key" if name == "semantic_scholar" else "")
        result = discovery.discover(DiscoveryRequest(
            query=Query("q"), output=output, run_dir=run), client)
    assert result["status"] == "failed"
    assert result["partial"] is False
    assert sorted(result["failed_sources"]) == ["OpenAlex", "SemanticScholar"]
    assert result["returned"] == 0
    assert all(entry["status"] != "empty" for entry in result["sources"])


def test_a_round_that_lost_one_source_says_partial(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    with server(peer({"results": []})) as openalex:
        with server(peer({}, status=503)) as broken:
            client = Sources(bases={"openalex": openalex, "semantic_scholar": broken},
                             throttle_dir=tmp_path, browser=None, budget=0.4,
                             setting=lambda name: "s2-key" if name == "semantic_scholar" else "")
            result = discovery.discover(DiscoveryRequest(
                query=Query("q"), output=tmp_path / "c.json", run_dir=run), client)
    assert result["status"] == "partial"
    # OpenAlex genuinely had nothing; that is an answer and is labelled as one.
    assert [entry["status"] for entry in result["sources"]] == ["empty", "unavailable"]


def test_a_round_nobody_answered_leaves_the_previous_list_alone(tmp_path: Path) -> None:
    """A network fact must never replace a candidate list with an empty one."""
    run = init_run(tmp_path)
    output = tmp_path / "candidates.json"
    both_sources(run, output)
    before = output.read_text()
    assert len(json.loads(before)) > 1

    with server(peer({}, status=503)) as broken:
        client = Sources(bases={"openalex": broken, "semantic_scholar": broken},
                         throttle_dir=tmp_path, browser=None, budget=0.4,
                         setting=lambda name: "s2-key" if name == "semantic_scholar" else "")
        result = discovery.discover(DiscoveryRequest(
            query=Query("q"), output=output, run_dir=run), client)
    assert result["status"] == "failed"
    assert result["wrote_output"] is False
    assert output.read_text() == before


def test_a_failed_round_exits_non_zero_so_a_caller_notices(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    result = run_script("discovery.py", "--query", "q", "--sources", "openalex",
                        "--output", str(tmp_path / "out.json"), "--run-dir", str(run), check=False)
    # conftest points every source at a closed port, so nobody can answer.
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "failed"
    assert not (tmp_path / "out.json").exists()


def test_a_round_is_refused_once_the_time_budget_is_spent(tmp_path: Path) -> None:
    run = init_run(tmp_path)
    run_script("workflow.py", "record-search", "--run-dir", str(run), "--round", "initial",
               "--provider", "OpenAlex", "--query", "q", "--reason", "first round",
               "--elapsed-seconds", "400")
    blocked = run_script("discovery.py", "--query", "q", "--sources", "openalex",
                         "--input-json", "openalex=" + str(FIXTURES / "openalex.json"),
                         "--output", str(tmp_path / "out.json"), "--run-dir", str(run), check=False)
    assert blocked.returncode == 2
    assert "retrieval budget is spent" in blocked.stderr
