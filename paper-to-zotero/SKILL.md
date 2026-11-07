---
name: paper-to-zotero
description: Find, screen, acquire, verify, summarize, and save scholarly papers to Zotero from a natural-language research intent, known paper identifiers, or local PDFs. Use for literature searches that need a user-confirmed reading list, source PDFs, derived Markdown, and auditable Zotero ingestion. Search and PDF download use scansci-pdf 1.19.0 with grey sources including Sci-Hub on, and fall back to Kimi WebBridge. `--legal-only` or `SCANSCI_LEGAL_ONLY=1` forces legal sources. Each PDF falls through self-hosted MinerU (only when MINERU_API_BASE is set), a MinerU cloud token, then local markitdown. Uploading a PDF needs recorded consent. Zotero writes use Zotero MCP or the local Desktop API. Do not use for writing a literature review, introduction, or discussion.
---

# Paper to Zotero

Turn a research intent into a verified Zotero collection while preserving the distinction between source metadata, source PDFs, derived text, and generated summaries.

Resolve `SKILL_DIR` to the directory containing this `SKILL.md` (Claude Code also exposes `${CLAUDE_SKILL_DIR}`). Run every bundled helper as `python "$SKILL_DIR/scripts/<name>.py"`; the user's current working directory is the run workspace, not the skill directory.

## Three stages

1. **Ingest**: scansci searches and downloads. Kimi WebBridge is the fallback for both.
2. **Write**: Zotero MCP or the local Desktop API saves items, PDFs, Markdown and notes, then reads them back ([zotero-ingestion.md](references/zotero-ingestion.md)).
3. **Use**: writing skills read the Zotero collection. This skill ends at stage 2.

## Choose the entry path

