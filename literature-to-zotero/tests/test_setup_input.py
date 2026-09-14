"""Real Bash input regressions and safe, offline identity errors."""
from io import StringIO
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import configure
import verify


def bash_executable():
    bash = shutil.which('bash')
    if os.name == 'nt':
        git = shutil.which('git.exe')
        bash = str(Path(git).parent.parent / 'bin/bash.exe') if git else None
    if not bash:
        pytest.skip('Bash required')
    return bash


def prompt(tmp_path, replies, existing=''):
    bash = bash_executable()
    # Execute the real template and setup helper without starting account setup.
    library = (SCRIPTS / 'setup-wizard.sh').read_text(encoding='utf-8').split('TOTAL_STAGES=4\n')[0]
    script = tmp_path / 'input.sh'
    script.write_text(library + '\n' + (SCRIPTS / 'setup-input.sh').read_text(encoding='utf-8') + '''
WINDOWS=1
ask_authorization TEST_KEY '授权码：'
printf '%s' "$TEST_KEY" > result
''', encoding='utf-8', newline='\n')
    (tmp_path / '.env').write_text('TEST_KEY=' + existing + '\n', encoding='utf-8')
    env = dict(os.environ)
    env.pop('ENV_FILE', None)
    result = subprocess.run([bash, str(script)], input=replies, cwd=tmp_path,
                            capture_output=True, env=env, timeout=10)
    output = result.stdout.decode('utf-8') + result.stderr.decode('utf-8')
    value = (tmp_path / 'result').read_bytes() if (tmp_path / 'result').exists() else None
    return result.returncode, output, value


def test_ctrl_v_is_rejected_then_paste_succeeds_without_exposing_key(tmp_path):
    code, output, value = prompt(tmp_path, b'\x16\nfixture-private-key\n')
    assert code == 0
    assert value == b'fixture-private-key'
    assert '这次输入未保存' in output
    assert '已收到授权码' in output and '******' in output
    assert 'fixture-private-key' not in output


def test_old_control_character_is_not_kept_on_enter(tmp_path):
    code, output, value = prompt(tmp_path, b'\n', existing='\x16')
    assert code == 0 and value == b''
    assert '之前的输入没有正确粘贴' in output and '已跳过' in output


def test_valid_existing_key_is_kept_without_echo(tmp_path):
    code, output, value = prompt(tmp_path, b'\n', existing='fixture-existing-key')
    assert code == 0 and value == b'fixture-existing-key'
    assert '已保留已有授权' in output and 'fixture-existing-key' not in output


def test_backspace_and_surrounding_spaces(tmp_path):
    code, _, value = prompt(tmp_path, b'x\x7f  fixture-key-x\x08  \n')
    assert code == 0 and value == b'fixture-key-'


def test_eof_pauses_instead_of_accepting_partial_key(tmp_path):
    code, output, value = prompt(tmp_path, b'partial-secret')
    assert code == 130 and value is None
    assert '配置已暂停' in output and 'partial-secret' not in output


@pytest.mark.parametrize('bad', ['\x16', 'valid\x1b[200~', 'tab\tkey', 'key\nother=value', 'key\r', 'key\x7f', 'key\x00'])
def test_writer_rejects_controls_without_overwriting_existing(tmp_path, monkeypatch, bad):
    config = tmp_path / 'env'
    config.write_text('MINERU_TOKEN=old\n', encoding='utf-8')
    monkeypatch.setattr(configure.credentials, 'SKILL_ENV_FILE', config)
    with pytest.raises(ValueError):
        configure.save('MINERU_TOKEN', bad)
    assert config.read_text(encoding='utf-8') == 'MINERU_TOKEN=old\n'


@pytest.mark.parametrize('error, hint', [
    (urllib.error.HTTPError('https://api.zotero.org/keys/current', 403, 'fixture-secret', {}, None), '未接受'),
    (urllib.error.HTTPError('https://api.zotero.org/keys/current', 429, 'fixture-secret', {}, None), '请求次数'),
    (urllib.error.URLError('fixture-secret'), '检查网络'),
    (TimeoutError('fixture-secret'), '检查网络'),
], ids=['authorization-rejected', 'rate-limited', 'network-error', 'timeout'])
def test_identity_failure_is_actionable_and_secret_free(monkeypatch, capsys, error, hint):
    monkeypatch.setenv('ZOTERO_API_KEY', 'fixture-secret')
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(verify.urllib.request, 'urlopen', fail)
    assert verify.cmd_self_id() == 1
    result = capsys.readouterr()
    assert result.out == '' and hint in result.err
    assert 'fixture-secret' not in result.err


