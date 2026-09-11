#!/usr/bin/env python3
"""Process one approved selection end to end, and resume the same run.

This is the single public processing entry point. After the user's one
confirmation, it acquires, verifies, converts, writes and reads back every
selected paper without further instructions, and it can be re-run to finish
what a previous attempt left pending.

It owns no new machinery: acquisition is `browser_pdf.py`, conversion is
`mineru_parse.py`, writing is `zotero_ingest.py`, and every decision is
recorded through `workflow.py`. What it adds is the order, the per-paper
isolation, and one structured result.

Two judgements stay with the agent and come back as structured handoffs
rather than prompts: understanding the request (already settled before this
runs) and writing each paper's summary from its verified full text. A paper
that needs a summary is returned in `pending_summaries` with the source to
read; the agent writes it with `summary_artifact.py`, records it with
`workflow.py record-paper`, and re-runs this command on the same run.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import acquire  # noqa: E402
import capability  # noqa: E402
import credentials  # noqa: E402
import mineru_parse  # noqa: E402
import sources  # noqa: E402
import summary_artifact  # noqa: E402
import workflow  # noqa: E402
import zotero_ingest  # noqa: E402
from http_client import RequestError  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
STAGES = ("acquire", "convert", "ingest")


@dataclass(frozen=True)
class ProcessRequest:
    """One processing pass over a confirmed run, in checkable types.

    Every stage takes this instead of the parser's namespace, so a caller —
    including this module's own stages — is checked against the fields it
    actually reads rather than trusting attribute names to line up.
    """
    run_dir: Path
    ids: Sequence[str] | None = None
    stages: Sequence[str] = STAGES
    collection_key: str | None = None
    collection_name: str | None = None
    storage_root: Path | None = None
    reuse_map: Path | None = None
    dry_run: bool = False
    session: str | None = None
    browser_command: Sequence[str] | None = None
    api_base: str = "https://api.zotero.org"
    mineru_api_base: str = "https://mineru.net"
    mineru_model: str = "vlm"
    retry_budget: float = 90
    poll_timeout: float = 120
    browser_timeout: float = 300
    acquire_timeout: float = 240
    source_lookup: bool = True
    check_ingestion: bool = False

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> ProcessRequest:
        return cls(
            run_dir=Path(args.run_dir).resolve(),
            ids=[value.strip() for value in args.ids.split(",") if value.strip()] if args.ids else None,
            stages=[name for name in STAGES if name in args.stages.split(",")],
            collection_key=args.collection_key, collection_name=args.collection_name,
            storage_root=Path(args.storage_root).resolve() if args.storage_root else None,
            reuse_map=Path(args.reuse_map) if args.reuse_map else None,
            dry_run=args.dry_run, session=args.session, browser_command=args.browser_command,
            api_base=args.api_base, mineru_api_base=args.mineru_api_base,
            mineru_model=args.mineru_model, retry_budget=args.retry_budget,
            poll_timeout=args.poll_timeout, browser_timeout=args.browser_timeout,
            acquire_timeout=args.acquire_timeout, source_lookup=not args.no_source_lookup,
            check_ingestion=args.check_ingestion,
        )

    def ingest_request(self, ids: Sequence[str]) -> zotero_ingest.IngestRequest:
        return zotero_ingest.IngestRequest(
            run_dir=self.run_dir, collection_key=self.collection_key,
            collection_name=self.collection_name, ids=ids, storage_root=self.storage_root,
            reuse_map=self.reuse_map, api_base=self.api_base,
            retry_budget=self.retry_budget, dry_run=self.dry_run,
        )

    def parse_request(self, pdfs: Sequence[Path]) -> mineru_parse.ParseRequest:
        return mineru_parse.ParseRequest(
            pdfs=pdfs, run_dir=self.run_dir, model=self.mineru_model,
            api_base=self.mineru_api_base, retry_budget=self.retry_budget,
            poll_timeout=self.poll_timeout,
        )


def safe_name(identity: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", identity).strip("-") or "paper"


def browser_adapter(request: ProcessRequest) -> list[str]:
    """The program that speaks the acquisition protocol.

    The seam is a command line, not a Python call, because the real adapter
    drives a browser in another process anyway. Anything satisfying the
    `browser_pdf.py` contract — `resolve`/`capture` subcommands, one JSON line
    on stdout, exit 0 only on success — can stand here, which is what lets the
    acquisition logic be tested without a live browser.

    The command arrives as one already-split token per flag, so no caller has
    to know shell quoting rules — a path containing a space (this repository
    has one) would otherwise be torn in half with no error.
    """
    return list(request.browser_command) if request.browser_command else [sys.executable, str(SCRIPTS / "browser_pdf.py")]


def browser(request: ProcessRequest, *command: str) -> tuple[int, dict[str, Any]]:
    """Call the acquisition channel and read its single JSON line.

    One session per run, so a publisher's clearance cookie earned for one
    paper covers the rest of the batch.
    """
    session = request.session or ("ltz-" + safe_name(request.run_dir.name))[:60]
    completed = subprocess.run(
        [*browser_adapter(request), "--session", session, *command],
        text=True, capture_output=True, timeout=request.browser_timeout,
    )
    try:
        return completed.returncode, json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return completed.returncode, {"status": "failed", "kind": "error",
                                      "reason": (completed.stderr or completed.stdout).strip()[:300]}


def browser_channel(request: ProcessRequest) -> tuple[Any, list[str]]:
    """The browser adapter, if this machine has one.

    A caller who supplied `--browser-command` has taken the precondition on
    itself. Otherwise the bundled adapter needs Kimi, and its absence is not
    fatal any more: it removes one route, so papers reachable over plain HTTP
    still finish and only those needing the browser report the missing channel.
    """
    if not request.browser_command and os.environ.get("LITERATURE_BROWSER_DISABLED") == "1":
        return None, ["browser_disabled"]
    missing: list[str] = []
    checked = bool(request.browser_command)
    broken = False
    human_pending = False
    def call(*command: str) -> tuple[int, dict[str, Any]]:
        nonlocal broken, checked, human_pending
        if human_pending:
            return 2, {"status": "failed", "kind": "challenge_unsolved",
                       "detail": "earlier paper awaits a human click; preserve the current browser tab and continue HTTP work"}
        if not checked:
            checked = True
            missing.extend(capability.stage_missing("browser_fallback",
                           {"kimi": capability.kimi(capability.probe_kimi())}))
            broken = bool(missing)
        if broken:
            return 3, {"status": "failed", "kind": "browser_error",
                       "detail": "browser channel paused after an earlier error; inspect the existing session"}
        try:
            result = browser(request, *command)
        except (OSError, subprocess.SubprocessError) as error:
            broken = True
            return 3, {"status": "failed", "kind": "browser_error",
                       "detail": f"browser adapter stopped: {type(error).__name__}; inspect the existing session"}
        if result[1].get("kind") == "browser_error":
            broken = True
        if result[1].get("kind") == "challenge_unsolved":
            human_pending = True
        return result
    return call, missing


def stage_acquire(request: ProcessRequest, identities: list[str], candidates: dict[str, Any]) -> dict[str, Any]:
    """Fetch the source PDFs that are still missing. Each stage reads the run
    itself, so a stage always acts on what the previous one actually wrote."""
    run = request.run_dir
    wanted = [paper.id for paper in workflow.Run.open(run).papers(identities)
              if not paper.pdf and not paper.is_metadata_only]
    if not wanted:
        return {"attempted": [], "acquired": [], "failed": {}}
    channel, missing = browser_channel(request)
    # One client for the batch, so a DOI looked up for one paper is not looked
    # up again for the next, and the shared rate limits are honoured once.
    # API lookups never operate the browser behind the agent's back. Only
    # the explicit acquisition channel below may navigate the shared session.
    client = sources.Sources(browser=None) if request.source_lookup else None
    acquired, failed, unverified = [], {}, {}
    handoffs = []
    for identity in wanted:
        print(json.dumps({"paper": identity, "stage": "acquire"}), file=sys.stderr, flush=True)
        # Everything for one paper, recording included: a bookkeeping error on
        # one paper must not end the batch any more than a failed download does.
        try:
            target = run / "papers" / safe_name(identity)
            result = acquire.acquire(acquire.AcquireRequest(
                candidate=candidates[identity], output=target / "source.pdf",
                browser=channel, client=client, lookup=request.source_lookup,
                limits=acquire.Limits(total_seconds=request.acquire_timeout)))
            # State first, then the trail: a bookkeeping hiccup must not undo
            # a download that already succeeded.
            if result.get("ok"):
                workflow.Run.record(run, identity, "pdf_acquired", artifact="pdf=" + str(result["path"]))
                record_trail(run, identity, target, result)
                acquired.append(identity)
                continue
            fields: dict[str, str | None] = {"warning": f"acquisition: {result.get('reason')}"}
            if result.get("kept"):
                fields["artifact"] = "pdf_unverified=" + str(result["kept"])
                unverified[identity] = str(result["kept"])
            workflow.Run.record(run, identity, **fields)
            record_trail(run, identity, target, result)
            failed[identity] = str(result.get("reason"))
            handoffs.append({"id": identity, "title": candidates[identity].get("title"),
                             "doi": candidates[identity].get("doi"),
                             "session": request.session or ("ltz-" + safe_name(run.name))[:60],
                             "urls": result.get("browser_candidates", []),
                             "walls": result.get("walls", []),
                             "output": str(target / "source.pdf"),
                             "next_action": "read references/acquisition-and-artifacts.md: MyLOFT handoff; "
                                            "inspect the existing session, establish publisher entitlement once, "
                                            "then capture the selected paper and record its verified PDF"})
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
            failed[identity] = f"{type(error).__name__}: {error}"
    report: dict[str, Any] = {"attempted": wanted, "acquired": acquired, "failed": failed}
    if unverified:
        report["unverified"] = unverified
    if handoffs:
        report["browser_handoff"] = handoffs
    if missing:
        # Advisory, not a gate: the papers that needed the browser say so in
        # their own trail, and the rest were acquired without it.
        report["capability_missing"] = missing
    return report


def record_trail(run: Path, identity: str, target: Path, result: dict[str, Any]) -> None:
    """Write what acquisition actually tried, whether or not it worked.

    Every attempt keeps its channel, its redacted URL, the source that
    suggested it, the version it claims to be, the bytes and hash if any, and
    which of the acquisition walls stopped it. That is what makes a failure
    diagnosable later and a success auditable.
    """
    target.mkdir(parents=True, exist_ok=True)
    path = target / "acquisition.json"
    history = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    history.append({
        "at": workflow.utc_now(),
        "ok": bool(result.get("ok")),
        "channel": result.get("channel"),
        "source": result.get("source"),
        "version": result.get("version"),
        "reason": result.get("reason"),
        "walls": result.get("walls"),
        "sha256": (result.get("evidence") or {}).get("sha256"),
        "bytes": (result.get("evidence") or {}).get("bytes"),
        "verification": (result.get("evidence") or {}).get("status"),
        "attempts": result.get("trail"),
    })
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    workflow.Run.record(run, identity, artifact="acquisition_trail=" + str(path))


def stage_convert(request: ProcessRequest, identities: list[str]) -> dict[str, Any]:
    """Convert consented PDFs. A conversion failure keeps the PDF path open."""
    run = request.run_dir
    package = workflow.Run.open(run)
    pending, skipped = {}, {}
    for paper in package.papers(identities):
        if paper.markdown or not paper.pdf:
            continue
        if not package.consented("mineru", [paper.id]):
            skipped[paper.id] = "markdown_unavailable: no upload consent"
            continue
        pending[paper.id] = paper.pdf
    if skipped:
        for identity, reason in skipped.items():
            workflow.Run.record(run, identity, warning=reason)
    if not pending:
        return {"converted": [], "failed": {}, "skipped": skipped}
    if not credentials.mineru_token():
        for identity in pending:
            workflow.Run.record(run, identity, warning="markdown_unavailable: no MinerU token")
        return {"converted": [], "failed": {}, "skipped": {**skipped, **{key: "markdown_unavailable: no MinerU token" for key in pending}}}
    try:
        with workflow.run_lock(run, "conversion"):
            result = mineru_parse.parse(request.parse_request(list(pending.values())))
    except (RequestError, ValueError, OSError) as error:
        reason = f"markdown_unavailable: {error}"
        for identity in pending:
            workflow.Run.record(run, identity, warning=reason)
        return {"converted": [], "failed": {key: reason for key in pending}, "skipped": skipped}
    # Match on content hash, not path: MinerU parses identical bytes once and
    # returns the same record for every path that shares them, so two papers
    # pointing at the same file both need to see that one result.
    by_digest = {record.get("sha256"): record for record in result.get("files", []) if record.get("sha256")}
    by_path = {str(Path(record["path"]).resolve()): record for record in result.get("files", [])}
    converted, failed = [], {}
    for identity, pdf in pending.items():
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
        record = by_digest.get(digest) or by_path.get(str(pdf.resolve())) or {}
        try:
            if record.get("state") == "done" and record.get("markdown"):
                workflow.Run.record(run, identity, "markdown_derived", artifact="markdown=" + str(record["markdown"]))
                converted.append(identity)
                continue
            failed[identity] = "markdown_unavailable: " + str(record.get("reason") or record.get("state") or "not returned")
            workflow.Run.record(run, identity, warning=failed[identity])
        except (ValueError, OSError) as error:
            failed[identity] = f"{type(error).__name__}: {error}"
    return {"converted": converted, "failed": failed, "skipped": skipped}


def summary_handoff(package: workflow.Run, identities: list[str],
                    candidates: dict[str, Any]) -> list[dict[str, Any]]:
    """Papers whose full text is ready but whose summary the agent still owes."""
    handoff = []
    for paper in package.papers(identities):
        source = paper.markdown or paper.pdf
        if paper.summary or not source:
            continue
        handoff.append({
            "id": paper.id,
            "title": candidates.get(paper.id, {}).get("title"),
            "source": str(source),
            "source_basis": "markdown" if paper.markdown else "pdf",
            "instructions": str(SCRIPTS.parent / "references" / "paper-summary.md"),
            "template_version": "3",
            "output": str(package.directory / "papers" / safe_name(paper.id) / "summary.md"),
        })
    return handoff


def stage_ingest(request: ProcessRequest, identities: list[str]) -> dict[str, Any]:
    writable = [paper.id for paper in workflow.Run.open(request.run_dir).papers(identities) if paper.writable]
    if not writable:
        return {"status": "skipped", "reason": "no paper has a verified source PDF yet", "ids": []}
    try:
        return zotero_ingest.ingest(request.ingest_request(writable))
    except (RequestError, ValueError, KeyError, OSError) as error:
        return {"status": "pending", "reason": str(error) if isinstance(error, (RequestError, ValueError)) else f"{type(error).__name__}: {error}",
                "ids": writable}


def ingest_command(request: ProcessRequest, identities: list[str]) -> list[str]:
    """Carry the confirmed target and local read-back options across the summary gap."""
    command = [sys.executable, str(SCRIPTS / "process_run.py"),
               "--run-dir", str(request.run_dir), "--stages", "ingest",
               "--ids", ",".join(identities)]
    for flag, value in (
        ("--collection-key", request.collection_key), ("--collection-name", request.collection_name),
        ("--storage-root", request.storage_root), ("--reuse-map", request.reuse_map),
        ("--api-base", request.api_base), ("--retry-budget", request.retry_budget),
    ):
        if value is not None:
            command.extend([flag, str(value)])
    if request.dry_run:
        command.append("--dry-run")
    return command


def ingestion_readiness(request: ProcessRequest) -> dict[str, Any]:
    account = credentials.zotero_credentials()
    configured = bool(account['api_key'] and account['library_id'])
    access = None
    if configured:
        try:
            access = capability.zotero_key_access(account['api_key'], account['library_id'],
                                                 account['library_type'], request.api_base,
                                                 timeout=3, attempts=1)
        except (RequestError, OSError, ValueError):
            access = {'reachable': False, 'identity_match': None, 'write_permission': None}
    result = capability.zotero_key(configured, access)
    print(json.dumps({'stage': 'ingestion_readiness', 'at': workflow.utc_now(), **result}),
          file=sys.stderr, flush=True)
    return result


def process(request: ProcessRequest) -> dict[str, Any]:
    # Advisory only. A refused or unreachable key does not gate local artifacts.
    if request.check_ingestion and not request.dry_run:
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=1) as pool:
            readiness = pool.submit(ingestion_readiness, request)
            result = _process(request)
            result['ingestion_readiness'] = readiness.result()
            result.update(elapsed_seconds=round(time.monotonic() - started, 3), finished_at=workflow.utc_now())
            return result
    return _process(request)


def _process(request: ProcessRequest) -> dict[str, Any]:
    run = request.run_dir
    started = time.monotonic()
    started_at = workflow.utc_now()
    package = workflow.Run.open(run)
    if not package.confirmed:
        raise ValueError("candidate selection is not approved; confirm the list first")
    identities = package.resolve_ids(request.ids)
    if not identities:
        raise ValueError("no selected papers")
    candidates = package.require_candidates(identities)
    stages = list(request.stages)
    result: dict[str, Any] = {"run_dir": str(run), "stages": stages, "ids": identities}
    timings: dict[str, float] = {}
    def timed(stage: str, action: Any) -> Any:
        begin = time.monotonic()
        print(json.dumps({'stage': stage, 'status': 'started', 'at': workflow.utc_now()}),
              file=sys.stderr, flush=True)
        try:
            return action()
        finally:
            timings[stage] = round(time.monotonic() - begin, 3)
            print(json.dumps({'stage': stage, 'status': 'finished', 'at': workflow.utc_now(),
                              'elapsed_seconds': timings[stage]}), file=sys.stderr, flush=True)
    if request.dry_run:
        # A preview must not download anything or upload a PDF to MinerU, so
        # dry run means the read-only validation stage and nothing else.
        stages = [name for name in stages if name == "ingest"]
        result["stages"] = stages
        result["dry_run"] = True

    if "acquire" in stages:
        result["acquire"] = timed('acquire', lambda: stage_acquire(request, identities, candidates))
    if "convert" in stages:
        result["convert"] = timed('convert', lambda: stage_convert(request, identities))

    pending_summaries = summary_handoff(workflow.Run.open(run), identities, candidates)
    if "ingest" in stages:
        result["ingest"] = timed('ingest', lambda: stage_ingest(request, identities))

    package = workflow.Run.open(run)
    rows = package.report(identities)
    ingest_status = str(result.get("ingest", {}).get("status") or "skipped")
    if ingest_status in ("pending", "invalid_artifacts"):
        status = "pending"
    elif pending_summaries:
        status = "awaiting_summaries"
    elif not all(row["complete"] for row in rows):
        status = "partial"
    else:
        status = "complete"
    result.update({
        "status": status,
        "collection": result.get("ingest", {}).get("collection") or package.collection,
        "papers": rows,
        "pending_summaries": pending_summaries,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "started_at": started_at, "finished_at": workflow.utc_now(), "timings": timings,
        "next_action": {
            "awaiting_summaries": "read summary_batch_file, write each content_file from its full-text source, "
                                  "self-check once, execute summary_batch_command, then resume_command",
            "pending": "read the ingest reason, then re-run this command on the same run once the service recovers",
            "partial": "deliver the table; re-running retries only the rows marked actionable "
                       "(a paper with no obtainable full text is finished, not waiting)",
            "complete": "deliver the table and ingest.papers evidence now; built-in cloud/local read-back is finished. "
                        "Report file_action as reused/uploaded; independent content quality is not certified by this status.",
        }[status],
        "table": workflow.render_report(rows),
    })
    if pending_summaries:
        result["resume_command"] = ingest_command(request, identities)
        result["resume_shell"] = shlex.join(result["resume_command"])
        handoff = summary_artifact.prepare_handoff(run, pending_summaries, result['resume_command'])
        result['summary_batch_file'] = str(handoff)
        result['summary_batch_command'] = [sys.executable, str(SCRIPTS / 'summary_artifact.py'),
                                            '--batch-file', str(handoff), '--provider', '<actual-agent-model>']
    result.update(elapsed_seconds=round(time.monotonic() - started, 3), finished_at=workflow.utc_now())
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--ids", help="Comma-separated selected IDs; default is every selected paper")
    parser.add_argument("--stages", default=",".join(STAGES),
                        help="Comma-separated subset of: " + ", ".join(STAGES))
    parser.add_argument("--collection-key")
    parser.add_argument("--collection-name")
    parser.add_argument("--storage-root")
    parser.add_argument("--reuse-map")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-ingestion", action="store_true",
                        help="Check Zotero identity/write access once in parallel; never block acquisition or conversion")
    parser.add_argument("--session", help="Kimi WebBridge session; defaults to one session per run")
    parser.add_argument("--browser-command", action="append", metavar="TOKEN",
                        help="Program speaking the browser_pdf.py acquisition protocol, one "
                             "argv token per flag (default: the bundled browser_pdf.py)")
    parser.add_argument("--api-base", default="https://api.zotero.org")
    parser.add_argument("--mineru-api-base", default="https://mineru.net")
    parser.add_argument("--mineru-model", default="vlm", choices=("pipeline", "vlm"))
    parser.add_argument("--retry-budget", type=float, default=90)
    parser.add_argument("--poll-timeout", type=float, default=120)
    parser.add_argument("--browser-timeout", type=float, default=300)
    parser.add_argument("--acquire-timeout", type=float, default=240,
                        help="seconds one paper's acquisition may spend across every route")
    parser.add_argument("--no-source-lookup", action="store_true",
                        help="acquire only from links already recorded; ask no metadata source "
                             "for further open copies")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = process(ProcessRequest.from_args(args))
    except (ValueError, KeyError, OSError) as error:
        print(json.dumps({"status": "pending",
                          "reason": str(error) if isinstance(error, ValueError) else f"{type(error).__name__}: {error}"}))
        raise SystemExit(2)
    print(json.dumps(result, ensure_ascii=False))
    # Partial delivery and a summary handoff are normal outcomes, not failures:
    # only a state a caller must act on outside this run exits non-zero.
    if result["status"] == "pending":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
