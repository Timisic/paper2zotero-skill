"""Exercise the actual Tk controls in a hidden, fully offline demo window."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import setup_gui


def finish(root, app):
    deadline = time.monotonic() + 5
    while app.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)
    assert not app.busy


def forbid_accounts(monkeypatch):
    def forbidden(*_a, **_k):
        pytest.fail('Demo accessed accounts or saved a key')
    for name in ('connect', 'prepare', 'check', 'existing_key', 'extra_value',
                 'enable_kimi', 'enable_desktop', 'accept'):
        monkeypatch.setattr(setup_gui.connection, name, forbidden)
    monkeypatch.setattr(setup_gui.configure, 'save_many', forbidden)


def test_demo_desktop_check_is_ready_without_optional_cards(monkeypatch, tmp_path):
    monkeypatch.delenv('SEARCH_BACKEND', raising=False)
    try:
        root = setup_gui.tk.Tk()
    except setup_gui.tk.TclError:
        pytest.skip('Tk display unavailable')
    root.withdraw()
    forbid_accounts(monkeypatch)
    marker = tmp_path / 'ready'
    app = setup_gui.Wizard(root, agent='claude-code', demo=True, ready_file=str(marker))
    try:
        root.update()
        assert marker.read_text() == 'ready\n'
        app.prepared_next(None)
        assert app.page == 1
        assert 'Zotero Desktop · 本机附件' in app.heading.cget('text')
        next(w for w in app.controls if w.cget('text') == '暂时跳过').invoke()
        assert '仍会待完成' in app.status.get()
        buttons = [w for w in app.controls if w.cget('text') == '检查配置']
        assert len(buttons) == 1
        buttons[0].invoke()
        finish(root, app)
        assert '部分项目尚未完成' in app.status.get()
        next(w for w in app.controls if w.cget('text') == '上一步').invoke()
        next(w for w in app.controls if w.cget('text') == '检查本机 Zotero').invoke()
        finish(root, app)
        assert app.connected == {'desktop'}
        app.goto(app.page_titles().index('检查结果'))
        next(w for w in app.controls if w.cget('text') == '检查配置').invoke()
        finish(root, app)
        assert '检查通过' in app.status.get()
        next(w for w in app.controls if w.cget('text') == '更多配置（可选）').invoke()
        assert app.page == len(app.page_titles()) - 1
        assert list(app.extra_actions) == [
            'zotero', 'mineru', 'kimi', 'semantic_scholar', 'crossref', 'unpaywall']
        assert not any(isinstance(w, setup_gui.ttk.Combobox) for w in app.controls)
        app.extra_inputs['crossref'].set('draft@example.org')
        for service in app.extra_actions:
            if service == 'kimi':
                app.extra_actions[service].invoke()
                finish(root, app)
                assert '没有连接服务或保存' in app.status.get()
            else:
                app.extra_inputs[service].set(
                    'person@example.org' if service in ('crossref', 'unpaywall') else 'fixture-key')
                app.extra_actions[service].invoke()
                assert '没有写入配置' in app.status.get()
                if service == 'semantic_scholar':
                    assert app.extra_inputs['crossref'].get() == 'draft@example.org'
        app.goto(app.page_titles().index('检查结果'))
        assert app.connected == {'desktop'}
    finally:
        root.destroy()


def test_group_demo_rejects_a_control_character_in_the_web_api_key(monkeypatch):
    try:
        root = setup_gui.tk.Tk()
    except setup_gui.tk.TclError:
        pytest.skip('Tk display unavailable')
    root.withdraw()
    forbid_accounts(monkeypatch)
    app = setup_gui.Wizard(root, agent='claude-code', demo=True, group=True)
    try:
        root.update()
        app.prepared_next(None)
        app.goto(2)
        assert '连接 Zotero Web API' in app.heading.cget('text')
        app.key.set('\x16')
        app.verify('zotero')
        finish(root, app)
        assert '完整授权码' in app.status.get()
        assert 'zotero' not in app.connected
        app.key.set('demo-fixture-key')
        app.verify('zotero')
        finish(root, app)
        assert '12345678' in app.status.get() and '没有保存' in app.status.get()
    finally:
        root.destroy()


def test_result_check_passes_the_group_flag(monkeypatch):
    try:
        root = setup_gui.tk.Tk()
    except setup_gui.tk.TclError:
        pytest.skip('Tk display unavailable')
    root.withdraw()
    seen = {}

    def fake_check(agent, group=False):
        seen['agent'] = agent
        seen['group'] = group
        return {'ready': True, 'items': [{'name': 'Zotero Desktop · 本机附件', 'ok': True}]}

    monkeypatch.setattr(setup_gui.connection, 'check', fake_check)
    app = setup_gui.Wizard(root, agent='claude-code', demo=False, group=True)
    try:
        root.update()
        app.goto(app.page_titles().index('检查结果'))
        next(w for w in app.controls if w.cget('text') == '检查配置').invoke()
        finish(root, app)
        assert seen == {'agent': 'claude-code', 'group': True}
        assert '检查通过' in app.status.get()
    finally:
        root.destroy()
