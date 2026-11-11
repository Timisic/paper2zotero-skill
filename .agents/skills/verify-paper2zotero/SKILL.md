---
name: verify-paper2zotero
description: Verify paper2zotero's Python CLI workflows for discovery, scansci search and download, selection and consent, local PDF import, HTTP acquisition, conversion, Zotero read-back and recovery using isolated local fixtures. Use after workflow changes or to reproduce a regression. Fixture success is not live scansci-pdf, Kimi WebBridge, self-hosted MinerU, or Zotero Desktop acceptance.
metadata:
  internal: true
---

# Verify Paper to Zotero

Generated with PStack Personal `create-verification-skill`, which places project skills in `.agents/skills/`.

The repository's main executable surface is `paper-to-zotero/scripts/*.py`, orchestrated by the literature skill. There is no always-running application server. Read [the feature index](features/README.md) before driving. This maintenance skill does not invoke the literature skill against a user's actual library.

## Launch

From the repository root, use an explicit interpreter override or the current `python3`. `VERIFY_PYTHON` is a shell variable used by these commands; the runner uses `sys.executable` for its children and never searches for this task's environment.

```bash
VERIFY_PYTHON="${VERIFY_PYTHON:-python3}"
command -v "$VERIFY_PYTHON"
"$VERIFY_PYTHON" --version
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py doctor
```

Require Python >=3.11, `pytest` and `pymupdf`. Doctor reports their presence, the actual interpreter and source hashes; missing dependencies produce `ok: false` and exit 2. It installs nothing and makes no service calls. To use an existing environment, set `VERIFY_PYTHON` to its Python executable before running the commands. There is no dependency lock or project-managed test environment in the current repository: [docs/README.md](../../../docs/README.md) uses `python3 -m pytest`, and `.github/workflows/runtime.yml` installs pytest and pymupdf.

If no suitable existing environment is available, this optional preparation creates an isolated environment in the repository's already ignored `literature-runs/` directory. Run it only when dependency preparation is authorized; it does not modify global Python. Use an existing Python >=3.11 and installed `uv`; do not overwrite an existing environment:

```bash
VERIFY_ENV="$PWD/literature-runs/verification-env"
if [ -e "$VERIFY_ENV" ]; then
  echo "Environment already exists; inspect it and run doctor before reuse."
else
  uv venv --offline --python "$VERIFY_PYTHON" "$VERIFY_ENV" &&
    uv pip install --offline --python "$VERIFY_ENV/bin/python" 'pytest==9.1.1' 'pymupdf>=1.24'
fi
VERIFY_PYTHON="$VERIFY_ENV/bin/python"
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py doctor
```

`--offline` requires pytest and its dependencies in the local uv cache. If Python, uv or cache entries are absent, report the exact missing dependency; do not silently download them or fall back to a deleted task directory. Authorized online preparation can follow the repository CI's pytest installation in a virtual environment.

Once doctor passes:

```bash
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run
```

The ordinary project `run-python.sh` reads the real user's runtime configuration, so this harness deliberately runs the chosen interpreter directly. The environment is reusable and is not part of per-run scratch cleanup.

`run` snapshots current scripts, tests, references, and `paper-to-zotero/SKILL.md` into a unique temporary directory, drives the fixture tests whose modules are present, and tears down that snapshot. It collects `backend-defaults` from `tests/test_backend_defaults.py` and `scansci` from `tests/test_scansci_retrieval.py`. The scansci install-line test reads the copied skill file. Source edits must be finished before launching. No build is required. Test peers bind only `127.0.0.1:0` and are ready when their fixture context returns. Never point the helper at an existing service or a real Zotero data directory. A sandbox that refuses local bind needs narrowly scoped host approval for these fixture peers; do not disable the network guard.

## Doctor

The read-only `doctor` command above checks interpreter version, pytest, pymupdf, required CLI sources and source hashes. On this branch the required sources are `workflow.py`, `process_run.py`, `discovery.py`, `summary_artifact.py`, `zotero_ingest.py`, `local_pdf.py`, and `scansci_retrieval.py`. Exit 0 / `ok: true` means the local runner is worth driving, not that production credentials or services are healthy. During `run`, `guard.json` additionally proves that real Zotero's local port 23119 is blocked before any application code executes. Fixture ports are owned by this run, allocated dynamically and recorded in `ports.txt`.

## Drive

Run all features as above, or append one of:

```bash
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature discovery
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature scansci
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature selection
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature local-pdf
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature acquisition
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature delivery
"$VERIFY_PYTHON" .agents/skills/verify-paper2zotero/scripts/verify_runner.py run --feature backend-defaults
```

Use `--evidence /absolute/new/directory` to select a new evidence destination. Existing destinations are refused, preserving earlier proof. Default evidence goes to ignored `literature-runs/verification-YYYYMMDD-HHMMSS/`. The actual public CLI commands, arguments and results are captured in `commands.jsonl`; don't reconstruct production commands with live credentials from a fixture example.

The runner reuses `tests/http_fixture.py`, `zotero_peer.py`, `mineru_peer.py`, `fake_browser.py`, and their existing CLI scenarios. It creates a fresh child environment and disposable user profile; inherits no account settings, proxy, API key or browser session. `sitecustomize.py` permits Python connections only to fixture-owned ephemeral ports and blocks external DNS. This is a regression guard for this reviewed Python harness, not a general security sandbox for arbitrary subprocesses. Do not add arbitrary commands or live tests to the allowlisted scenario map without reviewing their boundaries.

## Evidence

