"""A release installs independently of the checkout and preserves user data."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import importlib.util
import pytest
from test_cli import assert_private_file

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'literature-to-zotero/scripts'


@pytest.mark.skipif(os.name == 'nt', reason='POSIX entry; Windows equivalent in test_windows_setup.py')
def test_release_survives_download_removal_and_repeat_install(tmp_path):
    output = tmp_path / 'download folder'
    subprocess.run([sys.executable, str(ROOT / 'scripts/build-distribution.py'),
                    '--output', str(output)], check=True, capture_output=True)
    release = output / 'literature-to-zotero'
    paths = [p.relative_to(release) for p in release.rglob('*')]
    assert not any({'tests', 'docs', '__pycache__', '.git'} & set(p.parts) for p in paths)
    assert (output / 'literature-to-zotero.zip').is_file()
    home = tmp_path / 'new home'
    home.mkdir()
    env = {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home), 'PYTHON_BIN': sys.executable, 'PAPER2ZOTERO_AGENT': 'codex', 'CODEX_HOME': str(home / '.codex')}
    command = ['bash', str(release / 'install/setup.sh'), '--dependencies-only']
    for _ in range(2):
        result = subprocess.run(command, env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
    shutil.rmtree(output)
    installed = home / '.codex/skills/literature-to-zotero'
    assert installed.is_symlink() and (installed / 'SKILL.md').is_file()
    result = subprocess.run(['bash', str(installed / 'scripts/run-python.sh'),
                             str(installed / 'scripts/workflow.py'), '--help'],
                            env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_conflict_preserves_existing_skill(tmp_path):
    existing = tmp_path / '.codex/skills/literature-to-zotero'
    existing.mkdir(parents=True)
    (existing / 'mine').write_text('user content')
    result = subprocess.run([sys.executable, str(SCRIPTS / 'install.py')],
                            env={**os.environ, 'HOME': str(tmp_path), 'USERPROFILE': str(tmp_path), 'PAPER2ZOTERO_AGENT': 'codex', 'CODEX_HOME': str(tmp_path / '.codex')}, capture_output=True)
    assert result.returncode != 0
    assert (existing / 'mine').read_text() == 'user content'
    assert not (tmp_path / '.local/share/literature-to-zotero/skill').exists()


def test_config_update_private_literal_and_preserves_other_values(tmp_path, monkeypatch):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location('setup_configure', SCRIPTS / 'configure.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = tmp_path / 'env'
    config.write_text('UNRELATED=keep\nMINERU_TOKEN=old\n')
    monkeypatch.setattr(module.credentials, 'SKILL_ENV_FILE', config)
    module.save('MINERU_TOKEN', 'literal-$()-`command`')
    module.save('UNRELATED', '')
    assert config.read_text() == 'UNRELATED=keep\nMINERU_TOKEN=literal-$()-`command`\n'
    assert_private_file(config)


def test_noninteractive_setup_stops_without_prompting_or_writing_secrets(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPTS / 'configure.py')],
                            input='', text=True, capture_output=True,
                            env={**os.environ, 'HOME': str(tmp_path), 'USERPROFILE': str(tmp_path), 'PAPER2ZOTERO_AGENT': 'codex', 'CODEX_HOME': str(tmp_path / '.codex')}, timeout=5)
    assert result.returncode == 2
    assert not (tmp_path / '.config/literature-to-zotero/env').exists()


def test_requested_optional_feature_failure_is_not_ready(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location('check_configure', SCRIPTS / 'configure.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = tmp_path / 'env'
    config.write_text('SETUP_BROWSER=1\n')
    monkeypatch.setattr(module.credentials, 'SKILL_ENV_FILE', config)
    monkeypatch.setattr(module.agent_installation, 'installation_ok', lambda _: True)
    monkeypatch.setattr(module.agent_installation, 'installed_paths', lambda **_: ['/fake/skill'])
    monkeypatch.setattr(module.subprocess, 'run', lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1 if command[-1] == 'kimi' else 0,
                                                    '{"ok": false}' if command[-1] == 'kimi' else '{"ok": true}', ''))
    assert module.check() == 1
    assert '待完成 浏览器获取全文' in capsys.readouterr().out


def test_wizard_keeps_template_library_and_isolates_demo():
    import hashlib
    wizard = (SCRIPTS / 'setup-wizard.sh').read_text()
    library = wizard.split('TOTAL_STAGES=4\n')[0]
    assert hashlib.sha256(library.encode()).hexdigest() == 'c9459b25a3584a9117a0a946843e07c7754b03e8e0b84d49dd69d3c67f773616'
    assert 'ENV_FILE="$DEMO_DIR/env"' in wizard
    assert "trap 'rm -rf \"$DEMO_DIR\"' EXIT" in wizard
    assert 'open_url() { note "[模拟打开网页] $1"; }' in wizard
    assert 'bootstrap.sh" --probe' in wizard
    assert wizard.count('\nstage "') == 7


def test_windows_install_uses_managed_copies_without_symlink_permission(tmp_path):
    code = '''import runpy, sys
sys.path.insert(0, str(__import__('pathlib').Path(sys.argv[1]).parent))
from pathlib import Path
module = runpy.run_path(sys.argv[1])
install = module['install']
install.__globals__['WINDOWS'] = True
install('codex')
install('codex')
'''
    result = subprocess.run([sys.executable, '-c', code, str(SCRIPTS / 'install.py')],
                            env={**os.environ, 'HOME': str(tmp_path), 'USERPROFILE': str(tmp_path), 'PAPER2ZOTERO_AGENT': 'codex', 'CODEX_HOME': str(tmp_path / '.codex')}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    skill = tmp_path / '.codex/skills/literature-to-zotero'
    assert not skill.is_symlink()
    assert (skill / 'SKILL.md').is_file()
    assert (skill / '.literature-to-zotero-managed').read_text() == 'v1'
    assert (skill / 'scripts/run-python.cmd').is_file()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX installer; Windows equivalent in test_windows_setup.py')
def test_online_installer_fetches_then_runs_without_overwriting_dirty_cache(tmp_path):
    cache = tmp_path / 'source with spaces'
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    git = bin_dir / 'git'
    git.write_text('''#!/usr/bin/env bash
set -eu
if [[ "$1" == --version ]]; then echo git-test; exit 0; fi
if [[ "$1" == clone ]]; then
  dest="${@: -1}"
  mkdir -p "$dest/.git" "$dest/install"
  printf '#!/usr/bin/env bash\\nprintf "setup reached"\\n' > "$dest/install/setup.sh"
  exit 0
fi
if [[ "$3" == remote ]]; then echo 'https://github.com/Timisic/paper2zotero-skill.git'; exit 0; fi
if [[ "$3" == status ]]; then echo ' M user-file'; exit 0; fi
exit 9
''')
    git.chmod(0o755)
    env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
           'PAPER2ZOTERO_SOURCE_DIR': str(cache)}
    command = ['bash', str(ROOT / 'install/install.sh'), '--dependencies-only']
    first = subprocess.run(command, input='', capture_output=True, text=True, env=env)
    assert first.returncode == 0, first.stderr
    assert 'setup reached' in first.stdout
    marker = cache / 'user-file'
    marker.write_text('keep my edits')
    second = subprocess.run(command, input='', capture_output=True, text=True, env=env)
    assert second.returncode != 0
    assert marker.read_text() == 'keep my edits'
    assert 'setup reached' not in second.stdout
