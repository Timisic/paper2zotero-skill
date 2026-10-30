# Acquire a verified source PDF

Download an open PDF through HTTP, verify the paper identity, and reject misleading or wrong files.

## Sub-features

- `http`: acquire source bytes without starting a browser
- `identity`: reject valid PDF of the wrong paper
- `content`: reject HTML served as application/pdf

## How to get to it (user POV)

After candidate confirmation, the agent calls `process_run.py --stages acquire`; lower-level acquisition uses the production acquire client. Browser fallback is an alternate entry but real browser access is not covered.

## Driving it with verify_runner

Preconditions: run Doctor from the parent SKILL.md; Python/pytest/Poppler are available, and only disposable fixture state is used.

```bash
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature acquisition
```

`test_http_acquisition.py::test_a_known_open_pdf_is_fetched_without_the_browser` calls `process_run.py --stages acquire --no-source-lookup` with a recording browser adapter, then `workflow.py status`. Require `pdf_acquired`, matching source bytes, an HTTP acquisition trail with SHA-256 and identity `verified`, and no browser marker file. The HTML and wrong-paper nodes in the runner call that same CLI. `stage_acquire` then uses the production acquire client. Direct `acquire.acquire` calls in the same test file are outside these three nodes.

Inspect `commands.jsonl` for the action and return value, `results.xml` for each assertion outcome, and `state/` for persisted artifacts. Run cleanup is automatic and must leave evidence intact.

## Gotchas

Only ephemeral local HTTP is used. Browser non-use is observed via the absent marker file; it is not inferred from a flag. Institutional access, live redirects and real Kimi sessions remain unverified.
