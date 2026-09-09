#!/usr/bin/env python3
"""Turn one topic into one deduplicated candidate list, across sources.

Two services now answer the same question, so two things need an owner that
neither of them can be: deciding when two records are the same paper, and
keeping every request inside the run's single retrieval budget.

**Identity.** A normalized DOI is the same paper, full stop. Without one, the
test is deliberately hard to pass — same normalized title, same year, same
first-author surname — because a wrong merge destroys a candidate silently
while a missed merge only shows the user two rows. Disagreements between two
sources about the same paper are recorded in `conflicts` rather than resolved
by whichever source was asked first, and a preprint is related to its version
of record, never folded into it.

**Budget.** The run's retrieval budget covers everything: both rounds, every
source, paging, throttle waits, failures and retries. Time already spent is
read from the run before each source is asked, so a restart continues where
the ledger left off instead of starting a fresh five minutes.

**Partial delivery.** One source being rate-limited, unauthenticated or down
is recorded as that, and the candidates from the other source are still
delivered. Only a source that genuinely answered "nothing" contributes an
absence, and a failed source is never allowed to look like one.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sources as source_module  # noqa: E402
import workflow  # noqa: E402
from sources import Answer, Query, Sources  # noqa: E402

# One source may not eat the whole run budget while another waits behind it.
PER_SOURCE_CEILING = 40.0
STOPWORDS = {"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"}
# Fields where two sources describing one paper may legitimately differ in
# wording, and where a difference is worth recording rather than overwriting.
COMPARED = ("title", "year", "venue")


@dataclass(frozen=True)
class DiscoveryRequest:
    """One retrieval round, in checkable types."""
    query: Query
    output: Path
    sources: Sequence[str] = source_module.DISCOVERY_SOURCES
    run_dir: Path | None = None
    round: str = "initial"
    reason: str = ""
    user_requested: bool = False
    fixtures: Mapping[str, Path] = field(default_factory=dict)


# ── Identity ───────────────────────────────────────────────────────────────

def normalized_title(value: Any) -> str:
    tokens = [token for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
              if token not in STOPWORDS]
    return " ".join(tokens)


def surname(value: Any) -> str:
    parts = re.findall(r"[a-z]+", str(value or "").lower())
    return parts[-1] if parts else ""


def identity(candidate: Mapping[str, Any]) -> str:
    """The key two records must share to be the same paper.

    A DOI is decisive. Without one the key deliberately includes the year and
    the first author's surname, so two same-titled papers from different years
    stay two candidates. A record with no title at all keeps its own source
    identity and merges with nothing.
    """
    identifiers = candidate.get("identifiers") or {}
    doi = source_module.canonical_doi(candidate.get("doi") or identifiers.get("doi"))
    if doi:
        return f"doi:{doi}"
    title = normalized_title(candidate.get("title"))
    if not title:
        return f"id:{candidate.get('id')}"
    authors = candidate.get("authors") or []
    return f"work:{title}|{candidate.get('year') or ''}|{surname(authors[0] if authors else '')}"


def _merge_identifiers(into: dict[str, Any], other: Mapping[str, Any],
                       conflicts: list[dict[str, Any]], label: str) -> None:
    for name, value in (other.get("identifiers") or {}).items():
        if value in (None, ""):
            continue
        existing = into.setdefault("identifiers", {}).get(name)
        if existing in (None, ""):
            into["identifiers"][name] = value
        elif str(existing) != str(value):
            conflicts.append({"field": f"identifiers.{name}", "kept": existing,
                              "reported": value, "source": label})


def combine(first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, Any]:
    """One paper described twice. Keeps both accounts, resolves nothing silently."""
    merged = dict(first)
    merged["identifiers"] = dict(merged.get("identifiers") or {})
    label = (second.get("sources") or ["unknown"])[0]
    conflicts: list[dict[str, Any]] = list(merged.get("conflicts") or [])

    for name in COMPARED:
        mine, theirs = merged.get(name), second.get(name)
        if theirs in (None, ""):
            continue
        if mine in (None, ""):
            merged[name] = theirs
        elif name == "title":
            if normalized_title(mine) != normalized_title(theirs):
                conflicts.append({"field": name, "kept": mine, "reported": theirs, "source": label})
        elif str(mine) != str(theirs):
            conflicts.append({"field": name, "kept": mine, "reported": theirs, "source": label})

    for name in ("publication_date", "venue_type", "work_type", "language", "abstract",
                 "landing_page_url", "oa_pdf_url", "is_oa", "oa_status", "doi",
                 "openalex_id", "semantic_scholar_id"):
        if merged.get(name) in (None, "", []) and second.get(name) not in (None, "", []):
            merged[name] = second[name]
            if name == "abstract":
                merged["abstract_source"] = second.get("abstract_source")
    if not merged.get("authors") and second.get("authors"):
        merged["authors"] = second["authors"]

    _merge_identifiers(merged, second, conflicts, label)
    merged["sources"] = list(dict.fromkeys([*(merged.get("sources") or []), *(second.get("sources") or [])]))
    # Every source's count survives with its own date: a citation number is an
    # observation by somebody at some time, not a property of the paper.
    seen = {(entry.get("source"), entry.get("observed_at")) for entry in merged.get("citations") or []}
    merged["citations"] = [*(merged.get("citations") or []),
                           *[entry for entry in second.get("citations") or []
                             if (entry.get("source"), entry.get("observed_at")) not in seen]]
    if merged.get("cited_by_count") is None and second.get("cited_by_count") is not None:
        merged.update({"cited_by_count": second["cited_by_count"],
                       "citation_source": second.get("citation_source"),
                       "citation_observed_at": second.get("citation_observed_at")})
    known = {entry["url"] for entry in merged.get("locations") or []}
    merged["locations"] = [*(merged.get("locations") or []),
                           *[entry for entry in second.get("locations") or [] if entry["url"] not in known]]
    if conflicts:
        merged["conflicts"] = conflicts
    return merged


# arXiv mints a DOI for the preprint itself. A `10.48550/arXiv.*` DOI is
# therefore evidence of a preprint, and saying it proves a version of record
# would promote every unpublished paper to published.
ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.", re.I)


def versions(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The versions of this work that are known to exist, and how they relate.

    A DOI and an arXiv id on one record usually mean a preprint *and* a
    version of record exist. Saying so keeps acquisition honest later:
    downloading the preprint is a real result, and it is not the version of
    record. The exception is arXiv's own DOI, which names the preprint.
    """
    identifiers = candidate.get("identifiers") or {}
    doi = candidate.get("doi")
    found: list[dict[str, Any]] = []
    if identifiers.get("arxiv"):
        found.append({"version": "preprint", "identifier": f"arXiv:{identifiers['arxiv']}"})
    if doi and ARXIV_DOI.match(str(doi)):
        if not identifiers.get("arxiv"):
            found.append({"version": "preprint", "identifier": f"doi:{doi}"})
    elif doi:
        found.append({"version": "published", "identifier": f"doi:{doi}"})
    for entry in candidate.get("locations") or []:
        if entry.get("version") in ("preprint", "accepted", "published"):
            if not any(item["version"] == entry["version"] for item in found):
                found.append({"version": entry["version"], "identifier": entry["url"]})
    return found


