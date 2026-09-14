"""Native setup operations: no UI, no secret logging, and no paper uploads."""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import agent_installation
import capability
import configure
import credentials

EXTRAS = {
    'kimi': ('Kimi WebBridge · 浏览器全文', 'https://www.kimi.com/products/kimi-webbridge', '',
             '需要从已登录的学校或机构网页获取全文时使用。\n① 打开页面，选择“搭配本地 Agent”，按 Windows 说明安装本地连接服务。\n② 安装并启用浏览器扩展，按扩展提示授权连接。\n③ 点击下方“启动并检查”。机构账号需要你自己在浏览器中登录。'),
    'semantic_scholar': ('Semantic Scholar · 补充学术检索', 'https://www.semanticscholar.org/product/api', 'SEMANTIC_SCHOLAR_API_KEY',
                         '补充论文、摘要和引用信息。\n① 打开官网，找到 API Key 申请入口并提交申请。\n② 申请可能需要等待；收到授权码后再回来粘贴。\n③ 点击“保存设置”。没有授权码可先跳过。'),
    'openalex': ('OpenAlex · 文献来源授权', 'https://openalex.org', 'OPENALEX_API_KEY',
                '为 OpenAlex 文献检索提供账号授权。\n① 打开官网，登录并进入账号/API 设置。\n② 复制 API Key，粘贴到下方后保存。使用额度以官网说明为准。'),
    'crossref': ('Crossref · 题录查询联系邮箱', 'https://www.crossref.org/documentation/retrieve-metadata/rest-api/', 'CROSSREF_MAILTO',
                '为 Crossref 题录查询提供联系邮箱。\n填写你可收信的邮箱即可，不需要授权码或邮箱密码。\n查询时邮箱会发送给 Crossref，用于服务方联系。'),
    'unpaywall': ('Unpaywall · 查找开放全文', 'https://unpaywall.org/products/api', 'UNPAYWALL_EMAIL',
                 '帮助查找合法开放的论文全文。\n填写你可收信的邮箱即可，不需要授权码或邮箱密码。\n查询时邮箱会发送给 Unpaywall；全文是否可得取决于论文。'),
    'desktop': ('Zotero Desktop · 本机附件', 'https://www.zotero.org/download', '',
                '希望在电脑上的 Zotero 阅读附件时使用。\n① 安装并打开 Zotero，登录账号。\n② 在高级设置开启本地 API。\n③ 在同步设置启用附件同步与自动下载，再点击“检查本机 Zotero”。'),
}


def extra_value(service: str) -> str:
    return credentials.source_setting(service)


def extra_settings(service: str, value: str) -> dict[str, str]:
    if service not in EXTRAS or not EXTRAS[service][2]:
        raise ValueError('请选择一个文献来源。')
    value = normalize_key(value)
    if service in ('crossref', 'unpaywall'):
        import re
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('请输入可收信的完整邮箱地址，例如 name@example.org。')
    return {EXTRAS[service][2]: value}


def enable_kimi() -> dict[str, str]:
    binary = capability.KIMI_BINARY
    if not binary.is_file():
        raise ValueError('尚未找到本地连接服务。请先按官网的本地 Agent 安装说明完成安装，再重试。')
    state = capability.probe_kimi(binary)
    if not state.get('running'):
        try:
            result = subprocess.run([str(binary), 'start'], capture_output=True, timeout=30,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.SubprocessError):
            raise ValueError('连接服务未能启动。请按官网说明修复后重试。') from None
        if result.returncode:
            raise ValueError('连接服务未能启动。请按官网说明修复后重试。')
        state = capability.probe_kimi(binary)
    if not state.get('running') or not state.get('extension_connected'):
        raise ValueError('浏览器扩展尚未连接。请启用扩展并按提示授权，等待约 30 秒后重试。')
    return {'SETUP_BROWSER': '1'}


def enable_desktop() -> dict[str, str]:
    for name in ('zotero-local', 'zotero-sync'):
        record = configure.probe(name)
        if not record['ok']:
            raise ValueError(str(record['action']))
    return {'SETUP_DESKTOP': '1'}


def normalize_key(value: str) -> str:
    value = value.strip()
    if not credentials.usable_secret(value) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('没有收到完整授权码，请重新复制网页上的授权码，再点击“粘贴”。')
    return value


