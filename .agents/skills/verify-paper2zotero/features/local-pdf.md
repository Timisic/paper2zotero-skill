# Import a local PDF

Import a selected source PDF, validate identity, and resume without replacing existing artifacts.

## Sub-features

- `import`: resolve mapping-relative source paths and copy verified bytes
- `resume`: reuse unchanged PDF and preserve later summary state
- `reject`: refuse unselected IDs, changed source conflicts and HTML disguised as PDF

## How to get to it (user POV)

Provide existing PDFs to the agent. The fast path is `paper-to-zotero/scripts/local_pdf.py`: it extracts a DOI or title, completes the record, then calls `workflow.py import-pdfs` and converts locally. This starter map still drives only that `import-pdfs` verifier (`tests/test_import_pdfs.py`). The fast-path cases live in `paper-to-zotero/tests/test_local_pdf.py` and are not part of these two checks.

## Driving it with verify_runner

Preconditions: run Doctor from the parent SKILL.md; Python/pytest/Poppler are available, and only disposable fixture state is used.

```bash
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature local-pdf
```

Both cases in `test_import_pdfs.py` call the public import CLI. `test_relative_mapping_import_and_resume_preserve_later_artifacts` checks byte equality on import, `action: reused` on repeat, unchanged manifest/mtime, then `partial` on changed input without overwriting the first copy. `test_selection_checked_before_any_copy_and_bad_pdf_stays_unrecorded` checks exit 2 for an unselected ID and `rejected` for HTML, with no recorded PDF artifact.

Inspect `commands.jsonl` for the action and return value, `results.xml` for each assertion outcome, and `state/` for persisted artifacts. Run cleanup is automatic and must leave evidence intact.

## Gotchas

The tiny `probe.pdf` is test material only. Candidates are seeded with its known title. Later summary state is seeded to verify preservation, not to validate summary generation.
