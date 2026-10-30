# Unified local workflow

This branch does not ship `zotero_local.py`, `local_parse.py`, or `tests/test_unified_local.py`. Doctor does not require those scripts. Their absence is not a doctor failure. `run --feature unified-local` reports that absence and does not collect tests. Do not invent those modules or treat this note as a drive recipe.

The landed write is `zotero_ingest.resolve_write_target`. Default `ZOTERO_WRITE_BACKEND=auto` opens `http://127.0.0.1:23119/api` when `--api-base` is still `https://api.zotero.org`, then uses the Web API if Desktop does not answer. `run --feature unified-local` does not collect `tests/test_lab_defaults.py`. Those loopback tests are `run --feature lab-defaults`. They are not the missing `test_unified_local.py` suite.

`scripts/verify.py zotero-local` is a different check. It probes the Zotero Desktop API on 127.0.0.1:23119 through `capability.py`. It is not the missing `zotero_local.py` module. A live probe needs Desktop to answer `GET /api/users/0/items?limit=1` with `Zotero-Server-ID`. Local API attach reads the `file://` target of `GET /file` in `_LocalFileRedirect.http_error_302` and posts the bytes to `/api/local/uploads/` with `Zotero-API-Key` and `Zotero-Server-ID`.
