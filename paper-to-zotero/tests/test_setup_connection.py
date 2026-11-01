"""Native account validation and all-or-nothing private saves."""
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.parse
from http_fixture import server

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import configure
import setup_connection as connection


@pytest.mark.parametrize('status,hint', [(200, ''), (401, '未接受'), (429, '额度'), (503, '网络')])
def test_openalex_connection_checks_candidate_key_before_replacing_saved_key(tmp_path, monkeypatch, capsys, status, hint):
    path = tmp_path / 'env'
    path.write_text('OPENALEX_API_KEY=old-key\nUNRELATED=keep\n')
    monkeypatch.setattr(configure.credentials, 'SKILL_ENV_FILE', path)
    monkeypatch.setenv('OPENALEX_API_KEY', 'inherited-old-key')
    calls = []
    def reply(method, url, body, headers):
        calls.append(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query))
        return status, {'results': []} if status == 200 else {'error': 'fixture-secret'}, {}
    before = path.read_bytes()
    with server(reply) as base:
        monkeypatch.setenv('LITERATURE_SOURCE_BASES', json.dumps({'openalex': base}))
        monkeypatch.setattr(sys, 'argv', ['configure.py', '--connect', 'openalex'])
        monkeypatch.setattr(sys, 'stdin', StringIO('fixture-secret'))
        if status == 200:
            assert configure.main() == 0
            assert configure.credentials.source_setting('openalex') == 'fixture-secret'
            assert configure.credentials._skill_env()['UNRELATED'] == 'keep'
        else:
            with pytest.raises(ValueError, match=hint) as caught:
                configure.main()
            assert 'fixture-secret' not in str(caught.value)
            assert path.read_bytes() == before
    assert len(calls) == 1 and calls[0]['api_key'] == ['fixture-secret']
    output = capsys.readouterr()
    assert 'fixture-secret' not in output.out + output.err


