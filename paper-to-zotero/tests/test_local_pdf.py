"""Local PDF fast path: bibliographic completion without replacing stored works."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import zlib

import pytest

from http_fixture import server
from test_cli import run_script
from test_sources import OPENALEX_WORK, sources_at
from test_workflow_resume import selected_run

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import local_pdf  # noqa: E402
import paper_artifacts  # noqa: E402


PROSE = (
    "This paper presents a framework for the evaluation of agents and "
    "reports the results of a cross-sectional study with a sample of four "
    "agents in the context of mental health care. "
) * 3

KNOWN_TITLE = "Large Language Models for Mental State Detection"


def pdf_with_text(body: str) -> bytes:
    escaped = body.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    stream = zlib.compress(f"BT ({escaped}) Tj ET".encode("latin-1"))
    return b"%PDF-1.7\n1 0 obj\n<< >>\nstream\n" + stream + b"\nendstream\nendobj\n%%EOF\n"


def document(head: str) -> bytes:
    return pdf_with_text(head.rstrip() + "\n" + PROSE)


def write_pdf(directory: Path, name: str, body: bytes) -> Path:
    path = directory / name
    path.write_bytes(body)
    return path


@pytest.fixture()
def builtin_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Poppler is installed in CI; these fixtures are for the builtin reader."""
    monkeypatch.setattr(local_pdf, "full_text", lambda _pdf: "")
    monkeypatch.setattr(paper_artifacts, "poppler_text", lambda _pdf: "")


def fresh_run(tmp_path: Path) -> Path:
    result = run_script("workflow.py", "init", "--run-root", str(tmp_path), "--slug", "local-pdf",
                        "--intent", "user supplied a PDF")
    return Path(json.loads(result.stdout)["run_dir"])


CLOUD_WARNING = "markdown_unavailable: cloud MinerU upload consent required"


class QuietLookup:
    def work(self, source: str, doi: str, *, budget: float | None = None) -> object:
        raise AssertionError(f"lookup must not run for an unreadable PDF ({source})")

    def search(self, source: str, query: object, *, budget: float | None = None) -> object:
        raise AssertionError("title search must not run for an unreadable PDF")

    def bibliographic(self, title: str, *, rows: int = 5, budget: float | None = None) -> object:
        raise AssertionError("bibliographic search must not run for an unreadable PDF")


class EmptyLookup:
    """A bibliographic client that answered and has no record."""

    def work(self, source: str, doi: str, *, budget: float | None = None) -> local_pdf.sources.Answer:
        return local_pdf.sources.Answer(source=source, question="work", status="not_found", detail="no record")

    def search(self, source: str, query: object, *, budget: float | None = None) -> local_pdf.sources.Answer:
        return local_pdf.sources.Answer(source=source, question="search", status="empty")

    def bibliographic(self, title: str, *, rows: int = 5, budget: float | None = None) -> local_pdf.sources.Answer:
        return local_pdf.sources.Answer(source="crossref", question="bibliographic", status="empty")


def test_unreadable_pdf_does_not_invent_a_candidate(tmp_path: Path) -> None:
    run = fresh_run(tmp_path)
    pdf = write_pdf(tmp_path, "scan.pdf", b"%PDF-1.4\n%%EOF\n")
    before = (run / "candidates.json").read_bytes()
    result = local_pdf.run_local_pdfs(run, [pdf], client=QuietLookup())  # type: ignore[arg-type]
    assert result["status"] == "pending"
    assert result["papers"][0]["status"] == "extraction_failed"
    assert result["papers"][0]["doi"] is None
    assert (run / "candidates.json").read_bytes() == before
    assert json.loads((run / "manifest.json").read_text())["gates"]["candidate_selection"] == "pending"
    assert not list((run / "papers").rglob("*.pdf"))
    assert not list((run / "papers").rglob("paper.md"))


def test_missing_doi_does_not_adopt_a_weak_bibliographic_hit(tmp_path: Path, builtin_extractor: None) -> None:
    run = fresh_run(tmp_path)
    pdf = write_pdf(tmp_path, "local.pdf", document("Evaluating Local Pdf Metadata Recovery"))
    unrelated = {
        "DOI": "10.9999/unrelated",
        "title": ["Quantum error correction on superconducting processors"],
        "author": [{"given": "Grace", "family": "Hopper"}],
        "issued": {"date-parts": [[2020]]},
    }
    openalex = {**OPENALEX_WORK, "title": "Superconducting processors for quantum error correction",
                "doi": "https://doi.org/10.9999/unrelated"}
    with server(lambda *args: (200, {"message": {"items": [unrelated]}}, {})) as crossref:
        with server(lambda *args: (200, {"results": [openalex]}, {})) as openalex_base:
            result = local_pdf.run_local_pdfs(
                run, [pdf], client=sources_at(tmp_path, crossref=crossref, openalex=openalex_base))
    paper = result["papers"][0]
    assert paper["metadata"] == "degraded"
    assert paper["doi"] is None
    assert str(paper["id"]).startswith("title:")
    assert "no confident bibliographic match" in paper["warning"]
    assert paper["status"] == "converted"
    assert Path(paper["markdown"]).is_file()
    stored = json.loads((run / "candidates.json").read_text())
    assert stored[0]["doi"] is None
    assert "10.9999/unrelated" not in json.dumps(stored)
    assert not json.loads((run / "manifest.json").read_text()).get("consents")


