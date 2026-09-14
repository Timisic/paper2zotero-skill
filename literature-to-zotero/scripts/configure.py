#!/usr/bin/env python3
"""Private setup writes and completion checks; no paper uploads."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import agent_installation
import credentials

SCRIPTS = Path(__file__).resolve().parent


def save(key: str, value: str) -> None:
    """Atomic, private update preserving unrelated configuration."""
    if not value:
        return
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('输入含控制字符，请重新粘贴完整内容')
    path = credentials.SKILL_ENV_FILE
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lines = path.read_text(encoding='utf-8').splitlines() if path.exists() else []
    lines = [line for line in lines if line.partition('=')[0].strip() != key]
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write('\n'.join([*lines, f'{key}={value}']) + '\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


# Human labels/actions stay here; service semantics remain in capability.py.
CHECKS = {
    'skill-links': ('连接 AI 助手', '重新运行安装，并指定你使用的助手。'),
    'zotero-key': ('保存到 Zotero', '重新运行向导的“连接 Zotero”，检查授权码及文库权限。'),
    'mineru': ('全文阅读材料', '重新运行向导的“启用全文阅读”，检查 MinerU 授权码。'),
    'zotero-local': ('连接电脑上的 Zotero', '打开 Zotero，在设置的高级选项中开启本地接口。'),
    'zotero-sync': ('下载 Zotero 附件', '在 Zotero 的同步设置中开启附件同步和自动下载。'),
    'kimi': ('浏览器获取全文', '打开已安装扩展的浏览器，确认连接服务已启动。'),
}
SETTINGS = {
    'ZOTERO_API_KEY', 'ZOTERO_LIBRARY_ID', 'ZOTERO_LIBRARY_TYPE', 'MINERU_TOKEN',
    'OPENALEX_API_KEY', 'SEMANTIC_SCHOLAR_API_KEY', 'CROSSREF_MAILTO',
    'UNPAYWALL_EMAIL', 'SETUP_DESKTOP', 'SETUP_BROWSER',
}


def probe(command: str) -> dict[str, object]:
    label, action = CHECKS[command]
    if command == 'skill-links':
        agent = os.environ.get('PAPER2ZOTERO_AGENT', 'auto')
        ok = agent_installation.installation_ok(agent)
        detail = ', '.join(agent_installation.installed_paths(agent=agent))
    else:
        try:
            result = subprocess.run([sys.executable, str(SCRIPTS / 'verify.py'), command],
                                    capture_output=True, text=True, timeout=60)
            payload = json.loads(result.stdout)
            ok = result.returncode == 0 and payload.get('ok') is True
            detail = str(payload.get('detail', ''))
        except (OSError, subprocess.SubprocessError, ValueError):
            ok, detail = False, '检查未能完成，请稍后重试。'
    return {'name': label, 'ok': ok, 'detail': detail, 'action': '' if ok else action}


def render(record: dict[str, object]) -> None:
    print(f"{'✓' if record['ok'] else '待完成'} {record['name']}")
    if not record['ok']:
        print(f"  下一步：{record['action']}")


def check(*, as_json: bool = False) -> int:
    records: list[dict[str, object]] = [
        {'name': '运行工具', 'ok': sys.version_info >= (3, 11), 'action': '重新运行安装入口。'},
    ]
    try:
        pdf = subprocess.run(['pdftotext', '-v'], capture_output=True, timeout=10)
        pdf_ok = pdf.returncode == 0
    except (OSError, subprocess.SubprocessError):
        pdf_ok = False
    records.append({'name': 'PDF 文本工具', 'ok': pdf_ok, 'action': '重新运行安装入口，修复 PDF 工具。'})
    commands = ['skill-links', 'zotero-key', 'mineru']
    settings = credentials._skill_env()
    if settings.get('SETUP_DESKTOP') == '1':
        commands += ['zotero-local', 'zotero-sync']
    if settings.get('SETUP_BROWSER') == '1':
        commands += ['kimi']
    for command in commands:
        record = probe(command)
        records.append(record)
        if not as_json:
            render(record)
    ready = all(record['ok'] for record in records)
    if as_json:
        print(json.dumps({'ready': ready, 'items': records}, ensure_ascii=False))
    else:
        for record in records[:2]:
            render(record)
        print('已通过检查，可以开始找论文、保存和生成阅读材料。' if ready else
              '安装已保存；仍有未完成项，重跑向导可继续。可以先尝试找论文。')
        print('额外检索来源按需使用；电脑上的附件是否已下载，在处理论文时单独检查。')
    return 0 if ready else 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Setup checks and private configuration updates.')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check', action='store_true')
    modes.add_argument('--verify', choices=CHECKS)
    modes.add_argument('--set', dest='setting', choices=sorted(SETTINGS), help='Read value from stdin, never from arguments.')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if args.check:
        return check(as_json=args.json)
    if args.verify:
        record = probe(args.verify)
        if args.json:
            print(json.dumps(record, ensure_ascii=False))
        else:
            render(record)
        return 0 if record['ok'] else 1
    if args.setting:
        value = sys.stdin.read().removesuffix('\n')
        save(args.setting, value)
        if os.name == 'nt' and value:
            subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                            '-File', str(SCRIPTS / 'protect-config.ps1'),
                            '-ConfigPath', str(credentials.SKILL_ENV_FILE)], check=True)
        return 0
    print('请重新运行安装向导；Windows 双击 install/setup.cmd，macOS/Linux 运行 bash install/setup.sh。')
    return 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f'配置未完成（{type(exc).__name__}）；已保存的项目会保留，请重跑向导。')
        raise SystemExit(1)
    except (KeyboardInterrupt, EOFError):
        print('\n已保存填写的配置；重跑向导可继续。')
        raise SystemExit(130)
