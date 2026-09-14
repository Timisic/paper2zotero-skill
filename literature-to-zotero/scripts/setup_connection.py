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
import urllib.error
import urllib.request

import agent_installation
import capability
import configure
import credentials
from http_client import SafeRedirect


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


def connect(service: str, value: str, *, group_id: str = '', group: bool = False) -> dict:
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
    if group and (not group_id.isascii() or not group_id.isdigit() or int(group_id) <= 0):
        raise ValueError('请填写群组页面对应的数字文库 ID。个人文库不需要填写 ID。')
    request = urllib.request.Request('https://api.zotero.org/keys/current',
                                     headers={'Zotero-API-Key': key, 'Zotero-API-Version': '3'})
    try:
        with urllib.request.build_opener(SafeRedirect()).open(request, timeout=15) as response:
            account = json.load(response)
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        if code in (401, 403):
            raise ValueError('Zotero 未接受这个授权码，请重新复制完整授权码，或检查它是否已被撤销。') from None
        if code == 429:
            raise ValueError('Zotero 暂时限制了请求次数，请稍后点击“验证并保存”。') from None
        raise ValueError('Zotero 服务暂时不可用，请稍后重试。') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError('暂时连不上 Zotero。请检查网络后重试，不需要手动查找文库 ID。') from None
    except (ValueError, TypeError):
        raise ValueError('Zotero 返回的信息无法读取，请稍后重试。') from None
    if not isinstance(account, dict):
        raise ValueError('Zotero 没有返回个人文库信息，请稍后重试。')
    library_id = group_id if group else str(account.get('userID', ''))
    if not library_id.isascii() or not library_id.isdigit() or int(library_id) <= 0:
        raise ValueError('Zotero 没有返回有效的文库信息，请稍后重试。')
    access = account.get('access') or {}
    if not isinstance(access, dict):
        access = {}
    if group:
        groups = access.get('groups') or {}
        rights = (groups.get(group_id) or groups.get('all') or {}) if isinstance(groups, dict) else {}
    else:
        rights = access.get('user') or {}
    if not isinstance(rights, dict) or not (rights.get('library') and rights.get('write')):
        raise ValueError('授权码缺少文库读写权限。请在 Zotero 网页勾选 Library access 和 Write access 后重试。')
    return {'ZOTERO_API_KEY': key, 'ZOTERO_LIBRARY_ID': library_id,
            'ZOTERO_LIBRARY_TYPE': 'group' if group else 'user'}


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
    if url not in {'https://www.zotero.org/settings/keys', 'https://mineru.net/apiManage/token'}:
        raise ValueError('未知的授权页面。')
    if os.name == 'nt':
        os.startfile(url)
    else:
        import webbrowser
        if not webbrowser.open(url):
            raise OSError('Browser unavailable')
