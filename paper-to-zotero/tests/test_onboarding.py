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


@pytest.mark.parametrize('advanced,last_stage', [(False, '4/4'), (True, '2/2')])
@pytest.mark.parametrize('customize', [False, True])
def test_demo_executes_correct_branch_without_touching_real_configuration(tmp_path, advanced, last_stage, customize):
    env = environment(tmp_path)
    config = tmp_path / '.config/literature-to-zotero/env'
    config.parent.mkdir(parents=True)
    config.write_text('MINERU_TOKEN=private-fixture\nSETUP_BROWSER=1\n')
    before = config.read_bytes()
    command = [shutil.which('bash') or 'bash', str(ROOT / 'install/setup.sh'), '--demo', '--agent', 'claude-code']
    if advanced:
        command.append('--advanced')
    prompt_before = (SCRIPTS.parent / 'references/paper-summary.md').read_bytes()
    replies = ('y\n' if customize else '\n') * 50
    result = subprocess.run(command, input=replies, env=env, text=True, encoding='utf-8', capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert f'Stage {last_stage}' in result.stdout
    assert '更多配置（可选）' in result.stdout
    assert 'Kimi WebBridge' in result.stdout and 'Semantic Scholar' in result.stdout
    assert '必配' not in result.stdout
    assert ('Zotero Desktop · 本机附件' in result.stdout) != advanced
    assert 'private-fixture' not in result.stdout + result.stderr
    assert config.read_bytes() == before
    assert ('[演示路径]' in result.stdout) == customize
    if customize:
        assert 'references/paper-summary.md' in result.stdout
        assert 'Save and continue' in result.stdout
    assert (SCRIPTS.parent / 'references/paper-summary.md').read_bytes() == prompt_before
    assert not (tmp_path / '.claude').exists()


def test_demo_accepts_windows_newlines_from_extra_names(tmp_path):
    env = environment(tmp_path)
    config = tmp_path / '.config/literature-to-zotero/env'
    config.parent.mkdir(parents=True)
    config.write_text('MINERU_TOKEN=private-fixture\n')
    before = config.read_bytes()
    wrapper = tmp_path / 'python'
    wrapper.write_text(
        '#!/bin/sh\n'
        'if [ "$1" = -c ] && printf %s "$2" | grep -q wizard_extras; then\n'
        "  printf 'zotero\\r\\nmineru\\r\\nkimi\\r\\nsemantic_scholar\\r\\ncrossref\\r\\nunpaywall\\r\\n'\n"
        '  exit 0\n'
        'fi\n'
        'exec "$REAL" "$@"\n',
        encoding='utf-8')
    wrapper.chmod(0o755)
    env['PYTHON_BIN'] = str(wrapper)
    env['REAL'] = sys.executable
    result = subprocess.run(
        [shutil.which('bash') or 'bash', str(ROOT / 'install/setup.sh'), '--demo', '--agent', 'claude-code'],
        input='\n' * 50, env=env, text=True, encoding='utf-8', capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert 'Semantic Scholar' in result.stdout
    assert '必配' not in result.stdout
    assert config.read_bytes() == before


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


@pytest.mark.parametrize('advanced', [False, True])
def test_terminal_demo_reaches_more_configuration_without_python(tmp_path, advanced):
    env = environment(tmp_path)
    env['PYTHON_BIN'] = str(tmp_path / 'absent-python')
    # The bootstrap probe may look for these alternatives. All are unavailable.
    script = '''python3.13() { return 127; }
python3.12() { return 127; }
python3.11() { return 127; }
export -f python3.13 python3.12 python3.11
exec bash "$@"
'''
    args = [shutil.which('bash') or 'bash', '-c', script, '--', str(ROOT / 'install/setup.sh'), '--demo-missing']
    if advanced:
        args.append('--advanced')
    result = subprocess.run(args, env=env, input='\n' * 50, capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stderr
    assert '待安装：Python' in result.stdout
    assert '更多配置（可选）' in result.stdout and 'Semantic Scholar' in result.stdout
    assert not (tmp_path / '.config/literature-to-zotero/env').exists()


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


def test_bootstrap_installs_default_tools_after_the_python_path(tmp_path):
    text = (SCRIPTS / 'bootstrap.sh').read_text(encoding='utf-8')
    probe = text.index('if [[ "${1:-}" == --probe ]]; then exit 0; fi')
    check = text.index('if [[ "${1:-}" == --check ]]; then')
    saved = text.index('literature-to-zotero/python-path')
    call = text.index('ensure_default_tools')
    runtime = text.index('if [[ "${1:-}" == --runtime-only ]]; then exit 0; fi')
    assert probe < check < saved < call < runtime
    bad = tmp_path / 'bad-pdf'
    good = tmp_path / 'good-pdf'
    blocker = tmp_path / 'no-install'
    for directory in (bad, good, blocker):
        directory.mkdir()
    (bad / 'pdftotext').write_text('#!/bin/sh\nexit 99\n', encoding='utf-8')
    (good / 'pdftotext').write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
    for name in ('apt-get', 'brew', 'sudo'):
        (blocker / name).write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
    for path in (bad / 'pdftotext', good / 'pdftotext', *((blocker / name) for name in ('apt-get', 'brew', 'sudo'))):
        path.chmod(0o755)
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
    env['PATH'] = os.pathsep.join((str(bad), str(good), str(blocker), env['PATH']))
    bash = shutil.which('bash') or 'bash'
    result = subprocess.run([bash, str(SCRIPTS / 'bootstrap.sh'), '--runtime-only'],
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'tools' in recorded.read_text(encoding='utf-8')
    assert 'good-pdf' in result.stdout
    assert (home / '.config/literature-to-zotero/python-path').is_file()
    assert (home / '.config/literature-to-zotero/pdf-bin').read_text(encoding='utf-8').rstrip().endswith('good-pdf')
    recorded.unlink()
    result = subprocess.run([bash, str(SCRIPTS / 'bootstrap.sh'), '--probe'],
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not recorded.exists()


def test_runtime_launcher_restores_verified_pdf_tool(tmp_path):
    env = environment(tmp_path)
    tools = tmp_path / '工具 with spaces'
    tools.mkdir()
    pdf = tools / ('pdftotext.exe' if os.name == 'nt' else 'pdftotext')
    pdf.write_text('#!/bin/sh\nexit 0\n')
    pdf.chmod(0o755)
    config = tmp_path / '.config/literature-to-zotero'
    config.mkdir(parents=True)
    (config / 'python-path').write_text(sys.executable + '\n')
    (config / 'pdf-bin').write_text(str(tools) + '\n')
    result = subprocess.run([shutil.which('bash') or 'bash', str(SCRIPTS / 'run-python.sh'), '-c',
                             'import shutil; print(shutil.which("pdftotext"))'],
                            env=env, text=True, encoding='utf-8', capture_output=True)
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == pdf


def test_service_timeout_is_actionable_and_other_checks_continue(tmp_path, monkeypatch, capsys):
    import mineru_parse
    monkeypatch.setattr(configure.credentials, 'SKILL_ENV_FILE', tmp_path / 'absent')
    monkeypatch.setattr(agent_installation, 'installation_ok', lambda _: False)
    monkeypatch.setattr(agent_installation, 'installed_paths', lambda **_: [])
    monkeypatch.setattr(configure.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(configure.capability, 'probe_discovery_search',
                        lambda: {'ok': True, 'detail': 'fixture', 'sources': {}})
    monkeypatch.setattr(configure.capability, 'probe_zotero_local_write', lambda *a, **k: True)
    monkeypatch.setattr(mineru_parse, 'converter_plan', lambda live=True: {
        'selected': 'markitdown', 'api_base': None, 'markitdown_install': "pip install 'markitdown[pdf]'"})
    assert configure.check(as_json=True) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report['ready']
    missing = [row for row in report['items'] if not row['ok']]
    assert len(missing) == 1
    assert missing[0]['name'] == '连接 AI 助手'
    assert missing[0]['action']
    names = [row['name'] for row in report['items']]
    assert names.index('连接 AI 助手') < names.index('Zotero Desktop · 本机附件')
