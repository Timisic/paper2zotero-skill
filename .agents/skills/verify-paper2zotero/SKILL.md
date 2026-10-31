---
name: verify-paper2zotero
description: Verify paper2zotero's Python CLI workflows for discovery, scansci search and download, selection and consent, local PDF import, HTTP acquisition, conversion, Zotero read-back and recovery using isolated local fixtures. Use after workflow changes or to reproduce a regression. Fixture success is not live scansci-pdf, Kimi WebBridge, lab MinerU, or Zotero Desktop acceptance.
---

# Verify Paper to Zotero

Generated using installed PStack Personal `create-verification-skill`, version `0.15.6-codex.1`, and its `references/codex-runtime.md`. The adapter places project skills in `.agents/skills/`. Source on this Mac: `/Users/hong/.codex/plugins/cache/plugins-cli/pstack-personal/0.15.6-codex.1/skills/create-verification-skill/SKILL.md`.

The repository is `/Users/hong/Downloads/Codex/paper skills`; its main executable surface is `paper-to-zotero/scripts/*.py`, orchestrated by the literature skill. There is no always-running application server. Read [the feature index](features/README.md) before driving. This maintenance skill does not invoke the literature skill against a user's actual library.

## Launch

From the repository root, use an explicit interpreter override or the current `python3`. `VERIFY_PYTHON` is a shell variable used by these commands; the runner uses `sys.executable` for its children and never searches for this task's environment.

```bash
VERIFY_PYTHON="${VERIFY_PYTHON:-python3}"
command -v "$VERIFY_PYTHON"
"$VERIFY_PYTHON" --version
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py doctor
```

Require Python >=3.11, `pytest`, `pdfinfo` and `pdftotext`. Doctor reports their presence, the actual interpreter and source hashes; missing dependencies produce `ok: false` and exit 2. It installs nothing and makes no service calls. To use an existing environment, set `VERIFY_PYTHON` to its Python executable before running the commands. There is no dependency lock or project-managed test environment in the current repository: [docs/README.md](../../../docs/README.md) uses `python3 -m pytest`, and `.github/workflows/runtime.yml` installs pytest plus Poppler. The initial acceptance used Python 3.14.7 and pytest 9.1.1; its task-local environment is historical evidence, not a required path.

If no suitable existing environment is available, this optional preparation creates an isolated environment in the repository's already ignored `literature-runs/` directory. Run it only when dependency preparation is authorized; it does not modify global Python. Use an existing Python >=3.11 and installed `uv`; do not overwrite an existing environment:

```bash
VERIFY_ENV="$PWD/literature-runs/verification-env"
if [ -e "$VERIFY_ENV" ]; then
  echo "Environment already exists; inspect it and run doctor before reuse."
else
  uv venv --offline --python "$VERIFY_PYTHON" "$VERIFY_ENV" &&
    uv pip install --offline --python "$VERIFY_ENV/bin/python" 'pytest==9.1.1'
fi
VERIFY_PYTHON="$VERIFY_ENV/bin/python"
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py doctor
```

`--offline` requires pytest and its dependencies in the local uv cache. If Python, uv or cache entries are absent, report the exact missing dependency; do not silently download them or fall back to a deleted task directory. Authorized online preparation can follow the repository CI's pytest installation in a virtual environment. Poppler is a separate prerequisite; on macOS the repository CI uses `brew install poppler`, and on Linux `poppler-utils`. Report its absence rather than running a system install automatically. This helper's child PATH searches the interpreter directory, system defaults, `/opt/homebrew/bin` and `/usr/local/bin`; custom Poppler locations need separate review and are not automatically inherited.

Once doctor passes:

```bash
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run
```

The ordinary project `run-python.sh` reads the real user's runtime configuration, so this harness deliberately runs the chosen interpreter directly. The environment is reusable and is not part of per-run scratch cleanup.

`run` snapshots current scripts, tests, references, and `paper-to-zotero/SKILL.md` into a unique temporary directory, drives the 64 fixture tests whose modules are present, and tears down that snapshot. It collects `lab-defaults` from `tests/test_lab_defaults.py` and `scansci` from `tests/test_scansci_retrieval.py`. The scansci install-line test reads the copied skill file. It does not collect `local-parser` or `unified-local`, because those test modules are not in this branch. Source edits must be finished before launching. No build is required. Test peers bind only `127.0.0.1:0` and are ready when their fixture context returns. Never point the helper at an existing service or a real Zotero data directory. A sandbox that refuses local bind needs narrowly scoped host approval for these fixture peers; do not disable the network guard.

