# Deliver artifacts and recover

Carry a confirmed batch through acquisition, conversion, summary handoff and Zotero read-back, then resume without duplicate work.

## Sub-features

- `deliver`: two selected papers receive PDF, Markdown and a note each
- `partial`: conversion failure still delivers PDFs and enables PDF-based summaries
- `recover`: lost MinerU submission is reconciled and retried once as a new batch

## How to get to it (user POV)

After selection use `process_run.py --stages acquire,convert,ingest`, write the returned summary artifact and resume. The documented modern split-pass/summary-batch entry is an additional path not covered by these three legacy-compatible full-chain scenarios.

## Driving it with verify_runner

Preconditions: run Doctor from the parent SKILL.md; Python/pytest/Poppler are available, and only disposable fixture state is used.

```bash
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature delivery
```

`test_full_chain.py::test_one_invocation_carries_a_confirmed_selection_to_read_back[ordinary-path]` runs the processing CLI against owned Zotero/MinerU peers and a scripted browser. First result must be `awaiting_summaries`; after `summary_artifact.py` and `workflow.py record-paper`, the second is `complete`. Peer assertions require two parents, two PDFs, two Markdown files and two notes; resumed acquisition/conversion lists are empty. `test_a_conversion_failure_still_delivers_the_pdf` requires PDF delivery and PDF-based summary handoffs despite failed conversion. `test_a_lost_mineru_submission_does_not_strand_the_chain` requires two submissions (lost plus recovered), converted Markdown and a reconciliation journal.

Inspect `commands.jsonl` for the action and return value, `results.xml` for each assertion outcome, and `state/` for persisted artifacts. Run cleanup is automatic and must leave evidence intact.

## Gotchas

Peer read-back proves the real writer/client behavior against a simulated service. `cloud_verified_at` in fixture output is not evidence of actual Zotero cloud delivery. Notes contain synthetic text. These three nodes pass an explicit `--mineru-api-base` to a MinerU v4 fixture. They do not call the LAN Tasks API. The product default, when that flag stays `https://mineru.net`, is self-hosted MinerU at `http://192.168.8.167:8000`, then MinerU cloud when `MINERU_TOKEN` is set, then markitdown. These nodes also pass a fixture `--api-base`, so they stay on the Web API client. A default write prefers `http://127.0.0.1:23119/api` and falls back to the Web API. Live Desktop must return `Zotero-Server-ID` and accept `POST /api/local/authorize`.

Local API attach reads the `file://` target of `GET /file` in `zotero_ingest._LocalFileRedirect.http_error_302` and posts the bytes to a same-origin `/api/local/uploads/` URL with `Zotero-API-Key` and `Zotero-Server-ID`. These nodes pass a fixture `--api-base`, so they exercise the Web API client. Do not read that fixture ingest as a live Desktop attach. Split-pass/batch-summary, deep paths and Windows variants remain unrun.
