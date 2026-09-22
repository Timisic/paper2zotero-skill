from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "zotero_markdown.py"
SPEC = importlib.util.spec_from_file_location("zotero_markdown", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeZotero:
    def __init__(self) -> None:
        self.updated: list[dict] = []

    def attachment_simple(self, files: list[str], parentid: str) -> dict[str, list[dict]]:
        return {"success": [{"key": "ATTACH1"}], "failure": [], "unchanged": []}

    def item(self, key: str) -> dict:
        return {"key": key, "data": {"contentType": "application/octet-stream"}}

    def update_item(self, item: dict) -> bool:
        self.updated.append(item)
        return True


def test_attachment_contract_sets_markdown_content_type(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    source.write_text("# Paper\n")
    client = FakeZotero()

    keys = MODULE.attach_markdown(client, source, "PARENT1")

    assert keys == ["ATTACH1"]
    assert client.updated[0]["data"]["contentType"] == "text/markdown"
