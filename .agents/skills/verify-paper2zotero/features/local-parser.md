# Local parser verification

This branch does not ship `paper-to-zotero/scripts/local_parse.py` or `tests/test_local_parse.py`. Doctor does not require `local_parse.py`. A missing file is not a doctor failure. `run --feature local-parser` reports that absence and does not collect tests. Do not invent a parser CLI or treat this note as a drive recipe.

PDF markdown on this branch goes through `process_run.stage_convert`. The default self-hosted origin is `http://192.168.8.167:8000` (`credentials.LAB_MINERU_API_BASE`). A live hop needs `GET /v1/health` on that host, then `POST /v1/tasks`. Leave `--mineru-api-base` at `https://mineru.net` so `choose_converter` supplies the lab origin. Passing the LAN URL as `--mineru-api-base` selects the cloud v4 client. A fixture pass does not open that host. Loopback coverage of the default origin is `tests/test_lab_defaults.py` under `run --feature lab-defaults`. That is a different entry point from the missing `local_parse.py` tests.
