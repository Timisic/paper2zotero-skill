"""These tests stay on loopback. They do not dial the lab host.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import credentials  # noqa: E402
import discovery  # noqa: E402
import mineru_parse  # noqa: E402
import process_run  # noqa: E402
import workflow  # noqa: E402
import zotero_ingest  # noqa: E402
from http_fixture import server  # noqa: E402
from sources import Query  # noqa: E402
from test_cli import run_script  # noqa: E402
from test_partial_delivery import run_with_pdf  # noqa: E402
from test_workflow_resume import selected_run  # noqa: E402
from zotero_peer import ZoteroLibrary  # noqa: E402

LAN = "http://192.168.8.167:8000"


def test_search_backend_defaults_to_scansci(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(credentials, "SKILL_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.delenv("SEARCH_BACKEND", raising=False)
    assert credentials.search_backend() == "scansci"
    assert credentials.discovery_sources_for() == ("scansci",)
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
    navigations = [call for call in calls if call[0] == "navigate"]
    assert len(navigations) == 1
    assert navigations[0][1].get("newTab") is not True
    assert "newTab" not in navigations[0][1]
    assert "attention" in navigations[0][1]["url"]
    assert "openalex" not in navigations[0][1]["url"]
    assert navigations[0][2] == "literature-discovery"
    assert json.loads(output.read_text())[0]["title"] == "Browser Hit"
    blocked = original(Query(text="x"), 5, transport=lambda *args: {"hits": [], "blocked": True})
    assert blocked.status == "unavailable"


def test_kimi_search_reuses_the_open_tab() -> None:
    calls = []

    def transport(action, payload, session, timeout):
        if isinstance(payload, dict) and payload.get("newTab"):
            raise TimeoutError("new tab hung")
        calls.append(action)
        if action == "list_tabs":
            return {"tabs": [{"url": "https://www.kimi.com/"}]}
        if action == "evaluate":
            return {"hits": [{"title": "Attached Hit"}], "blocked": False}
        return {}

    answer = discovery.kimi_search(Query(text="robots"), 40, transport=transport)
    assert answer.status == "ok"
    assert [record["title"] for record in answer.records] == ["Attached Hit"]
    assert calls.count("navigate") == 1
    assert "find_tab" not in calls
    assert discovery.PER_SOURCE_CEILING == 40.0


def test_wrapped_evaluate_hits_still_become_candidates(tmp_path: Path, monkeypatch) -> None:
    """command('evaluate') returns {type, value}; hits are inside value."""
    page = {"hits": [{"title": "Wrapped Hit", "year": 2024, "authors": ["Ada Lovelace"],
                      "url": "https://example.edu/paper"}], "blocked": False}
    assert discovery._unwrap_evaluate({"type": "string", "value": json.dumps(page)})["hits"] == page["hits"]
    assert discovery._unwrap_evaluate({"type": "object", "value": page})["hits"] == page["hits"]
    assert discovery._unwrap_evaluate(page)["hits"] == page["hits"]

    def transport(action, payload, session, timeout):
        if action == "list_tabs":
            return {"tabs": [{"url": "https://www.kimi.com/"}]}
        if action == "evaluate":
            return {"type": "string", "value": json.dumps(page)}
        return {}

    original = discovery.kimi_search
    monkeypatch.setattr(discovery, "kimi_search", lambda query, budget: original(query, budget, transport=transport))
    output = tmp_path / "candidates.json"
    result = discovery.discover(discovery.DiscoveryRequest(
        query=Query(text="attention robots"), output=output, sources=("kimi",)))
    assert result["status"] == "ok"
    assert result["returned"] == 1
    assert json.loads(output.read_text())[0]["title"] == "Wrapped Hit"


def test_a_down_default_page_is_unavailable() -> None:
    outage = json.dumps({"hits": [], "blocked": False, "trouble": True, "title": "Semantic Scholar"})
    navigated: list[str] = []

    def transport(action, payload, session, timeout):
        if action == "list_tabs":
            return {"tabs": [{"url": "https://www.kimi.com/"}]}
        if action == "navigate":
            navigated.append(payload["url"])
            return {}
        if action == "evaluate":
            return {"type": "string", "value": outage}
        return {}

    query = Query(text="robots")
    answer = discovery.kimi_search(query, 40, transport=transport)
    assert answer.status == "unavailable"
    assert answer.records == []
    assert answer.detail == "search page was not readable"
    assert navigated == [discovery.search_page(query)]
    assert navigated[0].startswith("https://www.semanticscholar.org/search?")
    assert "servers are having a bit of trouble" in discovery.EXTRACT_JS


def test_an_unreadable_evaluate_is_unavailable() -> None:
    navigated: list[str] = []

    def transport(action, payload, session, timeout):
        if action == "list_tabs":
            return {"tabs": [{"url": "https://www.kimi.com/"}]}
        if action == "navigate":
            navigated.append(payload["url"])
            return {}
        if action == "evaluate":
            return {"type": "string", "value": "not json"}
        return {}

    query = Query(text="robots")
    answer = discovery.kimi_search(query, 40, transport=transport)
    assert answer.status == "unavailable"
    assert answer.records == []
    assert answer.detail == "search page was not readable"
    assert navigated == [discovery.search_page(query)]


def test_an_outage_page_is_unavailable() -> None:
    navigated: list[str] = []

    def transport(action, payload, session, timeout):
        if action == "list_tabs":
            return {"tabs": [{"url": "https://www.kimi.com/"}]}
        if action == "navigate":
            navigated.append(payload["url"])
            return {}
        if action == "evaluate":
            return {"type": "string", "value": json.dumps({"hits": [], "blocked": False, "trouble": True})}
        return {}

    answer = discovery.kimi_search(Query(text="robots"), 40, transport=transport)
    assert answer.status == "unavailable"
    assert answer.records == []
    assert answer.detail == "search page was not readable"
    assert len(navigated) == 1


def test_a_real_empty_page_does_not_open_another_search() -> None:
    navigated: list[str] = []

    def transport(action, payload, session, timeout):
        if action == "list_tabs":
            return {"tabs": [{"url": "https://www.kimi.com/"}]}
        if action == "navigate":
            navigated.append(payload["url"])
        if action == "evaluate":
            return {"hits": [], "blocked": False}
        return {}

    answer = discovery.kimi_search(Query(text="very specific absent phrase"), 40, transport=transport)
    assert answer.status == "empty"
    assert len(navigated) == 1
    assert "scholar.google.com" not in navigated[0]


def test_a_configured_search_url_is_not_replaced_when_it_is_down(monkeypatch) -> None:
    monkeypatch.setenv("KIMI_SEARCH_URL", "https://example.edu/search?q={query}")
    navigated: list[str] = []

    def transport(action, payload, session, timeout):
        if action == "list_tabs":
            return {"tabs": [{"url": "https://www.kimi.com/"}]}
        if action == "navigate":
            navigated.append(payload["url"])
        if action == "evaluate":
            return {"hits": [], "blocked": False, "trouble": True}
        return {}

    answer = discovery.kimi_search(Query(text="robots"), 40, transport=transport)
    assert answer.status == "unavailable"
    assert navigated == ["https://example.edu/search?q=robots"]


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


def _consented_pdf(tmp_path: Path) -> tuple[Path, Path]:
    run, pdf = run_with_pdf(tmp_path)
    run_script("workflow.py", "consent", "--run-dir", str(run), "--service", "mineru",
               "--decision", "approved", "--source", "message:fixture")
    return run, pdf


def _tasks_peer(markdown: str, *, health: int = 200, create: int = 200):
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w") as archive:
        archive.writestr("out/full.md", markdown)
    raw = blob.getvalue()
    holder: dict[str, str] = {}

    def respond(method, path, body, headers):
        base = holder["base"]
        if method == "GET" and path == "/v1/health":
            if health != 200:
                return health, {"ok": False}, {}
            return 200, {"ok": True, "version": "fixture"}, {}
        if method == "POST" and path == "/v1/tasks":
            if create >= 400:
                return create, {"error": "no"}, {}
            receipt = {"task_id": "t1", "files": [{"upload": {"url": base + "/upload/t1", "headers": {}}}]}
            return 200, receipt, {}
        if method == "PUT" and path == "/upload/t1":
            return 200, b"", {}
        if method == "GET" and path == "/v1/tasks/t1":
            return 200, {"files": [{"status": "completed", "result_url": base + "/result/t1"}]}, {}
        if method == "GET" and path == "/result/t1":
            return 200, raw, {}
        return 404, {}, {}

    return respond, holder


def test_a_healthy_tasks_host_is_used_when_the_flag_names_it(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    monkeypatch.setattr(
        mineru_parse, "convert_markitdown",
        lambda _pdf: (_ for _ in ()).throw(AssertionError("markitdown")),
    )
    run, pdf = _consented_pdf(tmp_path)
    respond, holder = _tasks_peer("# Parsed\n")
    with server(respond) as base:
        holder["base"] = base
        result = process_run.stage_convert(
            process_run.ProcessRequest(run_dir=run, mineru_api_base=base, poll_timeout=5),
            ["doi:10.1000/alpha"],
        )
    assert result["converted"] == ["doi:10.1000/alpha"], result
    written = workflow.Run.open(run).paper("doi:10.1000/alpha").markdown
    assert written is not None and written.read_text(encoding="utf-8") == "# Parsed\n"
    assert not (pdf.parent / "markitdown").exists()


def test_a_healthy_env_host_is_preferred_over_markitdown(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    monkeypatch.setattr(
        mineru_parse, "convert_markitdown",
        lambda _pdf: (_ for _ in ()).throw(AssertionError("markitdown")),
    )
    run, _pdf = _consented_pdf(tmp_path)
    respond, holder = _tasks_peer("# From the lab\n")
    with server(respond) as base:
        holder["base"] = base
        monkeypatch.setenv("MINERU_API_BASE", base)
        result = process_run.stage_convert(
            process_run.ProcessRequest(run_dir=run, poll_timeout=5),
            ["doi:10.1000/alpha"],
        )
    assert result["converted"] == ["doi:10.1000/alpha"], result
    written = workflow.Run.open(run).paper("doi:10.1000/alpha").markdown
    assert written is not None and written.read_text(encoding="utf-8") == "# From the lab\n"


def test_a_tasks_failure_is_reported_and_markitdown_is_not_substituted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    monkeypatch.setattr(
        mineru_parse, "convert_markitdown",
        lambda _pdf: (_ for _ in ()).throw(AssertionError("markitdown")),
    )
    run, pdf = _consented_pdf(tmp_path)
    respond, holder = _tasks_peer("# Unused\n", create=500)
    with server(respond) as base:
        holder["base"] = base
        monkeypatch.setenv("MINERU_API_BASE", base)
        result = process_run.stage_convert(
            process_run.ProcessRequest(run_dir=run, poll_timeout=5),
            ["doi:10.1000/alpha"],
        )
    assert result["converted"] == []
    assert "HTTP 500" in result["failed"]["doi:10.1000/alpha"]
    assert not (pdf.parent / "markitdown").exists()


def test_markitdown_names_the_self_hosted_health_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    monkeypatch.setattr(mineru_parse, "markitdown_available", lambda: True)

    def fake(pdf: Path) -> str:
        dest = pdf.parent / "markitdown" / "paper.md"
        dest.parent.mkdir(parents=True)
        dest.write_text("<!-- converter: markitdown; not a MinerU layout parse -->\n\nlocal\n", encoding="utf-8")
        return str(dest)

    monkeypatch.setattr(mineru_parse, "convert_markitdown", fake)
    run, _pdf = _consented_pdf(tmp_path)
    respond, holder = _tasks_peer("# Unused\n", health=500)
    with server(respond) as base:
        holder["base"] = base
        monkeypatch.setenv("MINERU_API_BASE", base)
        result = process_run.stage_convert(
            process_run.ProcessRequest(run_dir=run, poll_timeout=5),
            ["doi:10.1000/alpha"],
        )
    assert result["converted"] == ["doi:10.1000/alpha"], result
    assert "500" in result["detail"]
    warnings = workflow.Run.open(run).paper("doi:10.1000/alpha").warnings
    assert any("500" in item for item in warnings)


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


def test_preflight_names_scansci_and_the_lan_host(monkeypatch) -> None:
    monkeypatch.delenv("SEARCH_BACKEND", raising=False)
    monkeypatch.delenv("MINERU_API_BASE", raising=False)
    monkeypatch.delenv("MINERU_ENDPOINT", raising=False)
    conversion = json.loads(run_script("preflight.py", "--json", "--skip-live", "--stage", "conversion").stdout)
    assert conversion["converter"]["api_base"] == LAN
    assert conversion["converter"]["lab_default"] == LAN
    assert conversion["converter"]["selected"] == "mineru-self-hosted"
    assert "token" not in conversion["converter"]
    discovered = json.loads(run_script("preflight.py", "--json", "--skip-live", "--stage", "discovery").stdout)
    assert discovered["search"] == {"backend": "scansci", "sources": ["scansci"]}


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


SUMMARY = (
    "# Core Summary\n\n- provider: `agent-default`\n- template_version: `1`\n"
    "- source_basis: `pdf`\n\nVerified probe summary.\n"
)


def _local_desktop(tmp_path: Path):
    """Zotero 10 loopback: GET /file is 302 to file://, and uploads require both local headers."""
    library = ZoteroLibrary(library="/api/users/0")
    files: dict[str, bytes] = {}
    state: dict[str, list] = {"uploads": [], "file_posts": []}

    def respond(method, path, body, headers):
        extra = {"Zotero-Server-ID": "fixture-server"}
        if method == "POST" and path == "/api/local/authorize":
            assert headers.get("Zotero-Server-ID") == "fixture-server"
            return 200, {"key": "local-key", "remember": False}, extra
        if path.startswith("/api/local/uploads/"):
            if headers.get("Zotero-API-Key") != "local-key" or headers.get("Zotero-Server-ID") != "fixture-server":
                return 401, {"error": "local upload requires the API key and server id"}, extra
            key = path.rstrip("/").split("/")[-1]
            files[key] = body
            state["uploads"].append(key)
            return 201, b"", extra
        if path.startswith("/api/users/0/items/") and "/file" in path.split("?")[0]:
            parts = [part for part in path.split("?")[0].split("/") if part]
            key = parts[4]
            state["file_posts"].append({
                "key": key, "method": method,
                "match": headers.get("If-Match"), "none": headers.get("If-None-Match"),
                "register": body.startswith(b"upload="),
            })
            if method == "GET":
                raw = files.get(key)
                if raw is None:
                    return 404, b"", extra
                target = tmp_path / "zotero-files" / key
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                return 302, b"", {**extra, "Location": target.resolve().as_uri()}
            if method == "POST" and body.startswith(b"upload="):
                if key in library.items and key in files:
                    library.items[key]["data"]["md5"] = hashlib.md5(files[key]).hexdigest()
                return 204, b"", extra
            if method == "POST":
                return 200, {
                    "url": "/api/local/uploads/" + key,
                    "prefix": "", "suffix": "",
                    "contentType": "application/octet-stream",
                    "uploadKey": "upload-" + key,
                }, extra
        status, payload, more = library.respond(method, path, body, headers)
        return status, payload, {**more, **extra}

    return library, files, state, respond


