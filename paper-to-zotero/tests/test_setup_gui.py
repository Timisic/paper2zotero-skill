"""Exercise the actual Tk controls in a hidden, fully offline demo window."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import setup_gui


def test_demo_validation_and_navigation_never_use_accounts_or_save(monkeypatch, tmp_path):
    try:
        root = setup_gui.tk.Tk()
    except setup_gui.tk.TclError:
        pytest.skip('Tk display unavailable')
    root.withdraw()
    def forbidden(*a, **k):
        pytest.fail('Demo accessed accounts or saved a key')
    for name in ('connect', 'prepare', 'check', 'existing_key', 'extra_value', 'enable_kimi', 'enable_desktop'):
        monkeypatch.setattr(setup_gui.connection, name, forbidden)
    monkeypatch.setattr(setup_gui.configure, 'save_many', forbidden)
    marker = tmp_path / 'ready'
    app = setup_gui.Wizard(root, agent='claude-code', demo=True, ready_file=str(marker))
    def finish():
        deadline = time.monotonic() + 5
        while app.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        assert not app.busy
    try:
        root.update()
        assert marker.read_text() == 'ready\n'
        app.prepared_next(None)
        app.key.set('\x16')
        app.verify('zotero')
        finish()
        assert '完整授权码' in app.status.get()
        assert app.page == 1 and not app.connected
        app.key.set('demo-fixture-key')
        app.verify('zotero')
        finish()
        assert '12345678' in app.status.get() and '没有保存' in app.status.get()
        app.goto(2)
        app.key.set('demo-openalex-key')
        app.verify('openalex')
        finish()
        app.goto(3)
        app.key.set('demo-fixture-token')
        app.verify('mineru')
        finish()
        assert app.connected == {'zotero', 'openalex', 'mineru'}
        app.goto(setup_gui.RESULT_PAGE)
        buttons = [w for w in app.controls if w.cget('text') == '检查配置']
        assert len(buttons) == 1
        buttons[0].invoke()
        finish()
        assert '检查通过' in app.status.get()
        next(w for w in app.controls if w.cget('text') == '更多配置（可选）').invoke()
        assert app.page == setup_gui.MORE_PAGE
        assert set(app.extra_actions) == set(setup_gui.connection.EXTRAS)
        assert not any(isinstance(w, setup_gui.ttk.Combobox) for w in app.controls)
        app.extra_inputs['crossref'].set('draft@example.org')
        for service in setup_gui.connection.EXTRAS:
            if service in ('kimi', 'desktop'):
                app.extra_actions[service].invoke()
                finish()
                assert '没有连接服务或保存' in app.status.get()
            else:
                app.extra_inputs[service].set('person@example.org' if service in ('crossref', 'unpaywall') else 'fixture-key')
                app.extra_actions[service].invoke()
                assert '没有写入配置' in app.status.get()
                if service == 'semantic_scholar':
                    assert app.extra_inputs['crossref'].get() == 'draft@example.org'
        app.goto(setup_gui.RESULT_PAGE)
        assert app.connected == {'zotero', 'openalex', 'mineru'}
        app.connected.remove('openalex')
        next(w for w in app.controls if w.cget('text') == '检查配置').invoke()
        finish()
        assert '部分项目尚未完成' in app.status.get()
    finally:
        root.destroy()
