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

BASIC_SERVICES = ('desktop',)
CONNECT_SERVICES = ('zotero', 'mineru')
EXTRA_SERVICES = ('mineru', 'mineru_api')
SERVICES = {
    'zotero': (
        '连接 Zotero Web API',
        'https://www.zotero.org/settings/keys',
        'ZOTERO_API_KEY',
        '默认写入走本机 Desktop。群组文库，或 ZOTERO_WRITE_BACKEND=web，才需要这个授权码。\n'
        '① 创建授权码，勾选 Library access、Notes access 和 Write access。\n'
        '② 粘贴完整 Key。个人文库 ID 会自动识别。',
    ),
    'mineru': (
        'MinerU 云端 Token',
        'https://mineru.net/apiManage/token',
        'MINERU_TOKEN',
        '可选。PDF 转 Markdown 先用 MinerU，失败或不配置时用本机 markitdown。\n'
        '① 在 API 管理页面创建 Token。\n'
        '② 粘贴后验证。',
    ),
    'mineru_api': (
        '自建 MinerU 地址',
        'https://github.com/opendatalab/MinerU',
        'MINERU_API_BASE',
        '可选。已在本机或内网部署 MinerU 服务时填写，转换时优先使用它。\n'
        '填写 IP 或域名，例如 192.168.1.20:8000 或 https://mineru.example.org。\n'
        '保存前会检查服务的 /v1/health。',
    ),
    'desktop': (
        'Zotero 本地 API',
        'https://www.zotero.org/download',
        '',
        '基础配置要本机 Zotero 能写入。\n'
        '① 打开 Zotero，进入 设置 → 高级。\n'
        '② 勾选「允许此计算机上的其他应用程序与 Zotero 通讯」。\n'
        '③ 回到这里点检查。Zotero 弹出授权框时选「始终允许」。',
    ),
}


def accept(service: str, value: str = '', *, group_id: str = '', group: bool | None = None) -> dict[str, str]:
    if service == 'desktop':
        return enable_desktop()
    if service == 'mineru_api':
        return {'MINERU_API_BASE': mineru_address(value)}
    return connect(service, value, group_id=group_id, group=group)


def extra_value(service: str) -> str:
    return credentials.mineru_api_base() if service == 'mineru_api' else existing_key(service)


def mineru_address(value: str) -> str:
    """Accept an IP or domain, with or without scheme and port, that answers /v1/health."""
    import urllib.parse
    import mineru_parse
    value = value.strip()
    if value and '://' not in value:
        value = 'http://' + value
    value = value.rstrip('/')
    parts = urllib.parse.urlsplit(value)
    try:
        parts.port
    except ValueError:
        parts = None
    if not parts or parts.scheme not in ('http', 'https') or not parts.hostname or parts.query or parts.fragment:
        raise ValueError('请填写 MinerU 服务的 IP 或域名，例如 192.168.1.20:8000 或 https://mineru.example.org。')
    if not mineru_parse.tasks_health(value, timeout=10).get('ok'):
        raise ValueError(f'连不上 {value}/v1/health。请确认 MinerU 服务已启动、地址和端口正确，然后重试。')
    return value


def enable_desktop() -> dict[str, str]:
    if not capability.probe_zotero_local_write():
        raise ValueError(capability.GUIDE['zotero_local']['do'])
    return {'SETUP_DESKTOP': '1'}


def normalize_key(value: str) -> str:
    value = value.strip()
    if not credentials.usable_secret(value) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('没有收到完整授权码，请重新复制网页上的授权码，再点击“粘贴”。')
    return value


def existing_key(service: str) -> str:
    if service == 'zotero':
        value = credentials.zotero_credentials()['api_key']
    elif service == 'mineru':
        value = credentials.mineru_token()
    else:
        return ''
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
    if service not in CONNECT_SERVICES:
        raise ValueError('未知服务。')
    key = normalize_key(value)
    if service == 'mineru':
        record = capability.probe_mineru(key)
        if not record.get('valid'):
            if record.get('code') is None:
                raise ValueError('暂时连不上全文阅读服务。请检查网络后重试，已保存的授权不受影响。')
            raise ValueError('全文阅读服务未接受这个授权码，请检查是否复制完整或已过期，然后重试。')
        return {'MINERU_TOKEN': key}
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


RUNTIME = agent_installation.shared_path('runtime')
# An offline bundle carries runtime/python and runtime/wheels at its root.
BUNDLE = Path(__file__).resolve().parents[2] / 'runtime'
MIRROR = 'https://pypi.tuna.tsinghua.edu.cn/simple'