def merge(batches: Sequence[Sequence[Mapping[str, Any]]]) -> tuple[list[dict[str, Any]], int]:
    """Fold every source's candidates into one list. Returns (candidates, merged)."""
    ordered: dict[str, dict[str, Any]] = {}
    merged_count = 0
    for batch in batches:
        for candidate in batch:
            key = identity(candidate)
            if key in ordered:
                ordered[key] = combine(ordered[key], candidate)
                merged_count += 1
            else:
                ordered[key] = dict(candidate)
    for candidate in ordered.values():
        found = versions(candidate)
        if found:
            candidate["versions"] = found
    return list(ordered.values()), merged_count


# ── Budget ─────────────────────────────────────────────────────────────────

class Budget:
    """The run's one retrieval budget, read before anything is spent.

    Time already spent lives in the run ledger, so a restart continues the same
    budget instead of starting a fresh one. With no run, discovery is a
    one-off command and the ceiling is the default budget for a single round.
    """

    def __init__(self, run_dir: Path | None) -> None:
        self.run_dir = run_dir
        summary = (workflow.Run.open(run_dir).search()
                   if run_dir and workflow.Run.exists(run_dir) else None)
        self.total = float(summary["budget_seconds"]) if summary else workflow.DEFAULT_SEARCH_SECONDS
        self.spent = float(summary["elapsed_seconds"]) if summary else 0.0
        self.started = time.monotonic()

    def remaining(self) -> float:
        return max(0.0, self.total - self.spent - (time.monotonic() - self.started))

    def elapsed(self) -> float:
        return time.monotonic() - self.started