def _use_local_writer(monkeypatch) -> None:
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.delenv("ZOTERO_LIBRARY_ID", raising=False)
    monkeypatch.delenv("ZOTERO_LOCAL_API_KEY", raising=False)
    monkeypatch.setenv("ZOTERO_WRITE_BACKEND", "local")


def _parent(key: str = "EXISTING") -> dict:
    return {"key": key, "version": 1, "data": {
        "key": key, "itemType": "journalArticle", "title": "Zotero MCP Write Probe",
        "DOI": "10.1000/alpha", "collections": [], "tags": [], "creators": [],
    }}


def test_local_api_attaches_pdf_and_markdown_through_a_file_redirect(tmp_path: Path, monkeypatch) -> None:
    from test_partial_delivery import run_with_pdf
    run, pdf = run_with_pdf(tmp_path)
    markdown = run / "paper.md"
    markdown.write_text("# Parsed\n")
    run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/alpha",
               "--state", "markdown_derived", "--artifact", "markdown=" + str(markdown))
    library, files, state, respond = _local_desktop(tmp_path)
    _use_local_writer(monkeypatch)
    with server(respond) as base:
        library.base = base
        monkeypatch.setenv("ZOTERO_LOCAL_API", base + "/api")
        result = zotero_ingest.ingest(zotero_ingest.IngestRequest(
            run_dir=run, collection_key="COLLECT1", retry_budget=5))
    assert result["status"] != "pending", result
    paper = result["papers"]["doi:10.1000/alpha"]
    assert "error" not in paper
    assert result["write_channel"] == "local_api"
    assert paper["attachments"]["source.pdf"]["file_action"] == "uploaded"
    assert paper["attachments"]["paper.md"]["file_action"] == "uploaded"
    assert set(files.values()) == {pdf.read_bytes(), markdown.read_bytes()}
    auth_posts = [post for post in state["file_posts"] if post["method"] == "POST" and not post["register"]]
    assert auth_posts
    assert all(post["none"] == "*" and not post["match"] for post in auth_posts)
    assert "https://api.zotero.org" not in json.dumps(result)