A pass requires exit 0, every selected present test passed, `guard.json` exit 0, and `cleanup.json` showing removed scratch and no listening owned ports. Check `pytest.log` and `results.xml`, not merely file existence. `doctor.json` identifies the interpreter and source hashes; `invocation.json` identifies the exact test nodes.

`commands.jsonl` retains action, stdout, stderr and exit status. `state/` retains disposable run manifests, candidates, PDFs, acquisition trails, hashes, conversion journals, summary handoffs and simulated Zotero storage after teardown. Paths in transcripts retain the original temporary location: map `<scratch>/cases/` to `<evidence>/state/` using `cleanup.json`. `network.jsonl` records allowed/blocked Python socket attempts; a blocked probe of 23119 is expected, as are unavailable-source attempts to closed fixture URLs. No real credentials are included; known test-secret strings are redacted in command transcripts. State can contain dummy fixture credentials and signed fixture URLs only.

Tests exercise public CLI paths and assert side effects and read-back, with a few source-failure / rejection checks calling the same production client directly. Fixture setup sometimes seeds candidate metadata or already acquired artifacts; that seeding is not proof of discovery or acquisition. The browser adapter, bibliographic responses, Zotero service, MinerU service and summary text are simulated. Tests prove orchestration, persisted files, consent boundaries, bytes/read-back and recovery against those boundaries. They do not prove scientific summary quality, actual publisher access, external authentication, a live scansci-pdf download, a live Kimi search, a self-hosted MinerU host, Desktop sync, a local file attach, semantic search, or real uploads.

## Cleanup

`run` always copies scenario state to evidence, stops only its own pytest process group, removes its unique scratch directory, and checks that its fixture ports no longer listen. Test peer context managers close their own servers. Evidence remains outside scratch after success and failure. Do not delete evidence, actual literature runs, real Zotero records or attachments. Do not kill processes by name. If interrupted externally before cleanup, inspect the recorded invocation and precise scratch path; report the interruption and check only the run's owned processes before targeted cleanup.

## Helpers

`verify_runner.py doctor|run [--feature NAME] [--repo PATH] [--evidence NEW_PATH]` is executable; examples use the chosen interpreter to avoid ambiguous shebang Python. `sitecustomize.py` is an imported network guard, not a standalone command. The runner is for macOS/Linux (POSIX process groups); Windows execution remains unverified.

Failure diagnosis: doctor failures mean missing interpreter/dependencies/source files; bind `PermissionError` means host sandbox restrictions; collection errors usually mean renamed test nodes; failing assertions identify behavior changes in the named feature; `commands.jsonl` gives failing CLI input/output, while `state/` gives the resulting files. Network guard blocks on a new endpoint mean the fixture boundary needs review, never permission to use a real service. After a failure, inspect `cleanup.json` before retrying into a new evidence directory.

## Limits and maintenance

No real integration runs are authorized by this skill. Unset `SEARCH_BACKEND` selects scansci. Backend selection, the grey default and the legal-only values are in [scansci.md](features/scansci.md). Conversion tries self-hosted MinerU only when `credentials.mineru_api_base()` is non-empty, then MinerU cloud when `MINERU_TOKEN` is set, then markitdown. `credentials.mineru_api_base()` returns the first configured value of `MINERU_API_BASE`, then `MINERU_ENDPOINT`. An empty value stops that lookup, so a set but empty `MINERU_API_BASE` blocks `MINERU_ENDPOINT`. Each paper falls through those hops in order. Unset `ZOTERO_WRITE_BACKEND` prefers the local API at `http://127.0.0.1:23119/api` and falls back to the Web API. `run --feature backend-defaults` drives `tests/test_backend_defaults.py` on loopback peers. That pass does not open a MinerU host, the Kimi daemon, or Zotero Desktop. The saved-backend rule is in [backend-defaults.md](features/backend-defaults.md).

Live Kimi needs the `kimi-webbridge` binary and `kimi-webbridge status`. Live MinerU needs the origin from `credentials.mineru_api_base()` to answer `GET /v1/health`, then `POST /v1/tasks`. Leaving `--mineru-api-base` at `https://mineru.net` health-checks `credentials.mineru_api_base()` and uses Tasks when that check passes. A failed check uses MinerU cloud when `MINERU_TOKEN` is set, otherwise markitdown when markitdown is installed. MinerU hops skip papers whose upload the user declined. A hop that fails a paper is recorded in `convert.attempts`. With neither, `stage_convert` records `no MinerU token` and skips the v4 client. A declined paper records `user declined upload`. An explicit base other than `https://mineru.net` that answers `GET /v1/health` is that Tasks host. An explicit base that fails the check is planned as cloud v4 against that same base, and `stage_convert` calls v4 only when a token is set. Offline fixtures pass that explicit base. Desktop reachability is `scripts/verify.py zotero-local`: it calls `capability.probe_zotero_local` and `capability.zotero_local`, and that probe is HTTP 200 on `GET http://127.0.0.1:23119/api/users/0/items?limit=1`. `capability.probe_zotero_local_write` needs that HTTP 200 and a `Zotero-Server-ID` header, and does not call `/local/authorize`. A writable session is `zotero_ingest.open_local_session`: the same header, then `POST /api/local/authorize` unless `ZOTERO_LOCAL_API_KEY` is already stored.

A live write needs a separately authorized, disposable library and storage. Otherwise report it as not run. The local upload path is in [delivery.md](features/delivery.md).

Personal-library semantic search and production content quality remain unaccepted. Installer GUI, natural-language screening, all platform variants and the wider test suite are outside this starter map.

Use PStack Personal's `/maintain-verification-skill` when entry points or behavior change. Update this map alongside the code; do not mark a skipped path verified by a different entry point.
