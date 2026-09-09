#!/usr/bin/env python3
"""A second adapter at the acquisition seam: scripted, no browser.

Speaks the same protocol as `scripts/browser_pdf.py` — `resolve` and `capture`
subcommands, one JSON line on stdout, exit 0 only on success — so
`process_run.py --browser-command` can drive the real acquisition logic
against outcomes chosen by a test: a captured file, a blocked publisher, a
valid PDF of the wrong paper, an unreachable host.

Usage: fake_browser.py <scenario.json> --session S <resolve|capture> ...

Scenario shape:

    {"resolve": {"<doi>": ["url", ...]},
     "capture": {"<url>": {"result": "captured", "source": "<pdf path>"}}}

`result` is one of captured, blocked, challenge_unsolved, wrong_document,
error. A captured entry copies `source` to the requested `--output`, which is
what makes real identity verification run against real bytes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


def emit(payload: dict[str, object], code: int) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return code


def flags(argv: list[str]) -> dict[str, str]:
    return {argv[index].lstrip("-"): argv[index + 1]
            for index in range(len(argv) - 1) if argv[index].startswith("--")}


def main(argv: list[str]) -> int:
    scenario = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    # The caller always passes the global --session before the subcommand.
    rest = argv[3:] if argv[1:2] == ["--session"] else argv[1:]
    action, options = (rest[0] if rest else ""), flags(rest[1:])

    if action == "resolve":
        urls = scenario.get("resolve", {}).get(options.get("doi", ""), [])
        return emit({"doi": options.get("doi"), "urls": urls}, 0 if urls else 2)

    if action != "capture":
        return emit({"status": "failed", "kind": "error", "reason": f"unsupported action {action!r}"}, 2)

    url = options.get("url", "")
    outcome = scenario.get("capture", {}).get(url)
    if outcome is None:
        return emit({"status": "failed", "kind": "error", "requested_url": url,
                     "reason": "host not reachable in this scenario"}, 2)
    report: dict[str, object] = {"status": "failed", "kind": outcome["result"], "requested_url": url}
    if outcome["result"] != "captured":
        return emit(report, 2)
    raw = Path(outcome["source"]).read_bytes()
    output = Path(options["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)
    report.update({"status": "captured", "kind": "pdf", "path": str(output.resolve()),
                   "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    return emit(report, 0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
