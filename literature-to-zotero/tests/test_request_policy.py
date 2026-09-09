"""The request policy every bibliographic source shares.

A rate limit belongs to an API key, so the pacing has to hold across `Client`
objects and across processes, and a retry has to queue like any other request.
These exercise `http_client` directly, because that is where the policy lives.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time

import pytest

from http_fixture import server

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from http_client import Client, RequestError, Throttle  # noqa: E402


def ok(*_args):
    return (200, {"ok": True}, {})


def test_one_key_paces_every_client_that_uses_it(tmp_path: Path) -> None:
    """Two entry points, one key: the second waits for the first's slot."""
    with server(ok) as base:
        first = Client(budget=10, throttle=Throttle("s2", 0.5, tmp_path))
        second = Client(budget=10, throttle=Throttle("s2", 0.5, tmp_path))
        started = time.monotonic()
        first.request("GET", base + "/a")
        second.request("GET", base + "/b")
        second.request("GET", base + "/c")
    # Three requests at one per half second: two full gaps after the first.
    assert time.monotonic() - started >= 1.0


def test_a_separate_process_shares_the_same_pacing_file(tmp_path: Path) -> None:
    """The file lock is what makes the limit real for a second command."""
    with server(ok) as base:
        program = (
            "import sys, time; sys.path.insert(0, %r);"
            "from http_client import Client, Throttle;"
            "c = Client(budget=10, throttle=Throttle('s2', 0.6, __import__('pathlib').Path(%r)));"
            "c.request('GET', %r); print(time.time())"
            % (str(Path(__file__).resolve().parents[1] / "scripts"), str(tmp_path), base + "/x")
        )
        Client(budget=10, throttle=Throttle("s2", 0.6, tmp_path)).request("GET", base + "/here")
        started = time.monotonic()
        subprocess.run([sys.executable, "-c", program], check=True, capture_output=True, text=True)
    assert time.monotonic() - started >= 0.5


def test_a_retry_spends_the_same_quota_as_a_first_attempt(tmp_path: Path) -> None:
    attempts = []

    def flaky(method, path, body, headers):
        attempts.append(path)
        return (200, {"ok": True}, {}) if len(attempts) > 1 else (500, {}, {})

    with server(flaky) as base:
        client = Client(budget=20, throttle=Throttle("s2", 0.5, tmp_path))
        started = time.monotonic()
        client.request("GET", base + "/retried")
    assert len(attempts) == 2
    assert time.monotonic() - started >= 0.5


def test_a_retry_after_slows_every_caller_of_the_key(tmp_path: Path) -> None:
    with server(lambda *args: (429, {}, {"Retry-After": "2"})) as base:
        with pytest.raises(RequestError) as limited:
            Client(budget=0.2, throttle=Throttle("s2", 0.1, tmp_path)).request("GET", base + "/items")
        assert limited.value.kind == "rate_limited"
        # A different client, told nothing, still inherits the service's wait.
        with pytest.raises(RequestError) as deferred:
            Client(budget=0.2, throttle=Throttle("s2", 0.1, tmp_path)).request("GET", base + "/items")
    assert deferred.value.kind == "rate_limited"
    assert deferred.value.retry_after > 0.5


def test_a_caller_out_of_budget_leaves_the_queue_untouched(tmp_path: Path) -> None:
    """Refusing to wait must not consume the slot the waiter would have used."""
    Throttle("s2", 2, tmp_path).reserve()
    with pytest.raises(RequestError) as refused:
        Throttle("s2", 2, tmp_path).reserve(remaining=0.1)
    assert refused.value.kind == "rate_limited"
    # The refused caller took nothing: the slot is still the one it declined.
    assert Throttle("s2", 2, tmp_path).reserve(remaining=30) >= 1.0


def test_an_oversized_body_is_refused_instead_of_buffered() -> None:
    with server(lambda *args: (200, b"x" * 5000, {"Content-Type": "application/pdf"})) as base:
        with pytest.raises(RequestError) as big:
            Client(budget=5).request("GET", base + "/huge", max_bytes=1000)
    assert big.value.kind == "too_large"


def test_a_declared_read_only_post_is_retried_and_never_outcome_unknown() -> None:
    """A batch query is a query even when its arguments travel in the body."""
    attempts = []

    def flaky(method, path, body, headers):
        attempts.append(method)
        return (200, {"ok": True}, {}) if len(attempts) > 1 else (500, {}, {})

    with server(flaky) as base:
        result = Client(budget=20).request("POST", base + "/batch", body=b"[]", read_only=True)
    assert result.status == 200
    assert attempts == ["POST", "POST"]

    with server(lambda *args: (500, {}, {})) as base:
        with pytest.raises(RequestError) as write:
            Client(budget=1).request("POST", base + "/items", body=b"[]")
    assert write.value.kind == "outcome_unknown"


def test_a_key_is_dropped_when_a_redirect_leaves_its_host() -> None:
    seen: dict[str, str | None] = {}

    def elsewhere(method, path, body, headers):
        seen["x-api-key"] = headers.get("x-api-key")
        return (200, {"ok": True}, {})

    with server(elsewhere) as other:
        with server(lambda *a: (302, {}, {"Location": other + "/moved"})) as base:
            Client(budget=5).request("GET", base + "/start", headers={"x-api-key": "secret"})
    assert seen["x-api-key"] is None


def test_running_out_of_attempts_keeps_the_diagnosis_it_earned(tmp_path: Path) -> None:
    """A 429 stays a rate limit; it must not decay into "host unreachable"."""
    with server(lambda *args: (429, {}, {})) as base:
        with pytest.raises(RequestError) as limited:
            Client(budget=30).request("GET", base + "/items", max_attempts=2)
    assert limited.value.kind == "rate_limited"
    assert limited.value.retry_after >= 1

    # A host that simply never answers still reports exhaustion, not a limit.
    with pytest.raises(RequestError) as silent:
        Client(budget=30).request("GET", "http://127.0.0.1:9/x", max_attempts=2)
    assert silent.value.kind == "retry_exhausted"