def test_local_api_replaces_its_own_filename_instead_of_a_sibling(tmp_path: Path, monkeypatch) -> None:
    from test_partial_delivery import run_with_pdf
    run, pdf = run_with_pdf(tmp_path)
    library, files, state, respond = _local_desktop(tmp_path)
    stale = b"stale-bytes-not-the-probe"
    files["OLDPDF"] = stale
    library.items["EXISTING"] = _parent()
    library.items["OLDPDF"] = {"key": "OLDPDF", "version": 1, "data": {
        "key": "OLDPDF", "itemType": "attachment", "parentItem": "EXISTING",
        "linkMode": "imported_file", "filename": "source.pdf", "contentType": "application/pdf",
        "md5": hashlib.md5(stale).hexdigest(), "tags": [], "relations": {},
    }}
    _use_local_writer(monkeypatch)
    with server(respond) as base:
        library.base = base
        monkeypatch.setenv("ZOTERO_LOCAL_API", base + "/api")
        result = zotero_ingest.ingest(zotero_ingest.IngestRequest(
            run_dir=run, collection_key="COLLECT1", retry_budget=5))
    assert result["status"] != "pending", result
    paper = result["papers"]["doi:10.1000/alpha"]
    assert "error" not in paper
    assert paper["attachments"]["source.pdf"]["file_action"] == "replaced"
    assert paper["attachments"]["source.pdf"]["key"] == "OLDPDF"
    pdfs = [item for item in library.items.values()
            if item["data"].get("itemType") == "attachment" and item["data"].get("contentType") == "application/pdf"]
    assert [item["key"] for item in pdfs] == ["OLDPDF"]
    assert files["OLDPDF"] == pdf.read_bytes()
    assert library.creations == 0
    auth = next(post for post in state["file_posts"] if post["method"] == "POST" and not post["register"])
    assert auth["match"] == hashlib.md5(stale).hexdigest()
    assert not auth["none"]


