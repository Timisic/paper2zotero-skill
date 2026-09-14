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

from agent_installation import CHOICES, selected_roots, agent_roots
from runtime_io import file_lock

WINDOWS = os.name == 'nt'
MARKER = '.literature-to-zotero-managed'
MANIFEST = '.literature-to-zotero-version.json'
SOURCE = Path(__file__).resolve().parent.parent


def _files(root: Path) -> dict[str, str]:
    files = [root / 'SKILL.md']
    for name in ('scripts', 'references', 'agents', 'assets'):
        files.extend(p for p in (root / name).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix != '.pyc')
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files)}


def _version(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


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
    shared = shared or Path.home() / '.local/share/literature-to-zotero/skill'
    if (shared.parent / '.install-state.json').exists():
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
        if (not target.is_absolute() or target.name not in ('skill', 'literature-to-zotero')
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



def _publish(targets: list[tuple[Path, str]], source: Path, destination: Path, journal: Path) -> None:
    previous = json.loads(journal.read_text(encoding='utf-8')) if journal.exists() else None
    files = _files(source)
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
                    shutil.copy2(source / relative, output)
                (staged / MARKER).write_text('v1', encoding='utf-8')
                (staged / MANIFEST).write_text(json.dumps({'version': version, 'files': files}, sort_keys=True), encoding='utf-8')
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


def install(agent: str = 'auto') -> None:
    roots = list(dict.fromkeys(selected_roots(agent)))
    if not roots:
        raise SystemExit('未找到已使用的 AI 助手。请运行 setup 并选择 Codex、Claude Code 或 Pi；Agent 可传 --agent。')
    destination = Path.home() / '.local/share/literature-to-zotero/skill'
    journal = destination.parent / '.install-state.json'
    with file_lock(destination.parent / '.install.lock'):
        if journal.exists() and not _finish_publication(journal):
            original = json.loads(journal.read_text(encoding='utf-8'))
            targets = [(Path(entry['target']), entry['kind']) for entry in original['entries']]
            _publish(targets, SOURCE, destination, journal)
        if WINDOWS:
            for root in agent_roots().values():
                if root not in roots and _owned(root / 'literature-to-zotero'):
                    roots.append(root)
        for root in roots:
            target = root / 'literature-to-zotero'
            if target.exists() or target.is_symlink():
                if WINDOWS and not target.is_symlink() and _owned(target):
                    continue
                if not target.is_symlink() or target.resolve() not in {SOURCE.resolve(), destination.resolve()}:
                    raise SystemExit(f'已有独立安装，已保留：{target}。请先移动该目录后重跑 setup。')
        targets = [(destination, 'copy'), *((root / 'literature-to-zotero', 'copy' if WINDOWS else 'link') for root in roots)]
        _publish(targets, SOURCE, destination, journal)
        for root in roots:
            print(f'已安装：{root / "literature-to-zotero"}')
        print(f'运行文件：{destination}')


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
