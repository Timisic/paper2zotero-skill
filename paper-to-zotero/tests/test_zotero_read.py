"""The read-only Zotero reader against a stand-in for Zotero Desktop's local API."""
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

from http_fixture import server
from pdf_fixture import pdf_with_text
from test_cli import ROOT

READER = ROOT.parent / "discussion-drafter" / "scripts" / "zotero_read.py"


def item(key, item_type="journalArticle", **data):
    return {"key": key, "data": {"key": key, "itemType": item_type, **data}}


class LocalApi:
    """Personal library: a collection with a subcollection of 120 papers, so
    enumeration needs two pages, and one paper with a note, a PDF and Markdown."""

    def __init__(self, storage: Path):
        self.requests = []
        self.collections = [item("ROOT", "collection", name="AI"),
                            item("SUB", "collection", name="干预类", parentCollection="ROOT")]
        self.members = {
            "ROOT": [item("PAPER", title="Chatbot RCT", DOI="10.1/x", collections=["ROOT"])],
            "SUB": [item(f"P{n:03}", title=f"Paper {n}") for n in range(120)]
                   + [item("PAPER", title="Chatbot RCT")],
        }
        self.children = {
            "PAPER": [item("NOTE", "note", note="<p>First &amp; main</p><p>Second</p>"),
                      item("PDF", "attachment", contentType="application/pdf", filename="source.pdf"),
                      item("MD", "attachment", contentType="text/markdown", filename="paper.md")],
            "PDF": [item("MARK", "annotation", annotationType="highlight", annotationText="effect size 0.4",
                         annotationComment="key result", annotationPageLabel="5")],
            "MD": [],
        }
        self.files = {"PDF": storage / "source.pdf", "MD": storage / "paper.md"}
        self.files["PDF"].write_bytes(pdf_with_text("Front page of the trial", "Results show an effect size of 0.4"))
        self.files["MD"].write_text("# Chatbot RCT\n\nFull text.", encoding="utf-8")

    def respond(self, method, path, body, headers):
        self.requests.append((method, path))
        parts = urlsplit(path)
        route, query = parts.path.removeprefix("/api/users/0"), parse_qs(parts.query)
        if method != "GET":
            return 405, {}, {}
        if route == "/collections":
            return self.page(self.collections, query)
        if route.startswith("/collections/") and route.endswith("/items/top"):
            rows = self.members[route.split("/")[2]]
            if "q" in query:
                rows = [row for row in rows if query["q"][0].lower() in row["data"]["title"].lower()]
            return self.page(rows, query)
        if route == "/items/top" and query.get("format") == ["bib"]:
            keys = query["itemKey"][0].split(",")
            entries = "".join(f'<div class="csl-entry">Author {k}. (2026). <i>Title {k}</i> &amp; more.</div>' for k in keys)
            return 200, f'<div class="csl-bib-body">{entries}</div>'.encode(), {}
        if route == "/items/top":
            keys = query["itemKey"][0].split(",")
            return 200, [{"key": k, "citation": f"<span>(Author {k}, 2026)</span>"} for k in keys if k != "GONE"], {}
        segments = route.split("/")
        key = segments[2]
        if route.endswith("/children"):
            return self.page(self.children[key], query)
        if route.endswith("/fulltext"):
            return (200, {"content": "indexed pdf text"}, {}) if key == "PDF" else (404, b"Not found", {})
        if route.endswith("/file/view/url"):
            return 200, self.files[key].as_uri().encode(), {}
        found = [row for rows in (self.members["SUB"], *self.children.values()) for row in rows if row["key"] == key]
        return (200, found[0], {}) if found else (404, b"Not found", {})

    @staticmethod
    def page(rows, query):
        start, limit = int(query.get("start", ["0"])[0]), int(query.get("limit", ["25"])[0])
        return 200, rows[start:start + limit], {"Total-Results": str(len(rows))}


