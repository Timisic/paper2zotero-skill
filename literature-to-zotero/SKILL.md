---
name: literature-to-zotero
description: Find, screen, acquire, verify, summarize, and save scholarly papers to Zotero from a natural-language research intent or known paper identifiers. Use for psychology and AI literature searches that need a user-confirmed reading list, authenticated MyLOFT access, source PDFs, derived Markdown, and auditable Zotero ingestion. Do not use for writing a cross-paper literature review.
---

# Literature to Zotero

Turn a research intent into a verified Zotero collection while preserving the distinction between source metadata, source PDFs, derived text, and generated summaries.

Resolve `SKILL_DIR` to the directory containing this `SKILL.md` (Claude Code also exposes `${CLAUDE_SKILL_DIR}`). Run every bundled helper as `python "$SKILL_DIR/scripts/<name>.py"`; the user's current working directory is the run workspace, not the skill directory.

## The shape of a run

**Natural language → one screened list → one confirmation → automatic processing → one result table.**

A clear request authorizes retrieval inside its own intent, so there is no separate plan approval. The single planned pause is the confirmation in step 5. After it, `process_run.py` carries the batch without further instructions, and delivers whatever succeeded rather than waiting for everything.

## Choose the entry path

- **Discovery**: the user describes a literature need. Run the full workflow below.
- **Known papers**: the user supplies DOI, title, URL, or PDF. Initialize a run package and import their metadata as candidates. Reuse explicit selection, collection and upload authorization already provided; otherwise confirm the missing choices. For local PDFs, follow the short [local PDF entry](references/acquisition-and-artifacts.md#local-pdf-entry), then start at conversion.

## Runtime

On Windows PowerShell, run `& "$SKILL_DIR/scripts/run-python.ps1" <script-path> <args>`; on cmd.exe use `scripts/run-python.cmd`. In Claude Code's Windows Git Bash, use `bash "$SKILL_DIR/scripts/run-python.sh" <script-path> <args>`. These launchers restore the verified Python and PDF-tool paths, including paths with spaces or Chinese characters. On macOS/Linux, for Python CLI examples below, use `bash "$SKILL_DIR/scripts/run-python.sh"` in place of `python` or `python3`. Setup records the verified interpreter there, so commands work even when the agent shell has an older system Python.

## Routine execution

Use one agent and one run. For a new discovery request, the first shell command is `workflow.py init`, using the [run-package example](references/workflow.md#run-package); the loaded skill already supplies its installation directory. Continue with scope and discovery. Follow the CLI examples; consult `--help` for a missing argument, and source code for an actual implementation failure. A task's bounded service call is its live capability check. Use preflight for setup or a specifically uncertain dependency; an ingestion probe failure does not stop local import, conversion or writing summaries. Full setup/doctor is for first installation or environment changes. Keep stage events visible and capture the complete result JSON so the next command uses the returned fields.

For failures, use the same run and the supported [recovery path](references/recovery.md). The scripts own retries, empty-batch reconciliation and publisher Cookie redirects within existing authorization. Ask the human for missing selection/consent, actual login or account entry; collect technical defects into one maintenance report instead of successive patch-approval questions. Keep diagnostics under the run's `debug/` directory and deliver completed papers without a housekeeping question. Fix implementation defects in the canonical repository and distribute them through the managed installer so updates retain the fix.

Normal delivery ends with the returned table, read-back evidence and links to existing run artifacts. A second copy, image export or ZIP is a separate user-requested deliverable. Use `ingest.papers` for parent/note keys, hashes, local paths and `file_action`; the writer already verified them. Artifact completion does not certify interpretation. Extra review rounds and idempotency replays belong to requested evaluations.

Target about ten minutes after confirmation for five ordinarily accessible papers, not a guarantee for gated sources. Follow timestamped stage events and `timings`; distinguish script execution from human/agent handoff time. Use 15–30-second process waits while doing independent reading. At ten minutes report completed artifacts and the specific outstanding stage; finish a bounded in-flight operation or actionable recovery rather than extending unchanged probes. A human access challenge keeps its tab while other papers proceed.

## Workflow

1. On first installation or after environment changes, read [workflow.md](references/workflow.md) and follow the [Agent installation instructions](https://github.com/Timisic/paper2zotero-skill/blob/main/install/AGENT_SETUP.md) using the current host and agent target to install dependencies and configure services. Do not re-run full setup on an ordinary run. Check what a stage needs when that stage runs: `preflight.py --stage discovery|acquisition|browser_fallback|conversion|ingestion|local_sync`. Discovery and acquisition require nothing local — a search is never blocked because Zotero Desktop is closed, and an open-access PDF is fetched without a browser. Kimi gates `browser_fallback` alone. The automatic processing entry point requires Zotero Web API read/write credentials. MCP can assist library reading but does not replace the scripted writer or its credentials.
2. Initialize the run package with `workflow.py init`. Store every query, decision, artifact, warning, and paper state there. Never write run artifacts into the installed skill.
3. Translate the intent into controlled concept groups and record it with `workflow.py record-scope` — evidence of what you understood, not a claim that the user approved a plan. Ask a clarifying round only for an ambiguity that changes the result (construct, task, or time range); give transparent defaults for lesser preferences, and never invent a direction to hit a question quota.
4. Read [discovery-and-screening.md](references/discovery-and-screening.md). Run one `discovery.py` round over OpenAlex and Semantic Scholar together — it merges and deduplicates them — then screen. At most one purposeful supplementary round, and only when reliable candidates are clearly too few; `discovery.py --round supplementary --reason ...` holds that budget, which covers every source, every retry and every throttle wait. Read each source's status before presenting: only `empty` says the literature has nothing, and a `partial` round must be reported as such. Aim to have the list in front of the user within about five minutes — a target to measure, not a guarantee.
5. Present **one** list of 10–15 screened candidates from `candidate_table.py` (six if six is all there is — never pad), and in the same message ask for the selection, the target collection, and the MinerU upload choice. `references/workflow.md` has the wording. Accept explicit IDs or a deterministic rule ("citation top ten") resolved against this fixed snapshot.
6. Record the answer with `workflow.py approve-candidates` and `workflow.py consent`. Only selected IDs authorize acquisition and Zotero writes; cloud upload additionally requires consent covering those IDs. If the user answered only the selection, start the authorized work immediately and ask about upload only when conversion is next and no consent covers it.
7. Read [acquisition-and-artifacts.md](references/acquisition-and-artifacts.md), then run the batch:

   ```bash
   python "$SKILL_DIR/scripts/process_run.py" --run-dir <run_dir> --stages acquire,convert --check-ingestion \
     --collection-name '<approved collection>' --storage-root <Zotero-data-dir>
   ```

   This pass acquires, verifies and converts. The advisory `--check-ingestion` checks Zotero identity/write access once alongside the work; failure does not block PDFs, conversion or summaries. After summaries, step 9 ingests once with read-back. PDF-first ingestion remains available for early partial delivery. Resume the same run with `--ids` for named gaps. Do not compose a new ingestion script at runtime: an implementation error is a maintenance problem to report, not something to patch mid-run.
8. If `acquire.browser_handoff` is present, complete the [MyLOFT handoff](references/acquisition-and-artifacts.md#myloft-handoff) in the same browser session after the command exits. Use page evidence and the subscribed database; capture and record the verified PDF, or a precise unresolved state. This is already-authorized work, not a new confirmation. Then use `--stages convert` for newly acquired files and proceed to summaries, without retrying unresolved downloads.
9. `status: awaiting_summaries` returns `summary_batch_file`: a JSON object whose `summaries` list contains each full-text source, source basis/hash, Markdown section locations and a `content_file` for the summary body. Read [paper-summary.md](references/paper-summary.md). Read each main text once, consulting a passage again only to resolve a concrete question. Write each `content_file` in the paper's language unless the user specifies otherwise, following the six-part analysis contract without a length limit; self-check once. Run `summary_batch_command` with the actual agent model as provider to save and record the batch, then its `resume_command` (or `resume_shell`) to ingest with the approved collection and local read-back options. This is an internal handoff, not a new confirmation.
10. Deliver the returned `table` (`workflow.py report` regenerates it): per paper, PDF / Markdown / summary / Zotero cloud / local sync / pending reason, plus the collection and the local run path. Deliver the built-in verification evidence without re-querying the same objects. Report cloud-verified papers as delivered while Desktop downloads; only missing local evidence warrants a separate local check.

## Hard invariants

- One confirmation is the normal path, not a licence to assume consent. Missing information is asked for; it is never treated as approval. Existing authorization for the same papers, service and operation is reused on resume; added papers extend scope, revocation narrows only what it names.
- Default ranking prefers relevance over citation count; explicit user selection overrides it. Record resolved IDs, source message and dated citation snapshot. Hard constraints and venue exceptions stay explicit; "prefer top venues" is a ranking preference, not a filter.
- Publisher abstracts, screening reasons, derived Markdown, and generated summaries stay separately labeled. Missing evidence stays missing — never fill a column to make the table look complete, and never present a gap as "no literature exists".
- A source PDF is parseable and identity-matched. A login page, error page, unrelated file, or browser printout is not one. Unreadable text means `unverified` and the file is kept for a human — never rejected as the wrong paper.
- Artifacts do not block each other. A verified PDF can be saved independently when Markdown or summary is unavailable; a readable PDF supports a summary labeled `source_basis=pdf`; a summary is never written from an abstract. A paper waiting for login or a temporary service recovery stays `partial` with an actionable warning. Use `metadata_only` only when acquisition is deliberately ended; it is not a completed paper.
- DOI is the primary work identity. Reuse existing Zotero items and merge only missing data. `read_back_verified` requires real read-back of the item, its collection membership and its uploaded attachment bytes; local verification additionally requires the storage path and a matching hash.
- Acquisition prefers plain HTTP and falls back to the browser. A known open PDF costs one HTTPS GET and opens no browser at all, so Kimi being disconnected stops only the papers that actually need it. One automatic publisher attempt leads to an agent MyLOFT handoff when needed. The browser has one owner and one Kimi WebBridge session; `browser_pdf.py` clears an anti-bot checkbox itself; `challenge_unsolved` pauses that source for one human click, and `blocked` / `error` are recorded outcomes, not retry loops. Acquisition never invents a route.
- A source's answer is not the literature's answer. `empty` means a service really has nothing; `rate_limited`, `authentication_required`, `not_configured` and `unavailable` mean the channel failed and must never be reported as an absence of papers. Citation counts stay per source and dated; conflicts between sources are recorded, not resolved by whoever answered first.
- An API key goes only to the service that issued it — never to a publisher, a redirect target, or the browser fallback — and pacing for one key is shared across every command on this machine.
- Credentials never appear in chat, commands shown to the user, logs, or run packages. All helpers resolve credentials through `credentials.py`; temporary signed URLs stay in private checkpoint files (0600).
- For Pi model identity, use the session's declared model or read only `PI_PROVIDER` and `PI_MODEL`. A substring search for `PI_` also matches `API_KEY`; never enumerate or filter the environment to discover model settings.
- MinerU is the only Markdown derivation path — no local fallback. Uploading a PDF to MinerU requires explicit consent; without a token or consent, record `markdown_unavailable` and keep the verified PDF.
- Cancellation preserves completed writes and the run package. Cleanup is a separate, explicit action.