def runtime_python(root: Path) -> Path:
    if os.name != 'nt':
        return root / 'bin/python3'
    # python-build-standalone keeps python.exe at its root; a venv keeps it in Scripts.
    return root / 'python.exe' if (root / 'python.exe').is_file() else root / 'Scripts/python.exe'


def _succeeds(command: list[str], timeout: int = 900) -> bool:
    try:
        return subprocess.run(command, capture_output=True, timeout=timeout,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_default_tools() -> Path:
    """Install scansci-pdf and markitdown into the private runtime and record its interpreter."""
    import scansci_retrieval
    packages = [f'scansci-pdf=={scansci_retrieval.PIN}', 'markitdown[pdf]']
    probe = ['-c', f'import importlib.metadata as m, markitdown; '
                   f'assert m.version("scansci-pdf") == "{scansci_retrieval.PIN}"']
    python = runtime_python(RUNTIME)
    if not (python.is_file() and _succeeds([str(python), *probe], 120)):
        if (BUNDLE / 'python').is_dir() and (BUNDLE / 'wheels').is_dir():
            shutil.rmtree(RUNTIME, ignore_errors=True)
            try:
                shutil.copytree(BUNDLE / 'python', RUNTIME, symlinks=True, dirs_exist_ok=True)
            except OSError:
                raise ValueError(f'无法把离线安装包中的 Python 复制到 {RUNTIME}。请检查磁盘空间和目录权限后重试。') from None
            python = runtime_python(RUNTIME)
            if not _succeeds([str(python), '-m', 'pip', 'install', '--no-index',
                              '--find-links', str(BUNDLE / 'wheels'), *packages]):
                raise ValueError('离线安装包中的依赖安装失败。请重新解压完整的离线安装包后重试。')
        else:
            if not python.is_file():
                shutil.rmtree(RUNTIME, ignore_errors=True)
                if not _succeeds([sys.executable, '-m', 'venv', str(RUNTIME)], 300):
                    shutil.rmtree(RUNTIME, ignore_errors=True)
                    minor = f'python3.{sys.version_info.minor}-venv'
                    raise ValueError(f'无法创建独立 Python 环境。Debian/Ubuntu 请先运行 sudo apt-get install {minor}，然后重试。'
                                     if sys.platform.startswith('linux') else
                                     '无法创建独立 Python 环境。请重新安装 Python 3.11+ 后重试。')
                python = runtime_python(RUNTIME)
            install = [str(python), '-m', 'pip', 'install', *packages]
            if not _succeeds(install) and (os.environ.get('PIP_INDEX_URL') or not _succeeds([*install, '-i', MIRROR])):
                raise ValueError('依赖下载失败，PyPI 和清华镜像都无法访问。请检查网络，或改用离线安装包。'
                                 f'（{scansci_retrieval.INSTALL_LINE}）')
        if not _succeeds([str(python), *probe], 120):
            raise ValueError('依赖安装后仍无法导入 scansci-pdf 或 markitdown。请重跑 setup。')
    directory = Path.home() / '.config/literature-to-zotero'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'python-path').write_text(str(python) + '\n', encoding='utf-8')
    return python


def prepare(agent: str) -> None:
    ensure_default_tools()
    with contextlib.redirect_stdout(io.StringIO()):
        importlib.import_module('install').install(agent)


def check(agent: str, *, group: bool = False) -> dict:
    executable = runtime_python(RUNTIME)
    if not executable.is_file():
        executable = Path(sys.executable).with_name('python.exe') if os.name == 'nt' else Path(sys.executable)
    command = [str(executable), str(Path(__file__).with_name('configure.py')), '--check', '--json']
    if group:
        command.append('--group')
    result = subprocess.run(command,
                            capture_output=True, text=True, encoding='utf-8', timeout=150,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                            env={**os.environ, 'PYTHONUTF8': '1', 'PAPER2ZOTERO_AGENT': agent})
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise ValueError('检查暂未完成，请稍后重试。已保存的设置会保留。') from None


def open_page(url: str) -> None:
    if url not in {record[1] for record in SERVICES.values()}:
        raise ValueError('未知的授权页面。')
    if os.name == 'nt':
        getattr(os, 'startfile')(url)
    else:
        import webbrowser
        if not webbrowser.open(url):
            raise OSError('Browser unavailable')


if __name__ == '__main__':
    # Windows -DependenciesOnly entry: prepare the runtime and skills without Git Bash.
    try:
        prepare(sys.argv[1] if len(sys.argv) > 1 else 'auto')
    except ValueError as error:
        raise SystemExit(str(error)) from None
    print(f'✓ 运行环境和 skill 已安装：{runtime_python(RUNTIME)}')
