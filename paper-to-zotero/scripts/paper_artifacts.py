#!/usr/bin/env python3
"""Verify that a downloaded PDF really is the paper it claims to be.

Text comes from PyMuPDF, which scansci-pdf already installs in the private
runtime. A scanned or image-only PDF yields no words, and "I could not read
the file" and "this is the wrong paper" are different answers, so
verification has three outcomes, not two:
  verified   - the text names this paper's DOI or title
  rejected   - the text is readable and names a *different* paper
  unverified - no readable text; the PDF is kept for a human to look at

Text extracted from a PDF carries kerning spaces inside words ("chatbo ts"),
so all matching happens on a whitespace-stripped copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


STOPWORDS = {"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"}
# A paper names itself in its opening pages; identity checks read no further.
FRONT_PAGES = 3


def title_tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2 and token not in STOPWORDS}


def despace(value: str) -> str:
    """Lowercased with all whitespace removed.

    PDF text carries kerning spaces inside words, so "chatbots" comes back as
    "chatbo ts". Matching on a despaced copy makes those invisible.
    """
    return re.sub(r"\s+", "", value).lower()


# ── Text extraction ────────────────────────────────────────────────────────

def pdf_text(source: Path | bytes, pages: int | None = FRONT_PAGES) -> str:
    """The text of the first `pages` pages, or of every page when None."""
    try:
        import pymupdf
        opened = pymupdf.open(source) if isinstance(source, Path) else pymupdf.open(stream=source, filetype="pdf")
        with opened as document:
            last = document.page_count if pages is None else min(pages, document.page_count)
            return "\n".join(page.get_text() for page in document.pages(0, last))
    except (ImportError, RuntimeError, ValueError, OSError):
        return ""


def has_words(text: str) -> bool:
    return len(re.findall(r"[A-Za-z]{3,}", text)) >= 5


def extract_text(source: Path | bytes, pages: int | None = FRONT_PAGES) -> tuple[str, str]:
    """(text, extractor); extractor is `pymupdf`, or `none` for a PDF with no words."""
    text = pdf_text(source, pages)
    return (text, "pymupdf") if has_words(text) else ("", "none")


# ── Identity ───────────────────────────────────────────────────────────────

DOI_IN_TEXT = re.compile(r"10\.\d{4,9}/[^\s\"<>,;)\]]+")
# A paper states its own DOI in the opening pages. Its reference list is full
# of *other* papers' DOIs, so a whole-document scan would flag every real
# article as a conflict.
FRONT_MATTER_CHARS = 4000
# Below this, a title carries too little to identify a paper: "Mental-LLM" is
# two common words that appear together in unrelated mental-health NLP papers.
MIN_TITLE_TOKENS = 4
# A camera-ready template that was never filled in. Preprints of conference
# papers are full of these ("https://doi.org/10.1145/XXXXXX.XXXXXX"), and a
# placeholder announces nothing — treating it as the document's declared
# identity rejects the right paper for printing an empty form field.
PLACEHOLDER_SUFFIX = re.compile(r"[xn]+(?:[.\-_][xn]+)*", re.I)
# A title this completely matched is the same work. If the document also
# declares a different DOI, that is a version difference (a preprint carrying
# its own DOI, say) — a reason to keep the file for a human, never a reason to
# call it somebody else's paper.
STRONG_TITLE_OVERLAP = 0.9


def placeholder_doi(value: str) -> bool:
    """Is this an unfilled template rather than a declared DOI? Pure."""
    _, _, suffix = value.partition("/")
    return bool(suffix) and bool(PLACEHOLDER_SUFFIX.fullmatch(suffix))


def front_matter_dois(text: str) -> set[str]:
    """DOIs printed where a paper declares its own identity."""
    found = {match.group(0).rstrip(".").lower() for match in DOI_IN_TEXT.finditer(text[:FRONT_MATTER_CHARS])}
    return {value for value in found if not placeholder_doi(value)}


def identity_evidence(text: str, expected_title: str, expected_doi: str | None) -> dict[str, object]:
    """How strongly this text says it is that paper. Pure."""
    packed = despace(text)
    normalized_doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", expected_doi or "", flags=re.I).lower()
    doi_match = bool(normalized_doi and despace(normalized_doi) in packed)
    printed = front_matter_dois(text)
    expected = title_tokens(expected_title)
    found = sum(1 for token in expected if token in packed)
    overlap = found / len(expected) if expected else 0.0
    return {
        "doi_match": doi_match,
        "title_token_overlap": round(overlap, 3),
        "title_tokens": len(expected),
        "front_matter_dois": sorted(printed),
        # The document announces a DOI and it is not the one we asked for.
        "doi_conflict": bool(normalized_doi and not doi_match and printed and normalized_doi not in printed),
    }


def judge(evidence: dict[str, object]) -> str:
    """`verified`, `rejected`, or `insufficient` — three answers, not two.

    "I cannot tell" is not "this is the wrong paper". A short title with no
    DOI evidence is thin, not damning, so the file is kept for a human rather
    than thrown away — and, just as importantly, never passed off as verified.
    """
    if evidence["doi_match"]:
        return "verified"
    tokens = evidence.get("title_tokens", 0)
    overlap = float(evidence["title_token_overlap"])  # type: ignore[arg-type]
    enough_title = isinstance(tokens, int) and tokens >= MIN_TITLE_TOKENS
    if evidence["doi_conflict"]:
        # A long title matched word for word says this is the same work even
        # though the document announces a different DOI. That is the preprint
        # / version-of-record case, so the file is kept for a human rather
        # than thrown away or passed off as the requested version.
        return "insufficient" if enough_title and overlap >= STRONG_TITLE_OVERLAP else "rejected"
    if not enough_title:
        return "insufficient"
    return "verified" if overlap >= 0.5 else "rejected"


def matches(evidence: dict[str, object]) -> bool:
    return judge(evidence) == "verified"


def verify(pdf: Path, expected_title: str, expected_doi: str | None) -> tuple[dict[str, object], int]:
    raw = pdf.read_bytes() if pdf.is_file() else b""
    if not raw.startswith(b"%PDF-"):
        return {"status": "rejected", "reason": "file is not a PDF", "path": str(pdf)}, 2
    digest = {
        "path": str(pdf.resolve()),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "source_kind": "source_pdf",
    }
    text, extractor = extract_text(pdf)
    if extractor == "none":
        # No readable text: the file may still be the right paper. Missing
        # evidence stays missing — never a rejection, never a silent pass.
        return {
            "status": "unverified",
            "reason": "no readable text could be extracted from this PDF",
            "extractor": extractor,
            "remediation": "该 PDF 没有可读文字（可能是扫描件）；请人工确认它与条目一致。",
            **digest,
        }, 3
    evidence = identity_evidence(text, expected_title, expected_doi)
    verdict = judge(evidence)
    if verdict == "rejected":
        return {
            "status": "rejected",
            "reason": ("this PDF states a different DOI" if evidence["doi_conflict"]
                       else "PDF identity could not be matched to title or DOI"),
            "extractor": extractor,
            "identity_evidence": evidence,
            "path": str(pdf),
        }, 2
    if verdict == "insufficient":
        return {
            "status": "unverified",
            "reason": "identity evidence is too thin to confirm: no DOI match and too few title words",
            "extractor": extractor,
            "identity_evidence": evidence,
            "remediation": "人工确认该 PDF 与条目一致；或补上候选的 DOI 后重试。",
            **digest,
        }, 3
    return {"status": "verified", "extractor": extractor, "identity_evidence": evidence, **digest}, 0


def command_verify(args: argparse.Namespace) -> None:
    payload, exit_code = verify(Path(args.pdf), args.title, args.doi)
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(exit_code)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--pdf", required=True)
    verify_parser.add_argument("--title", required=True)
    verify_parser.add_argument("--doi")
    verify_parser.set_defaults(func=command_verify)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