def test_setup_requires_openalex_even_when_other_search_sources_work(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(configure.credentials, 'SKILL_ENV_FILE', tmp_path / 'absent')
    monkeypatch.delenv('OPENALEX_API_KEY', raising=False)
    monkeypatch.setenv('SEMANTIC_SCHOLAR_API_KEY', 'other-key')
    _stub_check_surroundings(monkeypatch)
    import sources
    monkeypatch.setattr(sources.Sources, 'search', lambda *a, **k: pytest.fail('missing key must not use anonymous/fallback search'))
    assert configure.check(as_json=True) == 1
    result = json.loads(capsys.readouterr().out)
    missing = [row for row in result['items'] if not row['ok']]
    assert len(missing) == 1
    assert missing[0]['name'] == '论文检索（OpenAlex）'
    assert missing[0]['sources'] == {'OpenAlex': 'not_configured'}
    assert missing[0]['action'] == (
        '当前检索后端需要 OpenAlex 授权码。在更多配置里连接 OpenAlex，或删除 SEARCH_BACKEND 恢复 scansci。')


def test_openalex_setup_allows_a_slow_successful_response(monkeypatch):
    def reply(*args):
        time.sleep(3.2)  # A normal cross-region response exceeded the old 3s socket timeout.
        return 200, {'results': []}, {}
    with server(reply) as base:
        monkeypatch.setenv('LITERATURE_SOURCE_BASES', json.dumps({'openalex': base}))
        assert connection.connect('openalex', 'fixture-key') == {'OPENALEX_API_KEY': 'fixture-key'}


def test_terminal_connection_failure_preserves_account_then_saves_verified_identity(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'env'
    path.write_text('ZOTERO_API_KEY=old\nZOTERO_LIBRARY_ID=1\nUNRELATED=保留\n', encoding='utf-8')
    monkeypatch.setattr(configure.credentials, 'SKILL_ENV_FILE', path)
    monkeypatch.setattr(sys, 'argv', ['configure.py', '--connect', 'zotero'])
    monkeypatch.setattr(sys, 'stdin', StringIO('fixture-new-key'))
    response(monkeypatch, {'userID': 42, 'access': {'user': {'library': True}}})
    before = path.read_bytes()
    with pytest.raises(ValueError, match='读写权限'):
        configure.main()
    assert path.read_bytes() == before
    monkeypatch.setattr(sys, 'stdin', StringIO('fixture-new-key'))
    response(monkeypatch, {'userID': 42, 'access': {'user': {'library': True, 'write': True}}})
    assert configure.main() == 0
    assert configure.credentials._skill_env()['ZOTERO_LIBRARY_ID'] == '42'
    assert configure.credentials._skill_env()['UNRELATED'] == '保留'
    assert 'fixture-new-key' not in capsys.readouterr().out


def response(monkeypatch, payload):
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == 'https://api.zotero.org/keys/current'
            return StringIO(json.dumps(payload))
    monkeypatch.setattr(connection.capability.urllib.request, 'build_opener', lambda *a: Opener())


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


def test_account_repair_keeps_existing_group_unless_personal_is_explicit(tmp_path, monkeypatch):
    path = tmp_path / 'env'
    path.write_text('ZOTERO_API_KEY=old\nZOTERO_LIBRARY_ID=99\nZOTERO_LIBRARY_TYPE=group\n')
    monkeypatch.setattr(configure.credentials, 'SKILL_ENV_FILE', path)
    response(monkeypatch, {'userID': 42, 'access': {'user': {'library': True, 'write': True},
                                                   'groups': {'99': {'library': True, 'write': True}}}})
    assert connection.connect('zotero', 'fixture-key')['ZOTERO_LIBRARY_ID'] == '99'
    assert connection.connect('zotero', 'fixture-key', group=False)['ZOTERO_LIBRARY_ID'] == '42'


@pytest.mark.parametrize('bad', ['', '\x16', 'fixture\x16key', '[redacted]', 'key\nother'])
def test_bad_input_never_reaches_network(monkeypatch, bad):
    monkeypatch.setattr(connection.capability.urllib.request, 'build_opener', lambda *a: pytest.fail('network used'))
    with pytest.raises(ValueError):
        connection.connect('zotero', bad)


@pytest.mark.parametrize('code,hint', [(401, '未接受'), (403, '未接受'), (429, '请求次数'), (503, '暂时不可用')])
def test_http_error_hints_do_not_expose_response_or_key(monkeypatch, code, hint):
    class Opener:
        def open(self, *a, **k):
            raise urllib.error.HTTPError('https://api.zotero.org', code, 'fixture-secret', {}, StringIO('private response'))
    monkeypatch.setattr(connection.capability.urllib.request, 'build_opener', lambda *a: Opener())
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
    assert set(tmp_path.iterdir()) == {path, path.with_suffix('.lock')}


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


def test_kimi_accepts_existing_path_install_for_setup_and_preflight(tmp_path, monkeypatch):
    binary = tmp_path / 'kimi-webbridge'
    binary.touch()
    monkeypatch.setattr(connection.capability, 'KIMI_BINARY', tmp_path / 'missing')
    monkeypatch.setattr(connection.capability.shutil, 'which', lambda _: str(binary))
    calls = []
    def run(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, '{"running": true, "extension_connected": true}', '')
    monkeypatch.setattr(connection.capability.subprocess, 'run', run)
    assert connection.enable_kimi() == {'SETUP_BROWSER': '1'}
    assert connection.capability.probe_kimi()['installed']
    assert calls == [[str(binary), 'status'], [str(binary), 'status']]


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
    import runtime_io
    path = tmp_path / 'env'
    monkeypatch.setattr(configure.credentials, 'SKILL_ENV_FILE', path)
    # Exercise the private writer's Unix branch; the host's real lock stays native.
    monkeypatch.setattr(configure, 'private_text', lambda path, text: runtime_io.private_text(path, text))
    original_lock = configure.file_lock
    from contextlib import contextmanager
    @contextmanager
    def lock(*args, **kwargs):
        with original_lock(*args, **kwargs):
            with monkeypatch.context() as patch:
                patch.setattr(runtime_io, 'os', SimpleNamespace(name='posix', fdopen=os.fdopen))
                yield
    monkeypatch.setattr(configure, 'file_lock', lock)
    monkeypatch.setattr(configure.subprocess, 'run', lambda *a, **kw: pytest.fail('Unix save launched PowerShell'))
    configure.save_many({'SEMANTIC_SCHOLAR_API_KEY': 'fixture'})
    assert path.read_text() == 'SEMANTIC_SCHOLAR_API_KEY=fixture\n'


def _stub_check_surroundings(monkeypatch, *, write=True, read=False, search='http', conversion=True):
    """Keep Python, PDF, skill links, and Desktop off the network."""
    monkeypatch.setattr(configure.agent_installation, 'installation_ok', lambda _: True)
    monkeypatch.setattr(configure.agent_installation, 'installed_paths', lambda **_: ['/fixture'])
    real_run = subprocess.run

    def run(command, **kwargs):
        if command and command[0] == 'pdftotext':
            return subprocess.CompletedProcess(command, 0, '', '')
        return real_run(command, **kwargs)

    monkeypatch.setattr(configure.subprocess, 'run', run)
    monkeypatch.setattr(configure.capability, 'probe_zotero_local_write', lambda *a, **k: write)
    monkeypatch.setattr(configure.capability, 'probe_zotero_local', lambda *a, **k: read)
    if conversion:
        import mineru_parse
        monkeypatch.setattr(mineru_parse, 'converter_plan', lambda live=True: {
            'selected': 'markitdown', 'api_base': None,
            'markitdown_install': "pip install 'markitdown[pdf]'"})
    if search == 'scansci':
        import scansci_retrieval
        monkeypatch.setattr(configure.scansci_retrieval, 'library_ready', lambda: scansci_retrieval.LibraryStatus(
            ok=True, detail='scansci-pdf 1.19.0', install=scansci_retrieval.INSTALL_LINE))


def _product_env(monkeypatch, tmp_path):
    env = tmp_path / 'env'
    monkeypatch.setattr(configure.credentials, 'SKILL_ENV_FILE', env)
    for name in ('SEARCH_BACKEND', 'MINERU_API_BASE', 'MINERU_ENDPOINT', 'MINERU_TOKEN',
                 'OPENALEX_API_KEY', 'SETUP_DESKTOP', 'SETUP_BROWSER', 'ZOTERO_API_KEY',
                 'ZOTERO_LIBRARY_TYPE', 'ZOTERO_LIBRARY_ID'):
        monkeypatch.delenv(name, raising=False)
    return env


def test_product_default_check_passes_without_openalex_or_a_cloud_token(tmp_path, monkeypatch, capsys):
    import mineru_parse
    env = _product_env(monkeypatch, tmp_path)
    before = env.read_bytes() if env.exists() else None
    seen = []

    def health(base, timeout=3):
        seen.append(base)
        return {'ok': False, 'detail': 'stub'}

    monkeypatch.setattr(mineru_parse, 'tasks_health', health)
    monkeypatch.setattr(mineru_parse, 'markitdown_available', lambda: True)
    _stub_check_surroundings(monkeypatch, search='scansci', conversion=False)
    assert configure.check(as_json=True) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['ready'] is True
    assert [item['name'] for item in report['items']] == [
        '运行工具', 'PDF 文本工具', '连接 AI 助手', '论文检索（ScanSci）', '全文转换',
        'Zotero Desktop · 本机附件']
    assert report['items'][3]['detail'] == 'scansci-pdf 1.19.0'
    assert report['items'][3]['action'] == ''
    assert 'selected=markitdown' in report['items'][4]['detail']
    assert report['items'][4]['action'] == ''
    assert report['items'][5] == {
        'name': 'Zotero Desktop · 本机附件', 'ok': True, 'detail': '127.0.0.1:23119', 'action': ''}
    assert all('OpenAlex' not in item['name'] for item in report['items'])
    assert seen == [configure.credentials.LAB_MINERU_API_BASE]
    assert 'MINERU_API_BASE' not in os.environ
    assert (env.read_bytes() if env.exists() else None) == before


def test_closed_desktop_fails_even_with_a_saved_web_api_key(tmp_path, monkeypatch, capsys):
    env = _product_env(monkeypatch, tmp_path)
    env.write_text('ZOTERO_API_KEY=fixture-key\n', encoding='utf-8')
    before = env.read_bytes()
    _stub_check_surroundings(monkeypatch, write=False, read=False, search='scansci')
    assert configure.check(as_json=True) == 1
    report = json.loads(capsys.readouterr().out)
    missing = [row for row in report['items'] if not row['ok']]
    assert [row['name'] for row in missing] == ['Zotero Desktop · 本机附件']
    assert missing[0]['detail'] == configure.capability.zotero_local(False)['detail']
    assert missing[0]['action'] == configure.capability.GUIDE['zotero_local']['do']
    assert all(row['name'] != '保存到 Zotero' for row in report['items'])
    assert env.read_bytes() == before
    assert configure.check(as_json=False) == 1
    text = capsys.readouterr().out
    assert '待完成 Zotero Desktop · 本机附件' in text
    assert '下一步：' + configure.capability.GUIDE['zotero_local']['do'] in text


def test_readable_desktop_without_a_server_id_is_not_a_write_target(tmp_path, monkeypatch, capsys):
    env = _product_env(monkeypatch, tmp_path)
    env.write_text('SETUP_DESKTOP=1\n', encoding='utf-8')
    _stub_check_surroundings(monkeypatch, write=False, read=True, search='scansci')
    assert configure.check(as_json=True) == 1
    report = json.loads(capsys.readouterr().out)
    missing = [row for row in report['items'] if not row['ok']]
    assert len(missing) == 1
    assert missing[0]['detail'] == '本地 API 没有返回 Zotero-Server-ID，不能作为写入目标。'
    assert missing[0]['action'] == configure.capability.GUIDE['zotero_local']['do']


def test_group_check_still_requires_the_web_api_row(tmp_path, monkeypatch, capsys):
    env = _product_env(monkeypatch, tmp_path)
    _stub_check_surroundings(monkeypatch, search='scansci')
    assert configure.check(as_json=True, group=True) == 1
    report = json.loads(capsys.readouterr().out)
    missing = [row['name'] for row in report['items'] if not row['ok']]
    assert missing == ['保存到 Zotero']
    capsys.readouterr()
    env.write_text('ZOTERO_LIBRARY_TYPE=group\n', encoding='utf-8')
    assert configure.check(as_json=True) == 1
    report = json.loads(capsys.readouterr().out)
    assert [row['name'] for row in report['items'] if not row['ok']] == ['保存到 Zotero']


def test_unknown_basic_service_has_no_check_row(monkeypatch):
    _stub_check_surroundings(monkeypatch)
    monkeypatch.setattr(connection, 'BASIC_SERVICES', ('openalex',))
    with pytest.raises(ValueError, match='basic service has no check: openalex'):
        configure.check(as_json=True)


def test_wizard_extras_hide_openalex_until_that_backend_is_selected(monkeypatch):
    assert set(connection.BASIC_SERVICES).isdisjoint(connection.CONNECT_SERVICES)
    monkeypatch.setattr(connection.credentials, 'search_backend', lambda: 'scansci')
    assert connection.wizard_extras() == (
        'zotero', 'mineru', 'kimi', 'semantic_scholar', 'crossref', 'unpaywall')
    monkeypatch.setattr(connection.credentials, 'search_backend', lambda: 'http')
    assert connection.wizard_extras()[:2] == ('zotero', 'openalex')
    assert 'desktop' not in connection.wizard_extras()


def test_accept_openalex_probes_and_extra_settings_rejects_it(monkeypatch):
    with pytest.raises(ValueError):
        connection.extra_settings('openalex', 'fixture-key')
    seen = []

    def probe(key=None):
        seen.append(key)
        return {'ok': True, 'detail': 'ok', 'sources': {'OpenAlex': 'ok'}}

    monkeypatch.setattr(connection.capability, 'probe_discovery_search', probe)
    assert connection.accept('openalex', 'fixture-key') == {'OPENALEX_API_KEY': 'fixture-key'}
    assert seen == ['fixture-key']


def test_existing_key_is_empty_for_any_service_other_than_the_three_accounts(monkeypatch):
    monkeypatch.setattr(connection.credentials, 'mineru_token', lambda: 'secret-token')
    assert connection.existing_key('desktop') == ''
    assert connection.existing_key('kimi') == ''
    assert connection.existing_key('semantic_scholar') == ''


def test_enable_desktop_returns_the_flag_without_reading_sync_prefs(monkeypatch):
    monkeypatch.setattr(connection.capability, 'probe_zotero_local_write', lambda *a, **k: True)
    monkeypatch.setattr(connection.capability, 'zotero_prefs', lambda *a, **k: pytest.fail('sync prefs'))
    assert connection.enable_desktop() == {'SETUP_DESKTOP': '1'}
    monkeypatch.setattr(connection.capability, 'probe_zotero_local_write', lambda *a, **k: False)
    with pytest.raises(ValueError, match='Zotero-Server-ID'):
        connection.enable_desktop()


def test_verify_mineru_reports_the_conversion_hop_without_writing_env(tmp_path, monkeypatch, capsys):
    import mineru_parse
    import verify
    env = tmp_path / 'missing-env'
    monkeypatch.setattr(verify.credentials, 'SKILL_ENV_FILE', env)
    monkeypatch.delenv('MINERU_API_BASE', raising=False)
    monkeypatch.delenv('MINERU_ENDPOINT', raising=False)
    monkeypatch.delenv('MINERU_TOKEN', raising=False)
    monkeypatch.setattr(mineru_parse, 'tasks_health', lambda *a, **k: {'ok': False, 'detail': 'stub'})
    monkeypatch.setattr(mineru_parse, 'markitdown_available', lambda: True)
    assert verify.cmd_mineru() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['ok'] is True
    assert 'selected=markitdown' in payload['detail']
    monkeypatch.setattr(mineru_parse, 'markitdown_available', lambda: False)
    assert verify.cmd_mineru() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload['ok'] is False
    assert "pip install 'markitdown[pdf]'" in payload['detail']
    assert not env.exists()


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


def test_ensure_default_tools_skips_pip_when_both_are_present(monkeypatch, tmp_path):
    import mineru_parse
    import scansci_retrieval
    env = tmp_path / 'env'
    env.write_bytes(b'KEEP=1\n')
    monkeypatch.setattr(connection.credentials, 'SKILL_ENV_FILE', env)
    monkeypatch.setattr(scansci_retrieval, 'library_ready',
                        lambda: scansci_retrieval.LibraryStatus(True, 'scansci-pdf', scansci_retrieval.INSTALL_LINE))
    monkeypatch.setattr(mineru_parse, 'markitdown_available', lambda: True)
    monkeypatch.setattr(connection.subprocess, 'run', lambda *a, **k: pytest.fail('pip'))
    connection.ensure_default_tools()
    connection.ensure_default_tools()
    assert env.read_bytes() == b'KEEP=1\n'


def test_ensure_default_tools_installs_the_pinned_packages(monkeypatch, tmp_path):
    import mineru_parse
    import scansci_retrieval
    env = tmp_path / 'env'
    env.write_bytes(b'KEEP=1\n')
    monkeypatch.setattr(connection.credentials, 'SKILL_ENV_FILE', env)
    monkeypatch.setattr(scansci_retrieval, 'library_ready',
                        lambda: scansci_retrieval.LibraryStatus(False, 'missing', scansci_retrieval.INSTALL_LINE))
    monkeypatch.setattr(mineru_parse, 'markitdown_available', lambda: True)
    seen = []

    def run(command, **kwargs):
        seen.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(connection.subprocess, 'run', run)
    connection.ensure_default_tools()
    assert seen[0][0] == [sys.executable, '-m', 'pip', 'install',
                          f'scansci-pdf=={scansci_retrieval.PIN}', 'markitdown[pdf]']
    assert seen[0][1]['capture_output'] is True
    assert env.read_bytes() == b'KEEP=1\n'


def test_ensure_default_tools_failure_includes_the_install_line(monkeypatch):
    import mineru_parse
    import scansci_retrieval
    monkeypatch.setattr(scansci_retrieval, 'library_ready',
                        lambda: scansci_retrieval.LibraryStatus(False, 'missing', scansci_retrieval.INSTALL_LINE))
    monkeypatch.setattr(mineru_parse, 'markitdown_available', lambda: False)
    monkeypatch.setattr(connection.subprocess, 'run',
                        lambda *a, **k: subprocess.CompletedProcess(a[0], 1))
    with pytest.raises(ValueError) as caught:
        connection.ensure_default_tools()
    assert scansci_retrieval.INSTALL_LINE in str(caught.value)
    monkeypatch.setattr(connection.subprocess, 'run', lambda *a, **k: (_ for _ in ()).throw(OSError('missing')))
    with pytest.raises(ValueError) as caught:
        connection.ensure_default_tools()
    assert scansci_retrieval.INSTALL_LINE in str(caught.value)


def test_prepare_installs_default_tools_only_after_pdftotext_works(monkeypatch, tmp_path):
    tool = tmp_path / 'pdftotext'
    tool.write_text('#!/bin/sh\n', encoding='utf-8')
    monkeypatch.delenv('PAPER2ZOTERO_PDF_BIN', raising=False)
    monkeypatch.setattr(connection.Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(connection.shutil, 'which', lambda name: str(tool) if name == 'pdftotext' else None)
    seen = []

    def run(command, **kwargs):
        seen.append(list(command))
        return subprocess.CompletedProcess(command, 0)

    def tools():
        seen.append('ensure_default_tools')

    def import_module(name):
        seen.append(name)
        return type('Install', (), {'install': staticmethod(lambda agent: seen.append(('skill', agent)))})()

    monkeypatch.setattr(connection.subprocess, 'run', run)
    monkeypatch.setattr(connection, 'ensure_default_tools', tools)
    monkeypatch.setattr(connection.importlib, 'import_module', import_module)
    connection.prepare('codex')
    assert seen[0][-1] == '-v'
    assert seen[1] == 'ensure_default_tools'
    assert seen[2:] == ['install', ('skill', 'codex')]
    seen.clear()
    monkeypatch.setattr(connection.subprocess, 'run',
                        lambda command, **kwargs: seen.append('pdftotext') or subprocess.CompletedProcess(command, 1))
    with pytest.raises(ValueError, match='PDF 工具无法运行'):
        connection.prepare('codex')
    assert seen == ['pdftotext']