def existing_key(service: str) -> str:
    value = (credentials.zotero_credentials()['api_key'] if service == 'zotero'
             else credentials.mineru_token())
    try:
        return normalize_key(value)
    except ValueError:
        return ''


def library_target(group: bool | None = None, group_id: str = '') -> tuple[bool, str]:
    account = credentials.zotero_credentials()
    use_group = account['library_type'] == 'group' if group is None else group
    if use_group and not group_id and account['library_type'] == 'group':
        group_id = account['library_id']
    return use_group, group_id


def connect(service: str, value: str, *, group_id: str = '', group: bool | None = None) -> dict:
    key = normalize_key(value)
    if service == 'mineru':
        record = capability.probe_mineru(key)
        if not record.get('valid'):
            if record.get('code') is None:
                raise ValueError('暂时连不上全文阅读服务。请检查网络后重试，已保存的授权不受影响。')
            raise ValueError('全文阅读服务未接受这个授权码，请检查是否复制完整或已过期，然后重试。')
        return {'MINERU_TOKEN': key}
    if service != 'zotero':
        raise ValueError('未知服务。')
    group, group_id = library_target(group, group_id)
    if group and (not group_id.isascii() or not group_id.isdigit() or int(group_id) <= 0):
        raise ValueError('请填写群组页面对应的数字文库 ID。个人文库不需要填写 ID。')
    account = capability.zotero_key_info(key)
    library_id = group_id if group else capability.zotero_personal_id(account)
    access = capability.zotero_library_access(account, library_id, 'group' if group else 'user')
    if not access['identity_match'] or not access['write_permission']:
        raise ValueError('授权码缺少文库读写权限。请在 Zotero 网页勾选 Library access 和 Write access 后重试。')
    return {'ZOTERO_API_KEY': key, 'ZOTERO_LIBRARY_ID': library_id,
            'ZOTERO_LIBRARY_TYPE': 'group' if group else 'user'}


def save_account(values: dict[str, str]) -> None:
    """Commit an accepted connection and stop stale inherited values shadowing it."""
    configure.save_many(values)
    for key in values:
        os.environ.pop(key, None)


def prepare(agent: str) -> None:
    directory = Path.home() / '.config/literature-to-zotero'
    pdf = os.environ.get('PAPER2ZOTERO_PDF_BIN', '')
    tool = Path(pdf) / 'pdftotext.exe' if pdf else Path(shutil.which('pdftotext') or '')
    if not tool.is_file():
        raise ValueError('PDF 工具尚未就绪，请从 install/setup.cmd 重新打开。')
    result = subprocess.run([str(tool), '-v'], capture_output=True, timeout=10,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('PDF 工具无法运行，请从 install/setup.cmd 重新打开。')
    with contextlib.redirect_stdout(io.StringIO()):
        importlib.import_module('install').install(agent)
    directory.mkdir(parents=True, exist_ok=True)
    python = Path(sys.executable).with_name('python.exe') if os.name == 'nt' else Path(sys.executable)
    (directory / 'python-path').write_text(str(python) + '\n', encoding='utf-8')
    (directory / 'pdf-bin').write_text(str(tool.parent) + '\n', encoding='utf-8')


def check(agent: str) -> dict:
    executable = Path(sys.executable).with_name('python.exe') if os.name == 'nt' else Path(sys.executable)
    result = subprocess.run([str(executable), str(Path(__file__).with_name('configure.py')), '--check', '--json'],
                            capture_output=True, text=True, encoding='utf-8', timeout=150,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                            env={**os.environ, 'PYTHONUTF8': '1', 'PAPER2ZOTERO_AGENT': agent})
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise ValueError('检查暂未完成，请稍后重试。已保存的设置会保留。') from None


def open_page(url: str) -> None:
    if url not in {'https://www.zotero.org/settings/keys', 'https://mineru.net/apiManage/token',
                   *(record[1] for record in EXTRAS.values())}:
        raise ValueError('未知的授权页面。')
    if os.name == 'nt':
        os.startfile(url)
    else:
        import webbrowser
        if not webbrowser.open(url):
            raise OSError('Browser unavailable')
