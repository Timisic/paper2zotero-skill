# Architecture and working context

`paper-to-zotero/` and `writing/discussion-drafter/` are this repository's skills. All writing skills live in `writing/`; the vendored ones and their licences are listed in [THIRD_PARTY.md](THIRD_PARTY.md). [SKILL.md](paper-to-zotero/SKILL.md) and its references define literature ingestion. Maintainer docs start at [docs/README.md](docs/README.md).

## Workflow

Three stages. Ingest: scansci searches and downloads, with Kimi WebBridge as the fallback for both ([ADR-0005](docs/adr/0005-ingest-existing-pdf-scansci-kimi.md)). Write: the journaled writer saves through the local Desktop API, or the Web API, and reads back. Use: the writing skills read the Zotero collection through the local Desktop API with `writing/discussion-drafter/scripts/zotero_read.py`. Zotero MCP is optional for both.

Research intent → one candidate list → confirmation of selected papers, collection and upload choice → PDF acquisition and verification → conversion → full-text summary → Zotero ingestion and read-back → per-artifact result. A supplied PDF starts at `local_pdf.py` and joins the same conversion, summary and ingestion steps. One failed paper does not block the others. An interrupted run is continued, not recreated.

## Modules and ownership

| Module | Responsibility |
|---|---|
| `workflow.py` (`Run`, `Paper`) | Run schema, selected IDs, consent, artifact paths, state transitions and reporting; `import-pdfs` copies, verifies and records local PDFs |
| `local_pdf.py` | Local PDF fast path: extract DOI or title, complete the record, verify, then convert once consent is recorded |
| `process_run.py` | Compose acquisition, conversion and ingestion; return the summary handoff and the ingestion continuation |
| `discovery.py`, `sources.py` | Bounded discovery, source-specific responses, normalization and citation provenance |
| `scansci_retrieval.py` | scansci-pdf search and download adapter, grey and legal-only policy |
| `acquire.py`, `browser_pdf.py` | PDF route: existing file, scansci, open links and metadata lookups, then Kimi WebBridge |
| `paper_artifacts.py` | PDF integrity and identity verification |
| `mineru_parse.py` | Consented conversion, batch checkpoints, response-loss recovery and extracted artifacts |
| `summary_artifact.py` | Store the Agent's summary with provider, template version and source basis |
| `zotero_ingest.py` | DOI reuse, journaled writes, missing-field merges, artifact reuse and Zotero/local read-back |
| `credentials.py`, `capability.py` | Credential resolution and capability semantics; preflight, setup and verify consume these |
| `http_client.py` | Bounded requests, shared pacing, credential-safe redirects and uncertain-write outcomes |
| `writing/discussion-drafter/scripts/zotero_read.py` | Read-only library reads over the local Desktop API: collections, items, full notes, annotations, attachment text, PDF pages and APA citations. Standard library plus PyMuPDF, so it runs without the paper-to-zotero modules |

Scripts use `Run`/`Paper` rather than duplicating manifest navigation. Deterministic scripts own service operations and recovery; the Agent owns research interpretation, screening and summarization. Write paths are in [zotero-ingestion.md](paper-to-zotero/references/zotero-ingestion.md).

## Domain terms

- **Candidate**: a bibliographic work with source metadata, stable identity and screening evidence. DOI is the primary identity; title, year and first author are the fallback.
- **Selection**: the exact user-authorized candidate IDs, including any deterministic selection rule and its fixed snapshot. Approval adds ids, revocation removes only the ids it names, and a candidate import appends.
- **Consent**: permission to upload specified PDFs to MinerU. Added papers are outside previous consent until explicitly covered.
- **Source PDF**: the original downloaded or provided paper, distinct from browser printouts, derived text and generated notes.
- **Verification**: `verified` when identity matches; `rejected` when bytes or identity are wrong; `unverified` when identity cannot be established. Unreadable is not the same as wrong.
- **Derived Markdown**: the converter's reading representation, with extraction limits; it does not replace the source PDF.
- **Summary**: a full-text analysis in the paper's language by default, with one draft read-back before packaging. Artifact completion does not certify interpretation quality.
- **Run package**: resumable local evidence for one request: candidates, decisions, artifacts, checkpoints and per-paper state.
- **Access wall**: entitlement, anti-bot challenge or network reachability, each with a different remedy.

## Invariants

- One clear confirmation is the normal path; unknown choices are not consent. Cancellation preserves finished artifacts and writes. Cleanup requires its own scope.
- Source metadata, abstracts, generated screening reasons, derived Markdown and summaries remain distinguishable. Missing evidence stays missing; a source failure never means no literature exists.
- Shared request budgets include retries and waits. A failed write response may mean the write succeeded; reconcile the journal before retrying.
- API credentials reach only their issuing service and never appear in outputs, logs or run artifacts.
- Existing Zotero metadata, notes and attachments are preserved. DOI matches and identical attachment bytes are reused.
- Topic search and local PDFs share one [converter chain](paper-to-zotero/references/acquisition-and-artifacts.md#markdown). A missing token or failed conversion leaves the verified PDF usable. A summary requires readable full text, not an abstract alone.
- Delivery states are defined per paper in [zotero-ingestion.md](paper-to-zotero/references/zotero-ingestion.md) and per run in [workflow.md](paper-to-zotero/references/workflow.md#processing).

Read the relevant [ADRs](docs/README.md#architecture-decisions) before changing boundaries. Fixture tests are not live service acceptance. Workflow verification is [verify-paper2zotero](.agents/skills/verify-paper2zotero/SKILL.md).
