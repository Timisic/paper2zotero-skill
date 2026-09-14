"""Native account validation and all-or-nothing private saves."""
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import configure
import setup_connection as connection


def response(monkeypatch, payload):
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == 'https://api.zotero.org/keys/current'
            return StringIO(json.dumps(payload))
    monkeypatch.setattr(connection.urllib.request, 'build_opener', lambda *a: Opener())


def test_personal_identity_and_permissions_from_one_response(monkeypatch):
    response(monkeypatch, {'userID': 42, 'access': {'user': {'library': True, 'write': True}}})
    assert connection.connect('zotero', ' fixture-key \n') == {
        'ZOTERO_API_KEY': 'fixture-key', 'ZOTERO_LIBRARY_ID': '42', 'ZOTERO_LIBRARY_TYPE': 'user'}


@pytest.mark.parametrize('payload', [{}, [], {'userID': True}, {'userID': 42, 'access': {'user': {'library': True}}}])
def test_incomplete_account_cannot_be_saved(monkeypatch, payload):
    response(monkeypatch, payload)
    with pytest.raises(ValueError):
        connection.connect('zotero', 'fixture-key')


def test_group_uses_group_access_not_personal_id(monkeypatch):
    response(monkeypatch, {'userID': 42, 'access': {'groups': {'99': {'library': True, 'write': True}}}})
    result = connection.connect('zotero', 'fixture-key', group=True, group_id='99')
    assert result['ZOTERO_LIBRARY_ID'] == '99' and result['ZOTERO_LIBRARY_TYPE'] == 'group'
    with pytest.raises(ValueError, match='读写权限'):
        connection.connect('zotero', 'fixture-key', group=True, group_id='100')


@pytest.mark.parametrize('bad', ['', '\x16', 'fixture\x16key', '[redacted]', 'key\nother'])
def test_bad_input_never_reaches_network(monkeypatch, bad):
    monkeypatch.setattr(connection.urllib.request, 'build_opener', lambda *a: pytest.fail('network used'))
    with pytest.raises(ValueError):
        connection.connect('zotero', bad)


@pytest.mark.parametrize('code,hint', [(401, '未接受'), (403, '未接受'), (429, '请求次数'), (503, '暂时不可用')])
def test_http_error_hints_do_not_expose_response_or_key(monkeypatch, code, hint):
    class Opener:
        def open(self, *a, **k):
            raise urllib.error.HTTPError('https://api.zotero.org', code, 'fixture-secret', {}, StringIO('private response'))
    monkeypatch.setattr(connection.urllib.request, 'build_opener', lambda *a: Opener())
    with pytest.raises(ValueError, match=hint) as caught:
        connection.connect('zotero', 'fixture-secret')
    assert 'fixture-secret' not in str(caught.value)


def test_mineru_failure_does_not_write(monkeypatch):
    monkeypatch.setattr(connection.capability, 'probe_mineru', lambda key: {'valid': False, 'code': None})
    with pytest.raises(ValueError, match='检查网络'):
        connection.connect('mineru', 'fixture-key')


def test_save_account_atomically_preserves_unrelated_settings(tmp_path, monkeypatch):
    path = tmp_path / 'env'
    path.write_text('UNRELATED=保留\nZOTERO_API_KEY=old\nZOTERO_LIBRARY_ID=1\n', encoding='utf-8')
    monkeypatch.setattr(configure.credentials, 'SKILL_ENV_FILE', path)
    configure.save_many({'ZOTERO_API_KEY': 'new', 'ZOTERO_LIBRARY_ID': '2', 'ZOTERO_LIBRARY_TYPE': 'user'})
    assert path.read_text(encoding='utf-8') == 'UNRELATED=保留\nZOTERO_API_KEY=new\nZOTERO_LIBRARY_ID=2\nZOTERO_LIBRARY_TYPE=user\n'