- **Local / known PDF**: the user or the agent already has the PDF. DOI is optional. Skip discovery and the candidate-list confirmation, and follow the [local PDF fast path](references/acquisition-and-artifacts.md#local-pdf-fast-path) only. Supplying the file is the selection. Do not upload before MinerU consent is recorded; if it is missing, ask once and re-run. `--backend local` is the no-upload opt-out. Ask for the Zotero collection only if the user has not named one, and only before ingestion.
- **Topic search**: the user describes a literature need and does not have the PDFs. Run the steps below. A clear request authorizes retrieval inside its own intent; the single planned pause is the confirmation in step 5. After it, `process_run.py` carries the batch and delivers whatever succeeded.
- **Identifier with no file** (DOI, title, or URL): import that metadata as candidates and start at `process_run.py --stages acquire,convert`.

## Runtime

On Windows PowerShell, run `& "$SKILL_DIR/scripts/run-python.ps1" <script-path> <args>`; on cmd.exe use `scripts/run-python.cmd`. In Claude Code's Windows Git Bash, and on macOS/Linux, use `bash "$SKILL_DIR/scripts/run-python.sh" <script-path> <args>` in place of `python`. These launchers restore the Python and PDF-tool paths that setup verified, including paths with spaces or Chinese characters.

## Routine execution

Use one agent and one run. For a new discovery request, the first shell command is `workflow.py init`, using the [run-package example](references/workflow.md#run-package). Follow the CLI examples; consult `--help` for a missing argument, and source code only for an actual implementation failure. A task's bounded service call is its live capability check. Use preflight only for setup or a specifically uncertain dependency. Capture the complete result JSON so the next command uses the returned fields.

For failures, use the same run and the [recovery path](references/recovery.md). The scripts own retries and reconciliation within existing authorization. Ask the human only for missing selection or consent, an actual login, or account entry. Collect technical defects into one maintenance report, keep diagnostics under the run's `debug/` directory, and fix defects in the canonical repository so the managed installer distributes the fix.

Normal delivery ends with the returned table, read-back evidence and links to existing run artifacts. Use `ingest.papers` for parent/note keys, hashes, local paths and `file_action`; the writer already verified them. Artifact completion does not certify interpretation.

## Topic search

1. On first installation or after environment changes, follow the [Agent installation instructions](https://github.com/Timisic/paper2zotero-skill/blob/main/install/AGENT_SETUP.md) for the current host and agent target. Do not re-run setup on an ordinary run. Check one stage with `preflight.py --stage discovery|acquisition|browser_fallback|conversion|ingestion|local_sync` ([workflow.md](references/workflow.md#preflight)).
2. Initialize the run package with `workflow.py init`. Store every query, decision, artifact, warning, and paper state there. Never write run artifacts into the installed skill.
3. Translate the intent into controlled concept groups and record it with `workflow.py record-scope`. That is evidence of what you understood, not a plan approval. Ask a clarifying round only for an ambiguity that changes the result (construct, task, or time range); give transparent defaults for lesser preferences.
4. Read [discovery-and-screening.md](references/discovery-and-screening.md) and run one `discovery.py` round. Only `empty` means the literature has nothing.
5. Present **one** list of 10–15 screened candidates from `candidate_table.py` (six if six is all there is; never pad), and in the same message ask for the selection, the target collection, and the MinerU upload choice. [workflow.md](references/workflow.md#confirmation-copy) has the wording. Accept explicit IDs or a deterministic rule ("citation top ten") resolved against this fixed snapshot.
6. Record the answer with `workflow.py approve-candidates` and `workflow.py consent`. `approve-candidates` adds ids; `revoke-candidates --ids` removes ids and keeps their artifacts; `import-candidates` appends. Only selected IDs authorize acquisition and Zotero writes; cloud upload also needs consent covering those IDs. If the user answered only the selection, start the authorized work and ask about upload only when conversion is next.
7. Read [acquisition-and-artifacts.md](references/acquisition-and-artifacts.md), then run the batch:

   ```bash
   python "$SKILL_DIR/scripts/process_run.py" --run-dir <run_dir> --stages acquire,convert --check-ingestion \
     --collection-name '<approved collection>' --storage-root <Zotero-data-dir>
   ```

   Add `--legal-only` when the user wants legal PDF sources only. The advisory `--check-ingestion` failure does not block PDFs, conversion or summaries. Resume the same run with `--ids` for named gaps. Do not compose a new ingestion script at runtime.
8. If `acquire.browser_handoff` is present, complete the [MyLOFT handoff](references/acquisition-and-artifacts.md#myloft-handoff) in the same browser session after the command exits. This is already-authorized work. Then run `--stages convert` for newly acquired files, without retrying unresolved downloads.
9. `status: awaiting_summaries` returns `summary_batch_file`, whose `summaries` list gives each full-text source, its basis and hash, Markdown section locations and a `content_file`. Read [paper-summary.md](references/paper-summary.md). Write each `content_file` yourself, in this turn, in the paper's language unless the user specifies otherwise, then self-check once. Do not pause the user for the prose. Run `summary_batch_command` with the actual agent model as provider, then its `resume_command` (or `resume_shell`) to ingest.
10. Deliver the returned `table` (`workflow.py report` regenerates it) with the collection and the local run path. Report read-back papers as delivered while Desktop downloads. When the papers and notes are saved, add one short reminder in the user's language, naming the actual collection: “基于本次 Zotero 集合及子集合，可以用 academic-paper 的 lit-review 模式写文献综述，用 nature-writing 写引言；提供研究背景和核心发现后，用 discussion-drafter 写讨论并附 APA 参考文献表。” Say that the writing skills need a working Zotero MCP connection. This is a suggestion, not permission to start drafting.

## Hard invariants

- One confirmation is not a licence to assume consent. Missing information is asked for, never treated as approval. Existing authorization for the same papers, service and operation is reused on resume; added papers extend scope, and revocation narrows only what it names.
- Default ranking prefers relevance over citation count; explicit user selection overrides it. "Prefer top venues" is a ranking preference, not a filter.
- Publisher abstracts, screening reasons, derived Markdown, and generated summaries stay separately labeled. Missing evidence stays missing. Never fill a column to make the table look complete, and never present a gap as "no literature exists".
- A source PDF is parseable and identity-matched. A login page, error page, unrelated file, or browser printout is not one. Unreadable text means `unverified`, and the file is kept for a human.
- Artifacts do not block each other. A verified PDF can be saved without Markdown or a summary; a readable PDF supports a summary labeled `source_basis=pdf`; a summary is never written from an abstract. Use `metadata_only` only when acquisition is deliberately ended.
- DOI is the primary work identity. One DOI stays one item. Replace only this run's own PDF, Markdown and `literature-to-zotero` note. Do not write a note that says AutoResearch, and do not edit notes this run does not own.
- PDF order is an existing verified `source.pdf`, then scansci-pdf (`pip install 'scansci-pdf==1.19.0'`, no browser extra), then Kimi WebBridge ([acquisition order](references/acquisition-and-artifacts.md#acquisition-order)). The browser has one owner and one Kimi WebBridge session. A URL or SHA-256 already stored for this run is already obtained: do not open it again and do not click the publisher download control. The PDF is written under the run directory, not the Downloads folder.
- A source's answer is not the literature's answer. `rate_limited`, `authentication_required`, `not_configured` and `unavailable` mean the channel failed. Citation counts stay per source and dated.
- An API key goes only to the service that issued it. Credentials never appear in chat, commands shown to the user, logs, or run packages; helpers resolve them through `credentials.py`.
- For Pi model identity, use the session's declared model or read only `PI_PROVIDER` and `PI_MODEL`. A substring search for `PI_` also matches `API_KEY`; never enumerate the environment.
- Topic search and the local PDF fast path share one [converter chain](references/acquisition-and-artifacts.md#markdown). An upload hop needs recorded consent for that paper. A paper no hop converted keeps its verified PDF.
- Cancellation preserves completed writes and the run package. Cleanup is a separate, explicit action.
