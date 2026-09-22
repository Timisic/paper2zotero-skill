#!/usr/bin/env python3
"""Look up whether a DOI has a corresponding arXiv preprint.

CS/AI papers commonly appear as preprints first; the acquisition flow should
prefer the arXiv PDF when present (recorded as a preprint, not the version of
record). This helper answers that question without a browser by querying the
arXiv Atom API by DOI, falling back to title-token matching when the arXiv
metadata does not list the DOI.

A title match is a lead, never proof — two papers can share eight words — so
the entry's authors and published year come back with it and the caller is
expected to check them before treating the preprint as this paper.

Output (one JSON line):
  {"found": bool, "arxiv_id": "...", "title": "...", "abs_url": "...",
   "pdf_url": "...", "match": "doi" | "title", "authors": [...],
   "published_year": int | None}
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

ATOM_NS = {"a": "http://www.w3.org/2005/Atom", "ar": "http://arxiv.org/schemas/atom"}
API = "https://export.arxiv.org/api/query"


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2}


def entry_authors(entry: Any) -> list[str]:
    return [name.strip() for name in
            (element.findtext("a:name", "", ATOM_NS) for element in entry.findall("a:author", ATOM_NS))
            if name and name.strip()]


def entry_year(entry: Any) -> int | None:
    published = (entry.findtext("a:published", "", ATOM_NS) or "").strip()
    match = re.match(r"(\d{4})", published)
    return int(match.group(1)) if match else None


def parse_atom(xml_text: str, doi: str, title: str | None = None) -> dict[str, Any]:
    """Parse an arXiv Atom feed into the best matching entry (pure function)."""
    root = ET.fromstring(xml_text)
    expected_doi = (doi or "").strip().lower()
    title_tokens = _tokens(title) if title else set()
    best: dict[str, Any] | None = None
    for entry in root.findall("a:entry", ATOM_NS):
        entry_doi = (entry.findtext("ar:doi", "", ATOM_NS) or "").strip().lower()
        entry_title = re.sub(r"\s+", " ", (entry.findtext("a:title", "", ATOM_NS) or "")).strip()
        abs_url = (entry.findtext("a:id", "", ATOM_NS) or "").strip()
        arxiv_id = ""
        match = re.search(r"/abs/([^/?#]+)", abs_url)
        if match:
            arxiv_id = match.group(1)
        if not arxiv_id:
            continue
        if entry_doi and expected_doi and entry_doi == expected_doi:
            best = {
                "found": True,
                "arxiv_id": arxiv_id,
                "title": entry_title,
                "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                "match": "doi",
                "authors": entry_authors(entry),
                "published_year": entry_year(entry),
            }
            break
        overlap = 0.0
        if title_tokens and entry_title:
            tokens = _tokens(entry_title)
            if tokens:
                overlap = len(title_tokens & tokens) / len(title_tokens)
        if overlap >= 0.6 and best is None:
            best = {
                "found": True,
                "arxiv_id": arxiv_id,
                "title": entry_title,
                "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                "match": "title",
                "title_overlap": round(overlap, 3),
                "authors": entry_authors(entry),
                "published_year": entry_year(entry),
            }
    if best is None:
        return {"found": False, "match": None}
    return best


def fetch(query: str) -> str:
    url = f"{API}?{query}"
    openers = (urllib.request.build_opener(), urllib.request.build_opener(urllib.request.ProxyHandler({})))
    last_error: Exception | None = None
    for opener in openers:
        try:
            with opener.open(url, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"arXiv API request failed: {last_error}")


def doi_query(doi: str) -> str:
    return urllib.parse.urlencode({"search_query": f'doi:"{doi}"', "max_results": 10})


def title_query(title: str) -> str:
    tokens = sorted(_tokens(title))[:8]
    if not tokens:
        return urllib.parse.urlencode({"search_query": 'all:electron', "max_results": 1})
    expression = " AND ".join(f'all:{token}' for token in tokens)
    return urllib.parse.urlencode({"search_query": expression, "max_results": 10})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doi", required=True)
    parser.add_argument("--title", help="needed when arXiv metadata does not list the DOI")
    args = parser.parse_args(argv)
    try:
        xml_text = fetch(doi_query(args.doi))
        payload = parse_atom(xml_text, args.doi, args.title)
        if not payload.get("found") and args.title:
            xml_text = fetch(title_query(args.title))
            payload = parse_atom(xml_text, args.doi, args.title)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"found": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
