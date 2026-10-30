"""Lab defaults: Kimi search, LAN MinerU, local Zotero writes.

These tests stay on loopback. They do not dial the lab host.
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import credentials  # noqa: E402
import discovery  # noqa: E402
import mineru_parse  # noqa: E402
import zotero_ingest  # noqa: E402
from http_fixture import server  # noqa: E402
from sources import Query  # noqa: E402
from test_cli import run_script  # noqa: E402
from test_workflow_resume import selected_run  # noqa: E402
from zotero_peer import ZoteroLibrary  # noqa: E402

LAN = "http://192.168.8.167:8000"


def test_search_backend_defaults_to_kimi(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(credentials, "SKILL_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.delenv("SEARCH_BACKEND", raising=False)
    assert credentials.search_backend() == "kimi"
    assert credentials.discovery_sources_for() == ("kimi",)
    monkeypatch.setenv("SEARCH_BACKEND", "openalex")
    assert credentials.discovery_sources_for() == ("openalex",)


def test_kimi_search_writes_browser_hits_and_a_block_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def transport(action, payload, session, timeout):
        calls.append((action, payload, session))
        if action == "evaluate":
            return {"hits": [{"title": "Browser Hit", "year": 2020, "authors": ["Ada Lovelace"],
                              "url": "https://example.edu/paper"}], "blocked": False}
        return {}

    original = discovery.kimi_search
    monkeypatch.setattr(discovery, "kimi_search", lambda query, budget: original(query, budget, transport=transport))
    output = tmp_path / "candidates.json"
    result = discovery.discover(discovery.DiscoveryRequest(
        query=Query(text="attention robots"), output=output, sources=("kimi",)))
    assert result["status"] == "ok"
    assert result["returned"] == 1
    assert calls[0][0] == "navigate"
    assert "attention" in calls[0][1]["url"]
    assert "openalex" not in calls[0][1]["url"]
    assert calls[0][2] == "literature-discovery"
    assert json.loads(output.read_text())[0]["title"] == "Browser Hit"
    blocked = original(Query(text="x"), 5, transport=lambda *args: {"hits": [], "blocked": True})
    assert blocked.status == "unavailable"


def test_mineru_default_is_the_lan_host(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(credentials, "SKILL_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.delenv("MINERU_API_BASE", raising=False)
    monkeypatch.delenv("MINERU_ENDPOINT", raising=False)
    assert credentials.mineru_api_base() == LAN
    assert credentials.LAB_MINERU_API_BASE_TAILSCALE == "http://100.92.231.38:8000"
    monkeypatch.setenv("MINERU_TOKEN", "sk-fixture")
    plan = mineru_parse.converter_plan(live=False)
    assert plan["api_base"] == LAN
    assert plan["lab_default"] == LAN
    assert plan["chain"][:2] == ["mineru-self-hosted", "mineru-cloud"]
    assert plan["available"][0] == "mineru-self-hosted"
    assert plan["selected"] == "mineru-self-hosted"
    monkeypatch.setenv("MINERU_API_BASE", "")
    muted = mineru_parse.converter_plan(live=False)
    assert "mineru-self-hosted" not in muted["available"]
    assert muted["selected"] == "mineru-cloud"


def test_unhealthy_self_host_drops_out_of_the_chain(monkeypatch) -> None:
    def respond(method, path, body, headers):
        return 500, {"ok": False}, {}

    with server(respond) as base:
        monkeypatch.setenv("MINERU_API_BASE", base)
        monkeypatch.setenv("MINERU_TOKEN", "sk-fixture")
        plan = mineru_parse.converter_plan(live=True)
    assert "mineru-self-hosted" in plan["chain"]
    assert "mineru-self-hosted" not in plan["available"]
    assert plan["selected"] == "mineru-cloud"


def test_tasks_api_unpacks_full_md(tmp_path: Path) -> None:
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w") as archive:
        archive.writestr("out/full.md", "# Parsed\n")
    raw = blob.getvalue()
    holder: dict[str, str] = {}

    def respond(method, path, body, headers):
        base = holder["base"]
        if method == "POST" and path == "/v1/tasks":
            receipt = {"task_id": "t1", "files": [{"upload": {"url": base + "/upload/t1", "headers": {}}}]}
            return 200, receipt, {}
        if method == "PUT" and path == "/upload/t1":
            return 200, b"", {}
        if method == "GET" and path == "/v1/tasks/t1":
            return 200, {"files": [{"status": "completed", "result_url": base + "/result/t1"}]}, {}
        if method == "GET" and path == "/result/t1":
            return 200, raw, {}
        return 404, {}, {}

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fixture")
    with server(respond) as base:
        holder["base"] = base
        markdown = mineru_parse.parse_tasks_pdf(pdf, base, 5)
    assert Path(markdown).read_text(encoding="utf-8") == "# Parsed\n"


def test_preflight_names_kimi_and_the_lan_host(monkeypatch) -> None:
    monkeypatch.delenv("SEARCH_BACKEND", raising=False)
    monkeypatch.delenv("MINERU_API_BASE", raising=False)
    monkeypatch.delenv("MINERU_ENDPOINT", raising=False)
    conversion = json.loads(run_script("preflight.py", "--json", "--skip-live", "--stage", "conversion").stdout)
    assert conversion["converter"]["api_base"] == LAN
    assert conversion["converter"]["lab_default"] == LAN
    assert conversion["converter"]["selected"] == "mineru-self-hosted"
    assert "token" not in conversion["converter"]
    discovered = json.loads(run_script("preflight.py", "--json", "--skip-live", "--stage", "discovery").stdout)
    assert discovered["search"] == {"backend": "kimi", "sources": ["kimi"]}


def test_ingestion_stage_is_ready_from_local_write_without_calling_the_web_key(monkeypatch) -> None:
    seen: list[str] = []

    def respond(method, path, body, headers):
        seen.append(path)
        return 200, [], {"Zotero-Server-ID": "fixture-server"}

    with server(respond) as base:
        monkeypatch.setenv("ZOTERO_LOCAL_API", base + "/api")
        monkeypatch.setenv("ZOTERO_API_KEY", "fixture-secret")
        monkeypatch.setenv("ZOTERO_LIBRARY_ID", "123")
        monkeypatch.setenv("ZOTERO_LIBRARY_TYPE", "user")
        result = run_script("preflight.py", "--json", "--stage", "ingestion", "--zotero-api-base-url", base)
    payload = json.loads(result.stdout)
    assert payload["stage_ready"] is True
    assert payload["capabilities"]["zotero_write"]["ok"] is True
    assert not any(path.endswith("/keys/current") for path in seen)
    assert "fixture-secret" not in result.stdout


def test_ingest_uses_the_local_api_without_a_web_key(tmp_path: Path, monkeypatch) -> None:
    run = selected_run(tmp_path)
    run_script("workflow.py", "record-paper", "--run-dir", str(run),
               "--id", "doi:10.1000/alpha", "--state", "metadata_only")
    library = ZoteroLibrary(library="/api/users/0")
    state = {"auth": 0, "denied": 0}

    def respond(method, path, body, headers):
        if method == "POST" and path == "/api/local/authorize":
            state["auth"] += 1
            assert headers.get("Zotero-Server-ID") == "fixture-server"
            return 200, {"key": "local-key", "remember": False}, {"Zotero-Server-ID": "fixture-server"}
        if method == "POST" and path.endswith("/items") and state["denied"] == 0:
            state["denied"] += 1
            return 401, {"error": "unauthorized"}, {"Zotero-Server-ID": "fixture-server"}
        status, payload, extra = library.respond(method, path, body, headers)
        return status, payload, {**extra, "Zotero-Server-ID": "fixture-server"}

    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.delenv("ZOTERO_LIBRARY_ID", raising=False)
    monkeypatch.delenv("ZOTERO_LOCAL_API_KEY", raising=False)
    monkeypatch.setenv("ZOTERO_WRITE_BACKEND", "local")
    with server(respond) as base:
        library.base = base
        monkeypatch.setenv("ZOTERO_LOCAL_API", base + "/api")
        result = zotero_ingest.ingest(zotero_ingest.IngestRequest(
            run_dir=run, collection_key="COLLECT1", retry_budget=5))
    assert result["status"] == "complete", result
    assert result["write_channel"] == "local_api"
    assert state["auth"] == 2
    assert library.creations == 1
    assert "fixture-secret" not in json.dumps(result)
