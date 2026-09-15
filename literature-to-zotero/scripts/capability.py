#!/usr/bin/env python3
"""Single home for "can this machine run the skill?" capability checks.

A **capability** is one runtime precondition with a single record of
{ok, detail, remediation}. Probe functions measure facts (a file, a local
HTTP call, a daemon status) and are deterministic given their source;
judgement functions are pure and turn measured facts into a record, so the
semantics are written and tested once.

The three CLIs that used to duplicate probes and judgements now share this
module:
  scripts/preflight.py — run the probes, combine the capability records into
      a report plus one "ready" decision.
  scripts/verify.py    — thin per-stage caller (one command per capability).
  scripts/setup.py     — setup doctor: render the records as a human action
      checklist; missing items get their remediation.

Example semantic that lives here only: in Zotero 7 the attachment file-sync
preference is ON by default, so an absent prefs.js key means enabled
(storage_sync_enabled=None is NOT a failure; an explicit `false` is).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

from agent_installation import installed_paths

# A capability record. `detail` describes the measured state; `remediation`
# is the human action that fixes a missing capability. Never contains secrets.
Record = dict[str, str | bool]

ZOTERO_LOCAL_API = "http://127.0.0.1:23119/api/users/0/items?limit=1"
ZOTERO_API_BASE = "https://api.zotero.org"
KIMI_BINARY = Path.home() / ".kimi-webbridge" / "bin" / ("kimi-webbridge.exe" if os.name == "nt" else "kimi-webbridge")

# One canonical human fix per capability (single source for install
# knowledge, C3). The setup doctor renders `do` for a missing item; the setup
# wizard prints the same `do` and opens `url` when present. Fields are plain
# single-line strings (no newlines) so bash can consume them. Never contain
# secrets.
#
# `url` is only the page the wizard should open; the doctor never opens
# pages. State-specific follow-ups that only the doctor shows (e.g. a live
# key mismatch) live beside GUIDE as separate constants.
GUIDE: dict[str, dict[str, str]] = {
    "zotero_local": {
        "label": "Zotero Desktop 本地 API",
        "url": "https://www.zotero.org/download",
        "do": "打开 Zotero Desktop 并保持运行；首次需在设置开启本地 API（高级 → 本地接口）。",
    },
    "zotero_sync": {
        "label": "Zotero 附件文件同步",
        "url": "",
        "do": "Zotero → 偏好设置 → 同步 → 设置：勾选“同步附件文件”以及“下载从其他设备添加的文件”，然后点右上角同步。",
    },
    "zotero_mcp": {
        "label": "Zotero MCP 已配置",
        "url": "",
        "do": "在运行时配置里注册 zotero MCP（本机已验证 54yyyu/zotero-mcp），command 须可执行；配置路径见 setup doctor 的“关键路径”。",
    },
    "zotero_key": {
        "label": "Zotero Web API key",
        "url": "https://www.zotero.org/settings/keys",
        "do": "New API key（名称随意）→ 勾选个人文库 Read/Write（含 Notes/Files）→ Save Key → 立即复制（只显示一次）。把 key 交给向导隐藏录入（文库 ID 由向导自动获取）；不用向导时也可存入 env 的 ZOTERO_API_KEY / ZOTERO_LIBRARY_ID。凭据绝不进入聊天/日志/命令。",
    },
    "kimi": {
        "label": "Kimi WebBridge",
        "url": "https://www.kimi.ai/products/kimi-webbridge",
        "do": "安装 daemon：curl -fsSL https://cdn.kimi.com/webbridge/install.sh | bash；再按产品页安装并启用浏览器扩展（Chrome/Arc/Edge）。扩展刚启用时 daemon 需约 30 秒重连。",
    },
    "mineru": {
        "label": "MinerU token",
        "url": "https://mineru.net/apiManage/token",
        "do": "登录 mineru.net → API 管理 → 创建 Token（名称随意；数量已满先删旧 token）→ 立即复制（只显示一次，token 以 sk- 开头才是 API token）。把 token 交给向导隐藏录入，或保存到 ~/.config/mineru/token（0600）与 $MINERU_TOKEN。",
    },
    "discovery_sources": {
        "label": "文献检索来源",
        "url": "https://www.semanticscholar.org/product/api",
        "do": "在配置向导的“连接 OpenAlex（必配）”填写授权码并验证。Semantic Scholar、Crossref 和 Unpaywall 在最后的“更多配置”中按需填写。实际检索仍按各来源的响应报告可用情况。",
    },
    "skill_links": {
        "label": "skill 安装",
        "url": "",
        "do": "重跑安装入口；用 --agent codex、--agent claude-code 或 --agent pi 指定使用的助手。Windows 对应 -Agent 参数，使用目录复制，无需符号链接权限。",
    },
}

# Doctor-only, state-specific follow-ups (no wizard stage uses them).
KEY_LIVE_NOTE = "确认 key 属于当前 Zotero 桌面登录的账号且具备 library 写权限；撤销在聊天出现过的 key。"
KEY_SKIP_NOTE = "运行在线检查（不带 --skip-live 的 doctor / preflight）以验证 key 的身份与写权限。"



def _record(ok: bool, detail: str, remediation: str) -> Record:
    return {"ok": ok, "detail": detail, "remediation": remediation}


def _fix(key: str) -> str:
    """The canonical human fix text for a capability (GUIDE entry)."""
    return GUIDE[key]["do"]


# ── Probes: measure facts. Deterministic given their source. ───────────────

def zotero_profiles_dirs(
    platform: str | None = None, home: Path | None = None, appdata: str | None = None
) -> list[Path]:
    """Where Zotero keeps its profiles, per OS. Pure given its arguments.

    Zotero is cross-platform and so is this skill; hard-coding the macOS path
    made every Windows and Linux install report "attachment sync off" when it
    was only looking in the wrong place.
    """
    system = platform if platform is not None else sys.platform
    base = home if home is not None else Path.home()
    if system == "darwin":
        return [base / "Library" / "Application Support" / "Zotero" / "Profiles"]
    if system.startswith("win"):
        roaming = Path(appdata) if appdata else Path(os.environ.get("APPDATA", str(base / "AppData" / "Roaming")))
        return [roaming / "Zotero" / "Zotero" / "Profiles"]
    return [base / ".zotero" / "zotero", base / "snap" / "zotero" / "common" / ".zotero" / "zotero"]


def default_zotero_prefs() -> Path:
    """Newest Zotero profile's prefs.js, or an empty Path when none exists."""
    for profiles in zotero_profiles_dirs():
        candidates = sorted(profiles.glob("*/prefs.js"))
        if candidates:
            return candidates[0]
    return Path()


