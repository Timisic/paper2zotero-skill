"""paper_artifacts: identity verification and the difference between "wrong
paper" and "unreadable file"."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from pdf_fixture import pdf_with_text, pdf_without_text

SPEC = importlib.util.spec_from_file_location(
    "paper_artifacts", Path(__file__).resolve().parent.parent / "scripts" / "paper_artifacts.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PROSE = (
    "Evaluating the Quality of Psychotherapy Conversational Agents "
    "This paper presents a framework for the evaluation of chatbots and "
    "reports the results of a cross-sectional study with a sample of four "
    "agents in the context of mental health care doi:10.2196/65605 "
) * 3


# ── verification outcomes ──────────────────────────────────────────────────

def test_a_readable_pdf_verifies(tmp_path: Path) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(pdf_with_text(PROSE))
    payload, code = MODULE.verify(pdf, "Evaluating the Quality of Psychotherapy Conversational Agents", "10.2196/65605")
    assert payload["status"] == "verified"
    assert payload["extractor"] == "pymupdf"
    assert code == 0


def test_an_unreadable_pdf_is_unverified_never_rejected(tmp_path: Path) -> None:
    """A scan: being unable to read a file is not evidence against it."""
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(pdf_without_text())
    payload, code = MODULE.verify(pdf, "Some Real Paper Title About Agents", "10.1016/j.chbr.2024.100401")
    assert payload["status"] == "unverified"
    assert payload["extractor"] == "none"
    assert "扫描件" in str(payload["remediation"])
    assert code == 3


def test_an_unverified_pdf_still_reports_its_hash(tmp_path: Path) -> None:
    """The file is kept, so the caller still needs its identity on disk."""
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(pdf_without_text())
    payload, _ = MODULE.verify(pdf, "Title", "10.1/x")
    assert len(str(payload["sha256"])) == 64
    assert payload["bytes"] > 0


def test_readable_text_naming_another_paper_is_still_rejected(tmp_path: Path) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(pdf_with_text(PROSE))
    payload, code = MODULE.verify(pdf, "Deep sea sediment cores of the Pacific basin", "10.9999/nope")
    assert payload["status"] == "rejected"
    assert code == 2


def test_a_non_pdf_is_rejected_before_any_extraction(tmp_path: Path) -> None:
    pdf = tmp_path / "login.pdf"
    pdf.write_text("<html><title>Sign in</title></html>")
    payload, code = MODULE.verify(pdf, "Anything", None)
    assert payload["status"] == "rejected"
    assert code == 2


# ── extraction ─────────────────────────────────────────────────────────────

def test_identity_reads_only_the_front_pages(tmp_path: Path) -> None:
    pdf = tmp_path / "long.pdf"
    pdf.write_bytes(pdf_with_text(*(f"page {number} words appear on this page" for number in range(5))))
    front, _ = MODULE.extract_text(pdf)
    whole, _ = MODULE.extract_text(pdf, pages=None)
    assert "page 2" in front and "page 3" not in front
    assert "page 4" in whole


def test_a_broken_pdf_yields_no_evidence(tmp_path: Path) -> None:
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"%PDF-1.7\n%%EOF\n")
    assert MODULE.extract_text(pdf) == ("", "none")


# ── pure helpers ───────────────────────────────────────────────────────────

def test_kerning_spaces_inside_words_do_not_break_matching() -> None:
    """PDF text arrives as "chatbo ts"; matching happens despaced."""
    evidence = MODULE.identity_evidence(
        "Using cognitive behavioral therapy-based chatbo ts doi 10.1177/1460458 2251396428",
        "Using cognitive behavioral therapy-based chatbots",
        "10.1177/14604582251396428",
    )
    assert evidence["doi_match"] is True
    assert evidence["title_token_overlap"] == 1.0


def test_a_doi_url_is_normalised_before_matching() -> None:
    evidence = MODULE.identity_evidence("see 10.2196/65605 here", "x", "https://doi.org/10.2196/65605")
    assert evidence["doi_match"] is True
