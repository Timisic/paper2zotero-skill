"""Install and check one module at a time; stop at the first required module that is not ready.

Usage: modules.py [--agent codex|claude-code|pi|all] [runtime skills zotero mineru kimi]
With no module names, every module runs in order. Rerunning is safe: finished modules are kept.
"""
from __future__ import annotations

import argparse
import getpass
import importlib
import os
import sys

import agent_installation
import setup_connection as connection

AGENTS = {'1': 'codex', '2': 'claude-code', '3': 'pi'}


def ask(prompt: str) -> str:
    if not sys.stdin.isatty():
        return ''
    try:
        return input('  ' + prompt).strip()
    except EOFError:
        return ''


def install_runtime(agent: str) -> None:
    print(f'  运行环境：{connection.ensure_default_tools()}')


def install_skills(agent: str) -> None:
    try:
        importlib.import_module('install').install(agent)
    except SystemExit as error:
        raise ValueError(str(error)) from None


def open_zotero(agent: str) -> None:
    print('  ' + connection.SERVICES['desktop'][3].replace('\n', '\n  '))
    ask('完成后回车检查：')


def configure_mineru(agent: str) -> None:
    choice = ask('1 = MinerU 云端 Token，2 = 自建 MinerU 地址（IP 或域名），回车跳过：')
    if choice not in ('1', '2'):
        return
    service = 'mineru' if choice == '1' else 'mineru_api'
    _, url, _, instructions = connection.SERVICES[service]
    print('  ' + instructions.replace('\n', '\n  ') + '\n  ' + url)
    value = getpass.getpass('  粘贴 MinerU Token（输入不显示）：') if service == 'mineru' else ask('MinerU 服务地址：')
    if value:
        connection.save_account(connection.accept(service, value))


def all_ok(rows: list[dict]) -> bool:
    return bool(rows) and all(row['ok'] for row in rows)


# name: (title, purpose, required, setup step, check-row name prefixes, ready test)
MODULES = {
    'runtime': ('运行环境', 'Python、scansci-pdf（检索和下载）、markitdown（PDF 转 Markdown）', True,
                install_runtime, ('运行工具', '论文检索', '全文转换'), all_ok),
    'skills': ('文献 skill', '把 6 个 skill 装进你的 AI 助手', True,
               install_skills, ('连接 AI 助手',), all_ok),
    'zotero': ('Zotero 本地 API', '保存论文；写作 skill 也从这里读取', True,
               open_zotero, ('Zotero 本地 API',), all_ok),
    'mineru': ('MinerU', '更好的 PDF 转换；不配置就用本机 markitdown', False,
               configure_mineru, ('全文转换',), lambda rows: all_ok(rows) and 'MinerU' in rows[0]['detail']),
    'kimi': ('Kimi WebBridge', '用学校或机构的浏览器登录下载全文的备用通道；由你自己安装，这里只检查', False,
             lambda agent: None, ('Kimi',), all_ok),
}


def run(name: str, index: int, total: int, agent: str) -> bool:
    title, purpose, required, setup, prefixes, ready = MODULES[name]
    print(f'\n[{index}/{total}] {title}（{"必需" if required else "可选"}）：{purpose}')
    while True:
        try:
            setup(agent)
        except ValueError as error:
            print(f'  {error}')
        try:
            rows = [row for row in connection.check(agent)['items'] if row['name'].startswith(prefixes)]
        except ValueError as error:
            print(f'  {error}')
            rows = []
        for row in rows:
            mark = '✓' if row['ok'] else ('待完成' if required else '○')
            print(f"  {mark} {row['name']}" + (f"：{row['detail']}" if row.get('detail') else ''))
            if not row['ok'] and row.get('action'):
                print(f"    下一步：{row['action']}")
        if ready(rows):
            return True
        if all_ok(rows):
            print(f'  {"待完成" if required else "○"} 未配置 {title}')
        if ask('输入 r 重试，回车继续：').lower() != 'r':
            return False


def choose_agent(agent: str) -> str:
    if agent_installation.selected_roots(agent):
        return agent
    choice = ask('你要在哪个 AI 助手中使用？1 = Codex，2 = Claude Code，3 = Pi：')
    if choice not in AGENTS:
        raise SystemExit('未找到 AI 助手。请加 --agent codex、--agent claude-code 或 --agent pi 后重跑。')
    return AGENTS[choice]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--agent', choices=agent_installation.CHOICES, default=os.environ.get('PAPER2ZOTERO_AGENT', 'auto'))
    parser.add_argument('modules', nargs='*', metavar='module', help=' | '.join(MODULES))
    args = parser.parse_args()
    if set(args.modules) - set(MODULES):
        parser.error('模块只能是：' + '、'.join(MODULES))
    names = args.modules or list(MODULES)
    agent = choose_agent(args.agent)
    os.environ['PAPER2ZOTERO_AGENT'] = agent
    results = {}
    for index, name in enumerate(names, 1):
        results[name] = run(name, index, len(names), agent)
        if not results[name] and MODULES[name][2]:
            break
    print('\n结果：')
    for name in names:
        title, _, required, *_ = MODULES[name]
        state = results.get(name)
        print(f"  {'✓' if state else ('待完成' if required else '○')} {title}" + ('' if name in results else '（未运行）'))
    missing = [MODULES[name][0] for name in names if MODULES[name][2] and not results.get(name)]
    if missing:
        print(f"未完成：{'、'.join(missing)}。按上面的“下一步”处理后，重跑这个模块即可，已完成的模块会保留。")
        return 1
    print('必需模块全部就绪：可以找论文、保存到 Zotero，并用写作 skill 读取 Zotero 集合。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
