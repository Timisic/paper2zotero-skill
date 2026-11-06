#!/usr/bin/env python3
"""Build a standalone, allowlisted release directory and zip from working files."""
from pathlib import Path
import argparse
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'paper-to-zotero/scripts'))
from agent_installation import SKILL_NAMES
from install import _files


def build(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    release = output / 'paper-to-zotero'
    if release.exists():
        raise SystemExit(f'输出已存在，使用新的 --output 目录：{release}')
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        stage = Path(temporary) / release.name
        stage.mkdir(parents=True)
        shutil.copy2(ROOT / 'README.md', stage / 'README.md')
        shutil.copy2(ROOT / 'THIRD_PARTY.md', stage / 'THIRD_PARTY.md')
        shutil.copytree(ROOT / 'install', stage / 'install')
        for skill_name in SKILL_NAMES:
            for relative in _files(ROOT / skill_name):
                target = stage / skill_name / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / skill_name / relative, target)
        # User README is standalone; developer links stay in the repository only.
        readme = stage / 'README.md'
        readme.write_text(readme.read_text(encoding='utf-8').split('<!-- repository-only -->')[0].rstrip() + '\n', encoding='utf-8')
        stage.rename(release)
    shutil.make_archive(str(release), 'zip', output, release.name)
    return release


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    print(build(parser.parse_args().output.resolve()))
