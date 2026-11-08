# Acquire a verified source PDF

Download a verified PDF. `acquire()` checks an existing `source.pdf` first and returns channel `existing` when identity verification succeeds. scansci-pdf runs next, for a DOI or an arXiv id. A miss continues to known HTTP links, then a metadata lookup, then one Kimi WebBridge attempt. These three nodes disable the scansci fetch, pass `--no-source-lookup`, and prove the known-link HTTP route, including identity and content checks.

## Sub-features

- `http`: acquire source bytes over HTTP after scansci is disabled, without starting a browser
- `identity`: reject valid PDF of the wrong paper
- `content`: reject HTML served as application/pdf

## How to get to it (user POV)

After candidate confirmation, the agent calls `process_run.py --stages acquire`. That command uses the production acquire client. Kimi WebBridge is the last rung of the same `acquire()` call. These three nodes do not reach it, and real browser access is not covered.

## Driving it with verify_runner

Preconditions: run Doctor from the parent SKILL.md; Python/pytest/Poppler are available, and only disposable fixture state is used.

```bash
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature acquisition
```

`test_http_acquisition.py::test_a_known_open_pdf_is_fetched_without_the_browser` calls `process_run.py --stages acquire --no-source-lookup` with a recording browser adapter, then `workflow.py status`. Require `pdf_acquired`, matching source bytes, an HTTP acquisition trail with SHA-256 and identity `verified`, and no browser marker file. The HTML and wrong-paper nodes in the runner call that same CLI. `stage_acquire` then uses the production acquire client. Direct `acquire.acquire` calls in the same test file are outside these nodes.

Inspect `commands.jsonl` for `command` and `exit_code`, `results.xml` for each assertion outcome, and `state/` for persisted artifacts. Run cleanup is automatic and must leave evidence intact.

## Gotchas

These three nodes run `process_run.py` in a subprocess. They inherit `LITERATURE_SCANSCI_DISABLED=1` and skip `fetch_candidate`. The autouse stub that returns `NotAddressable` stays in the pytest process and does not run in that subprocess. The nodes record channel `http` from an ephemeral local peer. The success node observes browser non-use via the absent marker file. The HTML and wrong-paper nodes pass no browser command. `run --feature scansci` drives the mocked scansci download, including the grey default and `GreyPolicy.LEGAL`. Those nodes do not pass `--legal-only`. A green HTTP run is not live scansci-pdf acceptance. Institutional access, live redirects and real Kimi sessions remain unverified.
