#!/usr/bin/env python3
"""Get one paper's source PDF, by the cheapest route that actually works.

Acquisition used to begin by opening a browser, even for a paper whose open
PDF URL was already sitting in the candidate record. That is backwards: most
open-access PDFs are a plain HTTPS GET, and routing them through a browser
made every run depend on a daemon, an extension and a live tab to fetch files
that `urllib` can fetch in a second.

So the route is chosen, not assumed:

1. **Links already known** — the open PDF URLs discovery recorded — fetched
   directly over HTTP.
2. **Links worth asking for** — Unpaywall, OpenAlex, Crossref and Semantic
   Scholar for a DOI's open copies, arXiv for a preprint — asked for only when
   step 1 has not produced a verified file, and asked of one source at a time.
3. **The browser** (`browser_pdf.py`, ADR-0002) — for the three walls HTTP
   cannot climb: an institutional entitlement, an anti-bot challenge, and a
   host the shell cannot open but the browser can.

The browser channel is unchanged and is still the only thing that clears all
three walls at once. What changed is that it is the fallback rather than the
front door, so a paper on a plain OA host no longer needs it, and Kimi being
down no longer stops those papers.

Three guarantees hold whichever route ran:

- **Nothing is written until it is whole.** Bytes land in a temporary file
  under a size and time cap; only after the response completes is the file
  checked for a real PDF header and matched against the candidate's identity.
  HTML, a truncated transfer and a valid PDF of the wrong paper all fail, and
  an already verified artifact is never overwritten by an attempt.
- **The reason is specific.** `entitlement`, `challenge`, `reachability`,
  `rate_limited`, `not_a_pdf` and `identity_mismatch` each have a different
  fix, so they stay apart in the trail (CONTEXT.md, "Acquisition wall").
- **The version is recorded, not assumed.** A preprint acquired from arXiv is
  recorded as a preprint. A title-only arXiv match is a lead: it must be
  corroborated by author and year before it is fetched at all, and it never
  becomes the version of record by default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Callable, Iterator, Mapping, Sequence
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import browser_pdf  # noqa: E402
import paper_artifacts  # noqa: E402
import sources as source_module  # noqa: E402
from http_client import Client, RequestError  # noqa: E402
from sources import Sources  # noqa: E402

# The sources worth asking where a known DOI's open copy lives, best first.
# Unpaywall exists for exactly this question; Crossref knows the publisher's
# own registered links; the other two are already in hand from discovery.
LOOKUP_SOURCES = ("unpaywall", "openalex", "semantic_scholar", "crossref")
PDF_MAGIC = b"%PDF-"
# What a browser outcome means for the person who has to fix it. `blocked` and
# `error` are facts about the host; `browser_error` is a fact about *our*
# channel — a daemon that is down or timing out — and pointing the user at a
# mirror for that would be the wrong advice.
BROWSER_KINDS = {"blocked": "reachability", "challenge_unsolved": "challenge",
                 "challenge": "challenge", "error": "reachability",
                 "browser_error": "browser_unavailable", "landing": "not_a_pdf"}
HTTP_FAILURES = {
    "authentication_required": "entitlement",
    "permission_denied": "entitlement",
    "not_found": "reachability",
    "rate_limited": "rate_limited",
    "too_large": "too_large",
    "insecure_redirect": "reachability",
    "insecure_transport": "reachability",
}


@dataclass(frozen=True)
class Limits:
    """What one paper's acquisition may spend before it gives up.

    A ceiling on every axis a hostile or broken source could grow: bytes,
    seconds per link, seconds overall, and how many links are worth trying at
    all. Without the last one a paper with forty recorded locations would
    quietly become the slowest leg of a run.
    """
    max_bytes: int = 80_000_000
    per_url_seconds: float = 45.0
    total_seconds: float = 240.0
    max_http_urls: int = 6
    max_browser_urls: int = 1
    # Asking four services where a PDF lives is a detour worth seconds, not
    # minutes: whatever they answer still has to be downloaded afterwards.
    lookup_seconds: float = 30.0
    per_lookup_seconds: float = 10.0
    # One try per network route, then move on: with several candidate URLs in
    # hand, breadth finds the file faster than depth on a silent host.
    attempts_per_url: int = 2


@dataclass(frozen=True)
class AcquireRequest:
    """One paper, one destination, and the channels allowed to reach it."""
    candidate: Mapping[str, Any]
    output: Path
    browser: Callable[..., tuple[int, dict[str, Any]]] | None = None
    client: Sources | None = None
    limits: Limits = field(default_factory=Limits)
    lookup: bool = True


def redact(url: str) -> str:
    """A URL safe to write into a run package: no key, no signed token."""
    parts = urllib.parse.urlsplit(url)
    kept = [(key, value) for key, value in urllib.parse.parse_qsl(parts.query)
            if key.lower() not in ("api_key", "apikey", "key", "email", "token", "access_token", "signature", "sig")]
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, urllib.parse.urlencode(kept), ""))


# ── Where the full text might be ───────────────────────────────────────────

def known_locations(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The full-text links discovery already recorded for this candidate.

    Older runs carry only `oa_pdf_url` and `landing_page_url`; both shapes are
    read so a run created before multi-source discovery still acquires.
    """
    found: list[dict[str, Any]] = []
    for entry in candidate.get("locations") or []:
        if isinstance(entry, Mapping) and entry.get("url"):
            found.append(dict(entry))
    for url, kind in ((candidate.get("oa_pdf_url"), "pdf"), (candidate.get("landing_page_url"), "landing")):
        if isinstance(url, str) and url.startswith("http"):
            found.append({"url": url, "kind": kind, "source": "candidate", "version": "unknown"})
    return dedupe(found)


