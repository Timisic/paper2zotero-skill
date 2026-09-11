"""Exercise the distributed onboarding interface with an isolated user profile."""
from pathlib import Path
import json
import os
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'literature-to-zotero/scripts'
sys.path.insert(0, str(SCRIPTS))
import agent_installation
import configure


def environment(home):
    home.mkdir(exist_ok=True)
    return {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home),
            'CODEX_HOME': str(home / '.codex'), 'CLAUDE_CONFIG_DIR': str(home / '.claude'),
            'PAPER2ZOTERO_AGENT': 'auto', 'PYTHON_BIN': sys.executable}


@pytest.mark.parametrize('agent,folder', [('claude-code', '.claude'), ('codex', '.codex'), ('pi', '.pi/agent')])
def test_targeted_install_survives_other_agent_conflict(tmp_path, agent, folder):
    env = environment(tmp_path)
    other = '.codex' if agent != 'codex' else '.claude'
    conflict = tmp_path / other / 'skills/literature-to-zotero'
    conflict.mkdir(parents=True)
    (conflict / 'my-note').write_text('keep')
    for _ in range(2):
        result = subprocess.run([sys.executable, str(SCRIPTS / 'install.py'), '--agent', agent],
                                env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / folder / 'skills/literature-to-zotero/SKILL.md').is_file()
    assert (conflict / 'my-note').read_text() == 'keep'
    # The selected runtime must work from an unrelated working directory.
    result = subprocess.run([sys.executable, str(tmp_path / folder / 'skills/literature-to-zotero/scripts/workflow.py'),
                             '--help'], cwd=tmp_path, env=env, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_auto_detection_does_not_create_other_runtimes(tmp_path):
    env = environment(tmp_path)
    (tmp_path / '.claude').mkdir()
    result = subprocess.run([sys.executable, str(SCRIPTS / 'install.py')], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / '.claude/skills/literature-to-zotero/SKILL.md').is_file()
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
    codex = tmp_path / '.codex/skills/literature-to-zotero'
    codex.mkdir(parents=True)
    (codex / 'SKILL.md').write_text('fixture')
    claude = tmp_path / '.claude/skills/literature-to-zotero'
    claude.mkdir(parents=True)
    assert agent_installation.installation_ok('codex')
    assert not agent_installation.installation_ok('claude-code')
    assert not agent_installation.installation_ok('all')
    assert agent_installation.installed_paths(tmp_path) == [str(codex)]


@pytest.mark.parametrize('advanced,last_stage', [(False, '4/4'), (True, '7/7')])
@pytest.mark.parametrize('customize', [False, True])
def test_demo_executes_correct_branch_without_touching_real_configuration(tmp_path, advanced, last_stage, customize):
    env = environment(tmp_path)
    config = tmp_path / '.config/literature-to-zotero/env'
    config.parent.mkdir(parents=True)
    config.write_text('MINERU_TOKEN=private-fixture\nSETUP_BROWSER=1\n')
    before = config.read_bytes()
    command = ['bash', str(ROOT / 'install/setup.sh'), '--demo', '--agent', 'claude-code']
    if advanced:
        command.append('--advanced')
    prompt_before = (SCRIPTS.parent / 'references/paper-summary.md').read_bytes()
    replies = ('y\n' if customize else '\n') * 50
    result = subprocess.run(command, input=replies, env=env, text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert f'Stage {last_stage}' in result.stdout
    assert ('更多设置：补充检索来源' in result.stdout) == advanced
    assert 'private-fixture' not in result.stdout + result.stderr
    assert config.read_bytes() == before
    assert ('[演示路径]' in result.stdout) == customize
    if customize:
        assert 'references/paper-summary.md' in result.stdout
        assert 'Save and continue' in result.stdout
    assert (SCRIPTS.parent / 'references/paper-summary.md').read_bytes() == prompt_before
    assert not (tmp_path / '.claude').exists()


def test_private_writer_preserves_unicode_and_literal_shell_text(tmp_path):
    env = environment(tmp_path)
    config = tmp_path / '.config/literature-to-zotero/env'
    config.parent.mkdir(parents=True)
    config.write_text('UNRELATED=保留\nMINERU_TOKEN=old\n', encoding='utf-8')
    value = 'literal-中文-$()-`touch sentinel`'
    result = subprocess.run([sys.executable, str(SCRIPTS / 'configure.py'), '--set', 'MINERU_TOKEN'],
                            input=value, text=True, capture_output=True, env=env)
    assert result.returncode == 0, result.stderr
    assert config.read_text(encoding='utf-8') == f'UNRELATED=保留\nMINERU_TOKEN={value}\n'
    assert value not in result.stdout + result.stderr
    assert config.stat().st_mode & 0o777 == 0o600
    before = config.read_bytes()
    result = subprocess.run([sys.executable, str(SCRIPTS / 'configure.py'), '--set', 'MINERU_TOKEN'],
                            input='bad\nINJECTED=value', text=True, capture_output=True, env=env)
    assert result.returncode != 0
    assert config.read_bytes() == before


def test_runtime_launcher_restores_verified_pdf_tool(tmp_path):
    env = environment(tmp_path)
    tools = tmp_path / '工具 with spaces'
    tools.mkdir()
    pdf = tools / 'pdftotext'
    pdf.write_text('#!/bin/sh\nexit 0\n')
    pdf.chmod(0o755)
    config = tmp_path / '.config/literature-to-zotero'
    config.mkdir(parents=True)
    (config / 'python-path').write_text(sys.executable + '\n')
    (config / 'pdf-bin').write_text(str(tools) + '\n')
    result = subprocess.run(['bash', str(SCRIPTS / 'run-python.sh'), '-c',
                             'import shutil; print(shutil.which("pdftotext"))'],
                            env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(pdf)


def test_service_timeout_is_actionable_and_other_checks_continue(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(configure.credentials, 'SKILL_ENV_FILE', tmp_path / 'absent')
    monkeypatch.setattr(agent_installation, 'installation_ok', lambda _: True)
    monkeypatch.setattr(agent_installation, 'installed_paths', lambda **_: ['/fixture'])
    calls = []
    def run(command, **kwargs):
        calls.append(command[-1])
        if command[-1] == 'zotero-key':
            raise subprocess.TimeoutExpired(command, 60)
        return subprocess.CompletedProcess(command, 0, '{"ok": true}', '')
    monkeypatch.setattr(configure.subprocess, 'run', run)
    assert configure.check(as_json=True) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report['ready']
    assert 'mineru' in calls
    missing = [row for row in report['items'] if not row['ok']]
    assert len(missing) == 1
    assert missing[0]['action']
