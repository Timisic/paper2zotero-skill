#!/usr/bin/env python3
"""Read a Zotero library through Zotero Desktop's local API. Never writes.

Writing skills use this to read a collection: its items, full notes,
annotations, attachment text and APA citations. It needs only Zotero 7 running
with "Allow other applications on this computer to communicate with Zotero"
enabled; reads take no key and no MCP server. Every command prints JSON.
Standard library only; reading PDF pages also needs PyMuPDF, which the
paper-to-zotero runtime in `~/.config/literature-to-zotero/python-path` has.

  collections [--name TEXT]            all collections with full paths
  items --collection KEY [--no-subcollections]
  search --query TEXT [--collection KEY]
  children --item KEY                  full notes, attachments, annotations
  fulltext --item KEY                  text of each attachment of a paper
  pages --item KEY --pages 3-5         PDF text per page, for page citations
  cite --items KEY,KEY [--style apa]   in-text citations and a reference list
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

PAGE = 100
TEXT_TYPES = {"text/markdown", "text/plain", "text/html", "text/x-markdown"}
UNREACHABLE = ("Zotero 本地 API 无法访问：请打开 Zotero 7，并在 设置 → 高级 中勾选"
               "“允许此计算机上的其他应用程序与 Zotero 通信”。")


class RequestError(RuntimeError):
    def __init__(self, status: int | None) -> None:
        self.status = status
        super().__init__(f"HTTP {status}" if status else "unreachable")


class Reply:
    def __init__(self, body: bytes, headers: Any) -> None:
        self.body, self.headers = body, headers

    def json(self) -> Any:
        return json.loads(self.body)


class Library:
    def __init__(self, group: str | None = None) -> None:
        api = (os.environ.get("ZOTERO_LOCAL_API") or "http://127.0.0.1:23119/api").rstrip("/")
        self.root = api + (f"/groups/{group}" if group else "/users/0")
        # Loopback only: a system proxy must never see library reads.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def fetch(self, path: str, **params: Any) -> Reply:
        url = self.root + path + ("?" + urllib.parse.urlencode(params) if params else "")
        request = urllib.request.Request(url, headers={"Zotero-API-Version": "3"})
        try:
            with self.opener.open(request, timeout=30) as reply:
                return Reply(reply.read(), reply.headers)
        except urllib.error.HTTPError as error:
            error.close()
            raise RequestError(error.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RequestError(None) from None

    def get(self, path: str, **params: Any) -> Any:
        return self.fetch(path, **params).json()

    def text(self, path: str, **params: Any) -> str:
        return self.fetch(path, **params).body.decode("utf-8", errors="replace")

    def all(self, path: str, **params: Any) -> list[dict[str, Any]]:
        """Every page. Total-Results is the end, not a short page."""
        found: list[dict[str, Any]] = []
        while True:
            response = self.fetch(path, **params, limit=PAGE, start=len(found))
            page = response.json()
            found.extend(page)
            total = int(response.headers.get("Total-Results") or len(found))
            if not page or len(found) >= total:
                return found

    def file_path(self, key: str) -> Path | None:
        try:
            url = self.text(f"/items/{key}/file/view/url").strip()
        except RequestError as error:
            if error.status == 404:
                return None
            raise
        path = Path(urllib.request.url2pathname(urllib.parse.unquote(urllib.parse.urlsplit(url).path)))
        return path if path.is_file() else None


def note_text(value: str) -> str:
    """Zotero note HTML as plain text with paragraph breaks kept."""
    value = re.sub(r"(?i)<br\s*/?>|</(p|div|h[1-6]|li|tr|blockquote)>", "\n", value)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(re.sub(r"<[^>]+>", "", value))).strip()


def item_summary(item: dict[str, Any]) -> dict[str, Any]:
    data = item["data"]
    return {
        "key": data["key"],
        "itemType": data["itemType"],
        "title": data.get("title", ""),
        "creators": data.get("creators", []),
        "date": data.get("date", ""),
        "DOI": data.get("DOI", ""),
        "publicationTitle": data.get("publicationTitle", ""),
        "collections": data.get("collections", []),
        "abstractNote": data.get("abstractNote", ""),
    }


def collection_tree(library: Library) -> dict[str, dict[str, Any]]:
    rows = {c["key"]: c["data"] for c in library.all("/collections")}

    def path(key: str) -> str:
        parent = rows[key].get("parentCollection") or None
        return (path(parent) + " / " if parent in rows else "") + rows[key]["name"]

    return {key: {"key": key, "name": data["name"], "parent": data.get("parentCollection") or None,
                  "path": path(key)} for key, data in rows.items()}


def descendants(tree: dict[str, dict[str, Any]], root: str) -> list[str]:
    keys = [root]
    for key in keys:
        keys.extend(k for k, row in tree.items() if row["parent"] == key)
    return keys


def attachments(library: Library, key: str) -> list[dict[str, Any]]:
    item = library.get(f"/items/{key}")["data"]
    if item["itemType"] == "attachment":
        return [item]
    return [c["data"] for c in library.all(f"/items/{key}/children") if c["data"]["itemType"] == "attachment"]


def command_collections(library: Library, args: argparse.Namespace) -> Any:
    rows = sorted(collection_tree(library).values(), key=lambda row: row["path"])
    needle = (args.name or "").casefold()
    return [row for row in rows if needle in row["path"].casefold()]


def command_items(library: Library, args: argparse.Namespace) -> Any:
    tree = collection_tree(library)
    if args.collection not in tree:
        raise LookupError(f"collection {args.collection} not found")
    scope = [args.collection] if args.no_subcollections else descendants(tree, args.collection)
    items: dict[str, dict[str, Any]] = {}
    for key in scope:
        for item in library.all(f"/collections/{key}/items/top"):
            items.setdefault(item["key"], item_summary(item))
    return {"collections": [tree[key] for key in scope], "count": len(items), "items": list(items.values())}


def command_search(library: Library, args: argparse.Namespace) -> Any:
    path = f"/collections/{args.collection}/items/top" if args.collection else "/items/top"
    return [item_summary(item) for item in library.all(path, q=args.query, qmode="everything")]


def command_children(library: Library, args: argparse.Namespace) -> Any:
    notes, files, marks = [], [], []
    for child in library.all(f"/items/{args.item}/children"):
        data = child["data"]
        if data["itemType"] == "note":
            notes.append({"key": data["key"], "text": note_text(data.get("note", ""))})
        elif data["itemType"] == "attachment":
            files.append({"key": data["key"], "title": data.get("title", ""),
                          "contentType": data.get("contentType", ""), "filename": data.get("filename", "")})
            for mark in library.all(f"/items/{data['key']}/children"):
                note = mark["data"]
                if note["itemType"] == "annotation":
                    marks.append({"key": note["key"], "attachment": data["key"],
                                  "type": note.get("annotationType", ""), "page": note.get("annotationPageLabel", ""),
                                  "text": note.get("annotationText", ""), "comment": note.get("annotationComment", "")})
    return {"item": args.item, "notes": notes, "attachments": files, "annotations": marks}


def command_fulltext(library: Library, args: argparse.Namespace) -> Any:
    texts = []
    for attachment in attachments(library, args.item):
        key, kind = attachment["key"], attachment.get("contentType", "")
        entry = {"attachment": key, "contentType": kind, "filename": attachment.get("filename", "")}
        try:
            indexed = library.get(f"/items/{key}/fulltext")
            texts.append({**entry, "source": "zotero_index", "content": indexed.get("content", "")})
            continue
        except RequestError as error:
            if error.status != 404:
                raise
        path = library.file_path(key)
        if path and kind == "application/pdf":
            import pymupdf
            with pymupdf.open(path) as document:
                texts.append({**entry, "source": "file", "content": "\n".join(page.get_text() for page in document)})
        elif path and kind in TEXT_TYPES:
            texts.append({**entry, "source": "file", "content": path.read_text(encoding="utf-8", errors="replace")})
        else:
            texts.append({**entry, "source": "none", "content": ""})
    return {"item": args.item, "texts": texts}


def command_pages(library: Library, args: argparse.Namespace) -> Any:
    first, _, last = args.pages.partition("-")
    start, end = int(first), int(last or first)
    import pymupdf
    for attachment in attachments(library, args.item):
        path = library.file_path(attachment["key"]) if attachment.get("contentType") == "application/pdf" else None
        if path:
            with pymupdf.open(path) as document:
                count = document.page_count
                pages = [{"page": n, "text": document[n - 1].get_text()} for n in range(max(start, 1), min(end, count) + 1)]
            return {"item": args.item, "attachment": attachment["key"], "page_count": count, "pages": pages}
    raise LookupError(f"item {args.item} has no local PDF")


def bibliography_entries(markup: str) -> list[str]:
    entries = re.findall(r'<div class="csl-entry">(.*?)</div>', markup, flags=re.S)
    return [html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"</?i>", "*", entry))).strip() for entry in entries]


def command_cite(library: Library, args: argparse.Namespace) -> Any:
    keys = [key for key in args.items.split(",") if key]
    if not keys or len(keys) > PAGE:
        raise ValueError(f"cite takes 1 to {PAGE} item keys")
    rows = library.get("/items/top", itemKey=",".join(keys), include="citation", style=args.style, limit=PAGE)
    citations = {row["key"]: html.unescape(re.sub(r"<[^>]+>", "", row.get("citation", ""))) for row in rows}
    markup = library.text("/items/top", itemKey=",".join(keys), format="bib", style=args.style, limit=PAGE)
    return {"style": args.style, "citations": citations, "missing": [k for k in keys if k not in citations],
            "bibliography": bibliography_entries(markup)}


COMMANDS = {
    "collections": command_collections, "items": command_items, "search": command_search,
    "children": command_children, "fulltext": command_fulltext, "pages": command_pages, "cite": command_cite,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--group", help="group library ID; default is the personal library")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collections").add_argument("--name")
    items = commands.add_parser("items")
    items.add_argument("--collection", required=True)
    items.add_argument("--no-subcollections", action="store_true")
    search = commands.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--collection")
    for name in ("children", "fulltext"):
        commands.add_parser(name).add_argument("--item", required=True)
    pages = commands.add_parser("pages")
    pages.add_argument("--item", required=True)
    pages.add_argument("--pages", required=True, help="one page or a range, 1-based: 3 or 3-5")
    cite = commands.add_parser("cite")
    cite.add_argument("--items", required=True, help="comma-separated parent item keys")
    cite.add_argument("--style", default="apa")
    return parser


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    try:
        result = COMMANDS[args.command](Library(args.group), args)
    except RequestError as error:
        unreachable = error.status is None or error.status == 403
        print(json.dumps({"error": "unreachable" if error.status is None else "http_error", "status": error.status,
                          "remediation": UNREACHABLE if unreachable else "检查 item 或集合 key 是否属于该文库。"},
                         ensure_ascii=False))
        raise SystemExit(2)
    except ImportError:
        print(json.dumps({"error": "PyMuPDF 未安装：用 ~/.config/literature-to-zotero/python-path 里的 Python 运行本脚本。"},
                         ensure_ascii=False))
        raise SystemExit(2)
    except (LookupError, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(2)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
