from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "zotero_sync.py"


class EventuallyVisibleHandler(BaseHTTPRequestHandler):
    attempts = 0

    def do_GET(self) -> None:  # noqa: N802
        type(self).attempts += 1
        if type(self).attempts < 2:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"key":"COLL1"}')

    def log_message(self, format: str, *args: object) -> None:
        return


class AttachmentHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = b'{"key":"ATTACH1","data":{"filename":"paper.md"}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def test_wait_reports_collection_after_local_sync() -> None:
    server = HTTPServer(("127.0.0.1", 0), EventuallyVisibleHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--kind", "collection",
                "--key", "COLL1",
                "--base-url", f"http://127.0.0.1:{server.server_port}",
                "--expected-sha256", hashlib.sha256(b"# Local attachment\n").hexdigest(),
                "--timeout", "2",
                "--interval", "0.01",
            ],
            text=True,
            capture_output=True,
            check=True,
        )
    finally:
        server.shutdown()
    payload = json.loads(result.stdout)
    assert payload["status"] == "visible"
    assert payload["attempts"] == 2


def test_attachment_file_requires_local_storage_binary(tmp_path: Path) -> None:
    storage = tmp_path
    target = storage / "storage" / "ATTACH1"
    target.mkdir(parents=True)
    (target / "paper.md").write_bytes(b"# Local attachment\n")
    server = HTTPServer(("127.0.0.1", 0), AttachmentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--kind", "attachment-file",
                "--key", "ATTACH1",
                "--storage-root", str(storage),
                "--base-url", f"http://127.0.0.1:{server.server_port}",
                "--expected-sha256", hashlib.sha256(b"# Local attachment\n").hexdigest(),
            ],
            text=True,
            capture_output=True,
            check=True,
        )
    finally:
        server.shutdown()
    payload = json.loads(result.stdout)
    assert payload["status"] == "local_file_present"
    assert payload["path"] == str(target / "paper.md")
    assert payload["sha256"] == hashlib.sha256(b"# Local attachment\n").hexdigest()
