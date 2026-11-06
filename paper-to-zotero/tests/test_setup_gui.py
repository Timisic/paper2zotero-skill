"""Exercise the actual Tk controls in a hidden window."""
import sys
import time
from pathlib import Path

import pytest

if sys.platform != 'win32':
    pytest.skip('setup_gui is launched only by install/setup.ps1', allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import setup_gui


def finish(root, app):
    deadline = time.monotonic() + 5
    while app.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)
    assert not app.busy


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
    app = setup_gui.Wizard(root, agent='claude-code', group=True)
    try:
        root.update()
        app.goto(app.page_titles().index('检查结果'))
        next(w for w in app.controls if w.cget('text') == '检查配置').invoke()
        finish(root, app)
        assert seen == {'agent': 'claude-code', 'group': True}
        assert '检查通过' in app.status.get()
    finally:
        root.destroy()
