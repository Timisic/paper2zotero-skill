# Recovery without repeating authorization

## Read the checkpoint first

The manifest is the authority for selected IDs and MinerU consent. `zotero-state.json` records external write operations; `mineru-<fingerprint>.json` records a conversion batch. Keep these files with the run. Reuse the same commands after interruption instead of composing a new ingestion script or restarting the whole batch.

- Everything: `process_run.py --run-dir <run_dir> --storage-root <Zotero-data-dir>` resumes the same run. It re-uses acquired PDFs, submitted conversions and written items, and only fills what is missing. `--ids` restricts it to named papers; unselected papers are refused. It never re-runs setup or retrieval.
- Zotero only: `zotero_ingest.py --run-dir <run_dir> --storage-root <Zotero-data-dir>`.
- MinerU: repeat the original `mineru_parse.py --run-dir <run_dir> --pdf ...` arguments. Source hashes and converter settings identify existing work; reordering or adding papers reuses their earlier batch records.
- Completed conversion outputs are in each PDF's `mineru/<source-and-config-id>/` directory unless an output root was supplied. Preserve image assets beside `paper.md`. Record the returned Markdown paths with `workflow.py record-paper`.
- Legacy runs: use dry-run first. Correct actual source paths through same-state `record-paper`; use `--reuse-map` only for identity-verified existing keys. Bring prior consent into the manifest with its original message reference. Earlier approval remains valid; the new field does not require asking again.

## Interpret failures

| Result | Next action |
|---|---|
| `retry_exhausted` | Shared HTTP reader exhausted its budget. Save the pending stage; continue unrelated work. Retry the same command after reachability improves. |
| `outcome_unknown` | A write may have succeeded. Zotero reads its saved key before any replay. Never resend an unkeyed create blindly. |
| MinerU submission outcome unknown without batch ID | Preserve its journal; reconcile the batch with the service before starting another. No automatic resubmission is safe here. |
| `rate_limited` | Respect the returned wait; Zotero persists its retry time across command reruns. |
| `invalid_request` | Fix payload/schema or input; changing proxy will not fix a 400. |
| `authentication_required` / `permission_denied` | Check the credential, entitlement or signed-URL lifetime for this service. Request human login only when needed. |
| `conflict` | Read the current object again and merge missing fields; preserve concurrent user edits. |
| `sync_pending` | Cloud write succeeded and the paper is deliverable. Recheck local hashes later; do not hold the run. |
| `partial` | Written and read back with an artifact still missing. Deliver it, and fill only the named gap. |
| `awaiting_summaries` | Full text is ready; write those summaries and re-run the same command. Not a user decision. |
| Missing artifact | Correct its path from a real verified file, not a placeholder. |

Readers use bounded backoff, host-specific route preference and a default 90-second request budget. Writes are not automatically retried by the transport after an uncertain response. Proxy configuration comes from the environment, and loopback services always use direct access. OpenAlex may use the existing browser fallback for public metadata after reachability failures; private API writes never switch to a browser.

During active work report the stage, recently completed work, blocking service and next attempt within about 60 seconds. Keep tool waits bounded. After a service budget is exhausted, avoid an external shell loop around the whole CLI; return a concrete pending checkpoint when no independent work remains. No promise of unattended future retries without an actual scheduler.

## Authorization boundaries

A network failure does not invalidate existing approval. Same selected IDs, same service and same operation resume without asking. Handing a summary task from `process_run.py` back to the agent is internal to authorized work, not a new decision. New papers, a new upload service, materially changed scope or revoked permission require the relevant new decision. Source/reference provenance stays attached to consent and selection records. Token values and signed URLs stay out of chat and ordinary logs; MinerU upload URLs are kept only in a temporary 0600 checkpoint removed after completion.
