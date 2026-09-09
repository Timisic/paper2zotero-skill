"""A stage probe must not pay for unrelated services or read their secrets."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import preflight


@pytest.mark.parametrize("stage", ["discovery", "acquisition", "conversion"])
def test_local_stage_never_probes_other_services(monkeypatch, capsys, stage):
    def unrelated(*args, **kwargs):
        raise AssertionError("unrelated service/config was inspected")
    for name in ("probe_kimi", "probe_zotero_local", "probe_zotero_key", "probe_external_sources", "zotero_prefs"):
        monkeypatch.setattr(preflight.capability, name, unrelated)
    monkeypatch.setattr(preflight.credentials, "zotero_mcp_config", unrelated)
    monkeypatch.setattr(preflight.credentials, "zotero_credentials", unrelated)
    monkeypatch.setattr(preflight.credentials, "mineru_token", lambda: "fixture-token" if stage == "conversion" else unrelated())
    monkeypatch.setattr(sys, "argv", ["preflight.py", "--stage", stage, "--json"])
    preflight.main()
    result = json.loads(capsys.readouterr().out)
    assert result["stage_ready"] is True
    assert set(result["capabilities"]) == ({"mineru"} if stage == "conversion" else set())
    assert "fixture-token" not in json.dumps(result)


def test_ingestion_checks_only_its_own_write_key(monkeypatch, capsys):
    def unrelated(*args, **kwargs):
        raise AssertionError("unrelated probe")
    for name in ("probe_kimi", "probe_zotero_local", "probe_external_sources", "zotero_prefs"):
        monkeypatch.setattr(preflight.capability, name, unrelated)
    monkeypatch.setattr(preflight.credentials, "zotero_mcp_config", unrelated)
    monkeypatch.setattr(preflight.credentials, "mineru_token", unrelated)
    monkeypatch.setattr(preflight.credentials, "zotero_credentials", lambda *a: {"api_key": "fixture-secret", "library_id": "1", "library_type": "user"})
    monkeypatch.setattr(preflight.capability, "probe_zotero_key", lambda *a: {"reachable": True, "identity_match": True, "write_permission": True})
    monkeypatch.setattr(sys, "argv", ["preflight.py", "--stage", "ingestion", "--json"])
    preflight.main()
    output = capsys.readouterr().out
    assert json.loads(output)["stage_ready"] is True
    assert "fixture-secret" not in output


@pytest.mark.parametrize('status,permission', [(401, False), (403, False), (503, None)])
def test_key_probe_separates_service_failure_from_rejected_credentials(status, permission):
    from http_fixture import server
    calls = []
    def respond(method, path, body, headers):
        calls.append(path)
        return status, {}, {}
    with server(respond) as base:
        access = preflight.capability.zotero_key_access('fixture-secret', '1', 'user', base)
    assert access == {'reachable': True, 'identity_match': None, 'write_permission': permission}
    assert len(calls) == (1 if permission is False else 2)
    assert preflight.capability.zotero_key(True, access)['ok'] is False


def test_unreachable_key_probe_keeps_identity_and_permission_unknown(monkeypatch):
    import urllib.error
    class Offline:
        def open(self, *args, **kwargs):
            raise urllib.error.URLError('fixture network unavailable')
    monkeypatch.setattr(preflight.capability.urllib.request, 'build_opener', lambda *a: Offline())
    access = preflight.capability.zotero_key_access('fixture-secret', '1', 'user')
    assert access == {'reachable': False, 'identity_match': None, 'write_permission': None}


def test_failed_optional_runtime_probe_does_not_invent_identity_failure(monkeypatch):
    unknown = {'reachable': False, 'identity_match': None, 'write_permission': None}
    monkeypatch.setattr(preflight.capability, 'zotero_key_access', lambda *a: unknown.copy())
    monkeypatch.setattr(preflight.capability, 'zotero_key_access_via_runtime', lambda *a: {
        'reachable': False, 'identity_match': False, 'write_permission': False})
    assert preflight.capability.probe_zotero_key('fixture-secret', '1', 'user', command='fixture') == unknown
