#!/usr/bin/env python3
"""Build a standalone, allowlisted release directory and zip from working files."""
from pathlib import Path
import argparse
import shutil
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def build(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    release = output / 'literature-to-zotero'
    if release.exists():
        raise SystemExit(f'输出已存在，使用新的 --output 目录：{release}')
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        stage = Path(temporary) / release.name
        skill = stage / 'literature-to-zotero'
        skill.mkdir(parents=True)
        shutil.copy2(ROOT / 'README.md', stage / 'README.md')
        shutil.copytree(ROOT / 'install', stage / 'install')
        shutil.copy2(ROOT / 'literature-to-zotero/SKILL.md', skill / 'SKILL.md')
        for name in ('scripts', 'references', 'agents', 'assets'):
            source = ROOT / 'literature-to-zotero' / name
            if source.is_dir():
                shutil.copytree(source, skill / name,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        # User README is standalone; developer links stay in the repository only.
        readme = stage / 'README.md'
        readme.write_text(readme.read_text().split('<!-- repository-only -->')[0].rstrip() + '\n')
        stage.rename(release)
    shutil.make_archive(str(release), 'zip', output, release.name)
    return release


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    print(build(parser.parse_args().output.resolve()))
