#!/usr/bin/env python3
"""Verify that a downloaded PDF really is the paper it claims to be.

Identity checking needs the PDF's text, and getting text out of a PDF is the
part that varies by machine. `pdftotext` (poppler) is the good extractor and
is installed on almost nobody's machine by default, so a skill that requires
it fails everywhere it is distributed. The fallback here is a small
stdlib-only reader: inflate the content streams, pull the strings out of the
text operators, and keep the ones that decode to real text.

The fallback cannot read every PDF — a producer that embeds subset fonts with
custom (CID) encodings hands out glyph indices, not characters, and Elsevier
does exactly that. That case is the reason `readable()` exists: unreadable
output must never be fed to the matcher, because "I could not read the file"
and "this is the wrong paper" are different answers and only one of them
means the download failed.

So verification has three outcomes, not two:
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
import shutil
import subprocess
import sys
import zlib
from pathlib import Path


STOPWORDS = {"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"}
PDF_STRING = re.compile(rb"\((?:\\.|[^\\()])*\)", re.S)
PDF_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
           b"(": b"(", b")": b")", b"\\": b"\\"}
MAX_STREAMS = 60
MAX_STREAM_SCAN = 400
# Words this common appearing this often is what separates real prose from a
# glyph-index dump that merely looks like characters.
COMMON_WORDS = (" the ", " and ", " of ", " for ", " with ", " in ")


def title_tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2 and token not in STOPWORDS}


def despace(value: str) -> str:
    """Lowercased with all whitespace removed.

    PDF text carries kerning spaces inside words, so "chatbots" comes back as
    "chatbo ts". Matching on a despaced copy makes those invisible.
    """
    return re.sub(r"\s+", "", value).lower()


# ── Text extraction ────────────────────────────────────────────────────────

def _unescape(raw: bytes) -> bytes:
    out, index = bytearray(), 0
    while index < len(raw):
        char = raw[index : index + 1]
        if char != b"\\":
            out += char
            index += 1
            continue
        following = raw[index + 1 : index + 2]
        if following in ESCAPES:
            out += ESCAPES[following]
            index += 2
        elif following in b"01234567":
            end = index + 1
            while end < len(raw) and end < index + 4 and raw[end : end + 1] in b"01234567":
                end += 1
            out += bytes([int(raw[index + 1 : end], 8) & 0xFF])
            index = end
        else:
            out += following
            index += 2
    return bytes(out)


def pdf_strings(raw: bytes) -> list[str]:
    """The literal strings of a PDF's text-drawing operators. Pure.

    Only Flate-compressed streams that actually draw text are considered;
    fonts, images and metadata are skipped rather than decoded into noise.
    """
    chunks: list[bytes] = []
    for index, match in enumerate(PDF_STREAM.finditer(raw)):
        if index > MAX_STREAM_SCAN or len(chunks) >= MAX_STREAMS:
            break
        try:
            data = zlib.decompress(match.group(1))
        except zlib.error:
            continue
        if b"Tj" not in data and b"TJ" not in data:
            continue
        chunks.append(data)
    pieces: list[str] = []
    for chunk in chunks:
        for found in PDF_STRING.finditer(chunk):
            pieces.append(_unescape(found.group(0)[1:-1]).decode("latin-1"))
    return pieces


def printable_ratio(value: str) -> float:
    if not value:
        return 0.0
    return sum(32 <= ord(c) <= 126 for c in value) / len(value)


def join_readable(pieces: list[str]) -> str:
    """Keep only the pieces that decoded to text, drop the glyph-index noise."""
    return " ".join(piece for piece in pieces if piece and printable_ratio(piece) >= 0.8)


def readable(text: str) -> bool:
    """Is this text worth showing the matcher?

    A CID-encoded PDF yields plenty of bytes that survive a printable check
    but contain no words, so the test is for actual English prose.
    """
    if len(text) < 200 or printable_ratio(text) < 0.85:
        return False
    lowered = text.lower()
    return sum(word in lowered for word in COMMON_WORDS) >= 3


def builtin_text(pdf: Path) -> str:
    try:
        return join_readable(pdf_strings(pdf.read_bytes()))
    except (OSError, ValueError):
        return ""


def extract_text_from_bytes(raw: bytes) -> tuple[str, str]:
    """(text, extractor) for a PDF still in memory.

    Only the builtin reader applies here — poppler needs a file — so a caller
    checking bytes before writing them gets `none` on a PDF this reader
    cannot decode, and must treat that as "unknown", not as a mismatch.
    """
    text = join_readable(pdf_strings(raw))
    return (text, "builtin") if readable(text) else ("", "none")


def poppler_text(pdf: Path) -> str:
    executable = shutil.which("pdftotext")
    if not executable:
        return ""
    try:
        completed = subprocess.run(
            [executable, "-enc", "UTF-8", "-f", "1", "-l", "3", str(pdf), "-"],
            text=True, encoding='utf-8', errors='replace',
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (completed.stdout or '') if completed.returncode == 0 else ""


def has_words(text: str) -> bool:
    """Any real words at all — the bar for trusting a proper extractor."""
    return len(re.findall(r"[A-Za-z]{3,}", text)) >= 5


def extract_text(pdf: Path) -> tuple[str, str]:
    """(text, extractor) — extractor is `pdftotext`, `builtin`, or `none`.

    poppler's output is trusted whenever it contains words: a short document
    is legitimately short, and gating it on prose volume would turn a valid
    one-page PDF into `unverified`. The prose gate belongs to the builtin
    reader alone, whose failure mode is confident-looking noise. A scanned
    PDF gives poppler nothing, so it falls through to the builtin reader and
    then, honestly, to no evidence at all.
    """
    text = poppler_text(pdf)
    if has_words(text):
        return text, "pdftotext"
    text = builtin_text(pdf)
    if readable(text):
        return text, "builtin"
    return "", "none"


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
            "remediation": "安装 poppler（macOS: brew install poppler；Debian/Ubuntu: apt install poppler-utils；"
            "Windows: choco install poppler）以启用自动身份校验；或人工确认该 PDF 与条目一致。",
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
