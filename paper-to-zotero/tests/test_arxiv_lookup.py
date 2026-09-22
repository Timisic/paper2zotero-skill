"""arxiv_lookup: pure Atom parsing matches by DOI then by title."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "arxiv_lookup", Path(__file__).resolve().parent.parent / "scripts" / "arxiv_lookup.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

FEED_DOI = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2204.12749v1</id>
    <title>Control Globally, Understand Locally</title>
    <arxiv:doi>10.48550/ARXIV.2204.12749</arxiv:doi>
  </entry>
</feed>
"""

FEED_NO_DOI = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2204.12749v1</id>
    <title>Control Globally, Understand Locally: a global-to-local hierarchical graph network</title>
  </entry>
</feed>
"""


def test_matches_by_doi_field() -> None:
    result = MODULE.parse_atom(FEED_DOI, "10.48550/ARXIV.2204.12749")
    assert result["found"] is True
    assert result["match"] == "doi"
    assert result["arxiv_id"] == "2204.12749v1"
    assert result["pdf_url"] == "https://arxiv.org/pdf/2204.12749v1"
    assert "abs_url" in result


def test_ignores_wrong_doi() -> None:
    result = MODULE.parse_atom(FEED_DOI, "10.1234/other")
    assert result["found"] is False


def test_falls_back_to_title_overlap() -> None:
    result = MODULE.parse_atom(FEED_NO_DOI, "10.1234/x", "Control globally understand locally graph network")
    assert result["found"] is True
    assert result["match"] == "title"