def test_existing_doi_skips_the_same_pdf_and_refuses_an_autoresearch_note(tmp_path: Path, monkeypatch) -> None:
    from test_partial_delivery import run_with_pdf
    run, pdf = run_with_pdf(tmp_path)
    markdown = run / "paper.md"
    markdown.write_text("# Parsed\n")
    run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/alpha",
               "--state", "markdown_derived", "--artifact", "markdown=" + str(markdown))
    summary = run / "summary.md"
    summary.write_text(SUMMARY)
    run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/alpha",
               "--state", "summary_generated", "--artifact", "summary=" + str(summary))
    library, files, state, respond = _local_desktop(tmp_path)
    files["OLDPDF"] = pdf.read_bytes()
    library.items["EXISTING"] = _parent()
    library.items["OLDPDF"] = {"key": "OLDPDF", "version": 1, "data": {
        "key": "OLDPDF", "itemType": "attachment", "parentItem": "EXISTING",
        "linkMode": "imported_file", "filename": "publisher.pdf", "contentType": "application/pdf",
        "md5": hashlib.md5(pdf.read_bytes()).hexdigest(), "tags": [], "relations": {},
    }}
    library.items["ARNOTE"] = {"key": "ARNOTE", "version": 3, "data": {
        "key": "ARNOTE", "itemType": "note", "parentItem": "EXISTING",
        "note": "<p>AutoResearch v3</p>", "tags": [], "relations": {},
    }}
    _use_local_writer(monkeypatch)

    def ingest() -> dict:
        return zotero_ingest.ingest(zotero_ingest.IngestRequest(
            run_dir=run, collection_key="COLLECT1", retry_budget=5))

    with server(respond) as base:
        library.base = base
        monkeypatch.setenv("ZOTERO_LOCAL_API", base + "/api")
        first = ingest()
        summary.write_text(SUMMARY.replace("Verified probe summary.", "Revised probe summary."))
        run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/alpha",
                   "--state", "summary_generated", "--artifact", "summary=" + str(summary))
        second = ingest()
        kept = next(item["data"]["note"] for item in library.items.values()
                    if item["data"].get("itemType") == "note" and item["key"] != "ARNOTE")
        summary.write_text(SUMMARY.replace("Verified probe summary.", "AutoResearch v3 was not requested."))
        run_script("workflow.py", "record-paper", "--run-dir", str(run), "--id", "doi:10.1000/alpha",
                   "--state", "summary_generated", "--artifact", "summary=" + str(summary))
        third = ingest()
    assert first["status"] != "pending", first
    paper = first["papers"]["doi:10.1000/alpha"]
    assert "error" not in paper
    assert paper["attachments"]["source.pdf"]["key"] == "OLDPDF"
    assert paper["attachments"]["source.pdf"]["file_action"] == "reused"
    assert paper["attachments"]["paper.md"]["file_action"] == "uploaded"
    assert paper["note_action"] == "created_or_recovered"
    assert "OLDPDF" not in state["uploads"]
    assert second["papers"]["doi:10.1000/alpha"]["note_action"] == "replaced"
    notes = [item for item in library.items.values() if item["data"].get("itemType") == "note"]
    assert len(notes) == 2
    assert library.items["ARNOTE"]["data"]["note"] == "<p>AutoResearch v3</p>"
    assert library.items["ARNOTE"]["version"] == 3
    owned = next(item for item in notes if item["key"] != "ARNOTE")
    assert "Revised probe summary." in owned["data"]["note"]
    assert "AutoResearch" not in owned["data"]["note"]
    assert "literature-to-zotero:" in owned["data"]["note"]
    assert third["papers"]["doi:10.1000/alpha"]["note_action"] == "skipped"
    assert third["papers"]["doi:10.1000/alpha"]["note_skip"] == "paper-to-zotero does not write AutoResearch notes"
    assert owned["data"]["note"] == kept
    assert library.creations == 2
    parents = [item for item in library.items.values()
               if item["data"].get("itemType") not in ("attachment", "note", "collection")]
    assert [item["key"] for item in parents] == ["EXISTING"]


