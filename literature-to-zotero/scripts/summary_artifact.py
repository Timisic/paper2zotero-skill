#!/usr/bin/env python3
"""Persist a summary-provider result with explicit provenance metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--template-version", required=True)
    parser.add_argument("--source-basis", choices=("markdown", "pdf"), required=True)
    args = parser.parse_args()

    content = Path(args.content_file).read_text(encoding="utf-8").strip()
    if not content:
        print(json.dumps({"status": "failed", "reason": "summary content is empty"}))
        raise SystemExit(2)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "# Core Summary\n\n"
        f"- provider: `{args.provider}`\n"
        f"- template_version: `{args.template_version}`\n"
        f"- source_basis: `{args.source_basis}`\n\n"
        f"{content}\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "summary_generated",
        "provider": args.provider,
        "template_version": args.template_version,
        "source_basis": args.source_basis,
        "output": str(output.resolve()),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
