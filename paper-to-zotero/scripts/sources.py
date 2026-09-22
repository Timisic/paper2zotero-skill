#!/usr/bin/env python3
"""Ask one bibliographic source one question, and read its answer.

Five services answer questions this skill needs: OpenAlex and Semantic Scholar
find candidates, Crossref and Unpaywall locate a known DOI's full text, and
arXiv finds the open version of a preprinted paper. They disagree about
everything else — how they authenticate, how fast they may be asked, what they
call a PDF link, and how they say "no" — and every one of those disagreements
used to be a detail some caller had to remember.

So this module answers three questions and hides the rest:

    search(source, query)   candidates for a topic
    work(source, doi)       what this source knows about one DOI
    arxiv(doi, title)       the open preprint of a known paper, if any

Each returns an `Answer` with a **status**, not an exception, because the
difference between "this source has no such paper", "the key is wrong" and
"the network is down" changes what the caller should do — and only the first
one means there is nothing to find. `normalize` and `locations` then turn a
source's own JSON into this skill's Candidate and full-text location shapes,
so provider field names stop at this file.

Three policies are enforced here rather than trusted to callers:

- **Pacing** belongs to the key, so it is shared across processes
  (`http_client.Throttle`). The Semantic Scholar key is one request per second
  across *all* endpoints, retries included.
- **Credentials go to one host.** A key is attached only when the URL is on
  that source's own base, and `http_client` drops it again if a redirect
  leaves. Publisher requests and the browser fallback never carry one.
- **Only real answers are remembered.** The per-instance cache holds results
  and genuine emptiness; a 401, a 429 or a dropped connection is never
  remembered as "no papers".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Mapping, Sequence
import urllib.parse
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))

import arxiv_lookup  # noqa: E402
import credentials  # noqa: E402
from http_client import Client, RequestError, Throttle  # noqa: E402

# Where each service lives. `LITERATURE_SOURCE_BASES` overrides any of them
# with a JSON object, which is how the tests point a source at a local peer
# and how a caller behind a mirror points one somewhere else. A credential is
# tied to whichever base is configured, so an override never leaks a key to
# the real service or the key to the override.
BASES_ENV = "LITERATURE_SOURCE_BASES"
BASES: dict[str, str] = {
    "openalex": "https://api.openalex.org",
    "semantic_scholar": "https://api.semanticscholar.org",
    "crossref": "https://api.crossref.org",
    "unpaywall": "https://api.unpaywall.org",
    "arxiv": "https://export.arxiv.org",
    "pmc": "https://pmc-oa-opendata.s3.amazonaws.com",
}

# Seconds between two requests on one key. The Semantic Scholar figure is the
# quota granted for this key and covers every endpoint together; arXiv's is
# its published request rate for the public API. The rest are polite spacing
# for services that publish no hard per-second limit.
INTERVALS: dict[str, float] = {
    "openalex": 0.12,
    "semantic_scholar": 1.0,
    "crossref": 0.12,
    "unpaywall": 0.12,
    "arxiv": 3.0,
    "pmc": 0.34,
}

DISCOVERY_SOURCES = ("openalex", "semantic_scholar")
LABELS = {
    "openalex": "OpenAlex",
    "semantic_scholar": "SemanticScholar",
    "crossref": "Crossref",
    "unpaywall": "Unpaywall",
    "arxiv": "arXiv",
    "pmc": "PMC",
}

# The query parameters each source is actually sent, recorded in a run's query
# log so a round can be reproduced without keeping the URL (which carries a key).
SENT_FIELDS = {
    "openalex": ["search", "filter", "per-page", "sort"],
    "semantic_scholar": ["query", "year", "limit", "fields"],
}

S2_FIELDS = ("title,abstract,year,publicationDate,venue,publicationVenue,publicationTypes,"
             "externalIds,authors,citationCount,openAccessPdf,isOpenAccess,fieldsOfStudy")
OPENALEX_PER_PAGE_MAX = 200
S2_LIMIT_MAX = 100

# What a source calls a version, and what this skill calls it. The distinction
# is not cosmetic: a preprint and the version of record are different files
# with different content, and merging them silently loses that.
VERSIONS = {
    "submittedversion": "preprint",
    "acceptedversion": "accepted",
    "publishedversion": "published",
    "preprint": "preprint",
    "accepted": "accepted",
    "published": "published",
}


def _base_overrides() -> dict[str, str]:
    try:
        configured = json.loads(os.environ.get(BASES_ENV) or "{}")
    except ValueError:
        return {}
    return {str(name): str(url) for name, url in configured.items() if name in BASES}


def observed_at() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_doi(value: str | None) -> str | None:
    """A DOI in the one form everything else compares against."""
    if not value:
        return None
    cleaned = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", str(value), flags=re.I).strip().lower()
    return cleaned or None


@dataclass(frozen=True)
class Query:
    """One topical search, in the terms every source can express."""
    text: str
    from_year: int | None = None
    to_year: int | None = None
    limit: int = 25

    def key(self) -> str:
        return json.dumps([self.text, self.from_year, self.to_year, self.limit], sort_keys=True)


@dataclass(frozen=True)
class Answer:
    """What one source said, including the ways it said nothing.

    `status` is the whole point. `ok` and `empty` are answers — the second one
    means the source really has no match, and a caller may record that as
    coverage. Everything else is a failure of the channel, and a caller must
    not turn it into a claim about the literature.
    """
    source: str
    question: str
    status: str
    records: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""
    elapsed_seconds: float = 0.0
    requests: int = 0
    observed_at: str = ""
    cached: bool = False

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "empty")

    def report(self) -> dict[str, Any]:
        """The shape written into a run's query log. Never carries a key."""
        return {
            "source": LABELS.get(self.source, self.source),
            "question": self.question,
            "status": self.status,
            "detail": self.detail,
            "records": len(self.records),
            "requests": self.requests,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "observed_at": self.observed_at,
            "cached": self.cached,
        }


