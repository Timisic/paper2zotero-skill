# Discovery and shortlist

Find a bounded, deduplicated reading list with provenance and honest source failures.

## Sub-features

- `merge`: same DOI across OpenAlex and Semantic Scholar keeps both citation accounts
- `failure`: rate-limited source yields partial results, not an empty literature claim
- `shortlist`: a short candidate list is not padded. More than 15 rows exits 2 unless `--max-rows` is raised

## How to get to it (user POV)

Ask the literature agent to find papers; executable entry points are `workflow.py init`, `discovery.py --input-json`, and `candidate_table.py`. The natural-language screening itself is not automated here.

## Driving it with verify_runner

Preconditions: run Doctor from the parent SKILL.md; Python/pytest/Poppler are available, and only disposable fixture state is used.

```bash
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature discovery
```

`test_discovery.py::test_one_paper_found_twice_becomes_one_candidate_with_both_accounts` runs `workflow.py init` and `discovery.py --query "AI mental health intervention" --sources openalex,semantic_scholar --input-json openalex=... --input-json semantic_scholar=...`. The exact resolved commands are retained in `commands.jsonl`; candidates have one alpha DOI, both sources and citation counts 12 and 19. The failure scenario drives local 200/429 peers through the production discovery client and asserts partial results. `test_candidate_list.py::test_a_short_list_is_returned_as_is_without_padding` checks the CLI table retains only available candidates. `test_candidate_list.py::test_default_list_budget_is_fifteen_and_is_explicitly_overridable` exits 2 on 16 rows and writes 16 rows with `--max-rows 20`.

Inspect `commands.jsonl` for the action and return value, `results.xml` for each assertion outcome, and `state/` for persisted artifacts. Run cleanup is automatic and must leave evidence intact.

## Gotchas

Offline JSON input proves normalization, not live scholarly search. The 429 case is a client-level boundary check, not a CLI invocation. Preserve candidate provenance and distinguish empty from unavailable. Unset `SEARCH_BACKEND` selects scansci (`credentials.search_backend`). When the process environment omits `SEARCH_BACKEND`, a non-empty line in `~/.config/literature-to-zotero/env` is the backend, so a saved `kimi` line stays until that line is removed. Saving an empty value leaves the line in place. An empty or whitespace environment variable selects scansci. Kimi stays `SEARCH_BACKEND=kimi` and opens one page (`KIMI_SEARCH_URL`, otherwise the Semantic Scholar search URL). A blocked, unreadable, or outage page is `unavailable`. The one-page checks are collected by `run --feature lab-defaults`. The merge node passes `--sources openalex,semantic_scholar`. The failure node calls `discover()` with `sources` left unset. The suite sets `SEARCH_BACKEND=http`, so that call uses OpenAlex and Semantic Scholar. The shortlist node renders six rows, and `test_default_list_budget_is_fifteen_and_is_explicitly_overridable` refuses a 16th row. OpenAlex and Semantic Scholar also run for `SEARCH_BACKEND=http`, `openalex`, `semantic_scholar`, or the aliases `openalex,semantic_scholar` and `openalex+semantic_scholar`. `run --feature scansci` drives the scansci adapter. The suite sets `LITERATURE_BROWSER_DISABLED=1`, so a green discovery run does not start Kimi. Live Kimi needs the `kimi-webbridge` binary (`~/.kimi-webbridge/bin/kimi-webbridge` or `PATH`) and `kimi-webbridge status`.
