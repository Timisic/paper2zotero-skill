"""An in-memory MinerU peer: batch submission, signed upload, result zip.

Enough of the v4 protocol to drive a real conversion through
`mineru_parse.py` offline — which is what lets the full chain be tested with
conversion actually doing work, rather than skipped for want of consent.
"""
from __future__ import annotations

import io
import json
import zipfile
from typing import Any


def result_zip(body: str, image: bytes = b"PNG") -> bytes:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("full.md", body)
        bundle.writestr("images/1.png", image)
    return archive.getvalue()


class MineruService:
    def __init__(self, fail: set[str] | None = None, fail_all: bool = False,
                 lose_first_submission: bool = False) -> None:
        self.fail_all = fail_all
        # Drop the response to the first batch POST without answering, the way
        # a flaky link does: the client cannot know whether it was received.
        self.lose_first_submission = lose_first_submission
        self.base = ""
        self.submissions: list[dict[str, Any]] = []
        self.uploads: dict[str, bytes] = {}
        self.polls = 0
        # data_ids the service should report as failed conversions.
        self.fail = fail or set()

    def files(self) -> list[dict[str, str]]:
        return [entry for batch in self.submissions for entry in batch["files"]]

    def respond(self, method: str, path: str, body: bytes, headers: Any):
        if path == "/api/v4/file-urls/batch":
            payload = json.loads(body)
            self.submissions.append(payload)
            if self.lose_first_submission and len(self.submissions) == 1:
                return None
            batch = f"BATCH{len(self.submissions)}"
            urls = [f"{self.base}/upload/{entry['data_id']}" for entry in payload["files"]]
            return 200, {"code": 0, "data": {"batch_id": batch, "file_urls": urls}}, {}
        if path.startswith("/upload/"):
            self.uploads[path.rsplit("/", 1)[-1]] = body
            return 200, b"", {}
        if path.startswith("/api/v4/extract-results/batch/"):
            self.polls += 1
            index = int(path.rsplit("BATCH", 1)[-1]) - 1
            results = []
            for entry in self.submissions[index]["files"]:
                data_id = entry["data_id"]
                if self.fail_all or data_id in self.fail:
                    results.append({"data_id": data_id, "state": "failed"})
                elif data_id in self.uploads:
                    results.append({"data_id": data_id, "state": "done",
                                    "full_zip_url": f"{self.base}/zip/{data_id}"})
            return 200, {"code": 0, "data": {"extract_result": results}}, {}
        if path.startswith("/zip/"):
            data_id = path.rsplit("/", 1)[-1]
            return 200, result_zip(f"# Derived paper {data_id}\n\n![figure](images/1.png)\n"), {}
        return 404, {"code": 404}, {}
