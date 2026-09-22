"""paper_artifacts: identity verification must survive a bare machine.

`pdftotext` is not installed by default anywhere, so the interesting cases
are the ones where it is missing: a PDF the builtin reader can read, a PDF it
cannot, and the difference between "wrong paper" and "unreadable file".
"""

from __future__ import annotations

import importlib.util
import zlib
from pathlib import Path

import pytest

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


def pdf_with_text(body: str) -> bytes:
    """A minimal PDF whose single Flate content stream draws `body`."""
    escaped = body.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    stream = zlib.compress(f"BT ({escaped}) Tj ET".encode("latin-1"))
    return b"%PDF-1.7\n1 0 obj\n<< >>\nstream\n" + stream + b"\nendstream\nendobj\n%%EOF\n"


def pdf_with_glyph_indices() -> bytes:
    """What a CID-subset producer (Elsevier) hands out: glyph ids, not text."""
    glyphs = "".join(f"\\000\\{index:03o}" for index in range(1, 200))
    stream = zlib.compress(f"BT ({glyphs}) Tj ET".encode("latin-1"))
    return b"%PDF-1.7\n1 0 obj\n<< >>\nstream\n" + stream + b"\nendstream\nendobj\n%%EOF\n"


@pytest.fixture()
def no_poppler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MODULE, "poppler_text", lambda _pdf: "")


# ── the bare-machine path ──────────────────────────────────────────────────

def test_a_readable_pdf_verifies_without_poppler(tmp_path: Path, no_poppler: None) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(pdf_with_text(PROSE))
    payload, code = MODULE.verify(pdf, "Evaluating the Quality of Psychotherapy Conversational Agents", "10.2196/65605")
    assert payload["status"] == "verified"
    assert payload["extractor"] == "builtin"
    assert code == 0


def test_an_unreadable_pdf_is_unverified_never_rejected(tmp_path: Path, no_poppler: None) -> None:
    """The Elsevier case: refusing to read a file is not evidence against it."""
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(pdf_with_glyph_indices())
    payload, code = MODULE.verify(pdf, "Some Real Paper Title About Agents", "10.1016/j.chbr.2024.100401")
    assert payload["status"] == "unverified"
    assert payload["extractor"] == "none"
    assert "poppler" in str(payload["remediation"])
    assert code == 3


def test_an_unverified_pdf_still_reports_its_hash(tmp_path: Path, no_poppler: None) -> None:
    """The file is kept, so the caller still needs its identity on disk."""
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(pdf_with_glyph_indices())
    payload, _ = MODULE.verify(pdf, "Title", "10.1/x")
    assert len(str(payload["sha256"])) == 64
    assert payload["bytes"] > 0


def test_readable_text_naming_another_paper_is_still_rejected(tmp_path: Path, no_poppler: None) -> None:
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


# ── extractor choice ───────────────────────────────────────────────────────

def test_poppler_is_trusted_even_when_the_document_is_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A one-page PDF is legitimately short; that is not a reason to doubt it."""
    monkeypatch.setattr(MODULE, "poppler_text", lambda _pdf: "Zotero MCP Write Probe page one")
    pdf = tmp_path / "short.pdf"
    pdf.write_bytes(pdf_with_text("irrelevant"))
    assert MODULE.extract_text(pdf) == ("Zotero MCP Write Probe page one", "pdftotext")


def test_a_scanned_pdf_falls_through_to_no_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MODULE, "poppler_text", lambda _pdf: "\n\f\n")
    pdf = tmp_path / "scan.pdf"
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


def test_glyph_noise_is_not_mistaken_for_prose() -> None:
    assert MODULE.readable("\x00\x04\x00\x11" * 400) is False
    assert MODULE.readable(PROSE) is True


def test_prose_without_common_words_is_not_trusted() -> None:
    assert MODULE.readable("qxz " * 300) is False


def test_text_operators_are_read_and_other_streams_ignored() -> None:
    pdf = pdf_with_text("hello world")
    assert "hello world" in " ".join(MODULE.pdf_strings(pdf))
    fonts_only = b"%PDF-1.7\nstream\n" + zlib.compress(b"(never drawn)") + b"\nendstream\n"
    assert MODULE.pdf_strings(fonts_only) == []
