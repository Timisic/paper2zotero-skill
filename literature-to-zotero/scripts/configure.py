#!/usr/bin/env python3
"""Interactive setup; credentials stay local, checks never upload papers."""
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import webbrowser

import capability
import credentials

SCRIPTS = Path(__file__).resolve().parent


def save(key: str, value: str) -> None:
    """Atomic, private update preserving unrelated configuration."""
    if not value:
        return
    if any(c in value for c in '\r\n'):
        raise ValueError('配置必须为单行')
    path = credentials.SKILL_ENV_FILE
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [line for line in lines if line.partition('=')[0].strip() != key]
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write('\n'.join([*lines, f'{key}={value}']) + '\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def ask(key: str, label: str, *, secret: bool = False, current: str = '') -> str:
    current = current or credentials._skill_env().get(key, '')
    prompt = label + ('（回车保留已有值）' if current else '（可暂时留空）') + '：'
    value = (getpass.getpass(prompt) if secret else input(prompt)).strip()
    if value:
        if key == 'ZOTERO_LIBRARY_TYPE' and value not in {'user', 'group'}:
            raise ValueError('文库类型必须为 user 或 group')
        if key == 'ZOTERO_LIBRARY_ID' and not value.isdigit():
            raise ValueError('文库 ID 必须为数字')
        save(key, value)
        # The current process must verify exactly what the human just entered.
        os.environ[key] = value
    return value or current


def yes(prompt: str) -> bool:
    return input(prompt + ' [y/N]：').strip().lower() in {'y', 'yes', '是'}


def guide(key: str) -> None:
    item = capability.GUIDE[key]
    print(item['do'])
    if item['url']:
        print(item['url'])
        webbrowser.open(item['url'])


def check() -> int:
    states = {
        'Python 3.11+': sys.version_info >= (3, 11),
        'PDF 文本工具': bool(shutil.which('pdftotext')),
    }
    commands = [('Skill 安装', 'skill-links'), ('Zotero 云端写入', 'zotero-key'),
                ('MinerU 解析', 'mineru')]
    settings = credentials._skill_env()
    if settings.get('SETUP_DESKTOP') == '1':
        commands += [('Desktop 本地 API', 'zotero-local'), ('Desktop 附件同步', 'zotero-sync')]
    if settings.get('SETUP_BROWSER') == '1':
        commands += [('Kimi 浏览器连接', 'kimi')]
    for label, command in commands:
        result = subprocess.run([sys.executable, str(SCRIPTS / 'verify.py'), command],
                                capture_output=True, text=True, timeout=60)
        states[label] = result.returncode == 0
        print(f"{'✓' if states[label] else '待完成'} {label}")
        if not states[label]:
            print(result.stdout.strip() or '检查失败；请重跑 setup。')
    for label in ('Python 3.11+', 'PDF 文本工具'):
        print(f"{'✓' if states[label] else '待完成'} {label}")
    ready = all(states.values())
    print('核心环境及所选功能已通过检查。' if ready else '安装已保存；仍有未完成项，重跑 setup 可继续。检索不需要服务密钥。')
    print('浏览器访问和 Desktop 本地附件回读按需检查；此结果不代表已完成论文处理或本地同步。')
    return 0 if ready else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only setup checks; configure through setup.sh")
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        return check()
    print('请运行 bash setup.sh，在 Wizard 中配置账号。')
    return 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f'配置未完成（{type(exc).__name__}）；已保存的项目会保留，请重跑 setup。')
        raise SystemExit(1)
    except (KeyboardInterrupt, EOFError):
        print('\n已保存填写的配置；重跑 setup 可继续。')
        raise SystemExit(130)
