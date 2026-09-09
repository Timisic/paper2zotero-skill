"""An in-memory Zotero Web API peer, including the three-step file upload.

Enough of the real protocol to exercise the writer end to end offline: item
creation with client keys, collection membership, children listings, and the
authorize / storage / register upload dance. Optionally mirrors uploaded
binaries into a Zotero Desktop storage tree, so local-sync evidence can be
present or absent on purpose.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ZoteroLibrary:
    def __init__(self, storage: Path | None = None, library: str = '/users/123') -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.files: dict[str, bytes] = {}
        self.staged: dict[str, bytes] = {}
        self.creations = 0
        self.uploads = 0
        self.storage = storage
        self.library = library
        self.base = ''
        self.lost = False
        self.awaiting: str | None = None
        # Every request the writer makes, as (method, shape). Re-verifying an
        # unchanged paper should stay cheap: on a slow link the request count,
        # not the bytes, is what a resume costs.
        self.requests: list[tuple[str, str]] = []
        self.downloaded = 0
        self.conflicts = 0
        # Simulate Zotero Desktop touching an item while we download its file:
        # the version moves between a listing and any write that follows.
        self.bump_on_download = False

    def children(self, parent: str) -> list[dict[str, Any]]:
        return [item for item in self.items.values() if item['data'].get('parentItem') == parent]

    def shape(self, route: str) -> str:
        parts = [part for part in route.split('?')[0].split('/') if part]
        return '/'.join(part if index % 2 == 0 or part in ('file', 'children') else '{key}'
                        for index, part in enumerate(parts))

    def respond(self, method: str, path: str, body: bytes, headers: Any):
        route = path.removeprefix(self.library)
        self.requests.append((method, self.shape(route) if route != path else 'storage'))
        if path == '/storage':
            assert 'Zotero-API-Key' not in headers, 'library credential must not reach storage'
            if self.awaiting:
                self.staged[self.awaiting] = body
            return 201, b'', {}
        if method == 'GET' and route.startswith('/collections/'):
            key = route.split('/')[2].split('?')[0]
            return 200, {'key': key, 'data': {'name': 'Test'}}, {}
        if method == 'GET' and route.startswith('/items?'):
            return 200, list(self.items.values()), {}
        if '/file' in route:
            return self.file_route(method, route, body)
        if method == 'GET' and route.startswith('/items/'):
            key = route.split('/')[2]
            if '/children' in route:
                return 200, self.children(key), {}
            return (200, self.items[key], {}) if key in self.items else (404, {}, {})
        if method == 'POST' and route == '/items':
            item = json.loads(body)[0]
            if 'tags' not in item or 'relations' not in item:
                return 400, {'error': 'required item properties missing'}, {}
            self.creations += 1
            self.items[item['key']] = {'key': item['key'], 'version': 1, 'data': item}
            if self.lost:
                self.lost = False
                return None
            return 200, {'successful': {'0': self.items[item['key']]}}, {}
        if method == 'POST' and route == '/collections':
            collection = json.loads(body)[0]
            self.items.setdefault('collection:' + collection['key'], {'key': collection['key'], 'version': 1, 'data': collection})
            return 200, {'successful': {'0': {'key': collection['key'], 'version': 1, 'data': collection}}}, {}
        if method == 'PATCH' and route.startswith('/items/'):
            item = self.items[route.split('/')[2]]
            # Real Zotero rejects a write whose precondition is stale, and
            # bumps the version on every accepted one. Without both, a cached
            # version looks free in tests and 412s in production.
            precondition = headers.get('If-Unmodified-Since-Version')
            if precondition is not None and int(precondition) != item['version']:
                self.conflicts += 1
                return 412, {'error': 'version mismatch'}, {}
            item['data'].update(json.loads(body))
            item['version'] += 1
            return 204, b'', {}
        return 400, {'unsupported': [method, route]}, {}

    def file_route(self, method: str, route: str, body: bytes):
        key = route.split('/')[2]
        if method == 'GET':
            if key in self.files:
                self.downloaded += len(self.files[key])
                if self.bump_on_download and key in self.items:
                    self.items[key]['version'] += 1
                return 200, self.files[key], {}
            return 404, {}, {}
        if body.startswith(b'upload='):
            self.files[key] = self.staged.pop(key, b'')
            self.uploads += 1
            if self.storage is not None:
                filename = self.items[key]['data']['filename']
                target = self.storage / 'storage' / key / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(self.files[key])
            return 204, b'', {}
        self.awaiting = key
        return 200, {'url': self.base + '/storage', 'prefix': '', 'suffix': '',
                     'contentType': 'multipart/form-data; boundary=test', 'uploadKey': 'upload-' + key}, {}