def test_resume_command_omits_the_public_web_api(tmp_path: Path) -> None:
    import process_run
    plain = process_run.ProcessRequest(run_dir=tmp_path, collection_name="E2E Lab MinerU")
    command = process_run.ingest_command(plain, ["doi:10.1000/alpha"])
    assert "--api-base" not in command
    assert "https://api.zotero.org" not in command
    pinned = process_run.ingest_command(process_run.ProcessRequest(
        run_dir=tmp_path, collection_name="E2E Lab MinerU", api_base="http://127.0.0.1:9"), ["doi:10.1000/alpha"])
    assert pinned[pinned.index("--api-base") + 1] == "http://127.0.0.1:9"


def test_kimi_round_does_not_fall_back_to_openalex(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(credentials, "SKILL_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("SEARCH_BACKEND", "kimi")
    assert credentials.discovery_sources_for() == ("kimi",)
    assert credentials.discovery_sources_for("http") == ("openalex", "semantic_scholar")

    def boom(*_args, **_kwargs):
        raise AssertionError("HTTP search sources are not a Kimi fallback")

    monkeypatch.setattr(discovery.Sources, "search", boom)
    original = discovery.kimi_search

    def blocked(query, budget, transport=None):
        return original(query, budget, transport=lambda *_args: {"hits": [], "blocked": True})

    monkeypatch.setattr(discovery, "kimi_search", blocked)
    result = discovery.discover(discovery.DiscoveryRequest(
        query=Query(text="five paper lab batch"), output=tmp_path / "candidates.json",
        sources=credentials.discovery_sources_for()))
    assert result["status"] == "failed"
    assert result["wrote_output"] is False
    assert result["failed_sources"] == ["Kimi"]
    assert result["sources"][0]["status"] == "unavailable"
    assert "openalex" not in json.dumps(result["sources"]).lower()
