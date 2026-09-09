"""Native Windows regressions: exercise the distributed launcher and real Git Bash."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def environment(home):
    home.mkdir()
    env = {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home),
           'PYTHON_BIN': sys.executable, 'PYTHONUTF8': '1'}
    # The virtualenv interpreter is acceptable; account credentials are never used.
    return env


def release(tmp_path):
    path = tmp_path / 'download folder 中文'
    subprocess.run([sys.executable, str(ROOT / 'scripts/build-distribution.py'),
                    '--output', str(path)], check=True, capture_output=True,
                   env={**os.environ, 'PYTHONUTF8': '1'})
    return path / 'literature-to-zotero'


def run_setup(package, env, mode):
    return subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                           '-File', str(package / 'install/setup.ps1'), mode],
                          env=env, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=45)


def check_native_repeat_install_and_removed_download(tmp_path):
    package = release(tmp_path)
    env = environment(tmp_path / '用户 home')
    home = Path(env['USERPROFILE'])
    for _ in range(2):
        result = run_setup(package, env, '-DependenciesOnly')
        assert result.returncode == 0, result.stdout + result.stderr
    skill_root = home / '.codex/skills'
    assert list(skill_root.rglob('SKILL.md')) == [skill_root / 'literature-to-zotero/SKILL.md']
    backups = home / '.local/share/literature-to-zotero/backups'
    assert len(list(backups.rglob('SKILL.md'))) == 3
    result = run_setup(package, env, '-Check')
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'MINERU_TOKEN' in result.stdout
    assert '安装已保存' in result.stdout
    shutil.rmtree(package)
    result = subprocess.run([sys.executable,
                             str(skill_root / 'literature-to-zotero/scripts/workflow.py'),
                             '--help'], env=env, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def check_native_terminal_has_tty_and_verified_poppler(tmp_path):
    package = release(tmp_path)
    env = environment(tmp_path / '用户 home')
    marker = tmp_path / 'terminal-result.txt'
    env['PAPER2ZOTERO_TEST_RESULT'] = str(marker)
    # Replace only the test package's account wizard; never prompt for or access keys.
    # The production PowerShell -> mintty -> Bash launcher remains unchanged.
    (package / 'literature-to-zotero/scripts/setup-wizard.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
[[ -t 0 && -t 1 ]]
[[ "$1" == --demo ]]
pdftotext -v >/dev/null 2>&1
printf 'tty-and-poppler-ok' > "$PAPER2ZOTERO_TEST_RESULT"
''', encoding='utf-8', newline='\n')
    result = run_setup(package, env, '-Demo')
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text() == 'tty-and-poppler-ok'


@unittest.skipUnless(os.name == 'nt', 'native Windows launcher')
class WindowsSetupTests(unittest.TestCase):
    def test_repeat_install(self):
        with tempfile.TemporaryDirectory() as folder:
            check_native_repeat_install_and_removed_download(Path(folder))

    def test_terminal(self):
        with tempfile.TemporaryDirectory() as folder:
            check_native_terminal_has_tty_and_verified_poppler(Path(folder))

    def test_real_demo_stages(self):
        with tempfile.TemporaryDirectory() as folder:
            env = environment(Path(folder) / '用户 home')
            git = shutil.which('git.exe')
            self.assertIsNotNone(git)
            bash = Path(git).parent.parent / 'bin/bash.exe'
            result = subprocess.run([str(bash), str(ROOT / 'install/windows-wizard.sh'),
                                     '--demo'], env=env, input='\n' * 40, capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Stage 8/8', result.stdout)
            self.assertFalse((Path(env['HOME']) / '.config/literature-to-zotero/env').exists())


if __name__ == '__main__':
    unittest.main()
