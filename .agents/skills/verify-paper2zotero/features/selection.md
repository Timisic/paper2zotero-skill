# Selection and upload consent

Process only the papers explicitly selected and keep PDFs deliverable when cloud parsing lacks consent.

## Sub-features

- `confirm`: one selection gate, no obsolete plan gate
- `refuse`: reject unconfirmed or unselected processing
- `consent`: a MinerU upload without consent is skipped, and the PDF is still delivered. markitdown does not read that consent record, so an installed markitdown converts the paper instead

## How to get to it (user POV)

User confirms candidate IDs, collection and upload choice. Public CLI paths are `workflow.py approve-candidates` (adds ids), `workflow.py revoke-candidates` (removes ids), `workflow.py import-candidates`, `workflow.py consent`, and `process_run.py --stages ...`. `import-candidates` appends candidates the run does not already hold. New ids set `candidate_selection` back to `pending` and leave papers that were already selected in the selected state. An import that adds nothing leaves an approved selection approved. The four nodes below call `import-candidates` only to seed a list. They do not add ids to an approved selection, and they do not import a file that adds nothing.

## Driving it with verify_runner

Preconditions: run Doctor from the parent SKILL.md; Python/pytest/pymupdf are available, and only disposable fixture state is used.

```bash
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature selection
```

`test_single_gate_flow.py::test_clear_intent_reaches_candidates_without_a_plan_gate` invokes init/import/approve/status and expects `candidate_selection: approved`. The two refusal cases in `test_process_run.py` invoke processing and require exit 2 with the exact missing-selection/unselected reason. `test_conversion_without_consent_is_recorded_and_never_blocks_the_pdf` runs `process_run.py --stages convert,ingest` against the fixture library. The suite clears `MINERU_API_BASE` and sets `LITERATURE_MARKITDOWN_DISABLED=1`, so the MinerU upload is skipped and the PDF remains delivered with `markdown_unavailable: no upload consent`. With markitdown available, `stage_convert` converts that paper on this machine and writes no skip.

Inspect `commands.jsonl` for the action and return value, `results.xml` for each assertion outcome, and `state/` for persisted artifacts. Run cleanup is automatic and must leave evidence intact.

## Gotchas

Fixture approval represents a synthetic user, not permission for real uploads. No-consent testing still writes to the disposable Zotero peer; never substitute a production URL.
