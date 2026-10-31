# ScanSci search and download

Search and download through scansci-pdf 1.19.0 when `SEARCH_BACKEND` is unset. Grey PDF sources, including Sci-Hub, are on. These nodes mock the library.

## Sub-features

- `search`: an omitted, empty, or whitespace `SEARCH_BACKEND` calls `scansci_retrieval.search`. A missing install or any version other than `1.19.0` is `not_configured` and names `pip install 'scansci-pdf==1.19.0'`. An empty hit list is `empty`. A library error or a non-list payload is `unavailable`. A spent budget is `skipped` and does not call the library.
- `download`: `fetch_candidate` prefers a DOI, otherwise an arXiv id, recorded as `preprint`. No DOI and no arXiv id is `NotAddressable` and writes no scansci trail row. Grey sends `strategy=fastest` and `scihub_enabled=True`, so a Sci-Hub file is kept. `--legal-only` or `SCANSCI_LEGAL_ONLY` set to `1`, `true`, `yes`, `legal`, or `legal_only` forces legal sources and drops opaque labels such as Sci-Hub and `local_cache`. An unknown value raises `ValueError`.
- `backend`: `SEARCH_BACKEND=http` and the aliases `openalex,semantic_scholar` and `openalex+semantic_scholar` select OpenAlex and Semantic Scholar. `SEARCH_BACKEND=kimi` stays Kimi. The HTTP client rejects the source name `scansci`.

## How to get to it (user POV)

Leave `SEARCH_BACKEND` unset and ask for papers. `discovery.discover` calls `scansci_retrieval.search`. After confirmation, `acquire.acquire` calls `scansci_retrieval.fetch_candidate` before known HTTP links. When the process environment omits `SEARCH_BACKEND`, a non-empty line in `~/.config/literature-to-zotero/env` is the backend, so a saved `kimi` line stays until that line is removed. Saving an empty value leaves the line in place. An empty or whitespace environment variable selects scansci.

## Driving it with verify_runner

Preconditions: run Doctor from the parent SKILL.md. Python, pytest, and Poppler are available. Only disposable fixture state is used.

```bash
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature scansci
```

The runner collects `tests/test_scansci_retrieval.py`. The tests install a fake `scansci_pdf` module at version `1.19.0`. `test_the_skill_names_the_install_line` reads `paper-to-zotero/SKILL.md`, which the runner copies into the snapshot. `test_discover_asks_scansci_when_the_backend_is_unset` clears the suite's `SEARCH_BACKEND=http` and checks that `discover()` asks scansci. The other features keep the autouse stub that sets `LITERATURE_SCANSCI_DISABLED=1`.

Inspect `results.xml` for each assertion. These tests call the adapter in process, so `commands.jsonl` may stay empty. Run cleanup is automatic and must leave evidence intact.

## Gotchas

A pass does not download a paper and does not prove live scansci-pdf, Kimi WebBridge, lab MinerU, or Zotero Desktop. The product checks `scansci_pdf.__version__`. It does not inspect a browser extra. `scihub_browser_first_enabled` skips `download` and returns `unavailable`. After a scansci miss, acquire continues to known HTTP links. That HTTP route is `run --feature acquisition`.
