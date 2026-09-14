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
        app.key.set('demo-fixture-token')
        app.verify('mineru')
        finish()
        assert app.connected == {'zotero', 'mineru'}
        app.goto(3)
        buttons = [w for w in app.controls if w.cget('text') == '检查配置']
        assert len(buttons) == 1
        buttons[0].invoke()
        finish()
        assert '检查通过' in app.status.get()
        next(w for w in app.controls if w.cget('text') == '更多设置（可选）').invoke()
        assert app.page == 4
        for service in setup_gui.connection.EXTRAS:
            app.extra_service = service
            app.render()
            if service in ('kimi', 'desktop'):
                label = '启动并检查' if service == 'kimi' else '检查本机 Zotero'
                next(w for w in app.controls if w.cget('text') == label).invoke()
                finish()
                assert '没有连接服务或保存' in app.status.get()
            else:
                app.key.set('person@example.org' if service in ('crossref', 'unpaywall') else 'fixture-key')
                next(w for w in app.controls if w.cget('text') == '保存设置').invoke()
                assert '没有写入配置' in app.status.get()
        app.goto(3)
        assert app.connected == {'zotero', 'mineru'}
    finally:
        root.destroy()
