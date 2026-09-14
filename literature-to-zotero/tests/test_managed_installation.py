"""Publish and inspect real installations under an isolated user profile."""
import os
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import install
import agent_installation


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.delenv('CODEX_HOME', raising=False)
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    source = tmp_path / 'download'
    (source / 'scripts').mkdir(parents=True)
    (source / 'SKILL.md').write_text('fixture')
    (source / 'scripts/runtime.py').write_text('version = 1')
    monkeypatch.setattr(install, 'SOURCE', source)
    return source


def test_failed_staging_preserves_working_installation(runtime, monkeypatch):
    install.install('all')
    (runtime / 'scripts/runtime.py').write_text('version = 2')
    original = shutil.copy2
    def full_disk(source, target, *args, **kwargs):
        if Path(source).name == 'runtime.py':
            raise OSError('fixture disk full')
        return original(source, target, *args, **kwargs)
    monkeypatch.setattr(shutil, 'copy2', full_disk)
    with pytest.raises(OSError):
        install.install('all')
    assert agent_installation.installation_ok('all')
    for root in agent_installation.agent_roots().values():
        assert (root / 'literature-to-zotero/scripts/runtime.py').read_text() == 'version = 1'


def test_managed_installation_detects_missing_runtime_file(runtime):
    install.install('all')
    target = Path(agent_installation.installed_paths(agent='codex')[0])
    (target / 'scripts/runtime.py').unlink()
    assert not agent_installation.installation_ok('all')
    install.install('all')
    assert agent_installation.installation_ok('all')


def test_interrupted_activation_resumes_all_original_targets(runtime, monkeypatch):
    install.install('all')
    (runtime / 'scripts/runtime.py').write_text('version = 2')
    original = Path.rename
    shared = Path.home() / '.local/share/literature-to-zotero/skill'
    def interrupt(path, target):
        if Path(target) == shared and path.parent.name.startswith('.literature-update-'):
            raise OSError('fixture interrupted after old version moved')
        return original(path, target)
    with monkeypatch.context() as fault:
        fault.setattr(Path, 'rename', interrupt)
        with pytest.raises(OSError):
            install.install('all')
    assert not agent_installation.installation_ok('all')
    install.install('claude-code')
    assert agent_installation.installation_ok('all')
    for root in agent_installation.agent_roots().values():
        assert (root / 'literature-to-zotero/scripts/runtime.py').read_text() == 'version = 2'


def test_repeat_install_does_not_publish_another_copy(runtime):
    install.install('all')
    before = sorted(str(path) for path in Path.home().rglob('*'))
    install.install('all')
    assert sorted(str(path) for path in Path.home().rglob('*')) == before


def test_custom_summary_prompt_does_not_invalidate_runtime(runtime):
    (runtime / 'references').mkdir()
    (runtime / 'references/paper-summary.md').write_text('Packaged instructions')
    install.install('all')
    target = Path(agent_installation.installed_paths(agent='codex')[0])
    (target / 'references/paper-summary.md').write_text('My custom reading instructions')
    assert agent_installation.installation_ok('all')


@pytest.mark.parametrize('source_version', [1, 2])
def test_damaged_prepared_copy_is_rebuilt_on_rerun(runtime, monkeypatch, source_version):
    install.install('all')
    (runtime / 'scripts/runtime.py').write_text('version = 2')
    original = Path.rename
    shared = Path.home() / '.local/share/literature-to-zotero/skill'
    damaged = []
    def interrupt(path, target):
        if Path(target) == shared and path.parent.name.startswith('.literature-update-'):
            damaged.append(path)
            raise OSError('fixture interrupted activation')
        return original(path, target)
    with monkeypatch.context() as fault:
        fault.setattr(Path, 'rename', interrupt)
        with pytest.raises(OSError):
            install.install('all')
    (damaged[0] / 'scripts/runtime.py').write_text('corrupted staging')
    (runtime / 'scripts/runtime.py').write_text(f'version = {source_version}')
    install.install('claude-code')
    assert agent_installation.installation_ok('all')
    for root in agent_installation.agent_roots().values():
        assert (root / 'literature-to-zotero/scripts/runtime.py').read_text() == f'version = {source_version}'