@pytest.mark.skipif(os.name != 'nt', reason='Windows ACLs')
def test_acl_failure_preserves_old_account(tmp_path, monkeypatch):
    path = tmp_path / 'env'
    path.write_text('ZOTERO_API_KEY=old\nZOTERO_LIBRARY_ID=1\n', encoding='utf-8')
    before = path.read_bytes()
    monkeypatch.setattr(configure.credentials, 'SKILL_ENV_FILE', path)
    def fail(*a, **k):
        raise subprocess.CalledProcessError(1, 'protect-config')
    monkeypatch.setattr(configure.subprocess, 'run', fail)
    with pytest.raises(subprocess.CalledProcessError):
        configure.save_many({'ZOTERO_API_KEY': 'new', 'ZOTERO_LIBRARY_ID': '2'})
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(os.name != 'nt', reason='Windows browser association')
def test_browser_uses_windows_url_association(monkeypatch):
    opened = []
    monkeypatch.setattr(connection.os, 'startfile', opened.append)
    connection.open_page('https://www.zotero.org/settings/keys')
    assert opened == ['https://www.zotero.org/settings/keys']
    with pytest.raises(ValueError):
        connection.open_page('file:///arbitrary')


@pytest.mark.parametrize('service,value,setting', [
    ('semantic_scholar', 'fixture-key', 'SEMANTIC_SCHOLAR_API_KEY'),
    ('openalex', 'fixture-key', 'OPENALEX_API_KEY'),
    ('crossref', 'name@example.org', 'CROSSREF_MAILTO'),
    ('unpaywall', 'name@example.org', 'UNPAYWALL_EMAIL'),
])
def test_optional_settings_use_runtime_credential_names(service, value, setting):
    assert connection.extra_settings(service, value) == {setting: value}


@pytest.mark.parametrize('service,value', [('kimi', 'key'), ('crossref', 'no-email'),
                                          ('unpaywall', 'a@b c.org'), ('openalex', '\x16'),
                                          ('semantic_scholar', 'bad\nkey')])
def test_optional_bad_input_rejected(service, value):
    with pytest.raises(ValueError):
        connection.extra_settings(service, value)


def test_kimi_not_enabled_until_extension_is_connected(tmp_path, monkeypatch):
    binary = tmp_path / 'kimi-webbridge.exe'
    binary.touch()
    monkeypatch.setattr(connection.capability, 'KIMI_BINARY', binary)
    monkeypatch.setattr(connection.capability, 'probe_kimi', lambda *a: {'running': True, 'extension_connected': False})
    with pytest.raises(ValueError, match='扩展尚未连接'):
        connection.enable_kimi()
    monkeypatch.setattr(connection.capability, 'probe_kimi', lambda *a: {'running': True, 'extension_connected': True})
    assert connection.enable_kimi() == {'SETUP_BROWSER': '1'}


def test_kimi_starts_only_installed_service_and_rechecks(tmp_path, monkeypatch):
    binary = tmp_path / 'kimi-webbridge.exe'
    monkeypatch.setattr(connection.capability, 'KIMI_BINARY', binary)
    with pytest.raises(ValueError, match='尚未找到'):
        connection.enable_kimi()
    binary.touch()
    states = iter([{'running': False}, {'running': True, 'extension_connected': True}])
    monkeypatch.setattr(connection.capability, 'probe_kimi', lambda *a: next(states))
    calls = []
    def run(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(connection.subprocess, 'run', run)
    assert connection.enable_kimi() == {'SETUP_BROWSER': '1'}
    assert calls == [[str(binary), 'start']]


def test_unix_private_save_never_calls_powershell(tmp_path, monkeypatch):
    from types import SimpleNamespace
    path = tmp_path / 'env'
    monkeypatch.setattr(configure.credentials, 'SKILL_ENV_FILE', path)
    monkeypatch.setattr(configure, 'os', SimpleNamespace(name='posix', fdopen=os.fdopen, replace=os.replace))
    monkeypatch.setattr(configure.subprocess, 'run', lambda *a, **kw: pytest.fail('Unix save launched PowerShell'))
    configure.save_many({'SEMANTIC_SCHOLAR_API_KEY': 'fixture'})
    assert path.read_text() == 'SEMANTIC_SCHOLAR_API_KEY=fixture\n'


def test_kimi_status_uses_platform_executable_and_parses_connection(tmp_path, monkeypatch):
    expected_name = 'kimi-webbridge.exe' if os.name == 'nt' else 'kimi-webbridge'
    assert connection.capability.KIMI_BINARY.name == expected_name
    binary = tmp_path / expected_name
    binary.touch()
    def run(args, **kw):
        assert args == [str(binary), 'status']
        return subprocess.CompletedProcess(args, 0, '{"running": true, "extension_connected": true}', '')
    monkeypatch.setattr(connection.capability.subprocess, 'run', run)
    state = connection.capability.probe_kimi(binary)
    assert state['running'] and state['extension_connected']
