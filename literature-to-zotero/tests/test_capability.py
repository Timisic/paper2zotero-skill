"""Capability judgements are pure and their semantics live once.

Every runtime precondition ("capability") is a record of
{ok, detail, remediation}. preflight, verify and the setup doctor all read
these records, so a semantic change (e.g. storage_sync_enabled=None means
Zotero-7 default ON) is written and tested here once.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "capability.py"
SPEC = importlib.util.spec_from_file_location("capability", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_zotero_sync_missing_storage_pref_is_default_on(tmp_path: Path) -> None:
    """Zotero 7 prefs.js without sync.storage.enabled = default ON (not a fail)."""
    prefs = tmp_path / "prefs.js"
    prefs.write_text('user_pref("extensions.zotero.dataDir", "/tmp/Zotero");\n')

    result = MODULE.zotero_sync(MODULE.zotero_prefs(prefs))

    assert result["ok"] is True
    assert "None" in str(result["detail"])


def test_zotero_sync_explicit_true_is_ok_but_explicit_false_fails(tmp_path: Path) -> None:
    enabled = tmp_path / "on.js"
    enabled.write_text('user_pref("extensions.zotero.sync.storage.enabled", true);\n')
    disabled = tmp_path / "off.js"
    disabled.write_text('user_pref("extensions.zotero.sync.storage.enabled", false);\n')

    assert MODULE.zotero_sync(MODULE.zotero_prefs(enabled))["ok"] is True
    assert MODULE.zotero_sync(MODULE.zotero_prefs(disabled))["ok"] is False


def test_zotero_sync_missing_prefs_file_fails_with_remediation(tmp_path: Path) -> None:
    result = MODULE.zotero_sync(MODULE.zotero_prefs(tmp_path / "missing.js"))
    assert result["ok"] is False
    assert result["detail"]
    assert result["remediation"]


def test_zotero_prefs_parser_exposes_absent_and_disabled_values(tmp_path: Path) -> None:
    prefs = tmp_path / "prefs.js"
    prefs.write_text(
        'user_pref("extensions.zotero.dataDir", "/tmp/Zotero");\n'
        'user_pref("extensions.zotero.sync.storage.enabled", false);\n'
        'user_pref("extensions.zotero.downloadAssociatedFiles", false);\n'
    )

    result = MODULE.zotero_prefs(prefs)

    assert result == {
        "prefs_found": True,
        "data_dir": "/tmp/Zotero",
        "storage_sync_enabled": False,
        "download_associated_files": False,
    }
    absent = MODULE.zotero_prefs(tmp_path / "empty.js")
    assert absent["prefs_found"] is False
    assert absent["storage_sync_enabled"] is None


def test_zotero_local_requires_an_observed_http_200() -> None:
    assert MODULE.zotero_local(None)["ok"] is False
    assert MODULE.zotero_local(False)["ok"] is False
    assert MODULE.zotero_local(True)["ok"] is True


def test_kimi_requires_installed_daemon_running_and_connected_extension() -> None:
    assert MODULE.kimi({"installed": False, "running": None, "extension_connected": None})["ok"] is False
    assert MODULE.kimi({"installed": True, "running": True, "extension_connected": False})["ok"] is False
    assert MODULE.kimi({"installed": True, "running": True, "extension_connected": True})["ok"] is True
    assert MODULE.kimi({"installed": True, "running": None, "extension_connected": None})["ok"] is False


def test_zotero_key_requires_credentials_then_live_identity_and_write_permission() -> None:
    missing = MODULE.zotero_key(False, None)
    assert missing["ok"] is False
    assert "ZOTERO_API_KEY" in str(missing["remediation"])

    unassessed = MODULE.zotero_key(True, None)
    assert unassessed["ok"] is False

    unreachable = {"reachable": None, "identity_match": None, "write_permission": None}
    assert MODULE.zotero_key(True, unreachable)["ok"] is False

    partial = {"reachable": True, "identity_match": False, "write_permission": True}
    assert MODULE.zotero_key(True, partial)["ok"] is False

    full = {"reachable": True, "identity_match": True, "write_permission": True}
    assert MODULE.zotero_key(True, full)["ok"] is True


def test_zotero_mcp_requires_configured_block_with_executable_command() -> None:
    assert MODULE.zotero_mcp(False, True)["ok"] is False
    assert MODULE.zotero_mcp(True, False)["ok"] is False
    assert MODULE.zotero_mcp(True, True)["ok"] is True


def test_mineru_presence_is_ok_but_live_probe_failure_is_not() -> None:
    assert MODULE.mineru(False)["ok"] is False
    assert MODULE.mineru(True)["ok"] is True
    assert MODULE.mineru(True, {"valid": True, "code": 0, "msg": "ok"})["ok"] is True
    assert MODULE.mineru(True, {"valid": False, "code": None, "msg": "rejected"})["ok"] is False


def test_skill_links_ok_when_at_least_one_runtime_has_the_skill() -> None:
    assert MODULE.skill_links([])["ok"] is False
    ok = MODULE.skill_links(["/tmp/.codex/skills/literature-to-zotero"])
    assert ok["ok"] is True
    assert "literature-to-zotero" in str(ok["detail"])


def test_ready_is_conjunction_of_only_live_readiness_capabilities() -> None:
    ok_record = {"ok": True, "detail": "d", "remediation": "r"}
    broken_record = {"ok": False, "detail": "d", "remediation": "r"}
    assert MODULE.ready({}) is False
    assert MODULE.ready({"zotero_local": ok_record, "zotero_sync": ok_record, "kimi": ok_record, "zotero_key": ok_record}) is True
    assert MODULE.ready({"zotero_local": ok_record, "zotero_key": broken_record}) is False


class KeyAccessHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        assert self.headers["Zotero-API-Key"] == "secret"
        payload = {
            "userID": 123,
            "access": {"user": {"library": True, "files": True, "notes": True, "write": True}},
        }
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def test_zotero_key_access_probe_verifies_identity_and_write_permission() -> None:
    server = HTTPServer(("127.0.0.1", 0), KeyAccessHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = MODULE.zotero_key_access(
            "secret", "123", "user", f"http://127.0.0.1:{server.server_port}"
        )
    finally:
        server.shutdown()
    assert result == {"reachable": True, "identity_match": True, "write_permission": True}


class LocalApiHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def test_zotero_local_probe_answers_200(monkeypatch: object) -> None:
    server = HTTPServer(("127.0.0.1", 0), LocalApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(  # type: ignore[attr-defined]
            MODULE, "ZOTERO_LOCAL_API", f"http://127.0.0.1:{server.server_port}/"
        )
        assert MODULE.probe_zotero_local() is True
        monkeypatch.setattr(  # type: ignore[attr-defined]
            MODULE, "ZOTERO_LOCAL_API", f"http://127.0.0.1:{server.server_port}/missing"
        )
        assert MODULE.probe_zotero_local() is False
    finally:
        server.shutdown()


def test_kimi_probe_reads_daemon_status_json(tmp_path: Path) -> None:
    binary = tmp_path / "kimi-webbridge"
    binary.write_text(
        "#!/bin/sh\nprintf '%s\\n' '{\"running\": true, \"extension_connected\": true}'\n"
    )
    binary.chmod(0o755)
    status = MODULE.probe_kimi(binary)
    assert status["installed"] is True
    assert status["running"] is True
    assert status["extension_connected"] is True


def test_kimi_probe_skips_daemon_call_when_live_is_false(tmp_path: Path) -> None:
    binary = tmp_path / "kimi-webbridge"
    binary.write_text("#!/bin/sh\nprintf '%s\\n' 'should-not-run'\n")
    binary.chmod(0o755)
    status = MODULE.probe_kimi(binary, live=False)
    assert status["installed"] is True
    assert status["running"] is None
    assert status["extension_connected"] is None


def test_skill_link_roots_discovers_symlinks_under_agent_roots(tmp_path: Path, monkeypatch: object) -> None:
    home = tmp_path / "home"
    link = home / ".codex" / "skills" / "literature-to-zotero"
    link.parent.mkdir(parents=True)
    link.symlink_to(tmp_path / "target", target_is_directory=True)
    assert MODULE.skill_link_roots(home) == []  # A dangling link is not an installation.
    target = tmp_path / "target"
    target.mkdir()
    (target / "SKILL.md").write_text("fixture")
    roots = MODULE.skill_link_roots(home)
    assert any(str(link) == candidate for candidate in roots)


def test_guide_has_one_plain_text_entry_per_capability() -> None:
    """The setup doctor and wizard share one human fix per capability (C3)."""
    expected = {
        "zotero_local", "zotero_sync", "zotero_mcp", "zotero_key",
        "kimi", "mineru", "skill_links", "discovery_sources",
    }
    assert set(MODULE.GUIDE) == expected
    for key, entry in MODULE.GUIDE.items():
        assert set(entry) == {"label", "url", "do"}
        assert entry["label"]
        assert entry["do"]
        assert "\n" not in entry["do"]
        assert entry["url"] == "" or entry["url"].startswith(("http://", "https://"))


def test_missing_capability_records_carry_the_guide_fix_text() -> None:
    """Doctor remediation == wizard copy: both read GUIDE, never two texts."""
    assert MODULE.zotero_local(False)["remediation"] == MODULE.GUIDE["zotero_local"]["do"]
    assert MODULE.zotero_sync({"prefs_found": False})["remediation"] == MODULE.GUIDE["zotero_sync"]["do"]
    assert MODULE.zotero_mcp(False, False)["remediation"] == MODULE.GUIDE["zotero_mcp"]["do"]
    assert MODULE.kimi({"installed": False})["remediation"] == MODULE.GUIDE["kimi"]["do"]
    assert MODULE.mineru(False)["remediation"] == MODULE.GUIDE["mineru"]["do"]
    assert MODULE.skill_links([])["remediation"] == MODULE.GUIDE["skill_links"]["do"]


def test_zotero_key_state_specific_notes_are_doctor_only() -> None:
    assert MODULE.zotero_key(False, None)["remediation"] == MODULE.GUIDE["zotero_key"]["do"]
    assert MODULE.zotero_key(True, None)["remediation"] == MODULE.KEY_SKIP_NOTE
    mismatch = {"reachable": True, "identity_match": False, "write_permission": True}
    assert MODULE.zotero_key(True, mismatch)["remediation"] == MODULE.KEY_LIVE_NOTE



# ── portability and advisory reachability ──────────────────────────────────

def test_zotero_profiles_are_looked_for_where_each_os_keeps_them() -> None:
    home = Path("/home/u")
    assert MODULE.zotero_profiles_dirs("darwin", home) == [
        home / "Library" / "Application Support" / "Zotero" / "Profiles"
    ]
    assert MODULE.zotero_profiles_dirs("win32", home, "C:/Users/x/AppData/Roaming") == [
        Path("C:/Users/x/AppData/Roaming") / "Zotero" / "Zotero" / "Profiles"
    ]
    assert MODULE.zotero_profiles_dirs("linux", home)[0] == home / ".zotero" / "zotero"


def test_reachability_is_advisory_and_cannot_gate_readiness() -> None:
    """It has no `ok` field, so `capability.ready` can never consume it."""
    report = MODULE.reachability_report({"crossref": True, "openalex": False, "arxiv": None})
    assert "ok" not in report
    assert report["advisory"] is True
    assert (report["reachable"], report["measured"]) == (1, 2)


def test_skipping_live_probes_reports_unknown_not_unreachable() -> None:
    results = MODULE.probe_external_sources(live=False)
    assert set(results.values()) == {None}
    assert MODULE.reachability_report(results)["measured"] == 0


def test_discovery_sources_report_coverage_without_blocking_a_search() -> None:
    """A missing optional key narrows coverage; it never stops discovery."""
    partial = MODULE.discovery_sources(
        {"openalex": True, "semantic_scholar": False, "crossref": True,
         "unpaywall": False, "arxiv": True})
    assert partial["ok"] is True
    assert "semantic_scholar" in partial["detail"]
    assert "unpaywall" in partial["detail"]
    assert partial["remediation"]

    # Discovery still requires nothing local, so this record gates no stage.
    assert MODULE.STAGE_REQUIREMENTS["discovery"] == ()
    assert "discovery_sources" not in MODULE.STAGE_REQUIREMENTS["acquisition"]
    assert MODULE.discovery_sources({"openalex": False, "arxiv": False})["ok"] is False


def test_acquisition_is_gated_on_nothing_and_the_browser_route_on_kimi() -> None:
    """HTTP acquisition needs no local capability; only the fallback needs Kimi."""
    assert MODULE.STAGE_REQUIREMENTS["acquisition"] == ()
    assert MODULE.STAGE_REQUIREMENTS["browser_fallback"] == ("kimi",)
    down = {"kimi": MODULE.kimi({"installed": True, "running": False, "extension_connected": False})}
    assert MODULE.stage_missing("acquisition", down) == []
    assert MODULE.stage_missing("browser_fallback", down) == ["kimi"]
