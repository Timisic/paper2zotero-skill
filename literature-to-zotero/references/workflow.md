# Workflow contract

## Preflight

In the commands below, `SKILL_DIR` is the directory containing the loaded `SKILL.md`.

`python "$SKILL_DIR/scripts/preflight.py" --json` reports every capability plus one overall `ready`. Ordinary runs start the stage directly; when uncertain, `--stage` checks only its dependencies and omits unrelated credentials/network probes.

```bash
python "$SKILL_DIR/scripts/preflight.py" --json --stage ingestion
```

| Stage | Requires | Not required |
|---|---|---|
| `discovery` | nothing local | Zotero Desktop, file sync, Kimi |
| `acquisition` | nothing: an open PDF is an HTTPS GET | Kimi WebBridge, Zotero of any kind |
| `browser_fallback` | Kimi WebBridge connected | Zotero of any kind |
| `conversion` | MinerU token (plus recorded consent) | Zotero Desktop |
| `ingestion` | Zotero Web API key with write permission | Zotero Desktop being open |
| `local_sync` | Zotero Desktop local API and attachment file sync | — |

Searching is never gated on Zotero Desktop or its sync state. A configured token is not proof of current reachability, and a successful key probe proves account permission, not that a later upload will succeed. Use the setup doctor (`scripts/setup.py`) on first use or environment changes, not on every run.

Treat returned text containing `Error`, `Forbidden`, `Cannot perform`, or an equivalent failure as failure even when the protocol reports `is_error=false`.

Markdown derivation runs through MinerU precise API (`vlm`). It needs a token (`$MINERU_TOKEN` or `~/.config/mineru/token`) and user consent to upload the PDF. When either is absent, record `markdown_unavailable` and keep the verified PDF; do not substitute another converter.

## Run package

Initialize one run outside the skill directory:

```bash
python "$SKILL_DIR/scripts/workflow.py" init \
  --run-root literature-runs \
  --slug <short-ascii-topic> \
  --intent '<verbatim user intent>' \
  --from-year <year> --to-year <year>
```

Keep the returned absolute `run_dir`. Its manifest is the workflow's source of truth. The manifest carries exactly one gate, `candidate_selection`; a run created before this simplification is read without its retired plan gate.

Scripts reach run state through `workflow.Run` and `workflow.Paper` rather than the manifest's JSON: `Run.open(dir)` to read, `Run.locked(dir)` to mutate under the run lock, `Run.record(dir, id, ...)` for a single paper. A `Paper` answers `pdf` / `markdown` / `summary` (the artifact, only when the file is on disk), `path(field)` (what was recorded, present or not), `state`, `warnings` and `writable`. Anything writing its own manifest navigation is duplicating a rule that lives there.

Record the interpreted scope as evidence — it authorizes nothing and blocks nothing:

```bash
python "$SKILL_DIR/scripts/workflow.py" record-scope --run-dir <run_dir> \
  --scope 'AI mental-health interventions; 2023-2026; English preferred; prefer top venues'
```

Each retrieval round is logged against one run-level budget (`workflow.py status` reports `search`). `discovery.py --run-dir` records its own round across every source it asked, including the time lost to failures and throttle waits; a restart reads the spent time back from the ledger instead of starting a fresh budget. `workflow.py record-search` logs a round run through another provider. A second supplementary round is refused unless the user asked to widen coverage (`--user-requested`).

After screening:

```bash
python "$SKILL_DIR/scripts/workflow.py" import-candidates --run-dir <run_dir> --file <candidates.json>
python "$SKILL_DIR/scripts/candidate_table.py" --input <candidates.json> --output <candidate-table.md>
```

The table needs a screening sentence (`hit_reason`) and refuses more than 15 rows unless `--max-rows` is raised because the user asked for a longer list. `candidate_set` is optional: label candidates only when the distinction helps this user.

After the user's confirmation:

```bash
python "$SKILL_DIR/scripts/workflow.py" approve-candidates --run-dir <run_dir> \
  --ids '<id1,id2,id3>' --source '<selection message reference>' \
  --rule '<explicit IDs or resolved ranking rule>'

python "$SKILL_DIR/scripts/workflow.py" consent --run-dir <run_dir> \
  --service mineru --decision approved --source '<consent message reference>'
```

`--ids` narrows consent to a subset; omitted means the current selected set. `denied` and `revoked` are also accepted. Later additions are not implicitly consented. Repeating the same selection preserves progress.