def dedupe(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for entry in entries:
        unique.setdefault(str(entry["url"]), dict(entry))
    return list(unique.values())


def candidate_doi(candidate: Mapping[str, Any]) -> str | None:
    identifiers = candidate.get("identifiers") or {}
    doi = candidate.get("doi") or identifiers.get("doi")
    if not doi and str(candidate.get("id") or "").startswith("doi:"):
        doi = str(candidate["id"]).removeprefix("doi:")
    return source_module.canonical_doi(doi)


def corroborates(found: Mapping[str, Any], candidate: Mapping[str, Any]) -> tuple[bool, str]:
    """May this arXiv entry be treated as this paper's preprint?

    A DOI match is proof. A title match is not: it has to agree with the
    candidate on an author surname and on a plausible year before the file is
    worth fetching, and even then what it yields is the preprint.
    """
    if found.get("match") == "doi":
        return True, "arxiv_doi"
    expected = {surname(name) for name in candidate.get("authors") or []} - {""}
    reported = {surname(name) for name in found.get("authors") or []} - {""}
    if not expected or not (expected & reported):
        return False, "arxiv title lead: no shared author"
    year, published = candidate.get("year"), found.get("published_year")
    if isinstance(year, int) and isinstance(published, int) and abs(year - published) > 1:
        return False, f"arxiv title lead: year {published} does not match {year}"
    return True, "arxiv_title_author_year"


def surname(value: Any) -> str:
    parts = re.findall(r"[a-z]+", str(value or "").lower())
    return parts[-1] if parts else ""


def looked_up_locations(candidate: Mapping[str, Any], client: Sources, deadline: float,
                        trail: list[dict[str, Any]], limits: Limits) -> Iterator[list[dict[str, Any]]]:
    """Yield each source's leads; only the caller's verified download stops us."""
    doi = candidate_doi(candidate)
    identifiers = candidate.get("identifiers") or {}
    pmcid = str(identifiers.get("pmcid") or "")
    if pmcid.isdigit():
        pmcid = "PMC" + pmcid
    if not pmcid:
        for entry in known_locations(candidate):
            match = re.search(r"(?:pmc\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pmc)/articles/(?:PMC)?(\d+)", str(entry["url"]), re.I)
            if match:
                pmcid = "PMC" + match[1]
                break
    if pmcid and time.monotonic() < deadline:
        answer = client.pmc(pmcid, budget=min(15, deadline - time.monotonic()))
        trail.append({"lookup": "PMC", "status": answer.status, "detail": answer.detail})
        yield [entry for record in answer.records
               if not doi or source_module.canonical_doi(record.get("doi")) == doi
               for entry in source_module.locations("pmc", record)]
    for name in LOOKUP_SOURCES:
        if time.monotonic() >= deadline:
            break
        if not doi:
            break
        answer = client.work(name, doi, budget=min(limits.per_lookup_seconds,
                                                   max(1.0, deadline - time.monotonic())))
        trail.append({"lookup": source_module.LABELS[name], "status": answer.status,
                      "detail": answer.detail, "cached": answer.cached})
        if answer.records:
            yield source_module.locations(name, answer.records[0])

    if identifiers.get("arxiv"):
        yield [{"url": f"https://arxiv.org/pdf/{identifiers['arxiv']}", "kind": "pdf",
                "source": "arXiv", "version": "preprint", "identity_basis": "arxiv_identifier"}]
    elif time.monotonic() < deadline:
        answer = client.arxiv(doi, str(candidate.get("title") or "") or None,
                              budget=min(limits.per_lookup_seconds,
                                         max(1.0, deadline - time.monotonic())))
        trail.append({"lookup": "arXiv", "status": answer.status, "detail": answer.detail})
        if answer.records:
            entry = answer.records[0]
            allowed, basis = corroborates(entry, candidate)
            if allowed:
                yield [{**location, "identity_basis": basis} for location in source_module.locations("arxiv", entry)]
            else:
                # A lead that does not check out is recorded, never followed.
                trail.append({"lookup": "arXiv", "status": "unconfirmed", "detail": basis})


def browser_locations(locations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One publisher route, rather than opening indexes and mirrors in turn."""
    entries = [*ordered(locations, "pdf"), *ordered(locations, "landing")]
    excluded = ("pubmed.ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov",
                "www.semanticscholar.org", "doaj.org", "pmc-oa-opendata.s3.amazonaws.com")
    return [entry for entry in entries if urllib.parse.urlsplit(str(entry["url"])).hostname not in excluded]


def ordered(locations: Sequence[Mapping[str, Any]], kind: str) -> list[dict[str, Any]]:
    """Links of one kind, published versions before preprints."""
    rank = {"published": 0, "accepted": 1, "unknown": 2, "preprint": 3}
    chosen = [dict(entry) for entry in locations if entry.get("kind") == kind]
    return sorted(chosen, key=lambda entry: rank.get(str(entry.get("version")), 2))


# ── Fetching ───────────────────────────────────────────────────────────────

def fetch(url: str, destination: Path, client: Client, limits: Limits,
          budget: float) -> dict[str, Any]:
    """Download one URL into a temporary file. Returns an attempt record.

    Nothing is written to `destination` here. A response that turns out to be
    HTML, an error page or a truncated transfer leaves no artifact behind, and
    the caller's existing file — verified on an earlier run, perhaps — is
    untouched by an attempt that failed.
    """
    started = time.monotonic()
    attempt: dict[str, Any] = {"url": redact(url), "channel": "http"}
    try:
        reply = client.request("GET", url, budget=min(budget, limits.per_url_seconds),
                               max_bytes=limits.max_bytes, max_attempts=limits.attempts_per_url)
    except RequestError as error:
        attempt.update({"status": "failed", "kind": HTTP_FAILURES.get(error.kind, "reachability"),
                        "detail": error.kind, "elapsed_seconds": round(time.monotonic() - started, 3)})
        return attempt
    body = reply.body
    attempt["bytes"] = len(body)
    attempt["elapsed_seconds"] = round(time.monotonic() - started, 3)
    if not body.startswith(PDF_MAGIC):
        # A challenge page and an ordinary landing page are both HTML, and the
        # browser channel answers them differently, so they stay apart.
        text = body[:4000].decode("utf-8", errors="replace")
        challenged = bool(browser_pdf.CHALLENGE_TEXT.search(text))
        attempt.update({"status": "failed", "kind": "challenge" if challenged else "not_a_pdf",
                        "detail": f"response is not a PDF (content-type {reply.headers.get('Content-Type')})"})
        return attempt
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_bytes(body)
    attempt.update({"status": "captured", "kind": "pdf", "path": str(temporary),
                    "sha256": hashlib.sha256(body).hexdigest()})
    return attempt


def verified(temporary: Path, destination: Path, candidate: Mapping[str, Any],
             attempt: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """Identity-check a downloaded file, then place it only if it may be kept.

    Three answers, as everywhere else in this skill: the paper, the wrong
    paper, or a file nobody can read. Only the first two are decisions; the
    third keeps the file for a human without claiming anything about it.
    """
    evidence, status = paper_artifacts.verify(temporary, str(candidate.get("title") or ""),
                                              candidate.get("doi"))
    if status == 0:
        temporary.replace(destination)
        attempt["verification"] = "verified"
        return "verified", evidence
    if status == 3:
        if destination.exists():
            # Something is already here and this attempt cannot prove it is
            # better. The earlier file wins; nothing is destroyed to make room
            # for a file nobody can read.
            temporary.unlink(missing_ok=True)
            attempt["verification"] = "unverified_not_kept"
            return "rejected", evidence
        temporary.replace(destination)
        attempt["verification"] = "unverified"
        return "unverified", evidence
    temporary.unlink(missing_ok=True)
    attempt.update({"verification": "rejected", "kind": "identity_mismatch",
                    "detail": str(evidence.get("reason"))})
    return "rejected", evidence


def capture_with_browser(request: AcquireRequest, entry: Mapping[str, Any],
                         candidate: Mapping[str, Any], destination: Path) -> dict[str, Any]:
    """One browser capture attempt, in the acquisition trail's own terms.

    The capture lands in a temporary file for the same reason an HTTP download
    does: a wrong-paper capture must not be able to destroy a file that an
    earlier run already verified.
    """
    assert request.browser is not None
    command = ["capture", "--url", str(entry["url"]), "--output", str(destination),
               "--title", str(candidate.get("title") or "")]
    if candidate.get("doi"):
        command += ["--doi", str(candidate["doi"])]
    try:
        code, report = request.browser(*command)
    except (OSError, subprocess.SubprocessError) as error:
        # The adapter itself could not run. That is one route lost for this
        # paper, reported like any other wall — not an exception that ends a
        # batch other papers are still using HTTP for.
        return {"url": redact(str(entry["url"])), "channel": "browser", "status": "failed",
                "kind": "browser_unavailable", "detail": f"{type(error).__name__}: {error}"[:200]}
    kind = str(report.get("kind") or "error")
    attempt: dict[str, Any] = {"url": redact(str(entry["url"])), "channel": "browser",
                               "source": entry.get("source"), "version": entry.get("version"),
                               "status": str(report.get("status") or "failed"), "kind": kind}
    if code != 0 or report.get("status") != "captured":
        attempt["kind"] = BROWSER_KINDS.get(kind, kind)
        attempt["detail"] = str(report.get("detail") or report.get("reason") or report.get("remediation") or kind)[:300]
        attempt["status"] = "failed"
    else:
        attempt.update({"bytes": report.get("bytes"), "sha256": report.get("sha256")})
    return attempt


def acquire(request: AcquireRequest) -> dict[str, Any]:
    """Fetch and identity-check one source PDF. Never invents a route."""
    candidate = request.candidate
    limits = request.limits
    deadline = time.monotonic() + limits.total_seconds
    trail: list[dict[str, Any]] = []
    client = Client(budget=limits.per_url_seconds, timeout=min(30, limits.per_url_seconds), cookies=True)
    locations = known_locations(candidate)
    kept: str | None = None
    unresolved: dict[str, Any] | None = None

    if request.output.is_file():
        # A resumed run must not download what it already has, and a verified
        # artifact is never put at risk by a fresh attempt.
        existing, status = paper_artifacts.verify(
            request.output, str(candidate.get("title") or ""), candidate.get("doi"))
        if status == 0:
            return {"ok": True, "path": str(request.output), "channel": "existing",
                    "source": "run package", "version": None, "evidence": existing,
                    "trail": [{"channel": "existing", "status": "captured", "kind": "pdf",
                               "url": str(request.output), "verification": "verified"}]}
        if status == 3:
            # A file an earlier run kept for a human. It is this attempt's
            # fallback from the start, so a resume can only improve on the
            # diagnosis it already gave — never report less than last time.
            kept, unresolved = str(request.output), existing

    def try_http(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
        nonlocal kept, unresolved
        for entry in entries[: limits.max_http_urls]:
            if time.monotonic() >= deadline:
                break
            attempt = fetch(str(entry["url"]), request.output, client, limits,
                            budget=deadline - time.monotonic())
            attempt.update({"source": entry.get("source"), "version": entry.get("version"),
                            "identity_basis": entry.get("identity_basis")})
            trail.append(attempt)
            if attempt.get("status") != "captured":
                continue
            verdict, evidence = verified(Path(str(attempt["path"])), request.output, candidate, attempt)
            attempt.pop("path", None)
            if verdict == "verified":
                return {"ok": True, "path": str(request.output), "channel": "http",
                        "source": entry.get("source"), "version": entry.get("version"),
                        "evidence": evidence, "trail": trail}
            if verdict == "unverified" and kept is None:
                # Kept as a fallback, not claimed, and *not* an ending: an
                # erratum or a comment can reprint a paper's whole title, so
                # the remaining links still deserve a try. A later verified
                # file replaces this one; nothing worse ever does.
                kept, unresolved = str(request.output), evidence
        return None

    attempted: set[str] = set()
    result = try_http(ordered(locations, "pdf"))
    attempted.update(str(entry["url"]) for entry in locations)
    if result:
        return result

    if request.lookup and request.client is not None and time.monotonic() < deadline:
        for discovered in looked_up_locations(
                candidate, request.client,
                min(deadline, time.monotonic() + limits.lookup_seconds), trail, limits):
            fresh = [entry for entry in discovered if str(entry["url"]) not in attempted]
            locations = dedupe([*locations, *discovered])
            result = try_http(ordered(fresh, "pdf"))
            attempted.update(str(entry["url"]) for entry in fresh if entry.get("kind") == "pdf")
            if result:
                return result

    if request.browser is not None and time.monotonic() < deadline:
        # Only now: the browser is what clears entitlement, anti-bot and
        # reachability, and it costs a live daemon and a real tab.
        for entry in browser_locations(locations)[: limits.max_browser_urls]:
            if time.monotonic() >= deadline:
                break
            temporary = request.output.with_suffix(request.output.suffix + ".part")
            attempt = capture_with_browser(request, entry, candidate, temporary)
            trail.append(attempt)
            if attempt["status"] != "captured":
                temporary.unlink(missing_ok=True)
                continue
            verdict, evidence = verified(temporary, request.output, candidate, attempt)
            if verdict == "verified":
                return {"ok": True, "path": str(request.output), "channel": "browser",
                        "source": entry.get("source"), "version": entry.get("version"),
                        "evidence": evidence, "trail": trail}
            if verdict == "unverified" and kept is None:
                kept, unresolved = str(request.output), evidence

    if kept:
        return {"ok": False, "kept": kept, "reason": "pdf_unverified", "trail": trail,
                "evidence": unresolved}
    return {"ok": False, "reason": "no verified source PDF", "trail": trail,
            "browser_candidates": [redact(str(entry["url"])) for entry in browser_locations(locations)[:2]],
            "walls": sorted({str(entry.get("kind")) for entry in trail
                             if entry.get("status") == "failed" and entry.get("kind")})}
