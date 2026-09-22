#!/usr/bin/env python3
"""Discover and normalize scholarly works from OpenAlex.

OpenAlex is now one discovery source among two, and the retrieval, merging and
budget logic it used to own lives in `discovery.py` with `sources.py` behind
it. This command stays because it is the documented OpenAlex entry point and
older runs and scripts call it: it is `discovery.py --sources openalex` with
this command's flag names and its single-source summary shape.

Use `discovery.py` for a cross-source list.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import discovery  # noqa: E402
import sources as source_module  # noqa: E402

SOURCE = "openalex"


def summarize(result: dict[str, Any]) -> dict[str, Any]:
    """This command's own answer shape: one source, so one set of counts."""
    summary = {
        "query": result["query"],
        "source": source_module.LABELS[SOURCE],
        "source_count": result["source_count"],
        "returned": result["returned"],
        "duplicates_removed": result["duplicates_removed"],
        "output": result["output"],
        "status": result["sources"][0]["status"] if result["sources"] else "skipped",
        "wrote_output": result["wrote_output"],
    }
    for key in ("query_log", "search"):
        if key in result:
            summary[key] = result[key]
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    discovery.add_arguments(parser)
    parser.add_argument("--per-page", type=int, default=50)
    parser.add_argument("--input-json", action="append",
                        help="Use a saved OpenAlex response instead of the network")
    args = parser.parse_args(argv)

    request = discovery.request_from_args(args, [SOURCE])
    discovery.claim_round(request)
    result = discovery.discover(request)
    if request.run_dir:
        result.setdefault("query_log", str(request.run_dir / "queries.json"))
    print(json.dumps(summarize(result), ensure_ascii=False))
    return 2 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