# ── Retrieval ──────────────────────────────────────────────────────────────

def discover(request: DiscoveryRequest, client: Sources | None = None) -> dict[str, Any]:
    """Run one retrieval round over every requested source and write the list."""
    client = client or Sources()
    budget = Budget(request.run_dir)
    timestamp = source_module.observed_at()
    batches: list[list[dict[str, Any]]] = []
    outcomes: list[dict[str, Any]] = []
    raw_total = 0

    for name in request.sources:
        fixture = request.fixtures.get(name)
        if fixture is not None:
            payload = json.loads(Path(fixture).read_text(encoding="utf-8"))
            records = list(payload.get("results") or payload.get("data") or [])
            answer = Answer(source=name, question="search", status="ok" if records else "empty",
                            records=records, detail="fixture", observed_at=timestamp)
        elif budget.remaining() <= 0:
            # Recorded, not silently dropped: an unasked source is a coverage
            # fact the user is entitled to see next to the results.
            answer = Answer(source=name, question="search", status="skipped",
                            detail="retrieval budget spent", observed_at=timestamp)
        else:
            answer = client.search(name, request.query,
                                   budget=min(budget.remaining(), PER_SOURCE_CEILING, client.budget))
        outcomes.append(answer.report())
        raw_total += len(answer.records)
        batches.append([source_module.normalize(name, record, timestamp) for record in answer.records])

    candidates, merged_count = merge(batches)
    delivered = [entry for entry in outcomes if entry["status"] in ("ok", "empty")]
    failed = [entry for entry in outcomes if entry["status"] not in ("ok", "empty")]

    output = Path(request.output)
    # A network fact never becomes an empty result set. When no source
    # answered, the round has learned nothing about the literature, and
    # writing `[]` would destroy whatever a previous round put here — which,
    # when the output is the run's own `candidates.json`, is the approved
    # selection itself.
    if delivered:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result: dict[str, Any] = {
        "query": request.query.text,
        "sources": outcomes,
        "source_count": raw_total,
        "returned": len(candidates),
        "duplicates_removed": merged_count,
        "output": str(output.resolve()),
        "wrote_output": bool(delivered),
        "observed_at": timestamp,
        "elapsed_seconds": round(budget.elapsed(), 3),
        # One word for how the round went, so no caller has to infer it from
        # an empty list. `failed` means nobody answered — which is a fact
        # about the network, never a fact about the literature.
        "status": "ok" if not failed else ("partial" if delivered else "failed"),
        # A round that lost a source still delivers; the report says which.
        "partial": bool(failed) and bool(delivered),
        "failed_sources": [entry["source"] for entry in failed],
    }
    if request.run_dir:
        log_query(request, result)
        if workflow.Run.exists(request.run_dir):
            result["search"] = record_round(request, result["elapsed_seconds"])
    return result


