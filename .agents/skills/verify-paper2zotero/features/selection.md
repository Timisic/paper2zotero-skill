# Selection and upload consent

Process only the papers explicitly selected and keep PDFs deliverable when cloud parsing lacks consent.

## Sub-features

- `confirm`: one selection gate, no obsolete plan gate
- `refuse`: reject unconfirmed or unselected processing
- `consent`: a MinerU upload without consent is skipped, and the PDF is still delivered. markitdown does not read that consent record

## How to get to it (user POV)

User confirms candidate IDs, collection and upload choice. Public CLI paths are `workflow.py approve-candidates`, `workflow.py consent`, and `process_run.py --stages ...`.

## Driving it with verify_runner

Preconditions: run Doctor from the parent SKILL.md; Python/pytest/Poppler are available, and only disposable fixture state is used.

```bash
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature selection
```

`test_single_gate_flow.py::test_clear_intent_reaches_candidates_without_a_plan_gate` invokes init/import/approve/status and expects `candidate_selection: approved`. The two refusal cases in `test_process_run.py` invoke processing and require exit 2 with the exact missing-selection/unselected reason. `test_conversion_without_consent_is_recorded_and_never_blocks_the_pdf` runs `process_run.py --stages convert,ingest` against the fixture library. The suite clears `MINERU_API_BASE`. With no markitdown installed, the MinerU upload is skipped and the PDF remains delivered with `markdown_unavailable: no upload consent`. When markitdown is the selected hop, `stage_convert` converts on this machine and does not write that skip.

Inspect `commands.jsonl` for the action and return value, `results.xml` for each assertion outcome, and `state/` for persisted artifacts. Run cleanup is automatic and must leave evidence intact.

## Gotchas

Fixture approval represents a synthetic user, not permission for real uploads. No-consent testing still writes to the disposable Zotero peer; never substitute a production URL.
