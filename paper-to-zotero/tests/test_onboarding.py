"""Exercise the distributed onboarding interface with an isolated user profile."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'paper-to-zotero/scripts'
sys.path.insert(0, str(SCRIPTS))
import agent_installation
import configure
from test_cli import assert_private_file


def environment(home):
    home.mkdir(exist_ok=True)
    return {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home),
            'CODEX_HOME': str(home / '.codex'), 'CLAUDE_CONFIG_DIR': str(home / '.claude'),
            'PAPER2ZOTERO_AGENT': 'auto', 'PYTHON_BIN': sys.executable}


@pytest.mark.parametrize('agent,folder', [('claude-code', '.claude'), ('codex', '.codex'), ('pi', '.pi/agent')])
def test_targeted_install_survives_other_agent_conflict(tmp_path, agent, folder):
    env = environment(tmp_path)
    other = '.codex' if agent != 'codex' else '.claude'
    conflict = tmp_path / other / 'skills/paper-to-zotero'
    conflict.mkdir(parents=True)
    (conflict / 'my-note').write_text('keep')
    for _ in range(2):
        result = subprocess.run([sys.executable, str(SCRIPTS / 'install.py'), '--agent', agent],
                                env=env, capture_output=True, text=True, encoding='utf-8')
        assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / folder / 'skills/paper-to-zotero/SKILL.md').is_file()
    assert (conflict / 'my-note').read_text() == 'keep'
    # The selected runtime must work from an unrelated working directory.
    result = subprocess.run([sys.executable, str(tmp_path / folder / 'skills/paper-to-zotero/scripts/workflow.py'),
                             '--help'], cwd=tmp_path, env=env, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_auto_detection_does_not_create_other_runtimes(tmp_path):
    env = environment(tmp_path)
    (tmp_path / '.claude').mkdir()
    result = subprocess.run([sys.executable, str(SCRIPTS / 'install.py')], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / '.claude/skills/paper-to-zotero/SKILL.md').is_file()
    assert not (tmp_path / '.codex').exists()
    assert not (tmp_path / '.pi').exists()


def test_no_detected_agent_leaves_home_untouched(tmp_path):
    env = environment(tmp_path)
    result = subprocess.run([sys.executable, str(SCRIPTS / 'install.py')], env=env, capture_output=True)
    assert result.returncode != 0
    assert not list(tmp_path.iterdir())


def test_target_verification_rejects_empty_directory_and_other_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.delenv('CODEX_HOME', raising=False)
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    codex = tmp_path / '.codex/skills/paper-to-zotero'
    codex.mkdir(parents=True)
    (codex / 'SKILL.md').write_text('fixture')
    claude = tmp_path / '.claude/skills/paper-to-zotero'
    claude.mkdir(parents=True)
    assert not agent_installation.installation_ok('codex')
    for name in agent_installation.SKILL_NAMES[1:]:
        (codex.parent / name).mkdir()
        (codex.parent / name / 'SKILL.md').write_text('fixture')
    assert agent_installation.installation_ok('codex')
    assert not agent_installation.installation_ok('claude-code')
    assert not agent_installation.installation_ok('all')
    assert agent_installation.installed_paths(tmp_path) == [str(codex)]


def test_private_writer_preserves_unicode_and_literal_shell_text(tmp_path):
    env = environment(tmp_path)
    config = tmp_path / '.config/literature-to-zotero/env'
    config.parent.mkdir(parents=True)
    config.write_text('UNRELATED=保留\nMINERU_TOKEN=old\n', encoding='utf-8')
    value = 'literal-中文-$()-`touch sentinel`'
    result = subprocess.run([sys.executable, str(SCRIPTS / 'configure.py'), '--set', 'MINERU_TOKEN'],
                            input=value, text=True, encoding='utf-8', capture_output=True, env=env)
    assert result.returncode == 0, result.stderr
    assert config.read_text(encoding='utf-8') == f'UNRELATED=保留\nMINERU_TOKEN={value}\n'
    assert value not in result.stdout + result.stderr
    assert_private_file(config)
    before = config.read_bytes()
    result = subprocess.run([sys.executable, str(SCRIPTS / 'configure.py'), '--set', 'MINERU_TOKEN'],
                            input='bad\nINJECTED=value', text=True, encoding='utf-8', capture_output=True, env=env)
    assert result.returncode != 0
    assert config.read_bytes() == before


@pytest.mark.skipif(os.name == 'nt', reason='Windows setup runs through setup.ps1')
def test_bootstrap_check_forwards_group(tmp_path):
    fake = tmp_path / 'python'
    fake.write_text('#!/bin/sh\nif [ "$1" = -c ]; then exit 0; fi\nprintf "%s\\n" "$@" > "$OUT"\n', encoding='utf-8')
    fake.chmod(0o755)
    recorded = tmp_path / 'args'
    for extra, forwarded in ((['--group'], True), ([], False)):
        recorded.unlink(missing_ok=True)
        env = environment(tmp_path / 'home')
        env['PYTHON_BIN'] = str(fake)
        env['OUT'] = str(recorded)
        result = subprocess.run([shutil.which('bash') or 'bash', str(SCRIPTS / 'bootstrap.sh'), '--check', *extra],
                                env=env, capture_output=True, text=True, encoding='utf-8', timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        lines = recorded.read_text(encoding='utf-8').splitlines()
        assert lines[-1] == '--check' or lines[-2:] == ['--check', '--group']
        assert ('--group' in lines) is forwarded


@pytest.mark.skipif(os.name == 'nt', reason='Windows setup runs through setup.ps1')
def test_bootstrap_with_a_ready_python_prepares_the_runtime_without_package_managers(tmp_path):
    blocker = tmp_path / 'no-install'
    blocker.mkdir()
    for name in ('apt-get', 'brew', 'sudo'):
        (blocker / name).write_text('#!/bin/sh\necho "$0" >> "$OUT"\nexit 1\n', encoding='utf-8')
        (blocker / name).chmod(0o755)
    fake = tmp_path / 'python'
    fake.write_text('''#!/bin/sh
if [ "$1" = -c ]; then
  case "$2" in
    *ensure_default_tools*) printf 'tools\\n' >> "$OUT" ;;
  esac
  exit 0
fi
printf '%s\\n' "$@" >> "$OUT"
''', encoding='utf-8')
    fake.chmod(0o755)
    recorded = tmp_path / 'log'
    home = tmp_path / 'home'
    env = environment(home)
    env['PYTHON_BIN'] = str(fake)
    env['OUT'] = str(recorded)
    env['PATH'] = os.pathsep.join((str(blocker), env['PATH']))
    bash = shutil.which('bash') or 'bash'
    result = subprocess.run([bash, str(SCRIPTS / 'bootstrap.sh'), '--runtime-only'],
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    log = recorded.read_text(encoding='utf-8')
    assert 'tools' in log
    assert not [line for line in log.split() if line.endswith(('apt-get', 'brew', 'sudo'))]


@pytest.mark.skipif(os.name == 'nt', reason='Windows setup runs through setup.ps1')
def test_offline_bundle_uses_its_python_and_never_calls_package_managers(tmp_path):
    scripts = tmp_path / 'bundle/paper-to-zotero/scripts'
    scripts.mkdir(parents=True)
    shutil.copy2(SCRIPTS / 'bootstrap.sh', scripts / 'bootstrap.sh')
    bundled = tmp_path / 'bundle/runtime/python/bin/python3'
    bundled.parent.mkdir(parents=True)
    bundled.write_text('#!/bin/sh\ncase "$2" in *ensure_default_tools*) echo bundled >> "$OUT" ;; esac\nexit 0\n')
    blocker = tmp_path / 'blocker'
    blocker.mkdir()
    for name in ('apt-get', 'brew', 'sudo'):
        (blocker / name).write_text('#!/bin/sh\necho "$0" >> "$OUT"\nexit 1\n')
        (blocker / name).chmod(0o755)
    env = environment(tmp_path / 'home')
    env.pop('PYTHON_BIN')
    env['OUT'] = str(tmp_path / 'log')
    env['PATH'] = os.pathsep.join((str(blocker), env['PATH']))
    result = subprocess.run([shutil.which('bash') or 'bash', str(scripts / 'bootstrap.sh'), '--runtime-only'],
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    log = (tmp_path / 'log').read_text(encoding='utf-8').split()
    assert 'bundled' in log
    assert not [line for line in log if line.endswith(('apt-get', 'brew', 'sudo'))]


def test_service_timeout_is_actionable_and_other_checks_continue(tmp_path, monkeypatch, capsys):
    import mineru_parse
    monkeypatch.setattr(configure.credentials, 'SKILL_ENV_FILE', tmp_path / 'absent')
    monkeypatch.setattr(agent_installation, 'installation_ok', lambda _: False)
    monkeypatch.setattr(agent_installation, 'installed_paths', lambda **_: [])
    monkeypatch.setattr(configure.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess([], 0, '{"ok": false}', ''))
    monkeypatch.setattr(configure.capability, 'probe_discovery_search',
                        lambda: {'ok': True, 'detail': 'fixture', 'sources': {}})
    monkeypatch.setattr(configure.capability, 'probe_zotero_local_write', lambda *a, **k: True)
    monkeypatch.setattr(mineru_parse, 'converter_plan', lambda live=True: {
        'selected': 'markitdown', 'available': ['markitdown'], 'api_base': None, 'markitdown_install': "pip install 'markitdown[pdf]'"})
    assert configure.check(as_json=True) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report['ready']
    missing = [row for row in report['items'] if not row['ok'] and not row['optional']]
    assert len(missing) == 1
    assert missing[0]['name'] == '连接 AI 助手'
    assert missing[0]['action']
    names = [row['name'] for row in report['items']]
    assert names.index('连接 AI 助手') < names.index('Zotero 本地 API')
