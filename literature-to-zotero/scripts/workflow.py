#!/usr/bin/env python3
"""Create and advance a resumable literature workflow run package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Sequence
from runtime_io import file_lock, text_hash


SCHEMA_VERSION = 2

# The default list is one screened table, not a fixed core/expansion structure.
DEFAULT_LIST_BUDGET = 15
# One initial search plus at most one purposeful supplementary round, both
# inside a single run-level time budget the agent reports against.
DEFAULT_SUPPLEMENTARY_BUDGET = 1
DEFAULT_SEARCH_SECONDS = 300


class PaperState(str, Enum):
    DISCOVERED = "discovered"
    SELECTED = "selected"
    METADATA_VERIFIED = "metadata_verified"
    PDF_ACQUIRED = "pdf_acquired"
    MARKDOWN_DERIVED = "markdown_derived"
    SUMMARY_GENERATED = "summary_generated"
    ZOTERO_WRITTEN = "zotero_written"
    READ_BACK_VERIFIED = "read_back_verified"
    METADATA_ONLY = "metadata_only"
    PARTIAL = "partial"
    FAILED = "failed"
    SYNC_PENDING = "sync_pending"


# An artifact can arrive at any time after the source PDF exists: Markdown and
# a summary are written to the same parent whenever conversion or the agent
# produces them, including after the paper was already read back. These states
# therefore accept them, and a re-ingest writes the new artifact.
LATE_ARTIFACTS = {PaperState.MARKDOWN_DERIVED, PaperState.SUMMARY_GENERATED}

ALLOWED_TRANSITIONS: dict[PaperState, set[PaperState]] = {
    PaperState.DISCOVERED: {PaperState.SELECTED},
    # Acquisition verifies the PDF against the candidate's own metadata, so a
    # confirmed paper may go straight to an identity-checked source PDF.
    PaperState.SELECTED: {PaperState.METADATA_VERIFIED, PaperState.PDF_ACQUIRED,
                          PaperState.METADATA_ONLY, PaperState.PARTIAL, PaperState.FAILED},
    PaperState.METADATA_VERIFIED: {PaperState.PDF_ACQUIRED, PaperState.METADATA_ONLY, PaperState.PARTIAL, PaperState.FAILED},
    PaperState.PDF_ACQUIRED: {
        PaperState.MARKDOWN_DERIVED, PaperState.SUMMARY_GENERATED, PaperState.ZOTERO_WRITTEN,
        PaperState.PARTIAL, PaperState.FAILED,
    },
    PaperState.MARKDOWN_DERIVED: {
        PaperState.SUMMARY_GENERATED, PaperState.ZOTERO_WRITTEN, PaperState.PARTIAL, PaperState.FAILED,
    },
    PaperState.SUMMARY_GENERATED: {PaperState.ZOTERO_WRITTEN, PaperState.PARTIAL, PaperState.FAILED},
    PaperState.ZOTERO_WRITTEN: {
        PaperState.READ_BACK_VERIFIED, PaperState.SYNC_PENDING, PaperState.PARTIAL, PaperState.FAILED,
    },
    PaperState.SYNC_PENDING: {PaperState.READ_BACK_VERIFIED, PaperState.PARTIAL, PaperState.FAILED, *LATE_ARTIFACTS},
    PaperState.READ_BACK_VERIFIED: {PaperState.SYNC_PENDING, *LATE_ARTIFACTS},
    PaperState.METADATA_ONLY: {PaperState.PDF_ACQUIRED, PaperState.PARTIAL, PaperState.FAILED},
    PaperState.PARTIAL: {
        PaperState.PDF_ACQUIRED, PaperState.MARKDOWN_DERIVED, PaperState.SUMMARY_GENERATED,
        PaperState.ZOTERO_WRITTEN, PaperState.READ_BACK_VERIFIED, PaperState.SYNC_PENDING,
        PaperState.METADATA_ONLY, PaperState.FAILED,
    },
    PaperState.FAILED: {PaperState.METADATA_VERIFIED, PaperState.PDF_ACQUIRED},
}


@contextmanager
def run_lock(run: Path, name: str = "workflow") -> Iterator[None]:
    if name not in {"workflow", "zotero", "conversion"}:
        raise ValueError("unknown run lock")
    with file_lock(run / f'.{name}.lock'):
        yield


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def manifest_path(run_dir: Path) -> Path:
    return run_dir / "manifest.json"


def load_manifest(run_dir: Path) -> dict[str, Any]:
    path = manifest_path(run_dir)
    if not path.is_file():
        fail(f"run package has no manifest: {run_dir}")
    return migrate(read_json(path))


def migrate(manifest: dict[str, Any]) -> dict[str, Any]:
    """Read a schema-1 run without reinstating its retired search-plan gate.

    Schema 1 blocked retrieval behind a separate plan approval. That gate is
    gone, so an old run carrying `search_plan: pending` must not be stuck: the
    approved plan text survives as recorded scope, and only the candidate gate
    still holds work back.
    """
    gates = manifest.setdefault("gates", {})
    if "search_plan" in gates:
        del gates["search_plan"]
        manifest.setdefault("search_scope", manifest.get("search_plan"))
    manifest.setdefault("search", {
        "rounds": [],
        "supplementary_budget": DEFAULT_SUPPLEMENTARY_BUDGET,
        "budget_seconds": DEFAULT_SEARCH_SECONDS,
    })
    gates.setdefault("candidate_selection", "pending")
    return manifest


def search_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    search = manifest.get("search", {})
    rounds = search.get("rounds", [])
    elapsed = sum(float(entry.get("elapsed_seconds") or 0) for entry in rounds)
    budgeted = [entry for entry in rounds if entry.get("round") == "supplementary"
                and not entry.get("user_requested")]
    return {
        "rounds": len(rounds),
        "initial": sum(1 for entry in rounds if entry.get("round") == "initial"),
        "supplementary": sum(1 for entry in rounds if entry.get("round") == "supplementary"),
        "supplementary_remaining": max(0, search.get("supplementary_budget", DEFAULT_SUPPLEMENTARY_BUDGET) - len(budgeted)),
        "budget_seconds": search.get("budget_seconds", DEFAULT_SEARCH_SECONDS),
        "elapsed_seconds": int(elapsed) if elapsed == int(elapsed) else elapsed,
        "over_budget": elapsed > search.get("budget_seconds", DEFAULT_SEARCH_SECONDS),
    }


def save_manifest(run_dir: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = utc_now()
    write_json(manifest_path(run_dir), manifest)


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def resolve_artifact(run_dir: Path, value: str) -> Path:
    """A recorded artifact path, absolute or relative to its run. One rule."""
    path = Path(value).expanduser()
    return (path if path.is_absolute() else run_dir / path).resolve()


class Paper:
    """One selected paper: its state, its artifacts and its write evidence.

    Callers ask this what a paper has instead of reading manifest keys, which
    is what keeps "where does a recorded artifact actually live" — absolute or
    run-relative, present or merely recorded — a single answer.
    """

    ARTIFACTS = ("pdf", "markdown", "summary")

    def __init__(self, run_dir: Path, identity: str, record: dict[str, Any]) -> None:
        self.run_dir, self.id, self.record = run_dir, identity, record

    @property
    def state(self) -> str:
        return str(self.record["state"])

    @property
    def warnings(self) -> list[str]:
        return list(self.record.get("warnings", []))

    @property
    def zotero(self) -> dict[str, Any]:
        return dict(self.record.get("zotero", {}))

    def path(self, field: str) -> Path | None:
        """Where an artifact was recorded, whether or not it is still there."""
        value = self.record.get("artifacts", {}).get(field)
        return resolve_artifact(self.run_dir, value) if value else None

    def artifact(self, field: str) -> Path | None:
        """The artifact, only when the file is actually on disk."""
        path = self.path(field)
        return path if path and path.is_file() else None

    @property
    def pdf(self) -> Path | None:
        return self.artifact("pdf")

    @property
    def markdown(self) -> Path | None:
        return self.artifact("markdown")

    @property
    def summary(self) -> Path | None:
        return self.artifact("summary")

    @property
    def is_metadata_only(self) -> bool:
        return self.state == PaperState.METADATA_ONLY.value

    @property
    def writable(self) -> bool:
        """Enough to write something real to Zotero for this paper."""
        return bool(self.pdf) or self.is_metadata_only

    def validate_read_back(self, evidence: dict[str, Any]) -> None:
        if not evidence.get("collection_verified") or not evidence.get("note_key") or not evidence.get("cloud_verified_at"):
            raise ValueError("collection and note verification evidence required")
        if not self.path("pdf") or not self.path("summary"):
            raise ValueError("PDF and summary required")
        for field in self.ARTIFACTS:
            source = self.path(field)
            if not source:
                continue
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if field == "summary":
                digest = text_hash(source.read_text(encoding='utf-8'))
                if digest != evidence.get("note_sha256"):
                    raise ValueError("summary evidence differs from source")
                continue
            record = evidence.get("attachments", {}).get(source.name, {})
            local = Path(record.get("local_path") or "")
            if (record.get("state") != "binary_verified" or record.get("sha256") != digest
                    or not local.is_file() or hashlib.sha256(local.read_bytes()).hexdigest() != digest):
                raise ValueError(f"{field} local file/hash verification evidence required")

    def report(self, title: str | None = None) -> dict[str, Any]:
        return paper_report(self, title)


class Run:
    """A literature run: the manifest, the candidates and the papers.

    This is the interface to run state. Nothing outside it needs to know the
    manifest's JSON shape, where an artifact path is stored, or how consent is
    recorded — which is why those rules have one implementation each rather
    than one per calling script.

    Read with `Run.open`; mutate under the run lock with `Run.locked` (or
    `Run.record` for a single paper), then `save`.
    """

    def __init__(self, directory: Path, manifest: dict[str, Any]) -> None:
        self.directory, self.manifest = directory, manifest

    @classmethod
    def exists(cls, directory: str | Path) -> bool:
        """Whether this directory is an initialized run."""
        return manifest_path(Path(directory).resolve()).is_file()

    @classmethod
    def open(cls, directory: str | Path) -> Run:
        run_dir = Path(directory).resolve()
        return cls(run_dir, load_manifest(run_dir))

    @classmethod
    @contextmanager
    def locked(cls, directory: str | Path) -> Iterator[Run]:
        """Serialize a mutation against every other writer of this run."""
        run_dir = Path(directory).resolve()
        with run_lock(run_dir):
            yield cls.open(run_dir)

    @classmethod
    def record(cls, directory: str | Path, identity: str, state: str | None = None,
               **fields: str | None) -> Paper:
        """Lock, advance one paper, save. The common single-paper mutation."""
        with cls.locked(directory) as run:
            paper = run.advance(identity, state, **fields)
            run.save()
            return paper

    def save(self) -> None:
        save_manifest(self.directory, self.manifest)

    # ── What the user confirmed ──────────────────────────────────────────
    @property
    def confirmed(self) -> bool:
        return self.manifest["gates"]["candidate_selection"] == "approved"

    def require_confirmed(self) -> None:
        if not self.confirmed:
            raise ValueError("candidate selection is not approved")

    @property
    def selected(self) -> list[str]:
        return list(self.manifest["selected_ids"])

    def resolve_ids(self, ids: Sequence[str] | None) -> list[str]:
        """The papers a caller may act on: named ones, or the whole selection."""
        if not ids:
            return self.selected
        wanted = list(dict.fromkeys(ids))
        unknown = [value for value in wanted if value not in self.selected]
        if unknown:
            raise ValueError("unselected papers cannot be ingested: " + ", ".join(unknown))
        return wanted

    def consented(self, service: str, ids: Sequence[str]) -> bool:
        record = self.manifest.get("consents", {}).get(service, {})
        return record.get("decision") == "approved" and set(ids).issubset(record.get("ids", []))

    def require_consent(self, service: str, ids: Sequence[str]) -> None:
        if not self.consented(service, ids):
            raise ValueError(f"{service} upload consent missing for selected papers")

    def consent_source(self, service: str, identity: str) -> str | None:
        service_record = self.manifest.get("consents", {}).get(service, {})
        paper = service_record.get("papers", {}).get(identity, service_record)
        return paper.get("source") if isinstance(paper, dict) else None

    # ── Papers and candidates ────────────────────────────────────────────
    def paper(self, identity: str) -> Paper:
        record = self.manifest["papers"].get(identity)
        if record is None:
            raise ValueError(f"paper is not in this run: {identity}")
        return Paper(self.directory, identity, record)

    def papers(self, ids: Sequence[str] | None = None) -> list[Paper]:
        return [self.paper(identity) for identity in (ids if ids is not None else self.selected)]

    def candidates(self) -> dict[str, dict[str, Any]]:
        return {item["id"]: item for item in read_json(self.directory / "candidates.json")}

    def require_candidates(self, ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        """The candidate records for these papers, or a named failure."""
        candidates = self.candidates()
        unknown = [key for key in ids if key not in candidates]
        if unknown:
            raise ValueError("selected papers are missing from candidates.json: " + ", ".join(unknown))
        return candidates

    @property
    def collection(self) -> str | None:
        return self.manifest.get("collection")

    @collection.setter
    def collection(self, key: str) -> None:
        self.manifest["collection"] = key

    def search(self) -> dict[str, Any]:
        return search_summary(self.manifest)

    def record_search(self, round_name: str, provider: str, query: str, reason: str,
                      elapsed: float = 0.0, user_requested: bool = False) -> dict[str, Any]:
        """Append one retrieval round, holding the supplementary ceiling."""
        if round_name == "supplementary" and not user_requested and self.search()["supplementary_remaining"] <= 0:
            raise ValueError("supplementary search budget is spent; report coverage or record an explicit user request")
        entry = {"at": utc_now(), "round": round_name, "provider": provider, "query": query,
                 "reason": reason or "primary query", "elapsed_seconds": elapsed,
                 "user_requested": user_requested}
        self.manifest["search"]["rounds"].append(entry)
        self.manifest["events"].append({"event": "search_round_recorded", **entry})
        return self.search()

    # ── Mutation ─────────────────────────────────────────────────────────
    def advance(self, identity: str, state: str | None = None, artifact: str | None = None,
                warning: str | None = None, verification: str | None = None) -> Paper:
        apply_paper_update(self.directory, self.manifest, identity, state,
                           artifact=artifact, warning=warning, verification=verification)
        return self.paper(identity)

    # ── Reporting ────────────────────────────────────────────────────────
    def report(self, ids: Sequence[str] | None = None) -> list[dict[str, Any]]:
        candidates = self.candidates()
        return [paper.report(candidates.get(paper.id, {}).get("title")) for paper in self.papers(ids)]

    def table(self, ids: Sequence[str] | None = None) -> str:
        return render_report(self.report(ids))


def normalize_slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "literature-run"


def command_init(args: argparse.Namespace) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.run_root).expanduser().resolve() / f"{normalize_slug(args.slug)}-{stamp}"
    suffix = 1
    while run_dir.exists():
        run_dir = run_dir.with_name(f"{normalize_slug(args.slug)}-{stamp}-{suffix}")
        suffix += 1
    for child in ("papers", "logs"):
        (run_dir / child).mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "intent": args.intent,
        "constraints": {
            "from_year": args.from_year,
            "to_year": args.to_year,
            "language_preference": args.language,
            "list_budget": args.list_budget,
        },
        # One gate: the user's single confirmation over selection, target
        # collection and upload scope. Retrieval needs no separate approval.
        "gates": {"candidate_selection": "pending"},
        "search_scope": None,
        "search": {
            "rounds": [],
            "supplementary_budget": args.supplementary_budget,
            "budget_seconds": args.search_seconds,
        },
        "selected_ids": [],
        "papers": {},
        "events": [{"at": utc_now(), "event": "run_initialized"}],
    }
    write_json(run_dir / "candidates.json", [])
    write_json(run_dir / "queries.json", [])
    save_manifest(run_dir, manifest)
    print(json.dumps({"run_dir": str(run_dir)}, ensure_ascii=False))


def command_record_scope(args: argparse.Namespace) -> None:
    """Record the interpreted retrieval scope as evidence, never as a gate.

    A natural-language request authorizes retrieval inside its own intent, so
    this writes down what the agent understood — it does not claim the user
    approved a plan, and it blocks nothing.
    """
    run_dir = Path(args.run_dir).resolve()
    manifest = load_manifest(run_dir)
    if manifest.get("search_scope") and manifest["search_scope"] != args.scope:
        manifest["gates"]["candidate_selection"] = "pending"
    manifest["search_scope"] = args.scope
    manifest["events"].append({"at": utc_now(), "event": "search_scope_recorded", "scope": args.scope})
    save_manifest(run_dir, manifest)
    print(json.dumps({"search_scope": args.scope}, ensure_ascii=False))


def command_record_search(args: argparse.Namespace) -> None:
    """Append one retrieval round and hold the supplementary budget."""
    run = Run.open(args.run_dir)
    summary = run.record_search(args.round, args.provider, args.query, args.reason,
                                args.elapsed_seconds, args.user_requested)
    run.save()
    print(json.dumps(summary, ensure_ascii=False))


def command_import_candidates(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir).resolve()
    manifest = load_manifest(run_dir)
    candidates = read_json(Path(args.file))
    if not isinstance(candidates, list):
        fail("candidate file must contain a JSON array")
    ids = []
    for candidate in candidates:
        candidate_id = candidate.get("id")
        if not candidate_id or candidate_id in ids:
            fail("each candidate must have a unique id")
        ids.append(candidate_id)
        manifest["papers"].setdefault(candidate_id, {"state": PaperState.DISCOVERED.value, "artifacts": {}, "warnings": []})
    write_json(run_dir / "candidates.json", candidates)
    manifest["gates"]["candidate_selection"] = "pending"
    manifest["events"].append({"at": utc_now(), "event": "candidates_imported", "count": len(candidates)})
    save_manifest(run_dir, manifest)
    print(json.dumps({"imported": len(candidates)}))


def command_approve_candidates(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir).resolve()
    manifest = load_manifest(run_dir)
    requested = [value.strip() for value in args.ids.split(",") if value.strip()]
    requested = list(dict.fromkeys(requested))
    current_ids = {candidate["id"] for candidate in read_json(run_dir / "candidates.json")}
    unknown = [value for value in requested if value not in current_ids]
    if unknown:
        fail("unknown candidate ids: " + ", ".join(unknown))
    if requested == manifest["selected_ids"] and manifest["gates"]["candidate_selection"] == "approved":
        print(json.dumps({"selected": requested, "unchanged": True}))
        return
    manifest["selected_ids"] = requested
    for candidate_id in requested:
        if manifest["papers"][candidate_id]["state"] == PaperState.DISCOVERED.value:
            manifest["papers"][candidate_id]["state"] = PaperState.SELECTED.value
    manifest["gates"]["candidate_selection"] = "approved"
    snapshot_hash = hashlib.sha256((run_dir / "candidates.json").read_bytes()).hexdigest()
    snapshot = run_dir / "selections" / (snapshot_hash + ".json")
    if not snapshot.exists():
        write_json(snapshot, read_json(run_dir / "candidates.json"))
    manifest["selection"] = {
        "ids": requested, "at": utc_now(),
        "source": args.source, "rule": args.rule,
        "candidate_sha256": snapshot_hash, "candidate_snapshot": str(snapshot),
    }
    manifest["events"].append({"event": "candidate_selection_approved", **manifest["selection"]})
    save_manifest(run_dir, manifest)
    print(json.dumps({"selected": requested}, ensure_ascii=False))


def command_consent(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir).resolve()
    manifest = load_manifest(run_dir)
    if manifest["gates"]["candidate_selection"] != "approved":
        fail("candidate selection is not approved")
    ids = args.ids.split(",") if args.ids else list(manifest["selected_ids"])
    if not ids or any(key not in manifest["selected_ids"] for key in ids):
        fail("consent must name selected papers")
    record = {"decision": args.decision, "ids": ids, "source": args.source, "at": utc_now()}
    service = manifest.setdefault("consents", {}).setdefault(args.service, {})
    decisions = service.setdefault("papers", {
        key: {"decision": service.get("decision"), "source": service.get("source"), "at": service.get("at")}
        for key in service.get("ids", [])
    })
    for key in ids:
        decisions[key] = {"decision": args.decision, "source": args.source, "at": record["at"]}
    approved = [key for key, value in decisions.items() if value["decision"] == "approved"]
    service.update({"decision": "approved" if approved else args.decision, "ids": approved,
                    "source": args.source, "at": record["at"]})
    manifest["events"].append({"event": "consent_recorded", "service": args.service, **record})
    save_manifest(run_dir, manifest)
    print(json.dumps(record))


def apply_paper_update(
    run_dir: Path,
    manifest: dict[str, Any],
    identity: str,
    state: str | None,
    artifact: str | None = None,
    warning: str | None = None,
    verification: str | None = None,
) -> dict[str, Any]:
    """Advance one paper in a loaded manifest, enforcing every state rule.

    The CLI and the run processor both go through here, so a transition, an
    artifact path or read-back evidence is judged the same way whoever asks.
    `state=None` records an artifact or warning against whatever state the
    paper currently holds, which is how a caller attaches a note without
    having to know — or accidentally rewind — the state. Callers hold the run
    lock and save the manifest.
    """
    if manifest["gates"]["candidate_selection"] != "approved":
        raise ValueError("candidate selection is not approved")
    if identity not in manifest["selected_ids"]:
        raise ValueError(f"paper is not selected: {identity}")
    paper = manifest["papers"][identity]
    current_state = PaperState(paper["state"])
    try:
        next_state = current_state if state is None else PaperState(state)
    except ValueError:
        raise ValueError(f"unsupported paper state: {state}") from None
    if next_state != current_state and next_state not in ALLOWED_TRANSITIONS[current_state]:
        raise ValueError(f"invalid paper state transition: {current_state.value} -> {next_state.value}")
    paper["state"] = next_state.value
    if artifact:
        key, separator, value = artifact.partition("=")
        if not separator or not key or not value:
            raise ValueError("artifact must use key=value")
        if key in Paper.ARTIFACTS:
            path = resolve_artifact(run_dir, value)
            if not path.is_file():
                raise ValueError("artifact file does not exist")
            value = str(path)
        paper["artifacts"][key] = value
    if next_state == PaperState.READ_BACK_VERIFIED:
        evidence = read_json(Path(verification)) if verification else paper.get("zotero", {})
        if "papers" in evidence:
            evidence = evidence["papers"].get(identity, {})
        try:
            Paper(run_dir, identity, paper).validate_read_back(evidence)
        except (ValueError, OSError) as error:
            raise ValueError(f"verification evidence invalid: {error}") from None
        paper["zotero"] = evidence
    if warning and warning not in paper["warnings"]:
        paper["warnings"].append(warning)
    manifest["events"].append({"at": utc_now(), "event": "paper_state_changed", "id": identity, "state": next_state.value})
    return paper


def command_import_pdfs(args: argparse.Namespace) -> None:
    """Verify and import a fixed ID/file mapping; CLI main already holds the run lock."""
    from paper_artifacts import verify
    mapping_path = Path(args.file).resolve()
    entries = read_json(mapping_path)
    if not isinstance(entries, list) or not entries:
        raise ValueError("PDF mapping must be a nonempty list of {id, pdf}")
    if any(not isinstance(e, dict) or not isinstance(e.get("id"), str)
           or not isinstance(e.get("pdf"), str) for e in entries):
        raise ValueError("each PDF mapping needs string id and pdf fields")
    identities = [e["id"] for e in entries]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate paper IDs in PDF mapping")
    run = Run.open(args.run_dir)
    run.require_confirmed()
    run.resolve_ids(identities)
    candidates = run.require_candidates(identities)
    results = []
    for entry in entries:
        identity = entry["id"]
        source = Path(entry["pdf"])
        if not source.is_absolute():
            source = mapping_path.parent / source
        staged: Path | None = None
        try:
            raw = source.read_bytes()
            directory = run.directory / "papers" / hashlib.sha256(identity.encode()).hexdigest()[:16]
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=directory, suffix=".pdf", delete=False) as handle:
                handle.write(raw)
                staged = Path(handle.name)
            candidate = candidates[identity]
            evidence, code = verify(staged, candidate.get("title") or "", candidate.get("doi"))
            if code:
                # The user's original input stays available even when it cannot be verified.
                evidence["path"] = str(source.resolve())
                results.append({"id": identity, **evidence})
                continue
            paper = run.paper(identity)
            target = paper.pdf or directory / "source.pdf"
            if target.exists() and target.read_bytes() != raw:
                raise ValueError("existing PDF differs; preserved existing source and derived artifacts")
            reused = paper.pdf is not None
            if not target.exists():
                staged.replace(target)
            if not reused:
                run.advance(identity, "pdf_acquired", artifact="pdf=" + str(target))
                run.save()
            results.append({"id": identity, **evidence, "path": str(target),
                            "action": "reused" if reused else "imported"})
        except (ValueError, OSError) as error:
            results.append({"id": identity, "status": "error", "reason": str(error)})
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)
    print(json.dumps({"status": "complete" if all(r["status"] == "verified" for r in results) else "partial",
                      "run_dir": str(run.directory), "papers": results,
                      "next_action": "convert the verified PDFs with process_run.py --stages convert; include the approved collection and storage-root"}, ensure_ascii=False))


def command_record_paper(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir).resolve()
    manifest = load_manifest(run_dir)
    apply_paper_update(run_dir, manifest, args.id, args.state,
                       artifact=args.artifact, warning=args.warning, verification=args.verification)
    save_manifest(run_dir, manifest)
    print(json.dumps({"id": args.id, "state": args.state}))


DELIVERED_STATES = {
    PaperState.READ_BACK_VERIFIED.value, PaperState.SYNC_PENDING.value,
    PaperState.METADATA_ONLY.value, PaperState.PARTIAL.value,
}


def paper_report(paper: Paper, title: str | None = None) -> dict[str, Any]:
    """One row of the delivery table: per-artifact truth, not one success rate.

    Cloud completion and local sync are separate columns because a verified
    cloud attachment is deliverable while Zotero Desktop is still downloading
    it, and a missing summary must never be hidden behind a written PDF.

    `pending` is computed from what the paper has right now, never from its
    warning history — a warning recorded before a retry succeeded must not
    keep a finished paper looking unfinished forever. The history stays in
    `notes`, which is why the two fields are separate.
    """
    evidence = paper.zotero
    attachments = evidence.get("attachments", {})
    has = {field: paper.path(field) is not None for field in Paper.ARTIFACTS}
    pending: list[str] = []
    if not has["pdf"]:
        pending.append("no full text" if paper.is_metadata_only else "PDF pending")
    if has["pdf"] and not has["markdown"]:
        pending.append(evidence.get("markdown_status") or "markdown_unavailable")
    if has["pdf"] and not has["summary"]:
        pending.append("summary pending")
    if has["pdf"] and not evidence.get("cloud_verified_at"):
        pending.append("Zotero write pending")
    local = None
    if attachments:
        local = all(record.get("local_verified") for record in attachments.values())
        if not local:
            pending.append("local sync not checked" if evidence.get("local_checked") is False
                           else "local sync pending")
    return {
        "id": paper.id,
        "title": title or paper.id,
        "state": paper.state,
        "pdf": has["pdf"],
        "markdown": has["markdown"],
        "summary": has["summary"],
        "cloud_verified_at": evidence.get("cloud_verified_at"),
        "local_synced": local,
        "pending": list(dict.fromkeys(pending)),
        # Observed history: why something went the way it did. Read alongside
        # `pending`, which says what is actually still missing now.
        "notes": list(dict.fromkeys(paper.warnings))[-3:],
        # Every artifact present, written and synced. A readable PDF alone is
        # not a complete paper, however far the Zotero write got.
        "complete": not pending and has["pdf"],
        # Whether re-running could still change this row. A paper with no
        # obtainable full text is finished, not waiting for another attempt.
        "actionable": bool(pending) and not paper.is_metadata_only,
    }


def render_report(rows: list[dict[str, Any]]) -> str:
    def mark(value: bool | None) -> str:
        return {True: "yes", False: "no", None: "-"}[value]
    lines = ["Paper | PDF | Markdown | Summary | Zotero cloud | Local sync | Pending",
             "--- | --- | --- | --- | --- | --- | ---"]
    for row in rows:
        # The latest note explains an incomplete row; a finished row needs no
        # postmortem of the attempts that got it there.
        reasons = row["pending"] + (row["notes"][-1:] if row["pending"] and row.get("notes") else [])
        lines.append(" | ".join([
            str(row["title"]).replace("|", "\\|"),
            mark(row["pdf"]), mark(row["markdown"]), mark(row["summary"]),
            "verified" if row["cloud_verified_at"] else "-",
            mark(row["local_synced"]),
            "; ".join(reasons) or "-",
        ]))
    return "\n".join(lines) + "\n"


def command_report(args: argparse.Namespace) -> None:
    run = Run.open(args.run_dir)
    rows = run.report()
    if args.format == "markdown":
        print(render_report(rows), end="")
        return
    print(json.dumps({
        "run_dir": str(run.directory),
        "collection": run.collection,
        "delivered": sum(1 for row in rows if row["state"] in DELIVERED_STATES),
        "papers": rows,
        "table": render_report(rows),
    }, ensure_ascii=False))


def command_status(args: argparse.Namespace) -> None:
    run = Run.open(args.run_dir)
    counts = Counter(paper.state for paper in run.papers())
    print(json.dumps({
        "run_dir": str(run.directory),
        "intent": run.manifest["intent"],
        "gates": run.manifest["gates"],
        "search": run.search(),
        "selected": len(run.selected),
        "paper_states": dict(sorted(counts.items())),
        "consents": run.manifest.get("consents", {}),
        "papers": {paper.id: paper.record for paper in run.papers()},
    }, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("--run-root", default="literature-runs")
    init.add_argument("--slug", required=True)
    init.add_argument("--intent", required=True)
    init.add_argument("--from-year", type=int)
    init.add_argument("--to-year", type=int)
    init.add_argument("--language", default="en-preferred")
    init.add_argument("--list-budget", type=int, default=DEFAULT_LIST_BUDGET)
    init.add_argument("--supplementary-budget", type=int, default=DEFAULT_SUPPLEMENTARY_BUDGET)
    init.add_argument("--search-seconds", type=float, default=DEFAULT_SEARCH_SECONDS)
    init.set_defaults(func=command_init)

    for name in ("record-scope", "approve-plan"):
        scope = commands.add_parser(name, help="record the interpreted retrieval scope (evidence, not a gate)")
        scope.add_argument("--run-dir", required=True)
        scope.add_argument("--scope", "--plan", dest="scope", required=True)
        scope.set_defaults(func=command_record_scope)

    search = commands.add_parser("record-search")
    search.add_argument("--run-dir", required=True)
    search.add_argument("--round", choices=("initial", "supplementary"), required=True)
    search.add_argument("--provider", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--reason", required=True)
    search.add_argument("--elapsed-seconds", type=float, default=0.0)
    search.add_argument("--user-requested", action="store_true",
                        help="the user asked to widen coverage; exempt from the default ceiling")
    search.set_defaults(func=command_record_search)

    import_candidates = commands.add_parser("import-candidates")
    import_candidates.add_argument("--run-dir", required=True)
    import_candidates.add_argument("--file", required=True)
    import_candidates.set_defaults(func=command_import_candidates)

    approve_candidates = commands.add_parser("approve-candidates")
    approve_candidates.add_argument("--run-dir", required=True)
    approve_candidates.add_argument("--ids", required=True)
    approve_candidates.add_argument("--source", default="user-selection")
    approve_candidates.add_argument("--rule", default="explicit IDs")
    approve_candidates.set_defaults(func=command_approve_candidates)

    consent = commands.add_parser("consent")
    consent.add_argument("--run-dir", required=True)
    consent.add_argument("--service", choices=("mineru",), required=True)
    consent.add_argument("--decision", choices=("approved", "denied", "revoked"), required=True)
    consent.add_argument("--source", required=True)
    consent.add_argument("--ids")
    consent.set_defaults(func=command_consent)

    pdfs = commands.add_parser("import-pdfs", help="verify/copy/record selected local PDFs in one call")
    pdfs.add_argument("--run-dir", required=True)
    pdfs.add_argument("--file", required=True, help="JSON [{id, pdf}]; relative PDF paths resolve from this mapping file")
    pdfs.set_defaults(func=command_import_pdfs)

    record = commands.add_parser("record-paper")
    record.add_argument("--run-dir", required=True)
    record.add_argument("--id", required=True)
    record.add_argument("--state", required=True)
    record.add_argument("--artifact")
    record.add_argument("--warning")
    record.add_argument("--verification", help="Zotero writer journal or per-paper read-back evidence")
    record.set_defaults(func=command_record_paper)

    status = commands.add_parser("status")
    status.add_argument("--run-dir", required=True)
    status.set_defaults(func=command_status)

    report = commands.add_parser("report", help="per-artifact delivery table for the user")
    report.add_argument("--run-dir", required=True)
    report.add_argument("--format", choices=("json", "markdown"), default="json")
    report.set_defaults(func=command_report)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        if hasattr(args, 'run_dir') and args.command not in ('status', 'report'):
            with run_lock(Path(args.run_dir).resolve()):
                args.func(args)
        else:
            args.func(args)
    except (ValueError, OSError) as error:
        fail(str(error))


if __name__ == "__main__":
    main()
