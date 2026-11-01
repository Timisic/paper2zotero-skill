#!/usr/bin/env python3
"""Private setup writes and completion checks; no paper uploads."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import agent_installation
import credentials
import capability
import scansci_retrieval
from runtime_io import private_text, file_lock

SCRIPTS = Path(__file__).resolve().parent


def save(key: str, value: str) -> None:
    """Atomic, private update preserving unrelated configuration."""
    save_many({key: value})


def save_many(values: dict[str, str]) -> None:
    """Save an account together, securing the temporary file before replacement."""
    values = {key: value for key, value in values.items() if value}
    if not values:
        return
    if any(ord(c) < 32 or ord(c) == 127 for value in values.values() for c in value):
        raise ValueError('输入含控制字符，请重新粘贴完整内容')
    path = credentials.SKILL_ENV_FILE
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with file_lock(path.with_suffix('.lock'), blocking=True):
        lines = path.read_text(encoding='utf-8').splitlines() if path.exists() else []
        lines = [line for line in lines if line.partition('=')[0].strip() not in values]
        private_text(path, '\n'.join([*lines, *(f'{key}={value}' for key, value in values.items())]) + '\n')


# Human labels/actions stay here; service semantics remain in capability.py.
CHECKS = {
    'skill-links': ('连接 AI 助手', '重新运行安装，并指定你使用的助手。'),
    'zotero-key': ('保存到 Zotero', '群组文库才需要 Zotero Web API。重新运行向导的“连接 Zotero Web API”，检查授权码及文库权限。'),
    'mineru': ('全文转换', capability.GUIDE['mineru']['do']),
    'openalex': (
        '论文检索（OpenAlex）',
        '当前检索后端需要 OpenAlex 授权码。在更多配置里连接 OpenAlex，或删除 SEARCH_BACKEND 恢复 scansci。',
    ),
    'zotero-local': ('连接电脑上的 Zotero', '打开 Zotero，在设置的高级选项中开启本地接口。'),
    'zotero-sync': ('下载 Zotero 附件', '在 Zotero 的同步设置中开启附件同步和自动下载。'),
    'kimi': ('浏览器获取全文', '打开已安装扩展的浏览器，确认连接服务已启动。'),
}
SETTINGS = {
    'ZOTERO_API_KEY', 'ZOTERO_LIBRARY_ID', 'ZOTERO_LIBRARY_TYPE', 'MINERU_TOKEN',
    'OPENALEX_API_KEY', 'SEMANTIC_SCHOLAR_API_KEY', 'CROSSREF_MAILTO',
    'UNPAYWALL_EMAIL', 'SETUP_DESKTOP', 'SETUP_BROWSER',
    'SEARCH_BACKEND', 'MINERU_API_BASE', 'ZOTERO_LOCAL_API', 'ZOTERO_LOCAL_API_KEY',
    'ZOTERO_WRITE_BACKEND',
}


def probe(command: str) -> dict[str, object]:
    label, action = CHECKS[command]
    if command == 'openalex':
        record = capability.probe_discovery_search()
        return {'name': label, **record, 'action': '' if record['ok'] else action}
    if command == 'skill-links':
        agent = os.environ.get('PAPER2ZOTERO_AGENT', 'auto')
        ok = agent_installation.installation_ok(agent)
        detail = ', '.join(path for name in agent_installation.SKILL_NAMES
                           for path in agent_installation.installed_paths(agent=agent, skill_name=name))
    else:
        try:
            result = subprocess.run([sys.executable, str(SCRIPTS / 'verify.py'), command],
                                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
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


def search_row(backend: str) -> dict[str, object]:
    if backend == 'scansci':
        status = scansci_retrieval.library_ready()
        install = getattr(status, 'install', scansci_retrieval.INSTALL_LINE)
        return {'name': '论文检索（ScanSci）', 'ok': status.ok, 'detail': status.detail,
                'action': '' if status.ok else install}
    if backend == 'kimi':
        return {'name': '论文检索（Kimi WebBridge）', 'ok': True,
                'detail': '当前检索后端是 Kimi WebBridge', 'action': ''}
    if backend == 'semantic_scholar':
        return {'name': '论文检索（Semantic Scholar）', 'ok': True,
                'detail': '当前检索后端是 Semantic Scholar。授权码在更多配置，缺了这一项仍通过。',
                'action': ''}
    if backend in ('http', 'openalex'):
        discovery = capability.probe_discovery_search()
        name, action = CHECKS['openalex']
        return {'name': name, **discovery, 'action': '' if discovery['ok'] else action}
    raise ValueError('unknown SEARCH_BACKEND: ' + backend)


def conversion_row() -> dict[str, object]:
    import mineru_parse
    plan = mineru_parse.converter_plan(live=True)
    record = capability.converter_ready(plan)
    return {'name': '全文转换', 'ok': record['ok'] is True, 'detail': str(record['detail']),
            'action': '' if record['ok'] else str(record['remediation'])}


def desktop_row() -> dict[str, object]:
    import setup_connection
    name = setup_connection.SERVICES['desktop'][0]
    if capability.probe_zotero_local_write():
        return {'name': name, 'ok': True, 'detail': '127.0.0.1:23119', 'action': ''}
    if capability.probe_zotero_local():
        detail = '本地 API 没有返回 Zotero-Server-ID，不能作为写入目标。'
    else:
        detail = capability.zotero_local(False)['detail']
    return {'name': name, 'ok': False, 'detail': detail, 'action': capability.GUIDE['zotero_local']['do']}


def check(*, as_json: bool = False, group: bool = False) -> int:
    import setup_connection
    rows: list[dict[str, object]] = []
    python_ok = sys.version_info >= (3, 11)
    rows.append({'name': '运行工具', 'ok': python_ok, 'action': '' if python_ok else '重新运行安装入口。'})
    try:
        pdf = subprocess.run(['pdftotext', '-v'], capture_output=True, timeout=10)
        pdf_ok = pdf.returncode == 0
    except (OSError, subprocess.SubprocessError):
        pdf_ok = False
    rows.append({'name': 'PDF 文本工具', 'ok': pdf_ok,
                 'action': '' if pdf_ok else '重新运行安装入口，修复 PDF 工具。'})
    rows.append(probe('skill-links'))
    rows.append(search_row(credentials.search_backend()))
    rows.append(conversion_row())
    for name in setup_connection.BASIC_SERVICES:
        if name != 'desktop':
            raise ValueError('basic service has no check: ' + name)
        rows.append(desktop_row())
    if group or credentials.zotero_credentials()['library_type'] == 'group':
        rows.append(probe('zotero-key'))
    if credentials._skill_env().get('SETUP_BROWSER') == '1':
        rows.append(probe('kimi'))
    ready = all(row['ok'] for row in rows)
    if as_json:
        print(json.dumps({'ready': ready, 'items': rows}, ensure_ascii=False))
    else:
        for row in rows:
            render(row)
        print('已通过检查，可以开始找论文、保存和生成阅读材料。' if ready else
              '安装已保存；仍有未完成项，可在向导中继续修复。当前可用功能以上方检查为准。')
        print('额外检索来源按需使用；电脑上的附件是否已下载，在处理论文时单独检查。')
    return 0 if ready else 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Setup checks and private configuration updates.')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check', action='store_true')
    modes.add_argument('--verify', choices=CHECKS)
    modes.add_argument('--set', dest='setting', choices=sorted(SETTINGS), help='Read value from stdin, never from arguments.')
    import setup_connection
    modes.add_argument('--connect', choices=setup_connection.CONNECT_SERVICES, help='Validate and save an account; key arrives on stdin.')
    modes.add_argument('--guide', choices=setup_connection.SERVICES, help='Show shared setup instructions; no credentials.')
    modes.add_argument('--extra', choices=setup_connection.SERVICES, help='Save an optional setting from stdin or check a local connection.')
    parser.add_argument('--group-id', default='')
    parser.add_argument('--group', action='store_true', default=None)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if args.guide:
        title, url, _, instructions = setup_connection.SERVICES[args.guide]
        print(f'{title}\n{instructions}\n{url}')
        return 0
    if args.extra:
        raw = '' if args.extra in ('desktop', 'kimi') else sys.stdin.read()
        values = setup_connection.accept(args.extra, raw, group=args.group, group_id=args.group_id)
        setup_connection.save_account(values)
        print('设置已保存。' if setup_connection.SERVICES[args.extra][2] else '连接检查通过，已启用。')
        return 0
    if args.connect:
        values = setup_connection.connect(args.connect, sys.stdin.read(), group=args.group, group_id=args.group_id)
        setup_connection.save_account(values)
        print('连接成功，已安全保存。')
        return 0
    if args.check:
        return check(as_json=args.json, group=bool(args.group))
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
        return 0
    print('请重新运行安装向导；Windows 双击 install/setup.cmd，macOS/Linux 运行 bash install/setup.sh。')
    return 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc) if isinstance(exc, ValueError) else f'配置未完成（{type(exc).__name__}）；已保存的项目会保留，请重跑向导。')
        raise SystemExit(1)
    except (KeyboardInterrupt, EOFError):
        print('\n已保存填写的配置；重跑向导可继续。')
        raise SystemExit(130)
