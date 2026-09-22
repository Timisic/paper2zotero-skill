#!/usr/bin/env python3
"""Build a standalone, allowlisted release directory and zip from working files."""
from pathlib import Path
import argparse
import shutil
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def build(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    release = output / 'paper-to-zotero'
    if release.exists():
        raise SystemExit(f'输出已存在，使用新的 --output 目录：{release}')
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        stage = Path(temporary) / release.name
        stage.mkdir(parents=True)
        shutil.copy2(ROOT / 'README.md', stage / 'README.md')
        shutil.copytree(ROOT / 'install', stage / 'install')
        for skill_name in ('paper-to-zotero', 'discussion-drafter'):
            skill = stage / skill_name
            skill.mkdir()
            shutil.copy2(ROOT / skill_name / 'SKILL.md', skill / 'SKILL.md')
            for name in ('scripts', 'references', 'agents', 'assets'):
                source = ROOT / skill_name / name
                if source.is_dir():
                    shutil.copytree(source, skill / name,
                                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
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
