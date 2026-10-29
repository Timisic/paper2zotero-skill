#!/usr/bin/env python3
"""Turn local PDFs into verified candidates, then Markdown, without a search round.

The caller already has the file. This command reads a DOI or title from it,
completes the bibliographic record from Crossref and OpenAlex, appends a
candidate without replacing one that is already stored, and verifies the PDF
with the same identity check as ``import-pdfs``.

Markdown conversion is ``process_run.stage_convert`` (MinerU). Upload needs
recorded consent for the verified ids. Without that consent the command stops
after import and names the consent step. It does not upload. ``--backend local``
writes on-machine text instead and does not record consent.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paper_artifacts  # noqa: E402
import process_run  # noqa: E402
import sources  # noqa: E402
import workflow  # noqa: E402

# A title match this strong is the same work. Anything weaker must not donate
# its DOI: nearby papers share ordinary words, and a borrowed DOI would become
# the primary identity of the wrong file.
CONFIDENT_TITLE_OVERLAP = 0.8
SELECTION_SOURCE = "local-pdf: user supplied the PDF"
SELECTION_RULE = "files the user or agent already has"
CLOUD_CONSENT_WARNING = "markdown_unavailable: cloud MinerU upload consent required"


class BibliographyClient(Protocol):
    """The two lookups this path needs. ``Sources`` is the production client."""

    def work(self, source: str, doi: str, *, budget: float | None = None) -> sources.Answer: ...

    def search(self, source: str, query: sources.Query, *, budget: float | None = None) -> sources.Answer: ...

    def bibliographic(self, title: str, *, rows: int = 5, budget: float | None = None) -> sources.Answer: ...


def full_text(pdf: Path) -> str:
    """The whole PDF as text. Identity checks only need the front; conversion does not."""
    executable = shutil.which("pdftotext")
    if not executable:
        return ""
    try:
        completed = subprocess.run(
            [executable, "-enc", "UTF-8", str(pdf), "-"],
            text=True, encoding="utf-8", errors="replace",
            capture_output=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (completed.stdout or "") if completed.returncode == 0 else ""


def extract_document(pdf: Path) -> tuple[str, str]:
    text = full_text(pdf)
    if paper_artifacts.has_words(text):
        return text, "pdftotext"
    return paper_artifacts.extract_text(pdf)


def usable_title(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" .-")
    if len(paper_artifacts.title_tokens(cleaned)) < paper_artifacts.MIN_TITLE_TOKENS:
        return None
    return cleaned[:300]


def guess_title(text: str) -> str | None:
    """The title is the first substantial line before the abstract, not a DOI line."""
    front = text[:2500]
    cut = re.search(r"\babstract\b", front, re.I)
    head = front[:cut.start()] if cut else front
    lines = [re.sub(r"\s+", " ", line).strip(" -\t") for line in re.split(r"[\r\n]+", head)]
    lines = [line for line in lines if line and not re.search(r"\b10\.\d{4,9}/", line)
             and not line.lower().startswith("http")]
    if len(lines) >= 2:
        for line in lines[:8]:
            title = usable_title(line)
            if title:
                return title
        return None
    blob = re.sub(r"https?://\S+", " ", re.sub(r"\s+", " ", head))
    blob = re.sub(r"\b10\.\d{4,9}/\S+", " ", blob)
    return usable_title(" ".join(blob.split()[:18]))


def first_printed_doi(text: str) -> str | None:
    """The first declared DOI in the front matter. Later DOIs belong to the references."""
    for match in paper_artifacts.DOI_IN_TEXT.finditer(text[:paper_artifacts.FRONT_MATTER_CHARS]):
        value = match.group(0).rstrip(".").lower()
        if not paper_artifacts.placeholder_doi(value):
            return sources.canonical_doi(value)
    return None


def extract_pdf(pdf: Path) -> dict[str, Any]:
    if not pdf.is_file():
        return {"status": "extraction_failed", "reason": "file does not exist",
                "doi": None, "title": None, "text": "", "extractor": "none"}
    text, extractor = extract_document(pdf)
    if extractor == "none" or not text.strip():
        return {"status": "extraction_failed", "reason": "no readable text could be extracted from this PDF",
                "doi": None, "title": None, "text": "", "extractor": extractor}
    doi = first_printed_doi(text)
    title = guess_title(text)
    if not doi and not title:
        return {"status": "extraction_failed", "reason": "no DOI or usable title could be read from this PDF",
                "doi": None, "title": None, "text": text, "extractor": extractor}
    return {"status": "ok", "reason": "", "doi": doi, "title": title, "text": text, "extractor": extractor}


def title_overlap(expected: str, observed: str | None) -> float:
    tokens = paper_artifacts.title_tokens(expected)
    if not tokens or not observed:
        return 0.0
    packed = paper_artifacts.despace(observed)
    return sum(token in packed for token in tokens) / len(tokens)


def record_title(source: str, record: Mapping[str, Any]) -> str:
    if source == "crossref":
        titles = record.get("title") or []
        return str(titles[0]) if isinstance(titles, list) and titles else ""
    return str(record.get("title") or "")


def candidate_from_crossref(record: Mapping[str, Any], timestamp: str) -> dict[str, Any] | None:
    doi = sources.canonical_doi(str(record.get("DOI") or ""))
    titles = record.get("title") or []
    title = titles[0] if isinstance(titles, list) and titles else None
    if not isinstance(title, str) or not title.strip():
        return None
    authors: list[str] = []
    for person in record.get("author") or []:
        if not isinstance(person, dict):
            continue
        name = " ".join(part for part in (person.get("given"), person.get("family"))
                        if isinstance(part, str) and part)
        if name:
            authors.append(name)
    raw_issued = record.get("issued")
    issued: dict[str, Any] = raw_issued if isinstance(raw_issued, dict) else {}
    raw_parts = issued.get("date-parts")
    year: int | None = None
    if isinstance(raw_parts, list) and raw_parts:
        first = raw_parts[0]
        if isinstance(first, list):
            first = first[0] if first else None
        if isinstance(first, int):
            year = first
    container = record.get("container-title") or []
    venue = container[0] if isinstance(container, list) and container else None
    candidate: dict[str, Any] = {
        "doi": doi,
        "title": title.strip(),
        "year": year,
        "authors": authors,
        "venue": venue if isinstance(venue, str) else None,
        "abstract": record.get("abstract") if isinstance(record.get("abstract"), str) else None,
        "identifiers": {"doi": doi} if doi else {},
        "locations": sources.locations("crossref", record),
        "observed_at": timestamp,
        "sources": [sources.LABELS["crossref"]],
        "hit_reason": "user supplied a local PDF",
        "metadata_origin": "crossref",
    }
    candidate["id"] = f"doi:{doi}" if doi else sources.title_key(candidate)
    return candidate


def candidate_from_work(source: str, record: Mapping[str, Any]) -> dict[str, Any] | None:
    if source == "openalex":
        candidate = sources.normalize("openalex", record, sources.observed_at())
        if not candidate.get("title"):
            return None
        candidate["hit_reason"] = "user supplied a local PDF"
        candidate["metadata_origin"] = "openalex"
        return candidate
    if source == "crossref":
        return candidate_from_crossref(record, sources.observed_at())
    return None


def candidate_from_pdf(doi: str | None, title: str, origin: str) -> dict[str, Any]:
    """A record built only from the file, used when a lookup cannot complete it."""
    return {
        "id": f"doi:{doi}" if doi else sources.title_key({"title": title, "year": None}),
        "doi": doi,
        "title": title,
        "year": None,
        "authors": [],
        "sources": ["local-pdf"],
        "hit_reason": "user supplied a local PDF",
        "metadata_origin": origin,
        "identifiers": {"doi": doi} if doi else {},
    }


def lookup_doi(client: BibliographyClient, doi: str) -> tuple[dict[str, Any] | None, str | None]:
    """Complete one printed DOI. OpenAlex wins when both answered; neither invents a DOI."""
    found: dict[str, Mapping[str, Any]] = {}
    failures: list[str] = []
    expected = sources.canonical_doi(doi)
    for source in ("crossref", "openalex"):
        answer = client.work(source, doi)
        if answer.status == "ok" and answer.records and isinstance(answer.records[0], dict):
            found[source] = answer.records[0]
        elif answer.status not in ("empty", "not_found"):
            failures.append(f"{source}:{answer.status}")
    for source in ("openalex", "crossref"):
        record = found.get(source)
        if record is None:
            continue
        candidate = candidate_from_work(source, record)
        if candidate and sources.canonical_doi(candidate.get("doi")) == expected:
            return candidate, None
    if failures:
        return None, ("metadata_degraded: DOI lookup failed (" + ", ".join(failures)
                      + "); kept the DOI printed in the PDF")
    return None, "metadata_degraded: DOI lookup found no record; kept the DOI printed in the PDF"


def lookup_title(client: BibliographyClient, title: str) -> tuple[dict[str, Any] | None, str | None]:
    """Find one known title. A weak hit is refused so its DOI cannot label this file."""
    hits: list[tuple[str, Mapping[str, Any]]] = []
    failures: list[str] = []
    bibliographic = client.bibliographic(title)
    if bibliographic.ok:
        hits.extend(("crossref", record) for record in bibliographic.records if isinstance(record, dict))
    else:
        failures.append(f"crossref:{bibliographic.status}")
    searched = client.search("openalex", sources.Query(text=title, limit=5))
    if searched.ok:
        hits.extend(("openalex", record) for record in searched.records if isinstance(record, dict))
    else:
        failures.append(f"openalex:{searched.status}")
    best: tuple[str, Mapping[str, Any]] | None = None
    best_score = 0.0
    for source, record in hits:
        score = title_overlap(title, record_title(source, record))
        if score > best_score:
            best, best_score = (source, record), score
    if best is not None and best_score >= CONFIDENT_TITLE_OVERLAP:
        candidate = candidate_from_work(*best)
        if candidate and candidate.get("title"):
            return candidate, None
    if failures and not hits:
        return None, "metadata_degraded: no DOI; bibliographic lookup failed (" + ", ".join(failures) + ")"
    return None, "metadata_degraded: no DOI and no confident bibliographic match"


def load_candidates(run_dir: Path) -> list[Any]:
    path = run_dir / "candidates.json"
    if not path.is_file():
        return []
    payload = workflow.read_json(path)
    if not isinstance(payload, list):
        raise ValueError("candidates.json must be a list")
    return payload


def find_candidate(existing: Sequence[Any], *, doi: str | None = None, identity: str | None = None) -> dict[str, Any] | None:
    doi_norm = sources.canonical_doi(doi) if doi else None
    for item in existing:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        if identity and item.get("id") == identity:
            return item
        item_doi = sources.canonical_doi(item.get("doi")) if item.get("doi") else None
        if doi_norm and (item_doi == doi_norm or item.get("id") == f"doi:{doi_norm}"):
            return item
    return None


def display_title(title: str | None, pdf: Path) -> str:
    if title:
        return title
    stem = re.sub(r"\s+", " ", pdf.stem.replace("_", " ").replace("-", " ")).strip()
    return stem or "Untitled local PDF"


def resolve_candidate(client: BibliographyClient, extracted: Mapping[str, Any], pdf: Path,
                      existing: Sequence[Any]) -> dict[str, Any]:
    """Bibliographic completion. An already stored work is returned untouched."""
    doi = extracted.get("doi")
    title = extracted.get("title")
    if isinstance(doi, str) and doi:
        stored = find_candidate(existing, doi=doi)
        if stored:
            return {"metadata": "existing", "candidate": stored, "warning": None, "id": stored["id"]}
        found, warning = lookup_doi(client, doi)
        if found:
            stored = find_candidate(existing, doi=found.get("doi"), identity=str(found["id"]))
            if stored:
                return {"metadata": "existing", "candidate": stored, "warning": None, "id": stored["id"]}
            return {"metadata": "enriched", "candidate": found, "warning": None, "id": found["id"]}
        candidate = candidate_from_pdf(doi, display_title(title if isinstance(title, str) else None, pdf), "pdf-extract")
        return {"metadata": "degraded", "candidate": candidate, "warning": warning, "id": candidate["id"]}
    if not isinstance(title, str) or not title:
        raise ValueError("extraction succeeded without a DOI or a title")
    found, warning = lookup_title(client, title)
    if found:
        stored = find_candidate(existing, doi=found.get("doi"), identity=str(found["id"]))
        if stored:
            return {"metadata": "existing", "candidate": stored, "warning": None, "id": stored["id"]}
        return {"metadata": "enriched", "candidate": found, "warning": None, "id": found["id"]}
    candidate = candidate_from_pdf(None, title, "pdf-extract")
    stored = find_candidate(existing, identity=candidate["id"])
    if stored:
        return {"metadata": "existing", "candidate": stored, "warning": None, "id": stored["id"]}
    return {"metadata": "degraded", "candidate": candidate, "warning": warning, "id": candidate["id"]}


def add_candidates(run_dir: Path, existing: list[Any], added: Sequence[Mapping[str, Any]]) -> None:
    if not added:
        return
    workflow.write_json(run_dir / "candidates.json", existing)
    manifest = workflow.load_manifest(run_dir)
    for candidate in added:
        manifest["papers"].setdefault(str(candidate["id"]), {
            "state": workflow.PaperState.DISCOVERED.value, "artifacts": {}, "warnings": [],
        })
    manifest["events"].append({
        "at": workflow.utc_now(), "event": "local_pdf_candidates_added",
        "ids": [str(candidate["id"]) for candidate in added],
    })
    workflow.save_manifest(run_dir, manifest)


def render_local_markdown(title: str, doi: str | None, text: str) -> str:
    doi_line = f"DOI: {doi}\n\n" if doi else ""
    return (f"# {title}\n\n{doi_line}"
            "<!-- converter: local-text; not a MinerU layout parse -->\n\n"
            f"{text.strip()}\n")


def write_local_markdown(pdf: Path, title: str, doi: str | None, text: str) -> Path:
    target = pdf.parent / "local-text" / "paper.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_local_markdown(title, doi, text), encoding="utf-8")
    return target


def convert_local(run_dir: Path, plan: dict[str, Any], imported: Mapping[str, Any]) -> None:
    identity = str(plan["id"])
    run = workflow.Run.open(run_dir)
    paper = run.paper(identity)
    if paper.markdown:
        plan["markdown"] = str(paper.markdown)
        plan["convert"] = "reused"
        plan["status"] = "converted"
        return
    target = write_local_markdown(
        Path(str(imported["path"])),
        str(plan["candidate"].get("title") or identity),
        plan["candidate"].get("doi"),
        str(plan.get("text") or ""),
    )
    run.advance(identity, "markdown_derived", artifact="markdown=" + str(target))
    run.save()
    plan["markdown"] = str(target)
    plan["convert"] = "done"
    plan["status"] = "converted"


def mineru_ready(run_dir: Path, plans: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    verified = [plan for plan in plans if plan.get("import_status") == "verified"]
    package = workflow.Run.open(run_dir)
    ready: list[dict[str, Any]] = []
    for plan in verified:
        if package.consented("mineru", [str(plan["id"])]):
            ready.append(plan)
            continue
        plan["status"] = "consent_required"
        plan["convert"] = "consent_required"
        plan["reason"] = CLOUD_CONSENT_WARNING
        run = workflow.Run.open(run_dir)
        run.advance(str(plan["id"]), warning=CLOUD_CONSENT_WARNING)
        run.save()
        package = run
    return ready


def record_mineru_markdown(run_dir: Path, ready: Sequence[dict[str, Any]], outcome: Mapping[str, Any]) -> None:
    raw_failed = outcome.get("failed")
    raw_skipped = outcome.get("skipped")
    failed = raw_failed if isinstance(raw_failed, dict) else {}
    skipped = raw_skipped if isinstance(raw_skipped, dict) else {}
    for plan in ready:
        paper = workflow.Run.open(run_dir).paper(str(plan["id"]))
        if paper.markdown:
            plan["markdown"] = str(paper.markdown)
            plan["convert"] = "done"
            plan["status"] = "converted"
            continue
        plan["status"] = "convert_failed"
        plan["convert"] = "failed"
        plan["reason"] = failed.get(plan["id"]) or skipped.get(plan["id"])


def public_paper(plan: Mapping[str, Any]) -> dict[str, Any]:
    raw_candidate = plan.get("candidate")
    candidate: dict[str, Any] = raw_candidate if isinstance(raw_candidate, dict) else {}
    return {
        "id": plan.get("id"),
        "pdf": str(plan["pdf"]),
        "status": plan.get("status"),
        "metadata": plan.get("metadata"),
        "doi": candidate.get("doi"),
        "title": candidate.get("title"),
        "warning": plan.get("warning"),
        "reason": plan.get("reason") or None,
        "import_status": plan.get("import_status"),
        "markdown": plan.get("markdown"),
    }


def run_local_pdfs(run_dir: Path, pdfs: Sequence[Path], *, backend: str = "cloud",
                   collection_name: str | None = None, collection_key: str | None = None,
                   storage_root: Path | None = None, client: BibliographyClient | None = None) -> dict[str, Any]:
    if backend not in ("local", "cloud"):
        raise ValueError("backend must be local or cloud")
    if not pdfs:
        raise ValueError("at least one PDF is required")
    run_dir = workflow.absolute_path(run_dir)
    if not workflow.Run.exists(run_dir):
        raise ValueError(f"run package has no manifest: {run_dir}")
    bibliography = client or sources.Sources(browser=None, attempts=2, timeout=8, budget=12)
    with workflow.run_lock(run_dir):
        plans, identities, ready = _run_local_pdfs(
            run_dir, pdfs, backend=backend, client=bibliography)
    if ready:
        convert_ids = [str(plan["id"]) for plan in ready]
        outcome = process_run.stage_convert(
            process_run.ProcessRequest(run_dir=run_dir, ids=convert_ids, stages=("convert",)),
            convert_ids,
        )
        record_mineru_markdown(run_dir, ready, outcome)
    return finish(run_dir, plans, identities, backend=backend, collection_name=collection_name,
                  collection_key=collection_key, storage_root=storage_root)


def _run_local_pdfs(run_dir: Path, pdfs: Sequence[Path], *, backend: str,
                    client: BibliographyClient) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    existing = load_candidates(run_dir)
    plans: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    for pdf in pdfs:
        path = Path(pdf)
        extracted = extract_pdf(path)
        plan: dict[str, Any] = {"pdf": path, "text": extracted.get("text") or "", "status": extracted["status"],
                                "reason": extracted.get("reason") or "", "metadata": "failed", "warning": None}
        if extracted["status"] != "ok":
            plans.append(plan)
            continue
        resolved = resolve_candidate(client, extracted, path, existing)
        plan.update(resolved)
        if resolved["metadata"] != "existing":
            existing.append(resolved["candidate"])
            added.append(resolved["candidate"])
        plan["status"] = "ready"
        plans.append(plan)
    add_candidates(run_dir, existing, added)
    identities = list(dict.fromkeys(str(plan["id"]) for plan in plans if plan.get("id")))
    if identities:
        selected = workflow.load_manifest(run_dir)["selected_ids"]
        workflow.approve_selection(run_dir, list(dict.fromkeys([*selected, *identities])),
                                   SELECTION_SOURCE, SELECTION_RULE)
    imported: dict[str, Any] = {}
    seen: set[str] = set()
    mapping: list[dict[str, str]] = []
    for plan in plans:
        identity = plan.get("id")
        if not identity:
            continue
        if identity in seen:
            plan["status"] = "duplicate"
            plan["reason"] = "another file in this batch already uses this work"
            continue
        seen.add(str(identity))
        mapping.append({"id": str(identity), "pdf": str(Path(plan["pdf"]).resolve())})
    if mapping:
        mapping_path = run_dir / "local-pdf-mapping.json"
        workflow.write_json(mapping_path, mapping)
        for row in workflow.import_pdf_mapping(run_dir, mapping_path)["papers"]:
            imported[str(row["id"])] = row
        for plan in plans:
            row = imported.get(str(plan.get("id")))
            if row is None:
                continue
            plan["import_status"] = row.get("status")
            if row.get("status") != "verified":
                plan["status"] = row.get("status") or "error"
                plan["reason"] = row.get("reason") or plan.get("reason")
                continue
            if plan.get("warning"):
                run = workflow.Run.open(run_dir)
                run.advance(str(plan["id"]), warning=str(plan["warning"]))
                run.save()
    ready: list[dict[str, Any]] = []
    if backend == "local":
        for plan in plans:
            row = imported.get(str(plan.get("id")))
            if plan.get("import_status") == "verified" and row and row.get("path"):
                convert_local(run_dir, plan, row)
    else:
        ready = mineru_ready(run_dir, plans)
    return plans, identities, ready


CONSENT_NEXT_ACTION = (
    "MinerU upload consent is missing for the verified PDFs. Ask once unless the user already refused, "
    "record workflow.py consent --service mineru for those ids, then re-run local_pdf.py or "
    "process_run.py --stages convert. Do not upload before consent"
)


def finish(run_dir: Path, plans: Sequence[dict[str, Any]], identities: Sequence[str], *, backend: str,
           collection_name: str | None, collection_key: str | None, storage_root: Path | None) -> dict[str, Any]:
    failed_open = [plan for plan in plans if plan.get("status") == "extraction_failed"]
    consent_required = [str(plan["id"]) for plan in plans if plan.get("status") == "consent_required" and plan.get("id")]
    handoff_ids = [str(plan["id"]) for plan in plans
                   if plan.get("import_status") == "verified" and plan.get("status") != "consent_required"]
    continuation: dict[str, Any] = {}
    if plans and len(failed_open) == len(plans):
        status = "pending"
        action = "no DOI or usable title could be read; do not invent a bibliographic record"
    elif consent_required:
        status = "partial"
        action = CONSENT_NEXT_ACTION
    else:
        package = workflow.Run.open(run_dir)
        pending = process_run.summary_handoff(package, handoff_ids, package.candidates()) if handoff_ids else []
        request = process_run.ProcessRequest(
            run_dir=run_dir, ids=handoff_ids, stages=("ingest",),
            collection_key=collection_key, collection_name=collection_name, storage_root=storage_root,
        )
        continuation = process_run.attach_summary_handoff(run_dir, pending, handoff_ids, request)
        if continuation.get("pending_summaries"):
            status = "awaiting_summaries"
            action = process_run.AWAITING_SUMMARIES_ACTION
            if not collection_name and not collection_key:
                action += (". Add the Zotero collection the user already named on resume_command; "
                           "ask for it only when they have not, and only before ingestion")
        else:
            status = "partial"
            action = "deliver the rows that finished; the others name the evidence that is still missing"
    result: dict[str, Any] = {
        "status": status,
        "backend": backend,
        "run_dir": str(run_dir),
        "papers": [public_paper(plan) for plan in plans],
        "consent_required": consent_required,
        "next_action": action,
        **continuation,
    }
    if identities:
        result["table"] = workflow.Run.open(run_dir).table(list(identities))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--pdf", action="append", required=True, dest="pdfs",
                        help="Local PDF. Repeat for a batch. DOI is optional.")
    parser.add_argument("--backend", choices=("local", "cloud"), default="cloud",
                        help="cloud uploads verified PDFs to MinerU after recorded consent (default). "
                             "local writes text on this machine and does not record consent.")
    parser.add_argument("--collection-name")
    parser.add_argument("--collection-key")
    parser.add_argument("--storage-root")
    parser.add_argument("--crossref-base", help=argparse.SUPPRESS)
    parser.add_argument("--openalex-base", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bases = {}
    if args.crossref_base:
        bases["crossref"] = args.crossref_base
    if args.openalex_base:
        bases["openalex"] = args.openalex_base
    client = sources.Sources(bases=bases or None, browser=None, attempts=2, timeout=8, budget=12)
    try:
        result = run_local_pdfs(
            Path(args.run_dir), [Path(value) for value in args.pdfs], backend=args.backend,
            collection_name=args.collection_name, collection_key=args.collection_key,
            storage_root=Path(args.storage_root).resolve() if args.storage_root else None, client=client,
        )
    except (ValueError, OSError) as error:
        print(json.dumps({"status": "pending", "reason": str(error) if isinstance(error, ValueError)
                          else f"{type(error).__name__}: {error}"}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["status"] == "pending" else 0


if __name__ == "__main__":
    raise SystemExit(main())
