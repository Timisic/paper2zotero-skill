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
SCRIPTS = ROOT / 'paper-to-zotero/scripts'
sys.path.insert(0, str(SCRIPTS))
from agent_installation import SKILL_NAMES


@pytest.mark.skipif(os.name == 'nt', reason='POSIX entry; Windows equivalent in test_windows_setup.py')
def test_release_survives_download_removal_and_repeat_install(tmp_path):
    output = tmp_path / 'download folder'
    subprocess.run([sys.executable, str(ROOT / 'scripts/build-distribution.py'),
                    '--output', str(output)], check=True, capture_output=True)
    release = output / 'paper-to-zotero'
    paths = [p.relative_to(release) for p in release.rglob('*')]
    assert not any({'tests', 'docs', '__pycache__', '.git'} & set(p.parts) for p in paths)
    assert (output / 'paper-to-zotero.zip').is_file()
    home = tmp_path / 'new home'
    home.mkdir()
    env = {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home), 'PYTHON_BIN': sys.executable, 'PAPER2ZOTERO_AGENT': 'codex', 'CODEX_HOME': str(home / '.codex')}
    # Reuse this interpreter's packages so the private runtime installs nothing it already has.
    subprocess.run([sys.executable, '-m', 'venv', '--system-site-packages',
                    str(home / '.local/share/paper-to-zotero/runtime')], check=True)
    command = [shutil.which('bash') or 'bash', str(release / 'install/setup.sh'), '--dependencies-only']
    for _ in range(2):
        result = subprocess.run(command, env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
    shutil.rmtree(output)
    for name in SKILL_NAMES:
        skill = home / '.codex/skills' / name
        assert skill.is_symlink() and (skill / 'SKILL.md').is_file()
    assert (home / '.codex/skills/academic-paper/LICENSE').is_file()
    installed = home / '.codex/skills/paper-to-zotero'
    result = subprocess.run([shutil.which('bash') or 'bash', str(installed / 'scripts/run-python.sh'),
                             str(installed / 'scripts/workflow.py'), '--help'],
                            env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    # The installed bundle is itself a complete reinstall source.
    result = subprocess.run([sys.executable, str(installed / 'scripts/install.py'), '--agent', 'codex'],
                            env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_offline_build_lays_out_runtime_version_and_start_page(tmp_path, monkeypatch):
    import zipfile
    spec = importlib.util.spec_from_file_location('build_distribution', ROOT / 'scripts/build-distribution.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)

    def download_python(triple, runtime):
        assert triple == 'aarch64-apple-darwin'
        (runtime / 'python/bin').mkdir(parents=True)
        (runtime / 'python/bin/python3.12').write_text('interpreter')
        (runtime / 'python/bin/python3.12').chmod(0o755)
        if os.name != 'nt':
            (runtime / 'python/bin/python3').symlink_to('python3.12')

    def download_wheels(tags, wheels):
        assert tags == ['macosx_11_0_arm64']
        wheels.mkdir()
        with zipfile.ZipFile(wheels / 'pymupdf-1.0-cp310-abi3-macosx_11_0_arm64.whl', 'w') as wheel:
            wheel.writestr('pymupdf-1.0.dist-info/METADATA',
                           'Metadata-Version: 2.4\nName: PyMuPDF\nVersion: 1.0\nLicense-Expression: AGPL-3.0-or-later\n')

    monkeypatch.setattr(builder, 'download_python', download_python)
    monkeypatch.setattr(builder, 'download_wheels', download_wheels)
    archive = builder.build_offline(tmp_path, 'macos-arm64', 'v9.9.9')
    assert archive == tmp_path / 'paper2zotero-v9.9.9-macos-arm64.zip'
    root = 'paper2zotero-v9.9.9-macos-arm64/'
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert bundle.read(root + 'VERSION').decode() == 'v9.9.9\n'
        assert 'install/AGENT_SETUP.md' in bundle.read(root + '开始.md').decode()
        assert '| PyMuPDF | 1.0 | AGPL-3.0-or-later |' in bundle.read(root + 'runtime/LICENSES.md').decode()
        interpreter = bundle.getinfo(root + 'runtime/python/bin/python3')
        assert os.name == 'nt' or interpreter.external_attr >> 16 & 0o100, 'the interpreter stays executable after unzip'
    assert root + 'runtime/python/bin/python3.12' not in names
    assert root + 'runtime/wheels/pymupdf-1.0-cp310-abi3-macosx_11_0_arm64.whl' in names
    assert root + 'paper-to-zotero/SKILL.md' in names
    assert 'MIT License' in zipfile.ZipFile(archive).read(root + 'LICENSE').decode()
    assert not [name for name in names if '/tests/' in name]


def test_conflict_preserves_existing_skill(tmp_path):
    existing = tmp_path / '.codex/skills/paper-to-zotero'
    existing.mkdir(parents=True)
    (existing / 'mine').write_text('user content')
    result = subprocess.run([sys.executable, str(SCRIPTS / 'install.py')],
                            env={**os.environ, 'HOME': str(tmp_path), 'USERPROFILE': str(tmp_path), 'PAPER2ZOTERO_AGENT': 'codex', 'CODEX_HOME': str(tmp_path / '.codex')}, capture_output=True)
    assert result.returncode != 0
    assert (existing / 'mine').read_text() == 'user content'
    assert not (tmp_path / '.local/share/paper-to-zotero/skill').exists()


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


def test_wizard_keeps_template_library():
    import hashlib
    sys.path.insert(0, str(SCRIPTS))
    import setup_connection
    wizard = (SCRIPTS / 'setup-wizard.sh').read_text()
    library = wizard.split('BASIC_COUNT=1\n')[0]
    assert hashlib.sha256(library.encode()).hexdigest() == '68497de599f7e6cbb4fe77abeb78eea57fdd5b15fa7015043da691ce3664d672'
    assert wizard.count('\nstage "') == 5
    assert '必配' not in wizard
    basic_count = int(wizard.split('BASIC_COUNT=', 1)[1].split('\n', 1)[0])
    assert basic_count == len(setup_connection.BASIC_SERVICES)
    assert setup_connection.SERVICES['desktop'][0] in wizard


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
    skill = tmp_path / '.codex/skills/paper-to-zotero'
    assert not skill.is_symlink()
    assert (skill / 'SKILL.md').is_file()
    assert (skill / '.literature-to-zotero-managed').read_text() == 'v1'
    assert (skill / 'scripts/run-python.cmd').is_file()
    for name in SKILL_NAMES[1:]:
        assert not (skill.parent / name).is_symlink()
        assert (skill.parent / name / 'SKILL.md').is_file()


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
    command = [shutil.which('bash') or 'bash', str(ROOT / 'install/install.sh'), '--dependencies-only']
    first = subprocess.run(command, input='', capture_output=True, text=True, env=env)
    assert first.returncode == 0, first.stderr
    assert 'setup reached' in first.stdout
    marker = cache / 'user-file'
    marker.write_text('keep my edits')
    second = subprocess.run(command, input='', capture_output=True, text=True, env=env)
    assert second.returncode != 0
    assert marker.read_text() == 'keep my edits'
    assert 'setup reached' not in second.stdout
