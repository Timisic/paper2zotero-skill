# Zotero ingestion

`process_run.py` calls this writer as its last stage. Use `zotero_ingest.py` directly to dry-run, or to write when acquisition and conversion are already done.

## Journaled writer (all runtimes)

Use the same writer with or without Zotero MCP. MCP remains useful for discovery of existing library data; the writer owns this run's mutations and checkpoints.

```bash
python "$SKILL_DIR/scripts/zotero_ingest.py" --run-dir <run_dir> --dry-run
python "$SKILL_DIR/scripts/zotero_ingest.py" --run-dir <run_dir> \
  --collection-name '<approved collection name>' --storage-root <Zotero-data-dir>
```

For an existing collection, pass `--collection-key` instead. Subsequent calls reuse the saved collection automatically; `--ids` narrows a call to named selected papers. A run is bound to its first library and collection; changing targets is a separate decision. The writer requires only Python's standard library and the shared Zotero credentials. It serializes operations within the run (macOS/Linux file lock).

The writer:

1. Validates what the paper has. Only the source PDF gates ingestion, because its identity must be proven before anything is written; a paper without one must already be explicitly `metadata_only`. Markdown and the summary are checked when present and reported as pending when absent.
2. Scans every item page for a normalized DOI match. Without DOI it requires title, year and first-author identity. Ambiguous duplicates stop that paper. A supplied `--reuse-map <json>` maps selected candidate IDs to existing keys and is identity-checked.
3. Journals a stable key, creation payload and write token before each create. Response loss resumes by reading that key; a version-zero create cannot overwrite a persisted object.
4. Merges missing metadata, adds collection membership and requested tags using a version precondition, preserving populated fields and other collections. A conflict requires a fresh read on resume.
5. Reuses matching files by SHA-256. An empty attachment record resumes uploading instead of being treated as complete. Upload uses authorization, storage transfer and registration; storage receives no API key.
6. Writes a run- and content-versioned summary note when a summary exists. Existing user notes and summaries for other runs remain intact.
7. Reads back collection membership, the summary and attachment bytes. It verifies the exact local storage paths against source hashes before reporting `read_back_verified`.

Each paper ends in one state, and every one of them is a delivery, not a retry signal:

| Paper state | Meaning |
|---|---|
| `read_back_verified` | PDF and summary written, read back, and present in Desktop storage with matching hashes |
| `sync_pending` | everything is verified in the cloud; Zotero Desktop has not downloaded the binary yet |
| `partial` | written and read back, but an artifact is still missing (`pending` names which) |
| `metadata_only` | no full text was obtainable; explicitly not a completed paper |

A run-level `status` of `partial` therefore means "delivered, with named gaps", and only `pending` asks the caller to act. `zotero-state.json` holds per-operation and per-paper results. `manifest.json` reflects completed paper stages; a pending operation remains in the writer journal. Read `workflow.py status` and the writer journal together after a failure. The original local artifacts remain the reading source while Desktop sync is pending.

## Completion and local files

Cloud-verified papers are delivered immediately. When local files are absent or different the paper is reported `sync_pending` and the command still exits 0 — do not hold the batch, poll, or re-download the sources. Re-run the same command later, or use the standalone local check below, to upgrade the evidence. Inspect preflight if sync stays pending: file sync must be enabled, and automatic downloads must allow associated files.

The standalone local check remains available:

```bash
python "$SKILL_DIR/scripts/zotero_sync.py" --kind attachment-file --key <attachment-key> \
  --storage-root <Zotero-data-dir> --expected-sha256 <source-sha256>
```

`record-paper --state read_back_verified` requires matching evidence from the writer journal (`--verification <run_dir>/zotero-state.json`) or the paper's stored Zotero result. Metadata visibility alone does not satisfy it. Metadata-only papers remain explicitly labeled even after successful metadata writes.

## Compatibility helper

`zotero_markdown.py` remains a standalone PyZotero workaround for a runtime whose attachment tool rejects `.md`. Prefer the journaled writer for batch runs: the standalone helper has no run-level deduplication or recovery ledger. If conversion was declined or unavailable, preserve the PDF and label the missing derived artifact; a readable PDF may support a summary with `source_basis=pdf`.

For network and interrupted-write recovery, read [recovery.md](recovery.md).