# HTTP failure kinds, mapped to what a caller can do about them.
STATUS_FOR_KIND = {
    "rate_limited": "rate_limited",
    "authentication_required": "authentication_required",
    "permission_denied": "authentication_required",
    "not_found": "not_found",
}


def browser_json(url: str, session: str = "literature-discovery") -> dict[str, Any] | None:
    """Public metadata through the user's browser, for hosts the shell cannot open.

    Measured on the owner's network, `api.openalex.org` has been reachable
    from the browser and not from `urllib` — a network fact that must not turn
    into an empty candidate set (ADR-0002). Credentials are stripped from the
    query first: the browser fallback is a public channel.
    """
    import browser_pdf  # imported lazily: discovery must not need a browser

    parts = urllib.parse.urlsplit(url)
    public = urllib.parse.parse_qsl(parts.query)
    query = urllib.parse.urlencode([(k, v) for k, v in public if k not in ("api_key", "email")])
    stripped = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    try:
        result = browser_pdf.fetch_text(stripped, session)
    except browser_pdf.BrowserError:
        return None
    if not result.get("ok"):
        return None
    try:
        return dict(json.loads(str(result.get("body"))))
    except (ValueError, TypeError):
        return None


class Sources:
    """The bibliographic services, behind one question-shaped interface.

    One instance holds one client and one cache per source, so a command that
    asks about twenty papers reuses its route preference, its pacing queue and
    any DOI it has already looked up. The cache is deliberately per-instance
    and in memory: it makes one run cheaper without becoming a second store of
    record that could go stale unnoticed.
    """

    def __init__(self, *, bases: Mapping[str, str] | None = None, budget: float = 25,
                 timeout: float = 10, attempts: int = 3, throttle_dir: Path | None = None,
                 browser: Callable[[str], dict[str, Any] | None] | None = None,
                 setting: Callable[[str], str] = credentials.source_setting) -> None:
        self.bases = {**BASES, **_base_overrides(), **(bases or {})}
        self.budget, self.timeout = budget, timeout
        # A source that is not answering has somewhere else to be asked. Three
        # tries covers a dropped first call of a burst; more just makes a
        # caller wait out a service that is down.
        self.attempts = attempts
        self.browser = browser
        self.setting = setting
        self.clients: dict[str, Client] = {}
        self.cache: dict[str, Answer] = {}
        self.throttles = {name: Throttle(name, interval, throttle_dir)
                          for name, interval in INTERVALS.items()}

    # ── Channel ──────────────────────────────────────────────────────────

    def client(self, source: str) -> Client:
        if source not in self.clients:
            self.clients[source] = Client(budget=self.budget, timeout=self.timeout,
                                          throttle=self.throttles[source])
        return self.clients[source]

    def _auth(self, source: str, url: str, params: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
        """Credentials for this source, and only when the URL is its own.

        The check is against the configured base rather than a hardcoded
        hostname so it still holds when a test points a source at a local
        peer — and so a URL that came from a *record* (a publisher link, a
        mirror) can never collect the key by accident.
        """
        headers: dict[str, str] = {}
        if urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(self.bases[source]).netloc:
            return params, headers
        value = self.setting(source) if source in credentials.SOURCE_SETTINGS else ""
        if not value:
            return params, headers
        if source == "semantic_scholar":
            headers["x-api-key"] = value
        elif source == "openalex":
            params["api_key"] = value
        elif source == "crossref":
            params["mailto"] = value
        elif source == "unpaywall":
            params["email"] = value
        return params, headers

    def _fetch(self, source: str, question: str, path: str, params: dict[str, str], *,
               body: Any = None, budget: float | None = None, allow_browser: bool = True,
               parse: str = "json") -> tuple[Any, Answer]:
        """One request to one source, classified. Returns (payload, answer).

        `parse` is `json` for the four JSON APIs and `text` for arXiv, which
        answers in Atom XML.
        """
        url = self.bases[source] + path
        params, headers = self._auth(source, url, dict(params))
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        started = time.monotonic()
        stamp = observed_at()
        payload: Any = None
        status, detail = "ok", ""
        try:
            if body is None:
                reply = self.client(source).request("GET", url, headers=headers, budget=budget,
                                                    max_attempts=self.attempts)
            else:
                # A batch lookup is a query whose argument list outgrew a URL.
                # Declaring it read-only keeps it retryable without touching
                # the `outcome_unknown` contract that protects real writes.
                reply = self.client(source).request(
                    "POST", url, body=json.dumps(body).encode(), read_only=True, budget=budget,
                    max_attempts=self.attempts,
                    headers={**headers, "Content-Type": "application/json"})
            if parse == "text":
                payload = reply.body.decode("utf-8", errors="replace")
            else:
                payload = reply.json() if reply.body else None
        except RequestError as error:
            status = STATUS_FOR_KIND.get(error.kind, "unavailable")
            detail = error.kind
            if status == "unavailable" and allow_browser and self.browser is not None and body is None:
                payload = self.browser(url)
                if payload is not None:
                    status, detail = "ok", "browser_fallback"
        answer = Answer(source=source, question=question, status=status, detail=detail,
                        elapsed_seconds=time.monotonic() - started, requests=1, observed_at=stamp)
        return payload, answer

    def _remember(self, key: str, answer: Answer) -> Answer:
        """Cache real answers only; a failure must never mean 'no papers'."""
        if answer.ok:
            self.cache[key] = answer
        return answer

    def _cached(self, key: str) -> Answer | None:
        hit = self.cache.get(key)
        if hit is None:
            return None
        # A copy: a caller that edits its records must not edit the cache.
        return Answer(**{**hit.__dict__, "records": [dict(record) for record in hit.records],
                         "cached": True, "requests": 0, "elapsed_seconds": 0.0})

    # ── Questions ────────────────────────────────────────────────────────

    def search(self, source: str, query: Query, *, budget: float | None = None) -> Answer:
        """Candidates for one topic from one discovery source."""
        key = f"search:{source}:{query.key()}"
        hit = self._cached(key)
        if hit is not None:
            return hit
        if source == "openalex":
            filters = [f"from_publication_date:{query.from_year}-01-01"] if query.from_year else []
            if query.to_year:
                filters.append(f"to_publication_date:{query.to_year}-12-31")
            params = {"search": query.text, "per-page": str(min(query.limit, OPENALEX_PER_PAGE_MAX)),
                      "sort": "relevance_score:desc"}
            if filters:
                params["filter"] = ",".join(filters)
            payload, answer = self._fetch(source, "search", "/works", params, budget=budget)
            records = list((payload or {}).get("results") or [])
        elif source == "semantic_scholar":
            params = {"query": query.text, "limit": str(min(query.limit, S2_LIMIT_MAX)), "fields": S2_FIELDS}
            if query.from_year or query.to_year:
                params["year"] = f"{query.from_year or ''}-{query.to_year or ''}"
            if not self.setting(source):
                # The unauthenticated pool answers 429 to almost everything;
                # saying so up front beats spending the budget to learn it.
                return Answer(source=source, question="search", status="not_configured",
                              detail="SEMANTIC_SCHOLAR_API_KEY is not configured",
                              observed_at=observed_at())
            payload, answer = self._fetch(source, "search", "/graph/v1/paper/search", params, budget=budget)
            records = list((payload or {}).get("data") or [])
        else:
            raise KeyError(f"{source} is not a discovery source")
        if not answer.ok:
            return answer
        answer = Answer(**{**answer.__dict__, "records": records,
                           "status": "ok" if records else "empty"})
        return self._remember(key, answer)

    def pmc(self, pmcid: str, *, budget: float = 15) -> Answer:
        """Resolve the official distributed files, never the PMC website viewer.

        The August 2026 cloud dataset replaces the retired OA service. List
        versions instead of assuming version 1, and trust each version's DOI,
        licence and pdf_url. A PMC page need not have a distributable PDF.
        """
        pmcid = pmcid.upper()
        if not re.fullmatch(r"PMC\d+", pmcid):
            raise ValueError("invalid PMCID")
        key = "pmc:" + pmcid
        cached = self._cached(key)
        if cached:
            return cached
        started = time.monotonic()
        payload, answer = self._fetch("pmc", "files", "/", {
            "list-type": "2", "prefix": pmcid + ".", "delimiter": "/"},
            budget=budget, allow_browser=False, parse="text")
        if not answer.ok:
            return answer
        try:
            root = ET.fromstring(payload)
            ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
            prefixes = [str(node.text) for node in root.findall("s:CommonPrefixes/s:Prefix", ns)]
        except (ET.ParseError, TypeError):
            return Answer(**{**answer.__dict__, "status": "unavailable", "detail": "invalid PMC file listing"})
        records = []
        status, detail = "ok", ""
        for prefix in prefixes[:3]:
            if not re.fullmatch(re.escape(pmcid) + r"\.\d+/", prefix):
                continue
            left = budget - (time.monotonic() - started)
            if left <= 0:
                status, detail = "unavailable", "PMC lookup budget spent"
                break
            metadata, reply = self._fetch("pmc", "files", "/metadata/" + prefix.rstrip("/") + ".json", {},
                                          budget=left, allow_browser=False)
            if not reply.ok:
                status, detail = reply.status, reply.detail
                continue
            if isinstance(metadata, dict) and metadata.get("pdf_url") and str(metadata.get("is_retracted", "no")).lower() not in ("yes", "true"):
                records.append(metadata)
        if records:
            status = "ok"
        elif status == "ok":
            status, detail = "empty", "no distributed PDF for this PMCID"
        answer = Answer(**{**answer.__dict__, "records": records, "status": status,
                           "detail": detail, "elapsed_seconds": time.monotonic() - started})
        return self._remember(key, answer)

    def work(self, source: str, doi: str, *, budget: float | None = None) -> Answer:
        """What one source knows about one DOI."""
        normalized = canonical_doi(doi)
        if not normalized:
            return Answer(source=source, question="work", status="not_found",
                          detail="no DOI", observed_at=observed_at())
        key = f"work:{source}:{normalized}"
        hit = self._cached(key)
        if hit is not None:
            return hit
        # The slash stays a slash: these APIs address a DOI as a path suffix
        # and answer 404 to a percent-encoded one.
        quoted = urllib.parse.quote(normalized, safe="/")
        if source == "openalex":
            payload, answer = self._fetch(source, "work", f"/works/doi:{quoted}", {}, budget=budget)
            record = payload if isinstance(payload, dict) and payload.get("id") else None
        elif source == "crossref":
            payload, answer = self._fetch(source, "work", f"/works/{quoted}", {}, budget=budget)
            record = (payload or {}).get("message") if isinstance(payload, dict) else None
        elif source == "unpaywall":
            if not self.setting(source):
                return Answer(source=source, question="work", status="not_configured",
                              detail="UNPAYWALL_EMAIL is not configured", observed_at=observed_at())
            payload, answer = self._fetch(source, "work", f"/v2/{quoted}", {}, budget=budget)
            record = payload if isinstance(payload, dict) and payload.get("doi") else None
        elif source == "semantic_scholar":
            if not self.setting(source):
                return Answer(source=source, question="work", status="not_configured",
                              detail="SEMANTIC_SCHOLAR_API_KEY is not configured", observed_at=observed_at())
            payload, answer = self._fetch(source, "work", f"/graph/v1/paper/DOI:{quoted}",
                                          {"fields": S2_FIELDS}, budget=budget)
            record = payload if isinstance(payload, dict) and payload.get("paperId") else None
        else:
            raise KeyError(f"{source} cannot be asked about a DOI")
        if not answer.ok:
            return answer
        answer = Answer(**{**answer.__dict__, "records": [record] if record else [],
                           "status": "ok" if record else "not_found"})
        return self._remember(key, answer)

    def arxiv(self, doi: str | None, title: str | None = None, *, budget: float | None = None) -> Answer:
        """The open preprint of a known paper, matched by DOI before title.

        The DOI query is asked first because it is proof; the title query is
        asked only when that finds nothing, and what it returns is a *lead*.
        Two papers can share eight title words, so the record keeps which kind
        of match it was and the caller decides whether that is enough.
        """
        normalized = canonical_doi(doi)
        key = f"arxiv:{normalized or ''}:{(title or '').lower()}"
        hit = self._cached(key)
        if hit is not None:
            return hit
        started = time.monotonic()
        requests = 0
        found: dict[str, Any] = {"found": False, "match": None}
        queries = ([arxiv_lookup.doi_query(normalized)] if normalized else []) + \
                  ([arxiv_lookup.title_query(title)] if title else [])
        for query in queries:
            payload, reply = self._fetch("arxiv", "arxiv", "/api/query?" + query, {},
                                         budget=budget, allow_browser=False, parse="text")
            requests += reply.requests
            if not reply.ok:
                return Answer(**{**reply.__dict__, "requests": requests,
                                 "elapsed_seconds": time.monotonic() - started})
            try:
                found = arxiv_lookup.parse_atom(str(payload), normalized or "", title)
            except (ET.ParseError, ValueError, TypeError) as error:
                # `ParseError` is a `SyntaxError`, not a `ValueError`: a
                # truncated or HTML-ified feed would otherwise escape every
                # caller's handler and end the whole batch.
                return Answer(source="arxiv", question="arxiv", status="unavailable",
                              detail=f"unreadable feed: {type(error).__name__}", requests=requests,
                              elapsed_seconds=time.monotonic() - started, observed_at=observed_at())
            if found.get("found"):
                break
        answer = Answer(source="arxiv", question="arxiv",
                        status="ok" if found.get("found") else "empty",
                        records=[found] if found.get("found") else [], requests=requests,
                        elapsed_seconds=time.monotonic() - started, observed_at=observed_at())
        return self._remember(key, answer)



# ── Provider formats ───────────────────────────────────────────────────────

def _version(value: Any) -> str:
    return VERSIONS.get(str(value or "").strip().lower(), "unknown")


def _openalex_locations(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    seen = []
    for entry in (record.get("best_oa_location"), record.get("primary_location"), *(record.get("locations") or [])):
        if isinstance(entry, Mapping) and entry not in seen:
            seen.append(entry)
    return seen


def normalize(source: str, record: Mapping[str, Any], timestamp: str) -> dict[str, Any]:
    """One source's own JSON as this skill's Candidate. Pure.

    Every field that could be disputed later carries where it came from: the
    abstract names its source, the citation count is one dated observation
    among possibly several, and the identifiers keep each service's own key so
    a merge can be checked rather than trusted.
    """
    if source == "openalex":
        doi = canonical_doi(record.get("doi"))
        primary = record.get("primary_location") or {}
        venue = (primary.get("source") or {})
        best_oa = record.get("best_oa_location") or {}
        openalex_id = str(record.get("id") or "").rstrip("/").rsplit("/", 1)[-1]
        authors = [value.get("author", {}).get("display_name")
                   for value in record.get("authorships") or []
                   if value.get("author", {}).get("display_name")]
        identifiers = {"doi": doi, "openalex": openalex_id or None}
        ids = record.get("ids") or {}
        if isinstance(ids.get("pmid"), str):
            identifiers["pubmed"] = ids["pmid"].rsplit("/", 1)[-1]
        candidate = {
            "doi": doi,
            "openalex_id": record.get("id"),
            "title": record.get("title"),
            "year": record.get("publication_year"),
            "publication_date": record.get("publication_date"),
            "venue": venue.get("display_name"),
            "venue_type": venue.get("type"),
            "work_type": record.get("type"),
            "language": record.get("language"),
            "authors": authors,
            "abstract": rebuild_abstract(record.get("abstract_inverted_index")),
            "cited_by_count": record.get("cited_by_count"),
            "landing_page_url": primary.get("landing_page_url"),
            "oa_pdf_url": best_oa.get("pdf_url") or primary.get("pdf_url"),
            "is_oa": (record.get("open_access") or {}).get("is_oa"),
            "oa_status": (record.get("open_access") or {}).get("oa_status"),
            "identifiers": identifiers,
        }
        fallback = f"openalex:{openalex_id}" if openalex_id else None
    elif source == "semantic_scholar":
        external = record.get("externalIds") or {}
        doi = canonical_doi(external.get("DOI"))
        paper_id = record.get("paperId")
        open_access = record.get("openAccessPdf") or {}
        venue = record.get("publicationVenue") or {}
        identifiers = {"doi": doi, "semantic_scholar": paper_id}
        for name, key in (("arxiv", "ArXiv"), ("pubmed", "PubMed"), ("pmcid", "PubMedCentral"),
                          ("corpus_id", "CorpusId")):
            if external.get(key):
                identifiers[name] = str(external[key])
        candidate = {
            "doi": doi,
            "semantic_scholar_id": paper_id,
            "title": record.get("title"),
            "year": record.get("year"),
            "publication_date": record.get("publicationDate"),
            "venue": venue.get("name") or record.get("venue") or None,
            "venue_type": venue.get("type"),
            "work_type": (record.get("publicationTypes") or [None])[0],
            "language": None,
            "authors": [value.get("name") for value in record.get("authors") or [] if value.get("name")],
            "abstract": record.get("abstract"),
            "cited_by_count": record.get("citationCount"),
            "landing_page_url": (f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else None),
            "oa_pdf_url": open_access.get("url") or None,
            "is_oa": record.get("isOpenAccess"),
            "oa_status": (open_access.get("status") or "").lower() or None,
            "identifiers": identifiers,
        }
        fallback = f"s2:{paper_id}" if paper_id else None
    else:
        raise KeyError(f"{source} does not produce candidates")

    label = LABELS[source]
    candidate["id"] = f"doi:{candidate['doi']}" if candidate["doi"] else (fallback or title_key(candidate))
    candidate["sources"] = [label]
    candidate["abstract_source"] = label if candidate["abstract"] else None
    candidate["citations"] = ([{"source": label, "count": candidate["cited_by_count"],
                                "observed_at": timestamp}]
                              if candidate["cited_by_count"] is not None else [])
    candidate["citation_source"] = label if candidate["cited_by_count"] is not None else None
    candidate["citation_observed_at"] = timestamp if candidate["cited_by_count"] is not None else None
    candidate["locations"] = locations(source, record)
    candidate["observed_at"] = timestamp
    # No forced core/expansion slot: screening fills `hit_reason`, and a
    # candidate without one never reaches the user's list.
    candidate["hit_reason"] = None
    return candidate


def rebuild_abstract(inverted: Mapping[str, list[int]] | None) -> str | None:
    if not inverted:
        return None
    positioned = sorted((position, word) for word, positions in inverted.items() for position in positions)
    return " ".join(word for _, word in positioned)


def title_key(candidate: Mapping[str, Any]) -> str:
    title = re.sub(r"\W+", "-", str(candidate.get("title") or "untitled").lower()).strip("-")
    return f"title:{title}:{candidate.get('year') or 'unknown'}"


def locations(source: str, record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Where this source says the full text is. Pure, and always attributed.

    A URL without its provenance and version is not usable evidence: the same
    paper's preprint, accepted manuscript and version of record are different
    files, and which one was downloaded has to survive into the record.
    """
    label = LABELS.get(source, source)
    found: list[dict[str, Any]] = []

    def add(url: Any, kind: str, version: Any, host: str | None = None) -> None:
        if isinstance(url, str) and url.startswith("http") and "doi.org/" not in url:
            found.append({"url": url, "source": label, "kind": kind,
                          "version": _version(version), "host_type": host})

    if source == "openalex":
        for entry in _openalex_locations(record):
            add(entry.get("pdf_url"), "pdf", entry.get("version"),
                (entry.get("source") or {}).get("type") if isinstance(entry.get("source"), Mapping) else None)
            add(entry.get("landing_page_url"), "landing", entry.get("version"))
    elif source == "semantic_scholar":
        open_access = record.get("openAccessPdf") or {}
        # S2 reports an OA colour, which names the *host* and not the version:
        # green is a repository copy, the rest sit with the publisher. Which
        # version that copy is stays unknown until something else says so.
        colour = str(open_access.get("status") or "").lower()
        add(open_access.get("url"), "pdf", open_access.get("version"),
            "repository" if colour == "green" else ("publisher" if colour else None))
        arxiv_id = (record.get("externalIds") or {}).get("ArXiv")
        if arxiv_id:
            add(f"https://arxiv.org/pdf/{arxiv_id}", "pdf", "preprint", "repository")
    elif source == "crossref":
        for link in record.get("link") or []:
            if isinstance(link, Mapping) and str(link.get("content-type")) == "application/pdf":
                add(link.get("URL"), "pdf", link.get("content-version"))
        resource = (record.get("resource") or {}).get("primary") or {}
        add(resource.get("URL"), "landing", "published")
        for alternative in record.get("alternative-id") or []:
            # Crossref reports an Elsevier PII only as an alternative id; the
            # ScienceDirect URL it expands to is the article's real home.
            if isinstance(alternative, str) and re.fullmatch(r"S\d{4}[0-9X]{6,}", alternative):
                add(f"https://www.sciencedirect.com/science/article/pii/{alternative}", "landing", "published")
    elif source == "unpaywall":
        entries = [record.get("best_oa_location"), *(record.get("oa_locations") or [])]
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            add(entry.get("url_for_pdf"), "pdf", entry.get("version"), entry.get("host_type"))
            add(entry.get("url_for_landing_page"), "landing", entry.get("version"), entry.get("host_type"))
    elif source == "arxiv":
        add(record.get("pdf_url"), "pdf", "preprint", "repository")
        add(record.get("abs_url"), "landing", "preprint", "repository")
    elif source == "pmc":
        url = str(record.get("pdf_url") or "")
        if url.startswith("s3://pmc-oa-opendata/"):
            url = url.replace("s3://pmc-oa-opendata/", BASES["pmc"] + "/", 1)
        manuscript = str(record.get("is_manuscript", "no")).lower() in ("yes", "true")
        add(url, "pdf", "accepted" if manuscript else "published", "repository")
    else:
        raise KeyError(source)

    unique: dict[str, dict[str, Any]] = {}
    for entry in found:
        unique.setdefault(entry["url"], entry)
    return list(unique.values())


# What each source is for, in the report a human reads. No source's setting is
# mandatory: OpenAlex answers unauthenticated, so discovery always has a
# source and every credential here only widens or speeds up coverage.
# The two sources that cannot be used at all without their setting: the
# unauthenticated Semantic Scholar pool answers 429 to almost everything, and
# Unpaywall requires a contact address by its own terms of use. OpenAlex and
# Crossref answer anonymously — a setting there buys a faster pool, not access.
REQUIRES_SETTING = ("semantic_scholar", "unpaywall")

ROLES = {
    "openalex": "默认检索来源",
    "semantic_scholar": "第二检索来源与标识符补全",
    "crossref": "DOI 元数据与出版商登记链接",
    "unpaywall": "开放副本定位",
    "arxiv": "预印本版本",
    "pmc": "已知 PMCID 的官方 PDF 文件",
}


def usable_sources(setting: Callable[[str], str] = credentials.source_setting) -> dict[str, bool]:
    """Which sources can actually be asked a question right now."""
    return {name: name not in REQUIRES_SETTING or bool(setting(name)) for name in BASES}


def source_report(setting: Callable[[str], str] = credentials.source_setting) -> list[dict[str, Any]]:
    """Which sources are usable, for setup and doctor output. No values."""
    rows = []
    for source in BASES:
        names = credentials.SOURCE_SETTINGS.get(source, ())
        rows.append({
            "source": LABELS[source],
            "role": ROLES[source],
            "setting": names[0] if names else None,
            "configured": True if not names else bool(setting(source)),
            "usable": source not in REQUIRES_SETTING or bool(setting(source)),
            # Degrading is always allowed: a missing setting narrows this one
            # source and never blocks the others.
            "degrades_to": None if source == "openalex" else "跳过该来源",
            "requests_per_second": round(1 / INTERVALS[source], 2),
        })
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    """Report source configuration and pacing. Reads nothing secret aloud."""
    import argparse

    parser = argparse.ArgumentParser(description="Report bibliographic source configuration")
    parser.parse_args(argv)
    print(json.dumps({"sources": source_report()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