def log_query(request: DiscoveryRequest, result: Mapping[str, Any]) -> None:
    """Append this round's provenance to the run's query log."""
    assert request.run_dir is not None
    path = request.run_dir / "queries.json"
    queries = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    queries.append({
        "provider": "+".join(source_module.LABELS.get(name, name) for name in request.sources),
        "query": request.query.text,
        "round": request.round,
        "reason": request.reason,
        "filters": {"from_year": request.query.from_year, "to_year": request.query.to_year},
        "sent_fields": list(dict.fromkeys(
            field for name in request.sources for field in source_module.SENT_FIELDS.get(name, []))),
        "observed_at": result["observed_at"],
        "elapsed_seconds": result["elapsed_seconds"],
        "source_count": result["source_count"],
        "returned": result["returned"],
        "duplicates_removed": result["duplicates_removed"],
        "sources": result["sources"],
        "input_source": "fixture" if request.fixtures else "live_api",
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record_round(request: DiscoveryRequest, elapsed: float) -> dict[str, Any]:
    """Charge this round to the run's shared budget, however it went.

    Failures and throttle waits are charged too: they cost the user the same
    minutes a successful round does, and a budget that only counted successes
    would never stop.
    """
    assert request.run_dir is not None
    provider = "+".join(source_module.LABELS.get(name, name) for name in request.sources)
    with workflow.Run.locked(request.run_dir) as run:
        summary = run.record_search(request.round, provider, request.query.text,
                                    request.reason, elapsed, request.user_requested)
        run.save()
        return summary


def claim_round(request: DiscoveryRequest) -> None:
    """Refuse a round the run cannot afford, before any time is spent."""
    run_dir = request.run_dir
    if request.round == "supplementary":
        if not run_dir or not workflow.Run.exists(run_dir):
            workflow.fail("a supplementary round needs --run-dir with an initialized run")
        if not request.reason:
            workflow.fail("a supplementary round needs --reason")
    if not run_dir or not workflow.Run.exists(run_dir):
        return
    summary = workflow.Run.open(run_dir).search()
    if (request.round == "supplementary" and not request.user_requested
            and summary["supplementary_remaining"] <= 0):
        workflow.fail("supplementary search budget is spent; report coverage instead of another round")
    if Budget(run_dir).remaining() <= 0:
        # Refuse the round rather than run one that can ask nobody: an
        # all-skipped round costs a command and teaches the user nothing.
        workflow.fail(f"the run's {summary['budget_seconds']}s retrieval budget is spent "
                      f"({summary['elapsed_seconds']}s used); report coverage instead of another round")


def parse_fixtures(values: Sequence[str] | None, default_source: str) -> dict[str, Path]:
    """`--input-json path` or `--input-json source=path`, for offline rounds."""
    fixtures: dict[str, Path] = {}
    for value in values or []:
        name, separator, path = value.partition("=")
        fixtures[name if separator else default_source] = Path(path if separator else value)
    return fixtures


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--query", required=True)
    parser.add_argument("--from-year", type=int)
    parser.add_argument("--to-year", type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-dir", help="Append query provenance to this run package")
    parser.add_argument("--round", choices=("initial", "supplementary"), default="initial",
                        help="a supplementary round spends the run's single default top-up")
    parser.add_argument("--reason", default="", help="why this round runs; required for a supplementary round")
    parser.add_argument("--user-requested", action="store_true",
                        help="the user asked to widen coverage beyond the default ceiling")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    parser.add_argument("--sources", default=",".join(source_module.DISCOVERY_SOURCES),
                        help="Comma-separated subset of: " + ", ".join(source_module.DISCOVERY_SOURCES))
    parser.add_argument("--limit", type=int, default=50, help="records requested per source")
    parser.add_argument("--input-json", action="append", metavar="SOURCE=PATH",
                        help="Use a saved response for one source instead of the network")
    return parser


def request_from_args(args: argparse.Namespace, names: Sequence[str]) -> DiscoveryRequest:
    return DiscoveryRequest(
        query=Query(text=args.query, from_year=args.from_year, to_year=args.to_year,
                    limit=int(getattr(args, "limit", None) or getattr(args, "per_page", None) or 50)),
        output=Path(args.output),
        sources=list(names),
        run_dir=Path(args.run_dir).resolve() if args.run_dir else None,
        round=args.round, reason=args.reason, user_requested=args.user_requested,
        fixtures=parse_fixtures(args.input_json, names[0] if names else "openalex"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    names = [name for name in args.sources.split(",") if name.strip()]
    unknown = [name for name in names if name not in source_module.DISCOVERY_SOURCES]
    if unknown:
        workflow.fail("unknown discovery source(s): " + ", ".join(unknown))
    request = request_from_args(args, names)
    claim_round(request)
    result = discover(request)
    print(json.dumps(result, ensure_ascii=False))
    # A round nobody answered is a failure a caller must see, not a quiet
    # success that happened to return no papers.
    return 2 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
