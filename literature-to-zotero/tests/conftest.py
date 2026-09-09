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
import tempfile

CLOSED = "http://127.0.0.1:9"
SOURCES = ("openalex", "semantic_scholar", "crossref", "unpaywall", "arxiv", "pmc")

os.environ.setdefault("LITERATURE_SOURCE_BASES", json.dumps({name: CLOSED for name in SOURCES}))
os.environ.setdefault("LITERATURE_THROTTLE_DIR",
                      tempfile.mkdtemp(prefix="literature-throttle-"))
# Subprocess tests inherit this. Explicit fixture adapters remain usable;
# the installed Kimi daemon and the user's real tabs are never test peers.
os.environ["LITERATURE_BROWSER_DISABLED"] = "1"
