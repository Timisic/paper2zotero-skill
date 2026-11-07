# Lab defaults on loopback

Check the current search, conversion, and Zotero write defaults on loopback peers.

## Sub-features

- `search`: unset `SEARCH_BACKEND` resolves to `scansci`. When the process environment omits the variable, a non-empty line in `~/.config/literature-to-zotero/env` is the backend, so a saved `kimi` line stays until that line is removed. Grey PDF sources are on. `--legal-only` or `SCANSCI_LEGAL_ONLY` set to `1`, `true`, `yes`, `legal`, or `legal_only` forces legal sources. With no named sources, a scansci status other than `ok`, `empty`, or `skipped` falls back to Kimi. `SEARCH_BACKEND=kimi` searches with Kimi only and opens one WebBridge page. A blocked, unreadable, or outage page is `unavailable`. A readable page with no hits is `empty`.
- `convert`: self-hosted MinerU runs when the configured origin is non-empty and `GET /v1/health` returns HTTP 200 and the JSON body does not set `ok` to false. The origin is `MINERU_API_BASE`, or `MINERU_ENDPOINT` when `MINERU_API_BASE` is absent. An empty `MINERU_API_BASE` turns the hop off. Both names come from the process environment, then from `~/.config/literature-to-zotero/env`. MinerU cloud follows when a token is present. The token is `MINERU_TOKEN` in the environment, then the same key in that file, then `~/.config/mineru/token`. An empty environment value falls through. markitdown follows when markitdown is installed. MinerU hops take only papers with upload consent. markitdown does not read upload consent. Each paper falls through those hops in order
- `write`: a loopback local API accepts one item with no Web API key

## How to get to it (user POV)

Leave `SEARCH_BACKEND`, `MINERU_API_BASE`, and `ZOTERO_WRITE_BACKEND` unset. Search uses scansci when `~/.config/literature-to-zotero/env` has no `SEARCH_BACKEND` line. Grey PDF sources are on unless `--legal-only` is set or `SCANSCI_LEGAL_ONLY` is `1`, `true`, `yes`, `legal`, or `legal_only`. These nodes do not call `grey_policy`. `run --feature scansci` does. `SEARCH_BACKEND=kimi` searches with Kimi only and opens one page: `KIMI_SEARCH_URL` when set, otherwise the Semantic Scholar search URL. A blocked, unreadable, or outage page is `unavailable`. A readable page with no hits is `empty`. That Kimi search does not open a second page and does not call the OpenAlex or Semantic Scholar APIs. Conversion follows the convert bullet. MinerU hops skip papers without upload consent. markitdown converts a paper without that consent. A paper one hop fails moves on to the next. A Zotero write aimed at `https://api.zotero.org` prefers `http://127.0.0.1:23119/api` and falls back to the Web API.

## Driving it with verify_runner

Preconditions: run Doctor from the parent SKILL.md. Python, pytest, and Poppler are available. Only disposable fixture state is used.

```bash
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature lab-defaults
```

The nodes in `tests/test_lab_defaults.py` stay on loopback. `test_wrapped_evaluate_hits_still_become_candidates` writes one candidate when `command("evaluate")` returns `{type, value}` and the page JSON is in `value`. Five nodes drive the one-page failure contract on the same fixture transport: a down, unreadable, or outage page is `unavailable` after a single navigate; a readable page with no hits is `empty` and does not open `scholar.google.com`; a configured `KIMI_SEARCH_URL` is the only page when that page is down. None of these nodes open the Kimi daemon. `test_tasks_api_unpacks_full_md` unpacks a zip from `http_fixture.server`. `test_ingest_uses_the_local_api_without_a_web_key` creates one item on an in-process peer and does not attach a file.

Inspect `commands.jsonl`, `results.xml`, and `state/`. Run cleanup is automatic and must leave evidence intact.

## Gotchas

A pass covers loopback peers only. Live Kimi needs the `kimi-webbridge` binary and `kimi-webbridge status`. Live MinerU needs the origin from the convert bullet to pass `GET /v1/health`, then `POST /v1/tasks`. A `--mineru-api-base` that passes that check is that Tasks host. Leaving the flag at `https://mineru.net` health-checks the configured origin and posts `/v1/tasks` when the check passes. Fixture success is not that live host. Live Desktop needs `Zotero-Server-ID` on `127.0.0.1:23119`. `open_local_session` posts `/api/local/authorize` unless `ZOTERO_LOCAL_API_KEY` is already stored.

This feature's ingest node creates an item on a loopback peer and does not attach a file.
