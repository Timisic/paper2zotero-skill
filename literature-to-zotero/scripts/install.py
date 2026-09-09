"""Install runtime files at a stable path; preserve conflicting installations."""
from pathlib import Path
import shutil
import tempfile
import os

WINDOWS = os.name == "nt"
MARKER = ".literature-to-zotero-managed"

SOURCE = Path(__file__).resolve().parent.parent


def install() -> None:
    home = Path.home()
    destination = home / '.local/share/literature-to-zotero/skill'
    roots = [home / '.codex/skills', home / '.pi/agent/skills', home / '.claude/skills']
    if (home / '.agents/skills').is_dir():
        roots.append(home / '.agents/skills')
    # Preflight all conflicts before changing any runtime.
    for root in roots:
        link = root / 'literature-to-zotero'
        if link.exists() or link.is_symlink():
            if WINDOWS and (link / MARKER).is_file() and (link / MARKER).read_text() == "v1":
                continue
            if not link.is_symlink() or link.resolve() not in {SOURCE, destination}:
                raise SystemExit(f'已有独立安装，已保留：{link}。请先移动该目录后重跑 setup。')
    if SOURCE != destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            staged = Path(temporary) / 'skill'
            staged.mkdir()
            shutil.copy2(SOURCE / 'SKILL.md', staged / 'SKILL.md')
            for name in ('scripts', 'references', 'agents', 'assets'):
                if (SOURCE / name).exists():
                    shutil.copytree(SOURCE / name, staged / name,
                                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            if destination.exists():
                # Only the managed runtime is replaced. Preserve the previous version.
                backup = Path(tempfile.mkdtemp(prefix='previous-', dir=destination.parent))
                destination.rename(backup / 'skill')
            staged.rename(destination)
    for root in roots:
        root.mkdir(parents=True, exist_ok=True)
        link = root / 'literature-to-zotero'
        if link.is_symlink():
            if link.resolve() == destination:
                continue
            link.unlink()
        if WINDOWS:
            if link.exists():
                # Agent runtimes recursively discover SKILL.md. Backups must
                # live outside their skill roots or every rerun adds a duplicate.
                backup_root = destination.parent / 'backups'
                backup_root.mkdir(exist_ok=True)
                backup = Path(tempfile.mkdtemp(prefix='previous-literature-', dir=backup_root))
                link.rename(backup / 'skill')
            shutil.copytree(destination, link)
            (link / MARKER).write_text('v1')
        else:
            link.symlink_to(destination, target_is_directory=True)
        print(f'已安装：{link}')
    print(f'运行文件：{destination}')


if __name__ == '__main__':
    install()
