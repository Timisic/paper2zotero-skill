# Architecture and working context

`literature-to-zotero/` is the distributable skill. [README.md](README.md) covers user configuration and use; [SKILL.md](literature-to-zotero/SKILL.md) and its references define Agent execution. Public validation scope and platform limitations are documented in [docs/README.md](docs/README.md).

## Workflow

Research intent → one candidate list → confirmation of selected papers, collection and MinerU upload choice → PDF acquisition/verification → conversion → full-text summary → Zotero ingestion/read-back → per-artifact result.

A supplied PDF starts at the local import path. Existing authorization is reused within its scope. One failed paper does not block independent work on others. A run is continued rather than recreated after interruption.

## Modules and ownership

| Module | Responsibility |
|---|---|
| `workflow.py` (`Run`, `Paper`) | Run schema, selected IDs, consent, artifact paths, state transitions and reporting; `import-pdfs` handles local PDF copying/verification/recording |
| `process_run.py` | Compose acquisition, conversion and ingestion; return summary handoff and executable ingestion continuation |
| `discovery.py`, `sources.py` | Bounded discovery, source-specific responses, normalization and citation provenance |
| `acquire.py`, `browser_pdf.py` | HTTP-first retrieval; browser fallback when required by actual access evidence |
| `paper_artifacts.py` | PDF integrity and identity verification |
| `mineru_parse.py` | Consented conversion, batch checkpoints, response-loss recovery and extracted artifacts |
| `summary_artifact.py` | Store the Agent's summary with provider, template version and source basis |
| `zotero_ingest.py` | DOI reuse, journaled writes, missing-field merges, artifact reuse and cloud/local read-back |
| `credentials.py`, `capability.py` | Credential resolution and capability semantics; preflight/setup/verify consume these |
| `http_client.py` | Bounded requests, shared pacing, credential-safe redirects and uncertain-write outcomes |

Scripts use `Run`/`Paper` rather than duplicating manifest navigation. Deterministic scripts own service operations and recovery; the Agent owns research interpretation, screening and summarization. The automatic writer uses Zotero Web API credentials; MCP is optional assistance, not an alternative automatic writer.

## Domain terms

- **Candidate**: a bibliographic work with source metadata, stable identity and screening evidence. DOI is the primary identity; title/year/first author are the fallback.
- **Selection**: the exact user-authorized candidate IDs, including any deterministic selection rule and its fixed snapshot.
- **Consent**: permission to upload specified PDFs to MinerU. Added papers are outside previous consent until explicitly covered.
- **Source PDF**: the original downloaded/provided paper, distinct from browser printouts, derived text and generated notes.
- **Verification**: `verified` when identity matches; `rejected` when bytes or identity are wrong; `unverified` when identity cannot be established. Unreadable is not the same as wrong.
- **Derived Markdown**: MinerU's reading representation, with extraction limitations; it does not replace the source PDF.
- **Summary**: approximately 1,000 Chinese characters by default, with central findings, a key limitation and grounded takeaways. One explicit draft read-back checks measurement and inference boundaries before packaging. Artifact completion does not certify interpretation quality.
- **Run package**: resumable local evidence for one request—candidates, decisions, artifacts, checkpoints and per-paper state.
- **Summary handoff**: full-text source/basis and output instructions returned by processing; an internal step in already-authorized work.
- **Access wall**: entitlement, anti-bot challenge or network reachability, each with a different remedy.

## Invariants

- One clear confirmation is the normal path; unknown choices are not consent. Cancellation preserves finished artifacts and writes. Cleanup requires its own scope.
- Source metadata, abstracts, generated screening reasons, derived Markdown and summaries remain distinguishable.
- Missing evidence stays missing. Source failures (`not_configured`, `rate_limited`, `unavailable`) do not mean no relevant literature exists.
- Shared request budgets include retries and waits. A failed write response may mean the write succeeded; reconcile the journal before retrying.
- API credentials reach only their issuing service and never appear in outputs, logs or run artifacts.
- Existing Zotero metadata, notes and attachments are preserved. DOI matches and identical attachment bytes are reused; attachment `file_action` reports reuse/upload behavior.
- Conversion needs recorded upload consent. A missing token or failed conversion leaves the verified PDF usable; a summary requires readable full text, not an abstract alone.
- Cloud read-back checks item identity, collection, summary and attachment bytes. Local verification additionally needs real storage files with matching hashes.

## Delivery states

| State | Meaning |
|---|---|
| `awaiting_summaries` | Full text is ready; the Agent writes/checks summaries and uses the returned continuation command |
| `partial` | Deliverable work exists, with named missing artifacts or evidence |
| `sync_pending` | Cloud content is verified, but local attachment availability is not yet verified |
| `read_back_verified` | Required read-back evidence is present; inspect the per-artifact report for overall completeness |
| `metadata_only` | Full-text acquisition was explicitly ended; not a complete paper |

Stage preflight checks only that stage's dependencies. Network failure leaves identity/permission unknown, while explicit 401/403 refusal is a distinct observation. Ordinary execution begins with the business command; complete returned evidence is used for delivery without repeating the same checks.

## Development

Read the relevant [ADRs](docs/README.md#architecture-decisions) before changing boundaries. Add meaningful tests around consent, recovery, identity and read-back behavior. Fixture tests are not live service acceptance.

```bash
cd literature-to-zotero
python3 -m pytest tests -q
python3 -m mypy scripts
```

The tests isolate real browser/network state. Local PDFs, run artifacts and cleanup snapshots under `literature-runs/` are ignored by Git; preserve them separately when needed for reproduction. Commit task-owned changes in coherent groups; publishing and pushing are separate actions.