## Doctor

The read-only `doctor` command above checks interpreter version, pytest, `pdfinfo`, `pdftotext`, required CLI sources and source hashes. On this branch the required sources are `workflow.py`, `process_run.py`, `discovery.py`, `summary_artifact.py`, `zotero_ingest.py`, `local_pdf.py`, and `scansci_retrieval.py`. `local_parse.py` and `zotero_local.py` are not part of that check; the local-parser and unified-local notes apply when those scripts are present. Exit 0 / `ok: true` means the local runner is worth driving, not that production credentials or services are healthy. During `run`, `guard.json` additionally proves that real Zotero's local port 23119 is blocked before any application code executes. Fixture ports are owned by this run, allocated dynamically and recorded in `ports.txt`.

## Drive

Run all features as above, or append one of:

```bash
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature discovery
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature scansci
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature selection
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature local-pdf
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature acquisition
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature delivery
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature lab-defaults
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature local-parser
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature unified-local
```

Use `--evidence /absolute/new/directory` to select a new evidence destination. Existing destinations are refused, preserving earlier proof. Default evidence goes to ignored `literature-runs/verification-YYYYMMDD-HHMMSS/`. The actual public CLI commands, arguments and results are captured in `commands.jsonl`; don't reconstruct production commands with live credentials from a fixture example.

The runner reuses `tests/http_fixture.py`, `zotero_peer.py`, `mineru_peer.py`, `fake_browser.py`, and their existing CLI scenarios. It creates a fresh child environment and disposable user profile; inherits no account settings, proxy, API key or browser session. `sitecustomize.py` permits Python connections only to fixture-owned ephemeral ports and blocks external DNS. This is a regression guard for this reviewed Python harness, not a general security sandbox for arbitrary subprocesses. Do not add arbitrary commands or live tests to the allowlisted scenario map without reviewing their boundaries.

## Evidence

A pass requires exit 0, every selected present test passed (64 for a full run), `guard.json` exit 0, and `cleanup.json` showing removed scratch and no listening owned ports. Check `pytest.log` and `results.xml`, not merely file existence. `doctor.json` identifies the interpreter and source hashes; `invocation.json` identifies the exact test nodes.

`commands.jsonl` retains action, stdout, stderr and exit status. `state/` retains disposable run manifests, candidates, PDFs, acquisition trails, hashes, conversion journals, summary handoffs and simulated Zotero storage after teardown. Paths in transcripts retain the original temporary location: map `<scratch>/cases/` to `<evidence>/state/` using `cleanup.json`. `network.jsonl` records allowed/blocked Python socket attempts; a blocked probe of 23119 is expected, as are unavailable-source attempts to closed fixture URLs. No real credentials are included; known test-secret strings are redacted in command transcripts. State can contain dummy fixture credentials and signed fixture URLs only.

Tests exercise public CLI paths and assert side effects and read-back, with a few source-failure / rejection checks calling the same production client directly. Fixture setup sometimes seeds candidate metadata or already acquired artifacts; that seeding is not proof of discovery or acquisition. The browser adapter, bibliographic responses, Zotero service, MinerU service and summary text are simulated. Tests prove orchestration, persisted files, consent boundaries, bytes/read-back and recovery against those boundaries. They do not prove scientific summary quality, actual publisher access, external authentication, a live scansci-pdf download, a live Kimi search, the lab MinerU host, Desktop sync, a local file attach, semantic search, or real uploads.

## Cleanup

`run` always copies scenario state to evidence, stops only its own pytest process group, removes its unique scratch directory, and checks that its fixture ports no longer listen. Test peer context managers close their own servers. Evidence remains outside scratch after success and failure. Do not delete evidence, actual literature runs, real Zotero records or attachments. Do not kill processes by name. If interrupted externally before cleanup, inspect the recorded invocation and precise scratch path; report the interruption and check only the run's owned processes before targeted cleanup.

## Helpers

`verify_runner.py doctor|run [--feature NAME] [--repo PATH] [--evidence NEW_PATH]` is executable; examples use the chosen interpreter to avoid ambiguous shebang Python. `sitecustomize.py` is an imported network guard, not a standalone command. The runner is for macOS/Linux (POSIX process groups); Windows execution remains unverified.

