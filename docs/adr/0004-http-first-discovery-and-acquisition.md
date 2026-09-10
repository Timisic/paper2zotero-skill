# ADR-0004: Prefer HTTP; use the browser when needed

Status: Accepted. Supersedes the browser-first routing in [ADR-0002](0002-browser-acquisition-channel.md).

Routing every paper through the browser added interaction overhead and blocked open-access PDFs when the browser extension was disconnected. Depending on one discovery provider also made a single service failure limit the whole search.

`scripts/acquire.py` first tries known PDF links over HTTP. If no verified PDF is obtained, it asks metadata sources for further locations and then uses the browser where needed. `process_run.py` remains the processing entry point. A missing browser channel affects only papers that require it.

`scripts/discovery.py` searches OpenAlex and Semantic Scholar within one round, normalizes results and merges duplicates while retaining source-specific citation counts and observation dates. A preprint remains distinguishable from its version of record. Service failures are not reported as an absence of papers.

`scripts/sources.py` uses the shared request policy in `http_client.py`. Retries and throttle waits count toward the run budget. Credentials go only to their issuing service and are removed on cross-origin redirects. An uncertain write response is reconciled through its journal before replay.

## Consequences

- HTTP and browser requests must both return bytes that pass the same PDF identity checks.
- Lookup time and request size are bounded; one failing service must not stall every paper.
- An unreachable source must not replace an approved candidate file with an empty result.
- Pacing is shared across processes on this machine; it does not coordinate other machines using the same account.
- Current route order and browser handoff instructions live in [acquisition-and-artifacts.md](../../literature-to-zotero/references/acquisition-and-artifacts.md), rather than in historical timing reports.
