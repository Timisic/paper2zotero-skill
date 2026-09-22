#!/usr/bin/env python3
"""Render the one screened candidate list the user confirms against.

The table is a reading list, not a taxonomy: a candidate needs a screening
sentence and a source, and nothing forces it into a `core`/`expansion` slot or
pads the list to a target length. A short list stays short and says so.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# 10-15 papers is one readable list. It is a ceiling on the default view, not a
# quota: fewer reliable candidates are returned as they are.
DEFAULT_LIST_BUDGET = 15


def cell(value: Any) -> str:
    if value is None or value == "":
        return "Unknown"
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def citation_cell(candidate: dict[str, Any]) -> str:
    count = candidate.get("cited_by_count")
    source = candidate.get("citation_source")
    timestamp = candidate.get("citation_observed_at")
    if count is None:
        return "Unknown"
    date = str(timestamp or "unknown date").split("T", 1)[0]
    return f"{count} ({source or 'unknown source'}, observed {date})"


def venue_cell(candidate: dict[str, Any]) -> str:
    year, venue = candidate.get("year"), candidate.get("venue")
    if not year and not venue:
        return "Unknown"
    return " / ".join(cell(value) for value in (year, venue) if value)


def source_cell(candidate: dict[str, Any]) -> str:
    doi = candidate.get("doi") or (candidate["id"].removeprefix("doi:") if str(candidate.get("id", "")).startswith("doi:") else None)
    return cell(f"https://doi.org/{doi}" if doi
                else candidate.get("landing_page_url") or candidate.get("oa_pdf_url") or candidate.get("openalex_id"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-rows", type=int, default=DEFAULT_LIST_BUDGET,
                        help="raise only when the user asks for a longer list")
    args = parser.parse_args()

    candidates = json.loads(Path(args.input).read_text(encoding="utf-8"))
    incomplete = [candidate.get("id", "unknown") for candidate in candidates if not candidate.get("hit_reason")]
    if incomplete:
        print("candidate screening is incomplete: " + ", ".join(incomplete), file=sys.stderr)
        raise SystemExit(2)
    if len(candidates) > args.max_rows:
        print(f"candidate table exceeds the {args.max_rows}-row list budget", file=sys.stderr)
        raise SystemExit(2)
    labelled = any(candidate.get("candidate_set") in {"core", "expansion"} for candidate in candidates)
    columns = ["ID", "Paper", "Year / venue", "Why relevant", "Citations", "Source"] + (["Set"] if labelled else [])
    lines = [" | ".join(columns), " | ".join(["---"] * len(columns))]
    for candidate in candidates:
        row = [
            cell(candidate.get("id")),
            cell(candidate.get("title")),
            venue_cell(candidate),
            cell(candidate.get("hit_reason")),
            citation_cell(candidate),
            source_cell(candidate),
        ]
        if labelled:
            row.append(cell(candidate.get("candidate_set")))
        lines.append(" | ".join(row))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "rows": len(candidates),
        "output": str(output.resolve()),
        # A list under the default length is a coverage fact to report, not a
        # gap to fill with weaker papers.
        "below_default_list": len(candidates) < min(10, args.max_rows),
    }))


if __name__ == "__main__":
    main()
