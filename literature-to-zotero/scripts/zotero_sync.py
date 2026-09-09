#!/usr/bin/env python3
"""Wait until a cloud-written Zotero item or collection is visible locally."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("item", "collection", "attachment-file"), required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--storage-root", help="Zotero data directory; required for attachment-file")
    parser.add_argument("--expected-sha256", help="Require this SHA-256 for attachment-file")
    parser.add_argument("--base-url", default="http://127.0.0.1:23119")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()

    if args.kind == "attachment-file" and not args.storage_root:
        parser.error("--storage-root is required for attachment-file")
    plural = "collections" if args.kind == "collection" else "items"
    url = f"{args.base_url.rstrip('/')}/api/users/0/{plural}/{args.key}"
    deadline = time.monotonic() + args.timeout
    attempts = 0
    last_status: int | None = None
    while time.monotonic() <= deadline:
        attempts += 1
        try:
            with urllib.request.urlopen(url, timeout=min(3.0, max(args.interval, 0.1))) as response:
                last_status = response.status
                if response.status == 200:
                    if args.kind == "attachment-file":
                        payload = json.load(response)
                        filename = (payload.get("data") or {}).get("filename")
                        local_path = Path(args.storage_root) / "storage" / args.key / str(filename)
                        if local_path.is_file():
                            digest = hashlib.sha256(local_path.read_bytes()).hexdigest()
                            if args.expected_sha256 and digest != args.expected_sha256:
                                print(json.dumps({
                                    "status": "hash_mismatch",
                                    "kind": args.kind,
                                    "key": args.key,
                                    "path": str(local_path),
                                    "sha256": digest,
                                    "attempts": attempts,
                                }))
                                raise SystemExit(2)
                            print(json.dumps({
                                "status": "local_file_present",
                                "kind": args.kind,
                                "key": args.key,
                                "path": str(local_path),
                                "sha256": digest,
                                "attempts": attempts,
                            }))
                            return
                        time.sleep(args.interval)
                        continue
                    print(json.dumps({
                        "status": "visible",
                        "kind": args.kind,
                        "key": args.key,
                        "attempts": attempts,
                    }))
                    return
        except urllib.error.HTTPError as error:
            last_status = error.code
        except (urllib.error.URLError, TimeoutError):
            last_status = None
        time.sleep(args.interval)
    print(json.dumps({
        "status": "sync_pending",
        "kind": args.kind,
        "key": args.key,
        "attempts": attempts,
        "last_http_status": last_status,
    }))
    raise SystemExit(2)


if __name__ == "__main__":
    main()
