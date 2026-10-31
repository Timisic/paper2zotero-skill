"""scansci-pdf stays behind a fake module. No network, no Sci-Hub, no paywall."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import credentials  # noqa: E402
import discovery  # noqa: E402
import scansci_retrieval  # noqa: E402
import sources  # noqa: E402
from scansci_retrieval import (  # noqa: E402
    INSTALL_LINE,
    PIN,
    FetchHit,
    FetchMiss,
    GreyPolicy,
    NotAddressable,
    fetch_candidate,
    grey_policy,
    search,
)
from sources import Query  # noqa: E402

# Bound before the suite patch replaces scansci_retrieval.fetch_candidate.
_fetch = fetch_candidate


@pytest.fixture
def fetch(monkeypatch):
    monkeypatch.delenv(scansci_retrieval._FETCH_DISABLED_ENV, raising=False)
    return _fetch


def _install(monkeypatch, **parts):
    version = parts.pop("__version__", PIN)
    module = SimpleNamespace(__version__=version, **parts)
    monkeypatch.setitem(sys.modules, "scansci_pdf", module)
    return module


def _pdf_download(filename="paper.pdf", source="unpaywall", body=b"%PDF-1.4 ok"):
    def download(identifier, directory, **kwargs):
        path = Path(directory) / filename
        path.write_bytes(body)
        return {"success": True, "file": str(path), "source": source, "doi": identifier}

    return download


def test_search_maps_a_hit_into_a_candidate(monkeypatch) -> None:
    calls = []

    def search_papers(text, limit=None, year_from=None, year_to=None, **kwargs):
        calls.append({"text": text, "limit": limit, "year_from": year_from,
                      "year_to": year_to, "kwargs": kwargs})
        return [
            {"title": "Attention and Robots", "doi": "10.1000/scansci", "year": "2024",
             "authors": ["Ada Lovelace"], "url": "https://example.edu/paper",
             "oa_url": "https://example.edu/paper.pdf", "cited_by_count": 0,
             "abstract": "A study.", "is_oa": True},
            {"doi": "10.1000/untitled"},
        ]

    _install(monkeypatch, search_papers=search_papers)
    answer = search(Query(text="robots", from_year=2020, to_year=2024, limit=5), budget=10)
    assert answer.status == "ok"
    assert len(answer.records) == 1
    assert calls[0]["kwargs"] == {}
    assert calls[0]["text"] == "robots"
    record = answer.records[0]
    assert record["cited_by_count"] == 0
    assert record["landing_page_url"] == "https://example.edu/paper"
    assert record["oa_pdf_url"] == "https://example.edu/paper.pdf"
    candidate = sources.normalize("scansci", record, "2026-01-01T00:00:00+00:00")
    assert candidate["title"] == "Attention and Robots"
    assert candidate["doi"] == "10.1000/scansci"
    assert candidate["landing_page_url"] == "https://example.edu/paper"
    assert candidate["oa_pdf_url"] == "https://example.edu/paper.pdf"
    assert candidate["hit_reason"] is None
    assert candidate["sources"] == ["ScanSci"]
    pdfs = [item for item in candidate["locations"] if item["kind"] == "pdf"]
    assert pdfs[0]["url"] == "https://example.edu/paper.pdf"
    assert pdfs[0]["version"] == "unknown"


def test_a_raised_library_error_is_unavailable(monkeypatch) -> None:
    def search_papers(*_args, **_kwargs):
        raise RuntimeError("upstream down")

    _install(monkeypatch, search_papers=search_papers)
    answer = search(Query(text="robots"), budget=10)
    assert answer.status == "unavailable"
    assert answer.records == []


def test_an_empty_list_is_empty(monkeypatch) -> None:
    _install(monkeypatch, search_papers=lambda *_args, **_kwargs: [])
    answer = search(Query(text="robots"), budget=10)
    assert answer.status == "empty"
    assert answer.records == []


def test_a_non_list_is_unavailable(monkeypatch) -> None:
    _install(monkeypatch, search_papers=lambda *_args, **_kwargs: {"results": []})
    answer = search(Query(text="robots"), budget=10)
    assert answer.status == "unavailable"
    assert answer.records == []


def test_a_missing_import_is_not_configured(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "scansci_pdf", None)
    answer = search(Query(text="robots"), budget=10)
    assert answer.status == "not_configured"
    assert INSTALL_LINE in answer.detail
    assert answer.records == []


def test_the_wrong_version_is_not_configured(monkeypatch) -> None:
    def search_papers(*_args, **_kwargs):
        raise AssertionError("search_papers must not run for the wrong version")

    _install(monkeypatch, __version__="0.0.1", search_papers=search_papers)
    answer = search(Query(text="robots"), budget=10)
    assert answer.status == "not_configured"
    assert INSTALL_LINE in answer.detail
    assert answer.status != "empty"


def test_a_spent_budget_does_not_call_the_library(monkeypatch) -> None:
    def search_papers(*_args, **_kwargs):
        raise AssertionError("search_papers must not run when the budget is spent")

    _install(monkeypatch, search_papers=search_papers)
    answer = search(Query(text="robots"), budget=0)
    assert answer.status == "skipped"
    assert answer.records == []


def test_download_policy_reaches_the_library(tmp_path: Path, fetch, monkeypatch) -> None:
    seen = []

    def download(identifier, directory, **kwargs):
        seen.append(kwargs)
        path = Path(directory) / "paper.pdf"
        path.write_bytes(b"%PDF-1.4 ok")
        return {"success": True, "file": str(path), "source": "unpaywall", "doi": identifier}

    _install(monkeypatch, download=download, config=SimpleNamespace(load_config=lambda: {}))
    candidate = {"doi": "10.1000/policy", "title": "Policy"}
    grey = fetch(candidate, tmp_path / "grey", GreyPolicy.GREY)
    legal = fetch(candidate, tmp_path / "legal", GreyPolicy.LEGAL)
    assert isinstance(grey, FetchHit)
    assert isinstance(legal, FetchHit)
    assert seen[0] == {
        "strategy": "fastest",
        "scihub_enabled": True,
        "use_tor": False,
        "use_vpnsci": False,
        "bibtex": False,
        "rename": False,
    }
    assert seen[1] == {
        "strategy": "legal_only",
        "scihub_enabled": False,
        "use_tor": False,
        "use_vpnsci": False,
        "bibtex": False,
        "rename": False,
    }


def test_grey_keeps_a_scihub_file(tmp_path: Path, fetch, monkeypatch) -> None:
    _install(monkeypatch, download=_pdf_download(source="Sci-Hub"),
             config=SimpleNamespace(load_config=lambda: {}))
    result = fetch({"doi": "10.1000/grey", "title": "Grey"}, tmp_path / "stage", GreyPolicy.GREY)
    assert isinstance(result, FetchHit)
    assert result.source == "Sci-Hub"
    assert result.path.is_file()


@pytest.mark.parametrize("label", ["Sci-Hub", "local_cache"])
def test_a_grey_win_under_legal_is_not_a_hit(tmp_path: Path, fetch, monkeypatch, label: str) -> None:
    written = {}

    def download(identifier, directory, **kwargs):
        path = Path(directory) / "got.pdf"
        path.write_bytes(b"%PDF-grey")
        written["path"] = path
        return {"success": True, "file": str(path), "source": label, "doi": identifier}

    _install(monkeypatch, download=download, config=SimpleNamespace(load_config=lambda: {}))
    result = fetch({"doi": "10.1000/legal", "title": "Legal"}, tmp_path / "stage", GreyPolicy.LEGAL)
    assert not isinstance(result, FetchHit)
    assert isinstance(result, FetchMiss)
    assert result.status == "not_found"
    assert not written["path"].exists()


def test_legal_leaves_a_scihub_file_outside_staging(tmp_path: Path, fetch, monkeypatch) -> None:
    cache = tmp_path / "cache.pdf"
    cache.write_bytes(b"%PDF-scihub")

    def download(identifier, directory, **kwargs):
        return {"success": True, "file": str(cache), "source": "Sci-Hub", "doi": identifier}

    _install(monkeypatch, download=download, config=SimpleNamespace(load_config=lambda: {}))
    result = fetch({"doi": "10.1000/outside", "title": "Outside"}, tmp_path / "stage", GreyPolicy.LEGAL)
    assert isinstance(result, FetchMiss)
    assert result.status == "not_found"
    assert cache.read_bytes() == b"%PDF-scihub"


def test_a_candidate_without_doi_or_arxiv_is_not_addressable(tmp_path: Path, fetch, monkeypatch) -> None:
    called = []
    _install(monkeypatch, download=lambda *_args, **_kwargs: called.append(True))
    result = fetch({"title": "No identifiers"}, tmp_path, GreyPolicy.GREY)
    assert isinstance(result, NotAddressable)
    assert called == []


def test_browser_first_does_not_call_download(tmp_path: Path, fetch, monkeypatch) -> None:
    called = []
    config = SimpleNamespace(load_config=lambda: {"scihub_browser_first_enabled": True})
    _install(monkeypatch, download=lambda *_args, **_kwargs: called.append(True), config=config)
    result = fetch({"doi": "10.1000/browser", "title": "Browser"}, tmp_path / "stage", GreyPolicy.GREY)
    assert called == []
    assert isinstance(result, FetchMiss)
    assert result.status == "unavailable"


def test_a_stale_staging_file_cannot_satisfy_the_next_download(tmp_path: Path, fetch, monkeypatch) -> None:
    staging = tmp_path / "stage"
    staging.mkdir()
    stale = staging / "old.pdf"
    stale.write_bytes(b"%PDF-stale")

    def download(identifier, directory, **kwargs):
        return {"success": True, "file": str(Path(directory) / "old.pdf"),
                "source": "unpaywall", "doi": identifier}

    _install(monkeypatch, download=download, config=SimpleNamespace(load_config=lambda: {}))
    result = fetch({"doi": "10.1000/stale", "title": "Stale"}, staging, GreyPolicy.GREY)
    assert isinstance(result, FetchMiss)
    assert result.status == "unavailable"
    assert not stale.exists()


def test_a_cache_file_outside_staging_is_copied_and_left_in_place(tmp_path: Path, fetch, monkeypatch) -> None:
    cache = tmp_path / "cache.pdf"
    cache.write_bytes(b"%PDF-cache-bytes")

    def download(identifier, directory, **kwargs):
        return {"success": True, "file": str(cache), "source": "unpaywall", "doi": "10.1000/cache"}

    _install(monkeypatch, download=download, config=SimpleNamespace(load_config=lambda: {}))
    staging = tmp_path / "stage"
    result = fetch({"doi": "10.1000/cache", "title": "Cache"}, staging, GreyPolicy.GREY)
    assert isinstance(result, FetchHit)
    assert result.path.parent == staging
    assert result.path.read_bytes() == cache.read_bytes()
    assert cache.is_file()
    assert result.path.resolve() != cache.resolve()


def test_doi_wins_over_arxiv_and_an_arxiv_id_is_a_preprint(tmp_path: Path, fetch, monkeypatch) -> None:
    seen = []

    def download(identifier, directory, **kwargs):
        seen.append(identifier)
        path = Path(directory) / "paper.pdf"
        path.write_bytes(b"%PDF-1.4")
        source = "arxiv" if identifier == "2401.00001" else "publisher"
        return {"success": True, "file": str(path), "source": source, "doi": None}

    _install(monkeypatch, download=download, config=SimpleNamespace(load_config=lambda: {}))
    both = {"title": "Both", "doi": "10.1000/doiwins", "identifiers": {"arxiv": "2401.00001"}}
    doi_hit = fetch(both, tmp_path / "doi", GreyPolicy.GREY)
    arxiv_hit = fetch({"title": "Preprint", "identifiers": {"arxiv": "2401.00001"}},
                      tmp_path / "arxiv", GreyPolicy.GREY)
    assert seen == ["10.1000/doiwins", "2401.00001"]
    assert isinstance(doi_hit, FetchHit) and doi_hit.version == "unknown"
    assert isinstance(arxiv_hit, FetchHit) and arxiv_hit.version == "preprint"


@pytest.mark.parametrize(("raw", "expected"), [
    (None, GreyPolicy.GREY),
    ("", GreyPolicy.GREY),
    ("0", GreyPolicy.GREY),
    ("false", GreyPolicy.GREY),
    ("no", GreyPolicy.GREY),
    ("grey", GreyPolicy.GREY),
    (" TRUE ", GreyPolicy.LEGAL),
    ("1", GreyPolicy.LEGAL),
    ("yes", GreyPolicy.LEGAL),
    ("legal", GreyPolicy.LEGAL),
    ("legal_only", GreyPolicy.LEGAL),
])
def test_grey_policy_reads_the_opt_out(monkeypatch, tmp_path: Path, raw, expected) -> None:
    monkeypatch.setattr(credentials, "SKILL_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.delenv(scansci_retrieval.LEGAL_ONLY_ENV, raising=False)
    if raw is not None:
        monkeypatch.setenv(scansci_retrieval.LEGAL_ONLY_ENV, raw)
    assert grey_policy() is expected
    assert grey_policy(legal_only=True) is GreyPolicy.LEGAL


def test_an_unknown_legal_only_value_is_refused(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(credentials, "SKILL_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv(scansci_retrieval.LEGAL_ONLY_ENV, "maybe")
    with pytest.raises(ValueError):
        grey_policy()


def test_http_aliases_still_select_both_http_sources(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(credentials, "SKILL_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("SEARCH_BACKEND", "openalex+semantic_scholar")
    assert credentials.search_backend() == "http"
    assert credentials.discovery_sources_for() == ("openalex", "semantic_scholar")
    assert credentials.discovery_sources_for("scansci") == ("scansci",)
    assert {"scansci", "kimi", "openalex", "semantic_scholar"} <= credentials.known_discovery_sources()


def test_discover_asks_scansci_when_the_backend_is_unset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(credentials, "SKILL_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.delenv("SEARCH_BACKEND", raising=False)

    def fake_search(query, *, budget):
        assert budget > 0
        return sources.Answer(
            source="scansci", question="search", status="ok",
            records=[{
                "title": "From ScanSci", "doi": "10.1000/z", "year": 2024,
                "authors": ["Ada Lovelace"], "abstract": None, "cited_by_count": 1,
                "landing_page_url": "https://example.edu/p",
                "oa_pdf_url": "https://example.edu/p.pdf", "is_oa": True,
            }],
            observed_at="2026-01-01T00:00:00+00:00",
        )

    monkeypatch.setattr(scansci_retrieval, "search", fake_search)

    def boom(*_args, **_kwargs):
        raise AssertionError("HTTP search sources are not the scansci default")

    monkeypatch.setattr(discovery.Sources, "search", boom)
    output = tmp_path / "candidates.json"
    result = discovery.discover(discovery.DiscoveryRequest(
        query=Query(text="robots"), output=output))
    assert result["status"] == "ok"
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved[0]["title"] == "From ScanSci"
    assert saved[0]["doi"] == "10.1000/z"
    assert saved[0]["hit_reason"] is None


def test_the_http_client_still_rejects_scansci() -> None:
    with pytest.raises(KeyError):
        sources.Sources(browser=None, budget=0.1).search("scansci", Query(text="q"), budget=1)


def test_only_the_adapter_imports_scansci_pdf() -> None:
    root = Path(__file__).resolve().parents[1] / "scripts"
    offenders = []
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path.name == "scansci_retrieval.py":
            assert "import scansci_pdf" in text
            continue
        if "scansci_pdf" in text:
            offenders.append(path.name)
    assert offenders == []


def test_the_skill_names_the_install_line() -> None:
    text = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(encoding="utf-8")
    assert INSTALL_LINE in text
