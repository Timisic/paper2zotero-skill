"""Module-by-module install: each module is checked right after its step."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import modules


def row(name, ok, detail=''):
    return {'name': name, 'ok': ok, 'detail': detail, 'action': '' if ok else '修复它'}


def stub(monkeypatch, rows):
    ran = []
    monkeypatch.setattr(modules.agent_installation, 'selected_roots', lambda agent: ['root'])
    monkeypatch.setattr(modules.connection, 'check', lambda agent: {'items': rows})
    for name, record in modules.MODULES.items():
        title, purpose, required, _, prefixes, ready = record
        modules.MODULES[name] = (title, purpose, required, lambda agent, name=name: ran.append(name), prefixes, ready)
    return ran


READY = [row('运行工具', True), row('连接 AI 助手', True), row('论文检索（ScanSci）', True),
         row('全文转换', True, '本机 markitdown 可用'), row('Zotero 本地 API', True),
         row('Kimi WebBridge（浏览器备用下载）', False)]


def test_all_required_ready_passes_with_optional_modules_missing(monkeypatch, capsys):
    monkeypatch.setattr(modules, 'MODULES', dict(modules.MODULES))
    ran = stub(monkeypatch, READY)
    monkeypatch.setattr(sys, 'argv', ['modules.py'])
    assert modules.main() == 0
    assert ran == ['runtime', 'skills', 'zotero', 'mineru', 'kimi']
    out = capsys.readouterr().out
    assert '○ 未配置 MinerU' in out and '○ Kimi WebBridge' in out and '必需模块全部就绪' in out


def test_a_failed_required_module_stops_before_the_next(monkeypatch, capsys):
    monkeypatch.setattr(modules, 'MODULES', dict(modules.MODULES))
    rows = [*READY[:4], row('Zotero 本地 API', False), READY[5]]
    ran = stub(monkeypatch, rows)
    monkeypatch.setattr(sys, 'argv', ['modules.py'])
    assert modules.main() == 1
    assert ran == ['runtime', 'skills', 'zotero']
    out = capsys.readouterr().out
    assert '待完成 Zotero 本地 API' in out and '下一步：修复它' in out and '（未运行）' in out


def test_mineru_counts_only_when_the_conversion_row_names_it(monkeypatch, capsys):
    monkeypatch.setattr(modules, 'MODULES', dict(modules.MODULES))
    rows = [*READY[:3], row('全文转换', True, '自建 MinerU、本机 markitdown 可用'), *READY[4:]]
    stub(monkeypatch, rows)
    monkeypatch.setattr(sys, 'argv', ['modules.py', 'mineru'])
    assert modules.main() == 0
    assert '✓ MinerU' in capsys.readouterr().out