Failure diagnosis: doctor failures mean missing interpreter/dependencies/source files; bind `PermissionError` means host sandbox restrictions; collection errors usually mean renamed test nodes; failing assertions identify behavior changes in the named feature; `commands.jsonl` gives failing CLI input/output, while `state/` gives the resulting files. Network guard blocks on a new endpoint mean the fixture boundary needs review, never permission to use a real service. After a failure, inspect `cleanup.json` before retrying into a new evidence directory.

## Limits and maintenance

No real integration runs are authorized by this skill. Unset `SEARCH_BACKEND` selects scansci. When the process environment omits `SEARCH_BACKEND`, a non-empty line in `~/.config/literature-to-zotero/env` is the backend, so a saved `kimi` line stays until that line is removed. Saving an empty value leaves the line in place. An empty or whitespace environment variable selects scansci. Grey PDF sources are on. `--legal-only` or `SCANSCI_LEGAL_ONLY` set to `1`, `true`, `yes`, `legal`, or `legal_only` forces legal sources. An unknown value raises `ValueError`. Install with `pip install 'scansci-pdf==1.19.0'` and no browser extra. A missing install or any other version is `not_configured`. Kimi stays `SEARCH_BACKEND=kimi`. Kimi opens one page, `KIMI_SEARCH_URL` or the Semantic Scholar search URL. A blocked, unreadable, or outage page is `unavailable`, and a readable page with no hits is `empty`. That Kimi search does not open a second page or call the OpenAlex or Semantic Scholar APIs. OpenAlex and Semantic Scholar run for `SEARCH_BACKEND=http`, `openalex`, `semantic_scholar`, the aliases `openalex,semantic_scholar` and `openalex+semantic_scholar`, or an explicit `--sources` list. `run --feature scansci` drives the mocked adapter in `tests/test_scansci_retrieval.py`. Unset `MINERU_API_BASE` selects self-hosted MinerU at `http://192.168.8.167:8000`, then MinerU cloud when `MINERU_TOKEN` is set, then markitdown. Unset `ZOTERO_WRITE_BACKEND` prefers the local API at `http://127.0.0.1:23119/api` and falls back to the Web API. `run --feature lab-defaults` drives `tests/test_lab_defaults.py` on loopback peers. That pass does not open the lab host, the Kimi daemon, or Zotero Desktop.

Live Kimi needs the `kimi-webbridge` binary and `kimi-webbridge status`. Live MinerU needs `GET http://192.168.8.167:8000/v1/health`, then `POST /v1/tasks`. A `--mineru-api-base` that answers `GET /v1/health` is that Tasks host, including `http://192.168.8.167:8000` and `MINERU_API_BASE`. Leaving `--mineru-api-base` at `https://mineru.net` health-checks `credentials.mineru_api_base()` and uses Tasks when that check passes. A failed check uses MinerU cloud when `MINERU_TOKEN` is set, otherwise markitdown when markitdown is installed. With neither, `stage_convert` records `no MinerU token` and skips the v4 client. An explicit base other than `https://mineru.net` that answers `GET /v1/health` is that Tasks host. An explicit base that fails the check is planned as cloud v4 against that same base, and `stage_convert` calls v4 only when a token is set. Offline fixtures pass that explicit base. Desktop reachability is `scripts/verify.py zotero-local`: it calls `capability.probe_zotero_local` and `capability.zotero_local`, and that probe is HTTP 200 on `GET http://127.0.0.1:23119/api/users/0/items?limit=1`. `capability.probe_zotero_local_write` needs that HTTP 200 and a `Zotero-Server-ID` header, and does not call `/local/authorize`. A writable session is `zotero_ingest.open_local_session`: the same header, then `POST /api/local/authorize` unless `ZOTERO_LOCAL_API_KEY` is already stored.

Local API upload reads the artifact in `Writer.upload`, posts it with `POST .../file`, then posts those bytes to a same-origin `/api/local/uploads/` URL with `Zotero-API-Key` and `Zotero-Server-ID`. `GET /file` read-back uses `_LocalFileRedirect.http_error_302` to read the `file://` path from disk. A live write still needs a separately authorized, disposable library and storage. Otherwise report it as not run.

This branch does not ship `local_parse.py` or `zotero_local.py`. `run --feature local-parser` and `run --feature unified-local` report that absence. They are not doctor failures. Do not invent those scripts, and do not treat `lab-defaults` as those missing modules. Personal-library semantic search and production content quality remain unaccepted. Installer GUI, natural-language screening, all platform variants and the wider test suite are outside this starter map.

Use PStack Personal's `/maintain-verification-skill` when entry points or behavior change. Update this map alongside the code; do not mark a skipped path verified by a different entry point.