def test_missing_doi_adopts_a_confident_title_match(tmp_path: Path, builtin_extractor: None) -> None:
    run = fresh_run(tmp_path)
    pdf = write_pdf(tmp_path, "known.pdf", document(KNOWN_TITLE))
    crossref_seen: list[str] = []
    openalex_seen: list[str] = []

    def crossref_respond(method: str, path: str, body: bytes, headers: object) -> tuple[int, dict, dict]:
        crossref_seen.append(path)
        return 200, {"message": {"items": [{
            "DOI": "10.1145/3643540",
            "title": [KNOWN_TITLE],
            "author": [{"given": "Ada", "family": "Lovelace"}],
            "issued": {"date-parts": [[2024, 3, 2]]},
            "container-title": ["CHI"],
        }]}}, {}

    def openalex_respond(method: str, path: str, body: bytes, headers: object) -> tuple[int, dict, dict]:
        openalex_seen.append(path)
        return 200, {"results": [OPENALEX_WORK]}, {}

    with server(crossref_respond) as crossref:
        with server(openalex_respond) as openalex_base:
            result = local_pdf.run_local_pdfs(
                run, [pdf], collection_name="Local PDFs",
                client=sources_at(tmp_path, crossref=crossref, openalex=openalex_base))
    paper = result["papers"][0]
    assert paper["metadata"] == "enriched"
    assert paper["doi"] == "10.1145/3643540"
    assert paper["id"] == "doi:10.1145/3643540"
    assert paper["status"] == "converted"
    assert "local-text" in paper["markdown"]
    assert "not a MinerU layout parse" in Path(paper["markdown"]).read_text()
    assert any("query.bibliographic" in path for path in crossref_seen)
    assert any("search=" in path for path in openalex_seen)
    assert result["status"] == "awaiting_summaries"
    assert "Local PDFs" in result["resume_shell"]
    assert Path(result["summary_batch_file"]).is_file()
    assert not json.loads((run / "manifest.json").read_text()).get("consents")


def test_existing_candidate_is_not_overwritten(tmp_path: Path, builtin_extractor: None) -> None:
    run = selected_run(tmp_path)
    before = (run / "candidates.json").read_bytes()
    original = json.loads(before)
    pdf = write_pdf(tmp_path, "alpha.pdf", document(
        "A Different Heading That Must Not Replace The Stored Title\ndoi:10.1000/alpha"))

    class HostileLookup:
        def work(self, source: str, doi: str, *, budget: float | None = None) -> object:
            raise AssertionError("an existing DOI must not be looked up and written back")

        def search(self, source: str, query: object, *, budget: float | None = None) -> object:
            raise AssertionError("an existing DOI must not start a title search")

        def bibliographic(self, title: str, *, rows: int = 5, budget: float | None = None) -> object:
            raise AssertionError("an existing DOI must not start a bibliographic search")

    result = local_pdf.run_local_pdfs(run, [pdf], client=HostileLookup())  # type: ignore[arg-type]
    assert (run / "candidates.json").read_bytes() == before
    assert json.loads((run / "candidates.json").read_text()) == original
    paper = result["papers"][0]
    assert paper["metadata"] == "existing"
    assert paper["id"] == "doi:10.1000/alpha"
    assert paper["title"] == "Artificial intelligence interventions for mental health"
    assert paper["status"] == "converted"
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["selected_ids"] == ["doi:10.1000/alpha"]
    assert "openalex:W3" in {item["id"] for item in original}
    assert not manifest.get("consents")


def test_cloud_backend_does_not_convert_without_consent(tmp_path: Path, builtin_extractor: None) -> None:
    run = fresh_run(tmp_path)
    pdf = write_pdf(tmp_path, "cloud.pdf", document(f"{KNOWN_TITLE}\ndoi:10.1145/3643540"))
    result = local_pdf.run_local_pdfs(run, [pdf], backend="cloud", client=EmptyLookup())
    paper = result["papers"][0]
    assert paper["status"] == "consent_required"
    assert paper["markdown"] is None
    assert paper["import_status"] == "verified"
    assert paper["doi"] == "10.1145/3643540"
    assert result["status"] == "partial"
    assert "summary_batch_file" not in result
    assert not list((run / "papers").rglob("paper.md"))
    manifest = json.loads((run / "manifest.json").read_text())
    assert not manifest.get("consents")
    assert CLOUD_WARNING in manifest["papers"]["doi:10.1145/3643540"]["warnings"]


def test_local_conversion_keeps_text_beyond_the_identity_front_matter(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = fresh_run(tmp_path)
    pdf = write_pdf(tmp_path, "full.pdf", document("Evaluating Local Pdf Metadata Recovery"))
    later = "later page body " * 40
    monkeypatch.setattr(local_pdf, "full_text", lambda _pdf: "Evaluating Local Pdf Metadata Recovery\n" + PROSE + later)
    result = local_pdf.run_local_pdfs(run, [pdf], client=EmptyLookup())
    assert result["papers"][0]["status"] == "converted"
    assert later.strip() in Path(result["papers"][0]["markdown"]).read_text()


def test_cli_reports_extraction_failure(tmp_path: Path) -> None:
    run = fresh_run(tmp_path)
    pdf = write_pdf(tmp_path, "empty.pdf", b"%PDF-1.4\n%%EOF\n")
    completed = run_script("local_pdf.py", "--run-dir", str(run), "--pdf", str(pdf), check=False)
    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["status"] == "pending"
    assert payload["backend"] == "local"
    assert payload["papers"][0]["status"] == "extraction_failed"
