# Discovery and shortlist

Find a bounded, deduplicated reading list with provenance and honest source failures.

## Sub-features

- `merge`: same DOI across OpenAlex and Semantic Scholar keeps both citation accounts
- `failure`: rate-limited source yields partial results, not an empty literature claim
- `shortlist`: a short candidate list is not padded

## How to get to it (user POV)

Ask the literature agent to find papers; executable entry points are `workflow.py init`, `discovery.py --input-json`, and `candidate_table.py`. The natural-language screening itself is not automated here.

## Driving it with verify_runner

Preconditions: run Doctor from the parent SKILL.md; Python/pytest/Poppler are available, and only disposable fixture state is used.

```bash
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature discovery
```

`test_discovery.py::test_one_paper_found_twice_becomes_one_candidate_with_both_accounts` runs `workflow.py init` and `discovery.py --query "AI mental health intervention" --sources openalex,semantic_scholar --input-json openalex=... --input-json semantic_scholar=...`. The exact resolved commands are retained in `commands.jsonl`; candidates have one alpha DOI, both sources and citation counts 12 and 19. The failure scenario drives local 200/429 peers through the production discovery client and asserts partial results. `test_candidate_list.py::test_a_short_list_is_returned_as_is_without_padding` checks the CLI table retains only available candidates.

Inspect `commands.jsonl` for the action and return value, `results.xml` for each assertion outcome, and `state/` for persisted artifacts. Run cleanup is automatic and must leave evidence intact.

## Gotchas

Offline JSON input proves normalization, not live scholarly search. The 429 case is a client-level boundary check, not a CLI invocation. Preserve candidate provenance and distinguish empty from unavailable. Unset `SEARCH_BACKEND` selects Kimi (`credentials.search_backend`). These three nodes pass `--sources openalex,semantic_scholar` or render an existing table. The suite sets `SEARCH_BACKEND=http` and `LITERATURE_BROWSER_DISABLED=1`, so a green run does not start Kimi. Live Kimi needs the `kimi-webbridge` binary (`~/.kimi-webbridge/bin/kimi-webbridge` or `PATH`) and `kimi-webbridge status`.
