"""Publish complete managed runtimes; resume interrupted publication on rerun."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from agent_installation import CHOICES, SKILL_NAMES, selected_roots, agent_roots, shared_path
from runtime_io import file_lock

WINDOWS = os.name == 'nt'
MARKER = '.literature-to-zotero-managed'
MANIFEST = '.literature-to-zotero-version.json'
SOURCE = Path(__file__).resolve().parent.parent
DISCUSSION_SOURCE = SOURCE.parent / 'discussion-drafter'
LEGACY_NAME = 'literature-to-zotero'
SUMMARY = 'references/paper-summary.md'


def _journal(destination: Path) -> Path:
    name = '.install-state.json' if destination.name == 'skill' else f'.{destination.name}-install-state.json'
    return destination.parent / name


def _files(root: Path) -> dict[str, str]:
    files = [root / 'SKILL.md']
    for name in ('scripts', 'references', 'agents', 'assets'):
        files.extend(p for p in (root / name).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix != '.pyc')
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files)}


def _version(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def _upstream_summary_hash(source: Path) -> str:
    if _owned(source):
        record = json.loads((source / MANIFEST).read_text(encoding='utf-8'))
        return record.get('upstream_summary_hash', record['files'][SUMMARY])
    return hashlib.sha256((source / SUMMARY).read_bytes()).hexdigest()


def _owned(path: Path) -> bool:
    try:
        return (path / MARKER).read_text(encoding='utf-8') == 'v1'
    except (OSError, UnicodeError):
        return False


def _matches(path: Path, version: str | None = None, *, allow_summary_customization: bool = False) -> bool:
    try:
        record = json.loads((path / MANIFEST).read_text(encoding='utf-8'))
        files = _files(path)
        summary = 'references/paper-summary.md'
        if allow_summary_customization and summary in files and summary in record['files']:
            files[summary] = record['files'][summary]
        return bool(files) and record['files'] == files and record['version'] == _version(files) and (
            version is None or record['version'] == version)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def runtime_ready(path: Path, shared: Path | None = None) -> bool:
    """Independent skills keep their own ownership; managed ones require evidence."""
    if not (path / 'SKILL.md').is_file():
        return False
    if not (path / MARKER).exists() and not (path / MANIFEST).exists():
        return True
    if not _owned(path):
        return False
    shared = shared or shared_path('discussion-drafter' if path.name == 'discussion-drafter' else SKILL_NAMES[0])
    if _journal(shared).exists():
        return False
    try:
        version = json.loads((shared / MANIFEST).read_text(encoding='utf-8'))['version']
    except (OSError, ValueError, TypeError, KeyError):
        return False
    return (_matches(shared, version, allow_summary_customization=True)
            and _matches(path, version, allow_summary_customization=True))


def _write_journal(path: Path, record: dict) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def _finish_publication(journal: Path) -> bool:
    """The journal precedes every rename; existing complete destinations win."""
    record = json.loads(journal.read_text(encoding='utf-8'))
    for entry in record['entries']:
        target, staged, backup = (Path(entry[key]) for key in ('target', 'staged', 'backup'))
        parent = target.parent.parent.resolve()
        # These paths share the target volume and stay outside discoverable skills.
        if (not target.is_absolute() or target.name not in ('skill', LEGACY_NAME, *SKILL_NAMES)
                or staged.parent.parent.resolve() != parent
                or not staged.parent.name.startswith('.literature-update-')
                or backup.parent.parent.resolve() != parent
                or not backup.parent.name.startswith('.literature-backup-')):
            raise ValueError('安装恢复记录中的路径无效；已保留现有文件。')
        is_link = entry['kind'] == 'link'
        complete = (_matches(target, record['version']) and
                    (not is_link or target.is_symlink() and target.resolve() == Path(entry['link'])))
        if complete:
            continue
        prepared = (staged.is_symlink() and staged.resolve() == Path(entry['link']) if is_link
                    else _matches(staged, record['version']))
        if not prepared:
            if not target.exists() and not target.is_symlink() and backup.exists():
                backup.rename(target)
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            if backup.exists() or backup.is_symlink():
                raise ValueError('安装恢复发现目标已变化；已保留两个版本。')
            backup.parent.mkdir(exist_ok=True)
            target.rename(backup)
        staged.rename(target)
    journal.unlink()
    _discard_staging(record)
    return True


def _discard_staging(record: dict) -> None:
    for entry in record['entries']:
        staging_parent = Path(entry['staged']).parent
        if staging_parent.exists():
            # Every entry was checked against its explicitly named target above.
            resolved = staging_parent.resolve()
            if resolved.parent == Path(entry['target']).parent.parent.resolve() and resolved.name.startswith('.literature-update-'):
                shutil.rmtree(resolved)



def _publish(targets: list[tuple[Path, str]], source: Path, destination: Path, journal: Path,
             summary: bytes | None = None) -> None:
    previous = json.loads(journal.read_text(encoding='utf-8')) if journal.exists() else None
    files = _files(source)
    if summary is not None:
        files[SUMMARY] = hashlib.sha256(summary).hexdigest()
    version = _version(files)
    entries: list[dict[str, str]] = []
    staging_roots: list[Path] = []
    published = False
    try:
        for target, kind in targets:
            if _matches(target, version) and (kind != 'link' or target.is_symlink() and target.resolve() == destination):
                continue
            parent = target.parent.parent
            parent.mkdir(parents=True, exist_ok=True)
            staging_root = Path(tempfile.mkdtemp(prefix='.literature-update-', dir=parent))
            staging_roots.append(staging_root)
            staged = staging_root / 'skill'
            if kind == 'link':
                staged.symlink_to(destination, target_is_directory=True)
            else:
                staged.mkdir()
                for relative in files:
                    output = staged / relative
                    output.parent.mkdir(parents=True, exist_ok=True)
                    if relative == SUMMARY and summary is not None:
                        output.write_bytes(summary)
                    else:
                        shutil.copy2(source / relative, output)
                (staged / MARKER).write_text('v1', encoding='utf-8')
                manifest = {'version': version, 'files': files}
                if (source / SUMMARY).is_file():
                    manifest['upstream_summary_hash'] = _upstream_summary_hash(source)
                (staged / MANIFEST).write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
                if not _matches(staged, version):
                    raise ValueError('下载内容在安装期间发生变化，请重试。')
            backup = parent / ('.literature-backup-' + uuid.uuid4().hex) / 'skill'
            entries.append({'target': str(target), 'staged': str(staged), 'backup': str(backup),
                            'kind': kind, 'link': str(destination)})
        if entries:
            _write_journal(journal, {'version': version, 'entries': entries})
            published = True
            if not _finish_publication(journal):
                raise ValueError('预备文件在发布期间发生变化；请重跑安装以重新准备。')
            if previous:
                _discard_staging(previous)
        elif previous:
            # Recovery may have restored a complete version identical to the
            # available source. End the old publication instead of looping.
            journal.unlink()
            _discard_staging(previous)
    finally:
        # Only unjournaled staging is disposable; journaled paths must survive.
        if not published:
            for stage in staging_roots:
                resolved = stage.resolve()
                if resolved.parent == stage.parent.resolve() and resolved.name.startswith('.literature-update-'):
                    shutil.rmtree(resolved)


def _custom_summary(paths: list[Path]) -> bytes | None:
    """Preserve a changed prompt; conflicting per-agent customizations need review."""
    customized = set()
    for path in paths:
        if not _owned(path) or not (path / SUMMARY).is_file():
            continue
        try:
            record = json.loads((path / MANIFEST).read_text(encoding='utf-8'))
            data = (path / SUMMARY).read_bytes()
            packaged = record['files'][SUMMARY]
        except (OSError, ValueError, TypeError, KeyError):
            continue
        # Earlier upgrades may have recorded the customized prompt as the
        # installed baseline. Track the upstream hash separately going forward.
        baseline = record.get('upstream_summary_hash', packaged)
        if hashlib.sha256(data).hexdigest() != baseline:
            customized.add(data)
    if len(customized) > 1:
        raise SystemExit('不同助手中存在不同的自定义总结提示词，已全部保留。请先选择要继续使用的版本。')
    return next(iter(customized), None)


def _managed_legacy(path: Path, legacy_shared: Path) -> bool:
    return _owned(path) or (path.is_symlink() and path.resolve() in {
        legacy_shared.resolve(), SOURCE.resolve(), SOURCE.parent / LEGACY_NAME})


def install(agent: str = 'auto') -> None:
    roots = list(dict.fromkeys(selected_roots(agent)))
    if not roots:
        raise SystemExit('未找到已使用的 AI 助手。请运行 setup 并选择 Codex、Claude Code 或 Pi；Agent 可传 --agent。')
    legacy_shared = Path.home() / '.local/share/literature-to-zotero/skill'
    sources = dict(zip(SKILL_NAMES, (SOURCE, DISCUSSION_SOURCE)))
    # Existing managed installations participate in renaming; independent
    # shared-root installations remain owned by the user.
    existing_roots = [*agent_roots().values(), Path.home() / '.agents/skills', Path.home() / '.hermes/skills']
    for root in existing_roots:
        if root not in roots and (_managed_legacy(root / LEGACY_NAME, legacy_shared)
                                  or any(_owned(root / name) for name in SKILL_NAMES)):
            roots.append(root)
    # Preflight the entire bundle before publishing either skill.
    for name, source in sources.items():
        if not (source / 'SKILL.md').is_file():
            raise SystemExit(f'安装包缺少 {name}/SKILL.md，请重新下载完整安装包。')
        destination = shared_path(name)
        for target in [destination, *(root / name for root in roots)]:
            if target.exists() or target.is_symlink():
                if _owned(target):
                    continue
                if target.is_symlink() and target.resolve() in {source.resolve(), destination.resolve()}:
                    continue
                raise SystemExit(f'已有独立安装，已保留：{target}。请先移动该目录后重跑 setup。')
    with file_lock(shared_path(SKILL_NAMES[0]).parent / '.install.lock'):
        legacy_journal = _journal(legacy_shared)
        if legacy_journal.exists():
            with file_lock(legacy_shared.parent / '.install.lock'):
                if not _finish_publication(legacy_journal):
                    raise SystemExit('旧版安装有未完成的恢复记录，已保留。请先恢复旧版安装。')
        for name, source in sources.items():
            destination = shared_path(name)
            journal = _journal(destination)
            summary_paths = [destination, *(root / name for root in roots)]
            if journal.exists():
                summary_paths.extend(Path(entry['backup']) for entry in
                                     json.loads(journal.read_text(encoding='utf-8'))['entries'])
            if not any(_owned(path) for path in summary_paths):
                summary_paths.extend([legacy_shared, *(root / LEGACY_NAME for root in roots)])
            summary = _custom_summary(summary_paths) if name == SKILL_NAMES[0] else None
            if journal.exists():
                original = json.loads(journal.read_text(encoding='utf-8'))
                if not _finish_publication(journal):
                    targets = [(Path(entry['target']), entry['kind']) for entry in original['entries']]
                    _publish(targets, source, destination, journal, summary)
            targets = [(destination, 'copy'), *((root / name, 'copy' if WINDOWS else 'link') for root in roots)]
            _publish(targets, source, destination, journal, summary)
            for root in roots:
                print(f'已安装：{root / name}')
        # Only retire the old discoverable names after BOTH skills are ready.
        for root in roots:
            legacy = root / LEGACY_NAME
            if legacy.exists() or legacy.is_symlink():
                if _managed_legacy(legacy, legacy_shared):
                    backup = root.parent / ('.literature-backup-' + uuid.uuid4().hex)
                    backup.mkdir(parents=True)
                    legacy.rename(backup / LEGACY_NAME)
                    print(f'旧名称已备份：{backup / LEGACY_NAME}')
                else:
                    print(f'保留独立旧版安装：{legacy}')
        print(f'运行文件：{shared_path(SKILL_NAMES[0]).parent}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent', choices=CHOICES, default=os.environ.get('PAPER2ZOTERO_AGENT', 'auto'))
    parser.add_argument('--detect', action='store_true', help='Exit 0 if a target is available; write nothing.')
    args = parser.parse_args()
    if args.detect:
        raise SystemExit(0 if selected_roots(args.agent) else 1)
    try:
        install(args.agent)
    except (OSError, ValueError):
        print('安装未完成；已有版本和恢复记录已保留。请重新运行安装以继续。')
        raise SystemExit(1)
