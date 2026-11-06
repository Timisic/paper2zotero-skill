#!/usr/bin/env python3
"""Build the allowlisted release zip, or with --platform, self-contained offline zips."""
from pathlib import Path
import argparse
import email.parser
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'paper-to-zotero/scripts'))
from agent_installation import SKILL_NAMES
from install import _files
from scansci_retrieval import PIN

PYTHON_RELEASE = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261021/'
PYTHON_ARCHIVE = 'cpython-3.12.15+20261021-{}-install_only_stripped.tar.gz'
PLATFORMS = {
    'windows-x64': ('x86_64-pc-windows-msvc', ['win_amd64']),
    'macos-arm64': ('aarch64-apple-darwin', ['macosx_11_0_arm64']),
    'macos-x64': ('x86_64-apple-darwin', ['macosx_11_0_x86_64']),
    # manylinux2014 alone resolves an obsolete markitdown.
    'linux-x64': ('x86_64-unknown-linux-gnu',
                  ['manylinux_2_28_x86_64', 'manylinux_2_17_x86_64', 'manylinux2014_x86_64']),
}


def stage(destination: Path) -> None:
    destination.mkdir(parents=True)
    for name in ('README.md', 'THIRD_PARTY.md', '开始.md'):
        shutil.copy2(ROOT / name, destination / name)
    shutil.copytree(ROOT / 'install', destination / 'install')
    for skill_name in SKILL_NAMES:
        for relative in _files(ROOT / skill_name):
            target = destination / skill_name / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / skill_name / relative, target)
    # User README is standalone; developer links stay in the repository only.
    readme = destination / 'README.md'
    readme.write_text(readme.read_text(encoding='utf-8').split('<!-- repository-only -->')[0].rstrip() + '\n', encoding='utf-8')


def build(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    release = output / 'paper-to-zotero'
    if release.exists():
        raise SystemExit(f'输出已存在，使用新的 --output 目录：{release}')
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        stage(Path(temporary) / release.name)
        (Path(temporary) / release.name).rename(release)
    shutil.make_archive(str(release), 'zip', output, release.name)
    return release


def download_python(triple: str, runtime: Path) -> None:
    name = PYTHON_ARCHIVE.format(triple)
    with urllib.request.urlopen(PYTHON_RELEASE + 'SHA256SUMS', timeout=60) as response:
        sums = {line.split()[1]: line.split()[0] for line in response.read().decode().splitlines() if line.strip()}
    archive = runtime / name
    urllib.request.urlretrieve(PYTHON_RELEASE + name, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != sums[name]:
        raise SystemExit(f'SHA-256 不匹配：{name}')
    with tarfile.open(archive) as tar:
        # share/ holds man pages and terminfo, whose case-only name clashes break macOS builds.
        tar.extractall(runtime, filter=lambda member, path: None if member.name.startswith('python/share/')
                       else tarfile.data_filter(member, path))
    archive.unlink()


def download_wheels(tags: list[str], wheels: Path) -> None:
    subprocess.run([sys.executable, '-m', 'pip', 'download', '--only-binary=:all:', '--python-version', '3.12',
                    '--implementation', 'cp', *(f'--platform={tag}' for tag in tags), '--dest', str(wheels),
                    f'scansci-pdf=={PIN}', 'markitdown[pdf]'], check=True)


def licenses(wheels: Path) -> str:
    rows = []
    for wheel in sorted(wheels.glob('*.whl')):
        with zipfile.ZipFile(wheel) as archive:
            name = next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))
            metadata = email.parser.Parser().parsestr(archive.read(name).decode('utf-8'))
        classifiers = [c.split(' :: ')[-1] for c in metadata.get_all('Classifier', []) if c.startswith('License ::')]
        # A one-line License field is more precise than a classifier; multi-line ones are full texts.
        declared = (metadata.get('License') or '').strip().splitlines()
        license = (metadata.get('License-Expression') or (declared[0] if len(declared) == 1 else '')
                   or '; '.join(classifiers) or (declared[0][:80] if declared else '未声明'))
        rows.append(f"| {metadata['Name']} | {metadata['Version']} | {license.replace('|', '/')} |")
    return ('# 随附 Python 包的许可\n\n由构建脚本从每个 wheel 的 METADATA 生成。'
            'Python 解释器来自 python-build-standalone，许可见 `python/` 中的 LICENSE.txt 和 THIRD_PARTY.md。\n\n'
            '| 包 | 版本 | 许可 |\n| --- | --- | --- |\n' + '\n'.join(rows) + '\n')


def build_offline(output: Path, platform: str, version: str) -> Path:
    triple, tags = PLATFORMS[platform]
    name = f'paper2zotero-{version}-{platform}'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        root = Path(temporary) / name
        stage(root)
        runtime = root / 'runtime'
        runtime.mkdir()
        download_python(triple, runtime)
        python = runtime / 'python'
        # Zip tools disagree on symlinks; keep one real interpreter at bin/python3.
        for link in [path for path in python.rglob('*') if path.is_symlink()]:
            link.unlink()
        if (python / 'bin/python3.12').is_file():
            os.replace(python / 'bin/python3.12', python / 'bin/python3')
        download_wheels(tags, runtime / 'wheels')
        (runtime / 'LICENSES.md').write_text(licenses(runtime / 'wheels'), encoding='utf-8')
        (root / 'VERSION').write_text(version + '\n', encoding='utf-8')
        return Path(shutil.make_archive(str(output / name), 'zip', temporary, name))


def git_version() -> str:
    return subprocess.run(['git', 'describe', '--tags', '--always'], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--platform', action='append', choices=[*PLATFORMS, 'all'],
                        help='Build an offline zip with Python and wheels; repeat, or use all.')
    parser.add_argument('--version', help='VERSION for offline zips (default: git describe --tags --always).')
    args = parser.parse_args()
    if not args.platform:
        print(build(args.output.resolve()))
    else:
        version = args.version or git_version()
        for platform in list(PLATFORMS) if 'all' in args.platform else dict.fromkeys(args.platform):
            print(build_offline(args.output.resolve(), platform, version))
