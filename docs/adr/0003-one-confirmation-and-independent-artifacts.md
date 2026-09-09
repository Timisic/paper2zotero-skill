# ADR-0003: One confirmation, a bounded search, and artifacts that do not block each other

Status: Accepted

Date: 2026-09-05 (implementing `SIMPLIFICATION_PLAN.md`, baseline `d477d38`)

## Context

The first full production run worked and was unusable. From the session log
(`2026-09-05T05-50-48`), the wall-clock shape of it was:

| Phase | Time |
|---|---|
| Search approval → candidate list | 23 min 07 s |
| Waiting for a separate MinerU upload confirmation | 11 min 37 s |
| Ingestion prep → handoff, still unfinished | 21 min 36 s |
| MinerU conversion including network triage | 5 min 38 s |
| Downloading and verifying 10 papers | 3 min 03 s |

The slow parts were not the services. Acquisition was already fast (about
10–15 s per verified PDF). The cost was in the shape of the workflow: two
separate human gates with the second one arriving after the first had gone
cold, a `20 core + 10 expansion` structure that forced retrieval to keep
going until it could fill 30 slots, per-request budgets with no run-level
stop, and an ingestion path that refused to write anything for a paper until
that paper had a summary — so a batch stalled on its slowest artifact and the
run ended with a 12 min 51 s retry loop and nothing delivered.

The owner then decided the product trade-offs directly: deliver a batch of
papers worth reading quickly, accept incomplete coverage, deliver whatever
succeeded, and keep the reliability work from `74a470e`/`d477d38` intact.

## Decision

**One confirmation.** A natural-language request authorizes retrieval inside
its own intent. The separate search-plan gate is removed; the scope the agent
inferred is recorded as evidence (`workflow.py record-scope`), which
authorizes nothing. The one remaining pause combines candidate selection,
target collection and MinerU upload consent into a single message. A run
created under the old schema is read without its retired gate.

**A bounded search.** One initial round, at most one purposeful supplementary
round, and one run-level time budget (~5 min target) that network retries
spend rather than reset. `discover_openalex.py` claims the budget before it
spends time on the network, so a refused round costs nothing.

**One list.** 10–15 screened candidates with a required screening sentence and
a source link. `core`/`expansion` becomes optional labelling instead of a
required structure, and a short list stays short (`below_default_list`)
instead of being padded.

**Independent artifacts.** The writer validates and writes what a paper
actually has. Only the source PDF gates ingestion, because its identity must
be proven before anything is written; Markdown and the summary attach to the
same parent whenever they arrive. `partial` (an artifact is missing) and
`sync_pending` (only Zotero Desktop is behind) are deliveries, not failures,
and neither re-runs the batch.

**One processing entry point.** `process_run.py` composes the existing
modules — `browser_pdf`, `paper_artifacts`, `mineru_parse`, `zotero_ingest`,
`workflow` — into acquire → verify → convert → write → read back, per paper,
and resumes the same run afterwards. It adds no new service, no new state
system, and no scheduler. Summaries stay with the agent and come back as a
structured `awaiting_summaries` handoff rather than as a question to the user.

**Stage-scoped capability checks.** Each stage checks what it uses.
Discovery requires nothing local, so a search can never be blocked because
Zotero Desktop is closed.

## Consequences

- The normal path pauses for the user exactly once. Recovery inside an
  authorized scope, and handoffs between the fixed scripts and the agent,
  never ask again.
- "Complete" is now reachable only when every artifact is present and synced.
  A run where the user declined MinerU reports `partial` — honest, and
  deliverable at exit 0. Callers must read the structured status instead of
  retrying on any non-zero exit.
- Coverage is explicitly not guaranteed. The stopping rule can return six
  papers with a coverage note, and that is a correct result.
- Nothing in the identity, deduplication, authorization, hash, credential or
  recovery guarantees is relaxed; those regressions stay in the test suite.
- The paper-state machine now distinguishes progress from artifact arrival: a
  Markdown or summary may be recorded against an already read-back paper, and
  a re-ingest writes it. A confirmed paper may go straight to `pdf_acquired`,
  because acquisition verifies the PDF against the candidate's own metadata.
- The delivery row separates `pending` (what is missing now, from the
  artifacts), `notes` (why), and `actionable` (whether re-running can help).
  Reporting was previously derived partly from an append-only warning list,
  which made a recovered run look permanently unfinished.
- The five-minute first-list target is unmeasured in production. It must be
  met by removing excess retrieval, not by weakening evidence, hiding
  failures, or moving the start of the clock.
