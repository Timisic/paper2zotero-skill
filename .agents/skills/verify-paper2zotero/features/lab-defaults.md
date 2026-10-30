# Lab defaults on loopback

Check the current search, conversion, and Zotero write defaults on loopback peers.

## Sub-features

- `search`: unset `SEARCH_BACKEND` resolves to `kimi`
- `convert`: unset `MINERU_API_BASE` resolves to `http://192.168.8.167:8000`, then cloud, then markitdown
- `write`: a loopback local API accepts one item with no Web API key

## How to get to it (user POV)

Leave `SEARCH_BACKEND`, `MINERU_API_BASE`, and `ZOTERO_WRITE_BACKEND` unset. Search uses Kimi. Conversion uses self-hosted MinerU when `GET /v1/health` succeeds, otherwise MinerU cloud when `MINERU_TOKEN` is set, otherwise markitdown. A Zotero write aimed at `https://api.zotero.org` prefers `http://127.0.0.1:23119/api` and falls back to the Web API.

## Driving it with verify_runner

Preconditions: run Doctor from the parent SKILL.md. Python, pytest, and Poppler are available. Only disposable fixture state is used.

```bash
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature lab-defaults
```

The eight nodes in `tests/test_lab_defaults.py` stay on loopback. `test_mineru_default_is_the_lan_host` checks the default origin with `live=False`, so it does not open `192.168.8.167`. `test_tasks_api_unpacks_full_md` unpacks a zip from `http_fixture.server`. `test_ingest_uses_the_local_api_without_a_web_key` creates one item on an in-process peer and does not attach a file.

Inspect `commands.jsonl`, `results.xml`, and `state/`. Run cleanup is automatic and must leave evidence intact.

## Gotchas

A pass covers loopback peers only. Live Kimi needs the `kimi-webbridge` binary and `kimi-webbridge status`. Live MinerU needs `GET http://192.168.8.167:8000/v1/health`, then a convert that leaves `--mineru-api-base` at `https://mineru.net` so `choose_converter` posts `/v1/tasks`. Passing the LAN URL as `--mineru-api-base` selects the cloud v4 client. Live Desktop needs `Zotero-Server-ID` on `127.0.0.1:23119` and `POST /api/local/authorize`.

Automatic file attach is a product gap. CPython rejects a `GET /file` redirect to `file://` inside `urllib.request.HTTPRedirectHandler.http_error_302` before `zotero_ingest._LocalFileRedirect.redirect_request` runs. The local upload also needs `Zotero-API-Key` and `Zotero-Server-ID`. Item create can succeed while the attachment does not. Do not record that attach as verified. `local_parse.py` and `zotero_local.py` are still absent. This feature does not stand in for `run --feature local-parser` or `run --feature unified-local`.
