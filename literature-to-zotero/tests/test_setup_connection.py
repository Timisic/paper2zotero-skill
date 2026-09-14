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