def zotero_prefs(prefs_path: Path | None = None) -> dict[str, Any]:
    """Read attachment-sync preferences out of a Zotero prefs.js file.

    Absent keys are returned as None — an absent sync key is the Zotero 7
    default ON state, never a judgement of disabled.
    """
    path = prefs_path if prefs_path is not None else default_zotero_prefs()
    result: dict[str, Any] = {
        "prefs_found": path.is_file(),
        "data_dir": None,
        "storage_sync_enabled": None,
        "download_associated_files": None,
    }
    if not path.is_file():
        return result
    text = path.read_text(encoding="utf-8", errors="ignore")
    data_dir = re.search(r'user_pref\("extensions\.zotero\.dataDir", "([^"]+)"\);', text)
    storage = re.search(r'user_pref\("extensions\.zotero\.sync\.storage\.enabled", (true|false)\);', text)
    download = re.search(r'user_pref\("extensions\.zotero\.downloadAssociatedFiles", (true|false)\);', text)
    result["data_dir"] = data_dir.group(1) if data_dir else None
    result["storage_sync_enabled"] = storage.group(1) == "true" if storage else None
    result["download_associated_files"] = download.group(1) == "true" if download else None
    return result


def probe_zotero_local(timeout: int = 3) -> bool:
    """Zotero Desktop's local API answers on 127.0.0.1:23119 while it runs."""
    try:
        with urllib.request.urlopen(ZOTERO_LOCAL_API, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def probe_discovery_search(key: str | None = None) -> dict[str, Any]:
    """Setup requires an explicit OpenAlex key and a successful real query.

    Runtime source fallback remains independent of onboarding completeness.
    A candidate key is scoped to this probe, never saved or put in the process env.
    """
    import credentials
    from sources import Sources, Query
    key = credentials.source_setting('openalex') if key is None else key
    if not credentials.usable_secret(key):
        return {'ok': False, 'detail': '请先配置 OpenAlex 授权码，基础论文检索尚未完成。',
                'sources': {'OpenAlex': 'not_configured'}}
    client = Sources(timeout=10, budget=15, attempts=1,
                     setting=lambda source: key if source == 'openalex' else '')
    try:
        answer = client.search('openalex', Query(text='mental health', limit=1), budget=15)
        status, ok = answer.status, answer.ok
    except (OSError, ValueError, TypeError, AttributeError):
        status, ok = 'unavailable', False
    hints = {'authentication_required': 'OpenAlex 未接受授权码，请检查是否复制完整或已过期。',
             'rate_limited': 'OpenAlex 请求次数或账号额度暂时受限，请稍后重试或查看账号额度。'}
    detail = ('OpenAlex 授权检索通过' if ok else
              hints.get(status, 'OpenAlex 暂时无法完成检索，请检查网络和账号授权后重试；已保存配置保留。'))
    return {'ok': ok, 'detail': detail, 'sources': {'OpenAlex': status}}


def kimi_binary() -> Path:
    """Resolve both the standard installation and an existing PATH install."""
    return KIMI_BINARY if KIMI_BINARY.is_file() else Path(shutil.which('kimi-webbridge') or KIMI_BINARY)


def probe_kimi(binary: Path | None = None, live: bool = True) -> dict[str, str | bool | None]:
    """Ask the Kimi WebBridge daemon whether it and the browser extension run.

    When live is False only the binary's presence is measured (--skip-live).
    """
    executable = binary if binary is not None else kimi_binary()
    installed = executable.is_file()
    status: dict[str, str | bool | None] = {
        "installed": installed,
        "running": None,
        "extension_connected": None,
        "skipped": not live,
        "error": "",
    }
    if not installed or not live:
        return status
    try:
        completed = subprocess.run(
            [str(executable), "status"], text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=15,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        )
    except (OSError, subprocess.SubprocessError):
        status["error"] = "daemon status call failed"
        return status
    if completed.returncode != 0:
        status["error"] = completed.stderr.strip() or "daemon status exited non-zero"
        return status
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        status["error"] = "unexpected daemon status output"
        return status
    status["running"] = bool(payload.get("running"))
    status["extension_connected"] = payload.get("extension_connected") is True
    return status


# External data sources the workflow reads. Reachability here is *advisory*:
# it flaps minute to minute on restricted networks, every caller retries and
# then falls back to the user's browser, and `doi.org` is never on the
# critical path because DOIs are resolved from metadata instead. A red row is
# a hint for a human, never a reason to refuse to run.
EXTERNAL_SOURCES = {
    "crossref": "https://api.crossref.org/works/10.1038/nature12373",
    "openalex": "https://api.openalex.org/works/doi:10.1038/nature12373",
    "arxiv": "https://export.arxiv.org/api/query?search_query=all:electron&max_results=1",
    "europepmc": "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=cancer&format=json",
    "zotero_api": "https://api.zotero.org/",
    "mineru": "https://mineru.net/",
}
REACHABILITY_NOTE = (
    "可达性仅供参考：受限网络下逐分钟波动，脚本会重试并在失败时改走浏览器通道；"
    "全红时先检查网络或代理，个别红色通常无需处理。"
)


def probe_reachable(url: str, timeout: int = 8) -> bool:
    """Can this host be opened at all, with or without the ambient proxy?"""
    request = urllib.request.Request(url, headers={"User-Agent": "literature-to-zotero/0.1"})
    for opener in (
        urllib.request.build_opener(),
        urllib.request.build_opener(urllib.request.ProxyHandler({})),
    ):
        try:
            with opener.open(request, timeout=timeout) as response:
                return 200 <= response.status < 500
        except urllib.error.HTTPError as exc:
            return exc.code < 500
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    return False


def probe_external_sources(live: bool = True, sources: Mapping[str, str] | None = None) -> dict[str, bool | None]:
    """Measure每个外部数据源是否可达；--skip-live 时全部为 None。"""
    catalogue = sources if sources is not None else EXTERNAL_SOURCES
    if not live:
        return {name: None for name in catalogue}
    return {name: probe_reachable(url) for name, url in catalogue.items()}


def reachability_report(results: Mapping[str, bool | None]) -> dict[str, Any]:
    """Shape the advisory section. Deliberately NOT a capability record: it
    has no `ok` field, so it cannot be mistaken for something that gates
    readiness."""
    measured = [value for value in results.values() if value is not None]
    return {
        "sources": dict(results),
        "reachable": sum(1 for value in measured if value),
        "measured": len(measured),
        "advisory": True,
        "note": REACHABILITY_NOTE,
    }


def command_available(command: str | None) -> bool:
    if not command:
        return False
    return Path(command).is_file() or shutil.which(command) is not None


def skill_link_roots(home: Path | None = None) -> list[str]:
    """Absolute paths at which this skill is reachable from agent runtimes."""
    return installed_paths(home)


class ZoteroConnectionError(ValueError):
    """Safe connection failure; HTTP refusal differs from unknown permissions."""
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def zotero_key_info(api_key: str, api_base_url: str = ZOTERO_API_BASE,
                    *, timeout: float = 8, attempts: int = 2) -> dict[str, Any]:
    from http_client import SafeRedirect
    request = urllib.request.Request(f"{api_base_url.rstrip('/')}/keys/current",
                                     headers={"Zotero-API-Key": api_key, "Zotero-API-Version": "3"})
    failure = ZoteroConnectionError('暂时连不上 Zotero，请检查网络后重试；不需要重新申请授权码。')
    openers = (urllib.request.build_opener(SafeRedirect()),
               urllib.request.build_opener(urllib.request.ProxyHandler({}), SafeRedirect()))
    for opener in openers[:attempts]:
        try:
            with opener.open(request, timeout=timeout) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise ValueError('invalid account')
            return payload
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            if code in (401, 403):
                raise ZoteroConnectionError('Zotero 未接受这个授权码，请检查是否复制完整或已被撤销。', code) from None
            if code == 429:
                raise ZoteroConnectionError('Zotero 暂时限制了请求次数，请稍后重试。', code) from None
            failure = ZoteroConnectionError('Zotero 服务暂时不可用，请稍后重试。', code)
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
        except (ValueError, TypeError):
            failure = ZoteroConnectionError('Zotero 返回的信息暂时无法读取，请稍后重试。')
    raise failure


def zotero_personal_id(payload: dict[str, Any]) -> str:
    identity = str(payload.get('userID', ''))
    if not identity.isascii() or not identity.isdigit() or int(identity) <= 0:
        raise ValueError('Zotero 没有返回个人文库信息，请稍后重试。')
    return identity


def zotero_library_access(payload: dict[str, Any], library_id: str,
                          library_type: str) -> dict[str, bool | None]:
    access = payload.get('access')
    access = access if isinstance(access, dict) else {}
    if library_type == 'user':
        rights = access.get('user')
        identity = str(payload.get('userID')) == str(library_id)
    elif library_type == 'group':
        groups = access.get('groups')
        groups = groups if isinstance(groups, dict) else {}
        rights = groups.get(str(library_id)) or groups.get('all')
        identity = bool(rights)
    else:
        rights, identity = None, False
    rights = rights if isinstance(rights, dict) else {}
    return {'reachable': True, 'identity_match': identity,
            'write_permission': bool(rights.get('library') and rights.get('write'))}


def zotero_key_access(api_key: str, library_id: str, library_type: str,
                      api_base_url: str = ZOTERO_API_BASE, *, timeout: float = 8,
                      attempts: int = 2) -> dict[str, bool | None]:
    try:
        payload = zotero_key_info(api_key, api_base_url, timeout=timeout, attempts=attempts)
    except ZoteroConnectionError as error:
        return {'reachable': error.code is not None, 'identity_match': None,
                'write_permission': False if error.code in (401, 403) else None}
    return zotero_library_access(payload, library_id, library_type)


def zotero_key_access_via_runtime(
    command: str, api_key: str, library_id: str, library_type: str, api_base_url: str
) -> dict[str, bool | None]:
    """Fall back to the zotero-mcp runtime's Python env for the same probe."""
    result: dict[str, bool | None] = {"reachable": False, "identity_match": None, "write_permission": None}
    try:
        setup = subprocess.run(
            [command, "setup-info"], text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return result
    match = re.search(r"Python path:\s*(.+)", setup.stdout)
    if not match or not Path(match.group(1).strip()).is_file():
        return result
    probe = """
import json, os, sys
sys.path.insert(0, sys.argv[4])
from capability import zotero_key_access
print(json.dumps(zotero_key_access(os.environ['ZOTERO_PREFLIGHT_KEY'], sys.argv[2], sys.argv[3], sys.argv[1])))
"""
    environment = dict(os.environ)
    environment["ZOTERO_PREFLIGHT_KEY"] = api_key
    try:
        completed = subprocess.run(
            [match.group(1).strip(), "-c", probe, api_base_url, str(library_id), library_type, str(Path(__file__).resolve().parent)],
            text=True, encoding='utf-8', errors='replace',
            capture_output=True,
            timeout=20,
            env=environment,
        )
        payload = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return result
    return {
        "reachable": bool(payload.get("reachable")),
        "identity_match": payload.get("identity_match"),
        "write_permission": payload.get("write_permission"),
    }


def probe_zotero_key(
    api_key: str,
    library_id: str,
    library_type: str,
    api_base_url: str = ZOTERO_API_BASE,
    command: str | None = None,
) -> dict[str, bool | None]:
    """Probe key access directly; fall back to the zotero-mcp runtime when the
    direct channel is unreachable and a command is known."""
    access = zotero_key_access(api_key, library_id, library_type, api_base_url)
    if access["reachable"] is not True and command:
        fallback = zotero_key_access_via_runtime(command, api_key, library_id, library_type, api_base_url)
        if fallback["reachable"]:
            access.update(fallback)
    return access


def probe_mineru(token: str) -> dict[str, Any]:
    """Live probe: does MinerU accept this token for a file-urls batch call?"""
    body = json.dumps(
        {"files": [{"name": "probe.pdf", "data_id": "probe"}], "model_version": "vlm"}
    ).encode()
    request = urllib.request.Request(
        "https://mineru.net/api/v4/file-urls/batch",
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except Exception as exc:  # noqa: BLE001
        return {"valid": False, "code": None, "msg": f"probe failed: {type(exc).__name__}"}
    return {"valid": payload.get("code") == 0, "code": payload.get("code"), "msg": payload.get("msg")}


# ── Judgements: pure functions turning measured facts into records. ─────────

def zotero_local(available: bool | None) -> Record:
    """Zotero Desktop is running and answers its local API."""
    if available is None:
        return _record(False, "在线探测已跳过（--skip-live）", _fix("zotero_local"))
    if available:
        return _record(True, "本地 API 应答 127.0.0.1:23119", _fix("zotero_local"))
    return _record(False, "本地 API 不可达（Zotero Desktop 未运行，或端口/代理被拦截）", _fix("zotero_local"))


def zotero_sync(prefs: Mapping[str, Any]) -> Record:
    """Desktop attachment file sync is on.

    storage_sync_enabled=None means Zotero 7 default ON; only an explicit
    `false` disables it. download_associated_files is a narrower, advisory
    switch and never gates this capability.
    """
    if not prefs.get("prefs_found"):
        return _record(False, "未找到 prefs.js（Zotero 是否已安装？）", _fix("zotero_sync"))
    enabled = prefs.get("storage_sync_enabled") is not False
    detail = (
        f"storage_sync={prefs.get('storage_sync_enabled')}（None=Zotero 7 默认开启）"
        f"download_associated={prefs.get('download_associated_files')}（参考值，不构成门槛）"
    )
    return _record(enabled, detail, _fix("zotero_sync"))


def kimi(status: Mapping[str, str | bool | None]) -> Record:
    """Kimi daemon is installed, running, and its browser extension connected."""
    installed = status.get("installed") is True
    if not installed:
        return _record(False, "daemon 未安装（~/.kimi-webbridge/bin/kimi-webbridge）", _fix("kimi"))
    if status.get("skipped") is True:
        return _record(False, "在线探测已跳过（--skip-live）", _fix("kimi"))
    error = status.get("error")
    if error:
        return _record(False, str(error), _fix("kimi"))
    running = status.get("running")
    connected = status.get("extension_connected")
    ok = running is True and connected is True
    return _record(ok, f"running={running} extension_connected={connected}", _fix("kimi"))


def zotero_mcp(configured: bool, command_available: bool) -> Record:
    """A zotero MCP server block exists and its command is executable."""
    if not configured:
        return _record(False, "运行时配置里缺少 zotero MCP（或凭据/env 未配置）", _fix("zotero_mcp"))
    if not command_available:
        return _record(False, "zotero MCP 已配置但 command 不可执行", _fix("zotero_mcp"))
    return _record(True, "zotero MCP 已注册且 command 可执行", _fix("zotero_mcp"))


def zotero_key(configured: bool, access: Mapping[str, bool | None] | None) -> Record:
    """Web API credentials exist and the key reaches, owns and can write the library."""
    if not configured:
        return _record(
            False,
            "凭据缺失（ZOTERO_API_KEY / ZOTERO_LIBRARY_ID）",
            _fix("zotero_key"),
        )
    if access is None:
        return _record(
            False,
            "凭据已配置；在线身份/写权限校验未执行（--skip-live）",
            KEY_SKIP_NOTE,
        )
    ok = (
        access.get("reachable") is True
        and access.get("identity_match") is True
        and access.get("write_permission") is True
    )
    detail = (
        f"reachable={access.get('reachable')} "
        f"identity_match={access.get('identity_match')} "
        f"write_permission={access.get('write_permission')}"
    )
    remediation = KEY_LIVE_NOTE
    if access.get("identity_match") is None and access.get("write_permission") is None:
        remediation = "未取得身份/权限证据，不代表密钥无效。继续不依赖 Zotero 的步骤；入库时使用脚本的有界重试。"
    return _record(ok, detail, remediation)


def mineru(configured: bool, live: Mapping[str, Any] | None = None) -> Record:
    """A MinerU token is configured; optionally its live acceptance is known."""
    if not configured:
        return _record(False, "MINERU_TOKEN 未配置", _fix("mineru"))
    if live is None:
        return _record(True, "token 已配置（未做在线探测）", _fix("mineru"))
    if live.get("valid") is True:
        return _record(
            True,
            f"在线探测通过（probe code={live.get('code')} msg={live.get('msg')}）",
            _fix("mineru"),
        )
    return _record(
        False,
        f"在线探测失败（code={live.get('code')} msg={live.get('msg')}）",
        _fix("mineru"),
    )


def discovery_sources(usable: Mapping[str, bool]) -> Record:
    """Which bibliographic sources this machine can actually ask.

    Never a blocker. OpenAlex answers without a credential, so discovery
    always has at least one source; a Semantic Scholar key or Unpaywall
    address that is missing narrows coverage, and that is what gets reported.
    The record stays outside the readiness conjunction on purpose — a search
    must never be refused because an optional key is absent.
    """
    ready = sorted(name for name, ok in usable.items() if ok)
    missing = sorted(name for name, ok in usable.items() if not ok)
    detail = "可用：" + "、".join(ready) if ready else "无可用来源"
    if missing:
        detail += "；缺配置而跳过：" + "、".join(missing)
    return _record(bool(ready), detail, _fix("discovery_sources"))


def skill_links(roots: Sequence[str]) -> Record:
    """The skill is reachable from at least one agent runtime."""
    if not roots:
        return _record(False, "未链接到任何 agent 运行时", _fix("skill_links"))
    return _record(True, "已链接：" + "；".join(roots), _fix("skill_links"))


# What each stage of a run actually needs, checked when that stage runs.
# Discovery requires nothing local: a search must never be blocked because
# Zotero Desktop is closed or its file sync is still catching up. Local Zotero
# capabilities gate only the separate local-sync check, not delivery.
#
# Acquisition requires nothing either, since an open-access PDF is fetched
# over plain HTTP (ADR-0004). Kimi gates `browser_fallback` alone — the route
# taken for entitlement, anti-bot and reachability walls — so its absence
# narrows the routes available to one paper instead of stopping the stage.
STAGE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "discovery": (),
    "acquisition": (),
    "browser_fallback": ("kimi",),
    "conversion": ("mineru",),
    "ingestion": ("zotero_key",),
    "local_sync": ("zotero_local", "zotero_sync"),
}


def stage_missing(stage: str, records: Mapping[str, Record]) -> list[str]:
    """Names of the capabilities this stage needs and does not have."""
    if stage not in STAGE_REQUIREMENTS:
        raise KeyError(stage)
    return [name for name in STAGE_REQUIREMENTS[stage] if records.get(name, {}).get("ok") is not True]


def ready(records: Mapping[str, Record]) -> bool:
    """Conjunction over the live-readiness capabilities only.

    Callers pass exactly the records that gate "ready": zotero-local,
    zotero-sync, zotero-key and kimi. MCP configuration, MinerU and skill
    links are reported separately: MinerU absence is degradable, the scripted
    Web API helpers cover the MCP tool channel, and skill links matter only
    when invoking from an agent runtime.
    """
    return bool(records) and all(r.get("ok") is True for r in records.values())
