"""Native Windows regressions: exercise the distributed launcher and real Git Bash."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import time

ROOT = Path(__file__).resolve().parents[2]


def environment(home):
    home.mkdir()
    env = {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home),
           'PYTHON_BIN': sys.executable, 'PYTHONUTF8': '1',
           'CODEX_HOME': str(home / '.codex'), 'CLAUDE_CONFIG_DIR': str(home / '.claude')}
    # The virtualenv interpreter is acceptable; account credentials are never used.
    return env


def release(tmp_path):
    path = tmp_path / 'download folder 中文'
    subprocess.run([sys.executable, str(ROOT / 'scripts/build-distribution.py'),
                    '--output', str(path)], check=True, capture_output=True,
                   env={**os.environ, 'PYTHONUTF8': '1'})
    return path / 'literature-to-zotero'


def run_setup(package, env, *modes):
    return subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                           '-File', str(package / 'install/setup.ps1'), '-Agent', 'all', *modes],
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
    assert '全文阅读材料' in result.stdout
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

    def test_masked_input_restores_real_terminal_after_success_and_interrupt(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            package = release(path)
            env = environment(path / '用户 home')
            marker = path / 'input-result.txt'
            env['PAPER2ZOTERO_TEST_RESULT'] = str(marker)
            # Use a real mintty TTY and production reader. Only the keystrokes
            # are synthetic; no clipboard or user credentials are accessed.
            (package / 'literature-to-zotero/scripts/setup-wizard.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/setup-input.sh"
before=$(stty -g)
count=0
read() {
  [[ "$(stty -g)" != "$before" ]]
  count=$((count + 1))
  if [[ "$count" == 1 ]]; then printf -v char '%s' 'fixture-key'; else char=''; fi
}
value=$(read_authorization_line)
[[ "$value" == fixture-key ]]
[[ "$(stty -g)" == "$before" ]]
read() { kill -s TERM "$BASHPID"; }
status=0
value=$(read_authorization_line) || status=$?
[[ "$status" == 130 ]]
[[ "$(stty -g)" == "$before" ]]
printf 'masked-input-restored' > "$PAPER2ZOTERO_TEST_RESULT"
''', encoding='utf-8', newline='\n')
            result = run_setup(package, env, '-Demo')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(marker.read_text(), 'masked-input-restored')

    def test_real_demo_stages(self):
        with tempfile.TemporaryDirectory() as folder:
            env = environment(Path(folder) / '用户 home')
            git = shutil.which('git.exe')
            self.assertIsNotNone(git)
            bash = Path(git).parent.parent / 'bin/bash.exe'
            for extra, stage in [([], '4/4'), (['--advanced'], '7/7')]:
                result = subprocess.run([str(bash), str(ROOT / 'install/windows-wizard.sh'),
                                         '--demo', *extra], env=env, input='\n' * 40, capture_output=True,
                                        text=True, encoding='utf-8', errors='replace', timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('Stage ' + stage, result.stdout)
            self.assertFalse((Path(env['HOME']) / '.config/literature-to-zotero/env').exists())

    def test_agent_launch_returns_with_terminal_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            package = release(path)
            env = environment(path / '用户 home')
            marker = path / 'completed.txt'
            env['PAPER2ZOTERO_TEST_RESULT'] = str(marker)
            (package / 'literature-to-zotero/scripts/setup-wizard.sh').write_text('''#!/usr/bin/env bash
set -eu
test -t 0
sleep 3
printf 'finished' > "$PAPER2ZOTERO_TEST_RESULT"
''', encoding='utf-8', newline='\n')
            result = run_setup(package, env, '-Demo', '-LaunchWizard')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Wizard terminal is ready', result.stdout)
            self.assertFalse(marker.exists(), 'Agent waited for the entire wizard to finish')
            deadline = time.monotonic() + 10
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertEqual(marker.read_text(), 'finished')

    def test_online_entry_forwards_modes_and_preserves_dirty_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            source = path / 'local repository'
            (source / 'install').mkdir(parents=True)
            (source / 'install/setup.ps1').write_text('''param([switch]$DependenciesOnly, [switch]$Check, [switch]$LaunchWizard, [switch]$Advanced, [string]$Agent)
"$DependenciesOnly,$Check,$LaunchWizard,$Advanced,$Agent" | Set-Content $env:PAPER2ZOTERO_TEST_RESULT
''', encoding='utf-8')
            def git(*args):
                subprocess.run(['git', '-C', str(source), *args], check=True, capture_output=True)
            git('init', '-b', 'main')
            git('add', '.')
            git('-c', 'user.name=Setup Test', '-c', 'user.email=test@example.invalid',
                'commit', '-m', 'fixture')
            env = environment(path / '用户 home')
            cache = path / 'download cache'
            marker = path / 'mode.txt'
            env.update(PAPER2ZOTERO_SOURCE_DIR=str(cache), PAPER2ZOTERO_TEST_RESULT=str(marker),
                       GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='url.' + source.as_uri() + '.insteadOf',
                       GIT_CONFIG_VALUE_0='https://github.com/Timisic/paper2zotero-skill.git')
            command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                       '-File', str(ROOT / 'install/install.ps1'), '-Agent', 'claude-code']
            for mode, expected in [('-DependenciesOnly', 'True,False,False,False,claude-code'),
                                   ('-LaunchWizard', 'False,False,True,False,claude-code'),
                                   ('-Check', 'False,True,False,False,claude-code'),
                                   ('-Advanced', 'False,False,False,True,claude-code')]:
                result = subprocess.run([*command, mode], env=env, capture_output=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(marker.read_text().strip(), expected)
            (cache / 'user-file').write_text('preserve me')
            marker.unlink()
            result = subprocess.run(command, env=env, capture_output=True, timeout=25)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((cache / 'user-file').read_text(), 'preserve me')
            self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
