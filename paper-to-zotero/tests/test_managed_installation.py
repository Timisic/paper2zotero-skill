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
        assert (root / 'paper-to-zotero/scripts/runtime.py').read_text() == 'version = 1'


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
    shared = Path.home() / '.local/share/paper-to-zotero/skill'
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
        assert (root / 'paper-to-zotero/scripts/runtime.py').read_text() == 'version = 2'


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
    (runtime / 'scripts/runtime.py').write_text('version = 2')
    install.install('all')
    install.install('all')
    assert (target / 'references/paper-summary.md').read_text() == 'My custom reading instructions'
    assert agent_installation.installation_ok('all')


@pytest.mark.parametrize('windows', [False, True])
def test_bundle_migrates_managed_legacy_and_preserves_custom_prompt(runtime, monkeypatch, windows):
    monkeypatch.setattr(install, 'WINDOWS', windows)
    (runtime / 'references').mkdir()
    (runtime / install.SUMMARY).write_text('original instructions')
    legacy_shared = Path.home() / '.local/share/literature-to-zotero/skill'
    roots = list(agent_installation.agent_roots().values())
    old_targets = [(legacy_shared, 'copy'), *((root / install.LEGACY_NAME, 'copy' if windows else 'link') for root in roots)]
    legacy_shared.parent.mkdir(parents=True)
    install._publish(old_targets, runtime, legacy_shared, install._journal(legacy_shared))
    (legacy_shared / install.SUMMARY).write_text('custom instructions')
    for root in roots:
        (root / install.LEGACY_NAME / install.SUMMARY).write_text('custom instructions')
    config = Path.home() / '.config/literature-to-zotero/env'
    config.parent.mkdir(parents=True)
    config.write_text('EXISTING_SETTING=keep\n')
    (runtime / 'scripts/runtime.py').write_text('version = 2')
    install.install('codex')
    for root in roots:
        for name in agent_installation.SKILL_NAMES:
            target = root / name
            assert (target / 'SKILL.md').is_file()
            assert target.is_symlink() != windows
        assert (root / 'paper-to-zotero' / install.SUMMARY).read_text() == 'custom instructions'
        assert not (root / install.LEGACY_NAME).exists()
        backups = list(root.parent.glob('.literature-backup-*/literature-to-zotero'))
        assert len(backups) == 1
        assert (backups[0] / install.SUMMARY).read_text() == 'custom instructions'
    assert config.read_text() == 'EXISTING_SETTING=keep\n'
    assert agent_installation.installation_ok('all')
    install.install('all')
    assert (roots[0] / 'paper-to-zotero' / install.SUMMARY).read_text() == 'custom instructions'


def test_bundle_conflict_preflights_both_skills(runtime):
    conflict = Path.home() / '.codex/skills/discussion-drafter'
    conflict.mkdir(parents=True)
    (conflict / 'mine').write_text('keep')
    with pytest.raises(SystemExit, match='已有独立安装'):
        install.install('codex')
    assert not (conflict.parent / 'paper-to-zotero').exists()
    assert not agent_installation.shared_path('paper-to-zotero').exists()
    assert (conflict / 'mine').read_text() == 'keep'


def test_custom_prompt_survives_reinstall_from_runtime_then_upgrade(runtime, monkeypatch):
    (runtime / 'references').mkdir()
    (runtime / install.SUMMARY).write_text('packaged prompt')
    install.install('codex')
    shared = agent_installation.shared_path('paper-to-zotero')
    (shared / install.SUMMARY).write_text('my prompt')
    with monkeypatch.context() as installed_source:
        installed_source.setattr(install, 'SOURCE', shared)
        installed_source.setattr(install, 'DISCUSSION_SOURCE', agent_installation.shared_path('discussion-drafter'))
        install.install('codex')
    (runtime / 'scripts/runtime.py').write_text('version = 2')
    install.install('codex')
    assert (shared / install.SUMMARY).read_text() == 'my prompt'
    assert (shared / 'scripts/runtime.py').read_text() == 'version = 2'


def test_conflicting_custom_prompts_preserve_all_installed_copies(runtime, monkeypatch):
    monkeypatch.setattr(install, 'WINDOWS', True)
    (runtime / 'references').mkdir()
    (runtime / install.SUMMARY).write_text('packaged prompt')
    install.install('all')
    roots = list(agent_installation.agent_roots().values())
    for index, root in enumerate(roots):
        (root / 'paper-to-zotero' / install.SUMMARY).write_text(f'personal prompt {index}')
    (runtime / 'scripts/runtime.py').write_text('version = 2')
    with pytest.raises(SystemExit, match='不同助手'):
        install.install('all')
    for index, root in enumerate(roots):
        assert (root / 'paper-to-zotero' / install.SUMMARY).read_text() == f'personal prompt {index}'
        assert (root / 'paper-to-zotero/scripts/runtime.py').read_text() == 'version = 1'


def test_independent_legacy_skill_is_retained(runtime):
    old = Path.home() / '.codex/skills/literature-to-zotero'
    old.mkdir(parents=True)
    (old / 'SKILL.md').write_text('personal skill')
    install.install('codex')
    assert (old / 'SKILL.md').read_text() == 'personal skill'
    assert agent_installation.installation_ok('codex')


def test_missing_discussion_invalidates_bundle_and_rerun_repairs(runtime):
    install.install('all')
    discussion = Path(agent_installation.installed_paths(agent='codex', skill_name='discussion-drafter')[0])
    (discussion / 'SKILL.md').unlink()
    assert not agent_installation.installation_ok('codex')
    install.install('codex')
    assert agent_installation.installation_ok('all')


def test_interrupted_second_skill_resumes_all_targets(runtime, monkeypatch):
    destination = agent_installation.shared_path('discussion-drafter')
    original = Path.rename
    def interrupt(path, target):
        if Path(target) == destination and path.parent.name.startswith('.literature-update-'):
            raise OSError('interrupted discussion publication')
        return original(path, target)
    with monkeypatch.context() as fault:
        fault.setattr(Path, 'rename', interrupt)
        with pytest.raises(OSError):
            install.install('all')
    assert not agent_installation.installation_ok('all')
    install.install('codex')
    assert agent_installation.installation_ok('all')


@pytest.mark.parametrize('source_version', [1, 2])
def test_damaged_prepared_copy_is_rebuilt_on_rerun(runtime, monkeypatch, source_version):
    install.install('all')
    (runtime / 'scripts/runtime.py').write_text('version = 2')
    original = Path.rename
    shared = Path.home() / '.local/share/paper-to-zotero/skill'
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
        assert (root / 'paper-to-zotero/scripts/runtime.py').read_text() == f'version = {source_version}'