`record-paper` advances one paper after its artifact or external state has been verified. Paths resolve against the run and must exist.

```bash
python "$SKILL_DIR/scripts/workflow.py" record-paper \
  --run-dir <run_dir> --id <candidate-id> --state <state> \
  --artifact 'pdf=/absolute/path/to/source.pdf'
```

Terminal states are `read_back_verified`, `sync_pending`, `metadata_only`, `partial`, and `failed`. `partial` means an artifact is still missing; `sync_pending` means the cloud is verified and only Zotero Desktop has yet to download the binary. Neither is a failure and neither reruns the batch.

## Processing

Normal path: `--stages acquire,convert` → agent writes/checks summaries once → `--stages ingest`. With PDFs already present, start at `--stages convert`; with summaries ready, start at `--stages ingest`. The combined default command remains available for recovery and early partial delivery. Routine delivery does not need an extra idempotency replay.

```bash
python "$SKILL_DIR/scripts/process_run.py" --run-dir <run_dir> --stages acquire,convert \
  --collection-name '<approved collection name>' --storage-root <Zotero-data-dir>
```

One entry point for the normal path and for continuing: acquire → verify → convert (consented PDFs) → write → read back, per paper. `--ids` limits it to named papers; `--stages` limits it to part of the pipeline. `--dry-run` validates the local artifacts only — it never downloads a PDF or uploads one to MinerU. Its `status` is one of:

| `status` | Meaning | Exit |
|---|---|---|
| `complete` | every selected paper has all its artifacts, written and synced | 0 |
| `partial` | not every paper is complete; each row names what it is still missing | 0 |
| `awaiting_summaries` | full text is ready and the agent owes the summaries in `pending_summaries` | 0 |
| `pending` | a service or input error the caller must act on; re-run the same command | 2 |

After recording summaries, execute the returned `resume_command` argument list or its quoted `resume_shell`. It preserves the collection, selected IDs and local storage options. Conversion alone does not persist the collection; manually written ingestion commands must carry it again.

Never wrap this in a shell loop that retries on any non-zero exit. Read the structured result.

Failed acquisition returns `acquire.browser_handoff` with the paper ID, expected identity, output path, session, candidate URLs and observed walls. The agent follows the MyLOFT handoff in acquisition-and-artifacts.md before declaring full text unavailable. Only one browser owner operates at a time.

The browser fallback runs through a replaceable program: `--browser-command TOKEN` (repeat the flag once per argv token) substitutes anything speaking the `browser_pdf.py` protocol — `capture`, one JSON line on stdout, exit 0 only on success. The default is the bundled `browser_pdf.py`, and only that default requires the Kimi channel; when it is missing, HTTP acquisition still runs and the stage reports `capability_missing` beside the papers that needed a browser. `--no-source-lookup` restricts acquisition to links already recorded, and `--acquire-timeout` bounds one paper across every route. This is how the acquisition logic is tested without a live browser; it is not a way to acquire from an unverified source, since identity verification still runs on the bytes that come back.

## Confirmation copy

One message, one answer:

```text
<the candidate table>

Reply with the numbers you want (or a rule such as "citation top ten").
I will download and verify the source PDFs, save them to the Zotero collection
"<name>", convert them to Markdown and write a full-text-based summary.
Conversion uploads new PDFs to MinerU — reply e.g. "1-8, allow upload" or
"1-8, no upload".
```

State preferences and hard requirements separately, name the exact venue set when one applies, and preserve the user's language scope. If the user answers only with numbers, start the authorized work and ask about upload only when conversion is next.

Keep abstracts, complete author lists, and query syntax in the run package unless the user asks for them.

## Delivery report

`process_run.py` returns it, and `workflow.py report --run-dir <run_dir> --format markdown` regenerates it:

```text
Paper | PDF | Markdown | Summary | Zotero cloud | Local sync | Pending
```

Present it in the user's language, with the collection name and the local run path. A row is complete only when every artifact is present and synced — a readable PDF alone is not a completed paper, and cloud-verified with local sync pending is delivered, not blocked.

Each row separates three things. `pending` is what the paper is missing right now, computed from its artifacts, so a warning from an attempt that later succeeded never keeps a finished paper looking unfinished. `notes` is the observed history behind those gaps. `actionable` says whether re-running could still change the row — a paper with no obtainable full text is finished, not waiting. Without `--storage-root` the local copy is never inspected, and the row says `local sync not checked` rather than claiming a sync failure.