def read(base, *args):
    env = {**os.environ, "ZOTERO_LOCAL_API": base + "/api"}
    result = subprocess.run([sys.executable, str(READER), *args],
                            env=env, capture_output=True, text=True, encoding="utf-8")
    return result.returncode, json.loads(result.stdout)


def test_collections_carry_full_paths_and_filter_by_name(tmp_path):
    with server(LocalApi(tmp_path).respond) as base:
        code, rows = read(base, "collections", "--name", "干预")
    assert code == 0
    assert rows == [{"key": "SUB", "name": "干预类", "parent": "ROOT", "path": "AI / 干预类"}]


def test_items_cover_subcollections_across_pages_without_duplicates(tmp_path):
    with server(LocalApi(tmp_path).respond) as base:
        code, scope = read(base, "items", "--collection", "ROOT")
        _, only_root = read(base, "items", "--collection", "ROOT", "--no-subcollections")
    assert code == 0
    assert scope["count"] == 121
    assert [c["path"] for c in scope["collections"]] == ["AI", "AI / 干预类"]
    assert only_root["count"] == 1 and only_root["items"][0]["DOI"] == "10.1/x"


def test_children_return_whole_notes_attachments_and_annotations(tmp_path):
    with server(LocalApi(tmp_path).respond) as base:
        code, children = read(base, "children", "--item", "PAPER")
    assert code == 0
    assert children["notes"] == [{"key": "NOTE", "text": "First & main\nSecond"}]
    assert [a["key"] for a in children["attachments"]] == ["PDF", "MD"]
    assert children["annotations"] == [{"key": "MARK", "attachment": "PDF", "type": "highlight", "page": "5",
                                        "text": "effect size 0.4", "comment": "key result"}]


def test_fulltext_uses_the_index_then_falls_back_to_the_stored_file(tmp_path):
    with server(LocalApi(tmp_path).respond) as base:
        code, result = read(base, "fulltext", "--item", "PAPER")
    assert code == 0
    assert [(t["attachment"], t["source"]) for t in result["texts"]] == [("PDF", "zotero_index"), ("MD", "file")]
    assert result["texts"][1]["content"].startswith("# Chatbot RCT")


def test_pages_read_the_requested_pdf_pages(tmp_path):
    with server(LocalApi(tmp_path).respond) as base:
        code, result = read(base, "pages", "--item", "PAPER", "--pages", "2-9")
    assert code == 0
    assert result["page_count"] == 2
    assert [p["page"] for p in result["pages"]] == [2]
    assert "effect size of 0.4" in result["pages"][0]["text"]


def test_cite_returns_plain_citations_a_reference_list_and_missing_keys(tmp_path):
    with server(LocalApi(tmp_path).respond) as base:
        code, result = read(base, "cite", "--items", "PAPER,GONE")
    assert code == 0
    assert result["citations"] == {"PAPER": "(Author PAPER, 2026)"}
    assert result["missing"] == ["GONE"]
    assert result["bibliography"][0] == "Author PAPER. (2026). *Title PAPER* & more."


def test_search_stays_inside_the_collection(tmp_path):
    with server(LocalApi(tmp_path).respond) as base:
        code, rows = read(base, "search", "--query", "chatbot", "--collection", "SUB")
    assert code == 0
    assert [row["key"] for row in rows] == ["PAPER"]


def test_reader_never_writes(tmp_path):
    peer = LocalApi(tmp_path)
    with server(peer.respond) as base:
        for args in (["collections"], ["items", "--collection", "ROOT"], ["children", "--item", "PAPER"],
                     ["fulltext", "--item", "PAPER"], ["cite", "--items", "PAPER"]):
            read(base, *args)
    assert {method for method, _ in peer.requests} == {"GET"}


def test_unreachable_zotero_names_the_setting_to_enable():
    code, result = read("http://127.0.0.1:9", "collections")
    assert code == 2
    assert "允许此计算机上的其他应用程序与 Zotero 通信" in result["remediation"]
