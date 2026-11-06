# ADR-0005: Ingest through an existing PDF, then scansci, then Kimi WebBridge

Status: Accepted. Supersedes [ADR-0002](0002-browser-acquisition-channel.md) and [ADR-0004](0004-http-first-discovery-and-acquisition.md).

ADR-0004 searched OpenAlex and Semantic Scholar and fetched PDFs over plain HTTP, with the browser as the last resort. That path needed API keys before the first search, and many papers had no open link, so researchers often ended at the browser handoff. scansci-pdf searches and downloads in one library call and needs no account.

Ingest now has one order for search and one for PDFs:

- Search uses scansci-pdf. When scansci fails and no `--sources` list is given, the same round asks Kimi WebBridge. `SEARCH_BACKEND=kimi` searches with Kimi only. `SEARCH_BACKEND=http`, `openalex`, `semantic_scholar` or an explicit `--sources` list keeps the OpenAlex and Semantic Scholar path as an opt-in.
- A PDF comes from an existing verified `source.pdf`, then scansci (its library download, then one HTTPS GET per known open link and the metadata lookups), then one Kimi WebBridge attempt in the user's logged-in browser, then the agent's MyLOFT handoff.
- Grey sources, including Sci-Hub, are on by default. `--legal-only` or `SCANSCI_LEGAL_ONLY=1` restricts scansci to legal sources.

## Consequences

- Every route returns bytes that pass the same PDF identity check. The route never changes verification, hashing or recovery.
- A disconnected browser stops only the papers that reach Kimi WebBridge.
- A failed source is recorded as a failure, never as "no papers".
- The shared request policy, per-key pacing and credential stripping from ADR-0004 still apply to every HTTP call.
- Grey sources are a product default the user can turn off per run or per machine. The docs name the opt-out wherever they name the default.
- The current route details live in [acquisition-and-artifacts.md](../../paper-to-zotero/references/acquisition-and-artifacts.md) and [discovery-and-screening.md](../../paper-to-zotero/references/discovery-and-screening.md).
