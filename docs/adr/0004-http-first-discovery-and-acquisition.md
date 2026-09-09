# ADR-0004: HTTP is the front door; the browser is the fallback

Status: Accepted

Date: 2026-09-06 (implementing `API_FIRST_IMPLEMENTATION_PLAN.md`, baseline `b57f4dd`)

## Context

ADR-0002 made the user's browser a *transport* and solved a real problem: the
three acquisition walls — entitlement, anti-bot, reachability — are cleared
together only by a real, logged-in browser. That decision stands.

What did not stand was routing **everything** through it. `process_run.py`
resolved every DOI through the browser and captured every URL through the
browser, even for a paper whose open-access PDF URL was already sitting in the
candidate record. Three costs followed:

- The default acquisition stage refused to start unless Kimi was connected
  (`capability.STAGE_REQUIREMENTS["acquisition"] = ("kimi",)`), so a batch of
  plain open-access papers was blocked by a browser extension it did not need.
- Every paper paid a browser round trip — measured at 10–15 s — where an
  HTTPS GET costs 2–3 s.
- Discovery had one provider. OpenAlex answering slowly, or not at all, was
  the whole run's coverage.

ADR-0001 deferred a second acquisition adapter "until a second real provider
exists". Two now do: HTTP and browser at the acquisition seam, OpenAlex and
Semantic Scholar at the discovery seam. The owner approved both, with a
Semantic Scholar key rated at one request per second across all endpoints.

## Decision

**Acquisition chooses its route** (`scripts/acquire.py`). Links already
recorded are fetched directly over HTTPS first; only if that produces no
verified file are Unpaywall, OpenAlex, Semantic Scholar, Crossref and arXiv
asked where else the full text lives; only then does the browser run.
`process_run.py` remains the single processing entry point and still owns the
subprocess seam, so `--browser-command` continues to substitute any program
speaking the `browser_pdf.py` protocol.

**Kimi gates one route, not the stage.** `STAGE_REQUIREMENTS["acquisition"]`
is empty and a new `browser_fallback` stage carries the Kimi requirement, so
`preflight --stage acquisition` reports what acquisition actually needs. A
missing browser channel is reported as `capability_missing` beside the papers
that needed it, while HTTP-reachable papers finish.

**Two discovery providers behind one command** (`scripts/discovery.py`).
OpenAlex and Semantic Scholar are asked in one round and merged: a normalized
DOI is decisive, and without one a merge additionally demands the same
normalized title, year and first-author surname. Every source's citation count
survives with its own observation date, disagreements are recorded in
`conflicts` rather than resolved by whoever answered first, and a preprint is
related to its version of record instead of folded into it.
`discover_openalex.py` survives as the same command restricted to OpenAlex.

**One request policy for every source** (`scripts/sources.py` over
`http_client.Throttle`). Pacing belongs to the API key and is shared across
processes through a lock file, so two commands cannot together break one
limit and a retry queues like a first attempt. A key reaches only its own
source's host and is dropped on a cross-origin redirect. A batch query sent as
POST is declared read-only, leaving the `outcome_unknown` contract that
protects Zotero writes untouched. Failures are classified, and only a genuine
`empty` may be reported as an absence of papers.

**The retrieval budget covers everything.** Both rounds, every source, every
retry, every throttle wait and every failure are charged to the run ledger,
and a restart reads the spent time back instead of starting a fresh five
minutes.

This supersedes ADR-0002's *routing* choice — the browser is no longer the
first channel — and closes ADR-0001's C4 deferral. Everything else in
ADR-0002 stands unchanged: the capture loop, `classify_page`, the trusted CDP
click, the in-page SHA-256, and the rule that a blocked host is reported
rather than worked around. ADR-0003's product constraints are untouched.

## Consequences

- Measured on this machine (`docs/api-first-validation-2026-09-06.md`): five of
  seven acquired papers came over HTTP at 2.4–3.3 s each, and three were
  acquired through the public entry point with the browser adapter
  deliberately unavailable. The browser still did the work only it can do —
  a JMIR anti-bot interstitial and a subscribed APA article behind
  institutional entitlement.
- Asking four metadata sources rescued papers that used to end
  `metadata_only`: a Nature Machine Intelligence article and an ACM paper were
  both acquired as labelled arXiv preprints.
- Two live defects surfaced that the browser-only path had hidden. A DOI was
  percent-encoded into API paths, which Crossref and Unpaywall answer with
  404. And the identity guard rejected a correct preprint because the
  camera-ready template it printed — `10.1145/XXXXXX.XXXXXX` — was read as a
  declared, conflicting DOI. An unfilled placeholder now declares nothing, and
  a word-perfect title under a conflicting DOI is `unverified` (kept for a
  human) rather than `rejected`.
- New failure modes are named rather than collapsed: `not_a_pdf`,
  `too_large`, `rate_limited`, and `browser_unavailable` — the last meaning
  *our* channel broke, which needs a different fix from an unreachable host.
- The cost of a source being down is now bounded explicitly. An early version
  handed each metadata lookup the paper's whole 240 s budget, and four dead
  sources took five minutes per paper; lookups are capped per source and as a
  phase.
- One request policy is a shared file on this machine. It cannot constrain
  another machine using the same key, and that limit is reported rather than
  implied.
- A discovery round now writes its candidate file only when a source actually
  answered, and exits non-zero otherwise. Writing unconditionally would let a
  dead network replace a run's approved candidate list with an empty one — the
  same "a network fact never becomes an empty result set" rule ADR-0002
  applied to the browser fallback, now applied to the file on disk.
- Keeping an unreadable or version-conflicted download is a *fallback*, not an
  ending: the remaining links are still tried and a verified file replaces it.
  A document that reprints a paper's title (an erratum, a comment) can
  otherwise stop acquisition for a paper whose real PDF was one link away.
- Not decided here: paging beyond one page per source, citation-network
  expansion, and PubMed as a discovery provider. Adding sources widens
  retrieval, not relevance, and the run's one budget is the reason to be
  choosy.
