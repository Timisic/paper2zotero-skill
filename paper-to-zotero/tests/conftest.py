"""Keep the suite off the network and off the user's machine state.

Acquisition and discovery now prefer plain HTTP, so a test that names a real
host would really dial it — slowly, through whatever proxy the developer has
configured, with results that depend on the weather. Both seams are therefore
pointed at a closed local port by default: a test that wants a source stands
up its own peer and overrides this explicitly.

The pacing files move too. They are shared by design (that is the point of
`http_client.Throttle`), so a test run must not queue behind — or delay — the
real commands using the same key.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path

import pytest

if os.name == 'nt':
    git = shutil.which('git.exe')
    if git:
        # Git may resolve from cmd/, bin/, or mingw64/bin/ on hosted Windows.
        # Prefer its Bash over the unrelated System32 WSL launcher.
        for parent in Path(git).parents[:3]:
            bash_bin = parent / 'bin'
            if (bash_bin / 'bash.exe').is_file():
                os.environ['PATH'] = str(bash_bin) + os.pathsep + os.environ.get('PATH', '')
                break

# Unspecified install paths must never resolve to the developer's assistants.
# Individual tests may override these with their own profile, but an omitted
# USERPROFILE on Windows now lands in a disposable test profile.
profile = Path(tempfile.mkdtemp(prefix='literature-test-profile-'))
os.environ['HOME'] = str(profile)
os.environ['USERPROFILE'] = str(profile)
os.environ['CODEX_HOME'] = str(profile / '.codex')
os.environ['CLAUDE_CONFIG_DIR'] = str(profile / '.claude')

CLOSED = "http://127.0.0.1:9"
SOURCES = ("openalex", "semantic_scholar", "crossref", "unpaywall", "arxiv", "pmc")

os.environ.setdefault("LITERATURE_SOURCE_BASES", json.dumps({name: CLOSED for name in SOURCES}))
os.environ["SEARCH_BACKEND"] = "http"
os.environ["MINERU_API_BASE"] = ""
os.environ.setdefault("LITERATURE_THROTTLE_DIR",
                      tempfile.mkdtemp(prefix="literature-throttle-"))
os.environ["LITERATURE_BROWSER_DISABLED"] = "1"
# An installed markitdown would rescue every failed MinerU hop. Tests opt in.
os.environ["LITERATURE_MARKITDOWN_DISABLED"] = "1"

# The wizard opens pages with open/xdg-open/wslview and the GUI with webbrowser.
# Shadow them all, so no test can open a page in the developer's browser.
BROWSER_LOG = profile / "browser-opened.log"
fake_browser = profile / "fake-browser-bin"
fake_browser.mkdir()
for opener in ("open", "xdg-open", "wslview"):
    (fake_browser / opener).write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{BROWSER_LOG}"\n')
    (fake_browser / opener).chmod(0o755)
os.environ["PATH"] = str(fake_browser) + os.pathsep + os.environ.get("PATH", "")
os.environ["BROWSER"] = str(fake_browser / "open") + " %s"


@pytest.fixture(autouse=True)
def no_browser_opened():
    yield
    if BROWSER_LOG.exists():
        opened = BROWSER_LOG.read_text(encoding="utf-8")
        BROWSER_LOG.unlink()
        pytest.fail("test opened a page in the browser: " + opened)


@pytest.fixture(autouse=True)
def scansci_fetch_not_addressable(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    entry = str(scripts)
    added = entry not in sys.path
    if added:
        sys.path.insert(0, entry)
    try:
        import scansci_retrieval
    finally:
        if added:
            sys.path.remove(entry)
    monkeypatch.setenv(scansci_retrieval._FETCH_DISABLED_ENV, "1")

    def not_addressable(*_args, **_kwargs):
        return scansci_retrieval.NotAddressable()

    monkeypatch.setattr(scansci_retrieval, "fetch_candidate", not_addressable)