@pytest.mark.parametrize('payload', ['{}', '[]', '{"userID": null}', '{"userID": true}', '{"userID": -1}', '{"userID": "１２３"}'])
def test_missing_identity_is_not_success(monkeypatch, capsys, payload):
    monkeypatch.setenv('ZOTERO_API_KEY', 'fixture-secret')
    monkeypatch.setattr(verify.urllib.request, 'urlopen', lambda *a, **k: StringIO(payload))
    assert verify.cmd_self_id() == 1
    result = capsys.readouterr()
    assert result.out == '' and '没有返回个人文库信息' in result.err


def test_identity_success_prints_only_numeric_id(monkeypatch, capsys):
    monkeypatch.setenv('ZOTERO_API_KEY', 'fixture-secret')
    monkeypatch.setattr(verify.urllib.request, 'urlopen', lambda *a, **k: StringIO('{"userID": 12345}'))
    assert verify.cmd_self_id() == 0
    result = capsys.readouterr()
    assert result.out == '12345\n' and result.err == ''


def test_control_key_never_reaches_network(monkeypatch, capsys):
    monkeypatch.setenv('ZOTERO_API_KEY', '\x16')
    monkeypatch.setattr(verify.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('invalid key sent'))
    assert verify.cmd_self_id() == 1
    result = capsys.readouterr()
    assert not result.out and '重新复制' in result.err


@pytest.mark.parametrize('service', ['zotero', 'mineru'])
@pytest.mark.parametrize('retry', [True, False])
def test_real_stage_retries_or_defers_without_manual_personal_id(tmp_path, service, retry):
    wizard = (SCRIPTS / 'setup-wizard.sh').read_text(encoding='utf-8')
    library = wizard.split('TOTAL_STAGES=4\n')[0]
    first = wizard.index('stage "连接 Zotero：')
    second = wizard.index('stage "启用全文阅读：')
    third = wizard.index('if [[ "$ADVANCED" == 1 ]]; then\nstage "更多设置')
    stage = wizard[first:second] if service == 'zotero' else wizard[second:third]
    stub = '''
WINDOWS=1
DEMO=0
GROUP_LIBRARY=0
SKILL_DIR=.
PYTHON_BIN=identity_fixture
open_url() { :; }
existing_ok() { return 1; }
pause() { :; }
persist() { write_env "$1" "$2" >/dev/null; printf '%s\\n' "$1" >> persisted; export "$1=$2"; }
identity_fixture() {
  if [[ ! -f attempted ]]; then
    touch attempted
    printf '连接失败，请检查网络后重试\\n' >&2
    return 1
  fi
  printf '12345\\n'
}
verify_step() {
  if [[ "$1" == mineru && ! -f attempted ]]; then touch attempted; return 1; fi
  printf 'verified\\n'
}
'''
    script = tmp_path / 'stage.sh'
    script.write_text(library + '\n' + (SCRIPTS / 'setup-input.sh').read_text(encoding='utf-8')
                      + stub + stage, encoding='utf-8', newline='\n')
    replies = b'fixture-private-key\n' + (b'1\n\n' if retry else b'2\n')
    env = dict(os.environ)
    for key in ('ENV_FILE', 'ZOTERO_API_KEY', 'ZOTERO_LIBRARY_ID', 'ZOTERO_LIBRARY_TYPE', 'MINERU_TOKEN'):
        env.pop(key, None)
    result = subprocess.run([bash_executable(), str(script)], input=replies, cwd=tmp_path,
                            capture_output=True, env=env, timeout=10)
    output = (result.stdout + result.stderr).decode('utf-8')
    assert result.returncode == 0, output
    assert 'fixture-private-key' not in output
    assert '填写要保存到的群组文库 ID' not in output
    assert ('verified' in output) == retry
    if service == 'zotero':
        assert '连接失败，请检查网络后重试' in output
        assert ('ZOTERO_LIBRARY_ID' in (tmp_path / 'persisted').read_text()) == retry
