"""Bounded HTTP transport. Writes with lost responses require caller reconciliation."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import http.client
import http.cookiejar
import json
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Iterator
import urllib.error
import urllib.parse
import urllib.request

from runtime_io import file_lock


class RequestError(RuntimeError):
    def __init__(self, kind: str, status: int | None = None, retry_after: float = 0):
        self.kind, self.status, self.retry_after = kind, status, retry_after
        super().__init__(f'{kind} (HTTP {status})' if status else kind)


@dataclass
class Response:
    status: int
    body: bytes
    headers: Any

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except (ValueError, UnicodeError):
            raise RequestError('invalid_response', self.status) from None


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if old.scheme == 'https' and new.scheme != 'https':
            raise RequestError('insecure_redirect')
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and (old.scheme, old.netloc) != (new.scheme, new.netloc):
            # A credential is issued for one host. A publisher redirect out of
            # a metadata API must not carry that host's key with it.
            for name in ('Authorization', 'Zotero-api-key', 'X-api-key', 'Cookie'):
                redirected.remove_header(name)
        return redirected


def delay_seconds(value: str | None) -> float:
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            return 0


THROTTLE_DIR_ENV = 'LITERATURE_THROTTLE_DIR'
DEFAULT_THROTTLE_DIR = Path.home() / '.cache' / 'literature-to-zotero' / 'throttle'


def throttle_dir() -> Path:
    """Where the shared pacing files live. Overridable so tests stay local."""
    return Path(os.environ.get(THROTTLE_DIR_ENV) or DEFAULT_THROTTLE_DIR)


class Throttle:
    """One request per interval for a shared key, across processes on this machine.

    A rate limit belongs to the API key, not to a `Client` object. Two entry
    points running at once — a discovery command and an acquisition command,
    say — would each believe they owned the full rate, and together they would
    break it. So the time the next request may start lives in a small file
    guarded by `flock`, and every attempt claims a slot before it goes out:
    first tries, retries after a 5xx, and the extra requests of a paged search
    all queue in the same line.

    Two limits are worth stating rather than hiding. Traffic from *another
    machine* using the same key is outside this bound. And a process that dies
    between claiming a slot and sending its request simply leaves that slot
    unused, which is the safe direction to fail.
    """

    def __init__(self, key: str, interval: float, directory: Path | None = None) -> None:
        self.key, self.interval = key, max(0.0, interval)
        self.path = (directory or throttle_dir()) / f'{key}.slot'

    @contextmanager
    def _claim(self) -> Iterator[Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self.path.with_suffix('.lock'), blocking=True):
            with open(self.path, 'a+', encoding='ascii') as handle:
                yield handle

    @staticmethod
    def _read(handle: Any) -> float:
        handle.seek(0)
        try:
            return float(handle.read().strip() or 0)
        except ValueError:
            return 0.0

    @staticmethod
    def _write(handle: Any, value: float) -> None:
        handle.seek(0)
        handle.truncate()
        handle.write(f'{value:.6f}')
        handle.flush()

    def reserve(self, remaining: float | None = None) -> float:
        """Wait for this key's next slot and take it. Returns seconds waited.

        `remaining` is the caller's own deadline: when the slot lies beyond it,
        nothing is claimed and the wait is reported as a rate limit, so a
        caller out of budget spends no quota and leaves the queue as it found
        it.
        """
        if self.interval <= 0:
            return 0.0
        with self._claim() as handle:
            now = time.time()
            start = max(now, self._read(handle))
            wait = start - now
            if remaining is not None and wait > remaining:
                raise RequestError('rate_limited', retry_after=wait)
            self._write(handle, start + self.interval)
        if wait > 0:
            time.sleep(wait)
        return wait

    def defer(self, seconds: float) -> None:
        """Push every waiting caller back, e.g. after a Retry-After."""
        if seconds <= 0:
            return
        with self._claim() as handle:
            target = time.time() + seconds
            if target > self._read(handle):
                self._write(handle, target)


class Client:
    def __init__(self, budget: float = 90, timeout: float = 20, throttle: Throttle | None = None, *, cookies: bool = False):
        self.budget, self.timeout = budget, min(timeout, 30)
        self.throttle = throttle
        self.routes = {
            'direct': urllib.request.build_opener(urllib.request.ProxyHandler({}), SafeRedirect()),
            'environment': urllib.request.build_opener(SafeRedirect()),
        }
        if cookies:
            # Only public-PDF acquisition opts in. Standard domain/path rules
            # apply; no browser profile or persistent cookie storage is read.
            jar = http.cookiejar.CookieJar()
            for opener in self.routes.values():
                opener.add_handler(urllib.request.HTTPCookieProcessor(jar))
        self.preferred: dict[str, tuple[str, float]] = {}
        self.not_before: dict[str, float] = {}

    def request(self, method: str, url: str, *, body: bytes | None = None,
                headers: dict[str, str] | None = None, read_only: bool | None = None,
                max_bytes: int | None = None, budget: float | None = None,
                max_attempts: int | None = None) -> Response:
        """One bounded request.

        `read_only` overrides the method's default meaning. A query that has to
        be sent as POST because its argument list is too long for a URL — the
        Semantic Scholar batch endpoint is one — is still a query: it may be
        retried, and a lost response leaves nothing half-done. Declaring it
        here keeps that judgement out of the transport's guesswork and leaves
        the `outcome_unknown` contract for real writes untouched.
        """
        parts = urllib.parse.urlsplit(url)
        host = parts.netloc
        if parts.username or parts.password:
            raise RequestError('credentials_in_url')
        if parts.scheme != 'https' and parts.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise RequestError('insecure_transport')
        read_only = method in ('GET', 'HEAD') if read_only is None else read_only
        deadline = time.monotonic() + (self.budget if budget is None else budget)
        routes = ['direct'] if parts.hostname in ('127.0.0.1', 'localhost', '::1') else ['environment', 'direct']
        cached = self.preferred.get(host)
        if cached and cached[1] > time.monotonic() and cached[0] in routes:
            routes.remove(cached[0])
            routes.insert(0, cached[0])
        attempt = 0
        # The last thing the service actually told us. Running out of attempts
        # must not turn "you are going too fast" into "the host is unreachable":
        # those have different fixes, and the caller records which wall it hit.
        diagnosed: RequestError | None = None
        while True:
            remaining = deadline - time.monotonic()
            wait = max(0, self.not_before.get(host, 0) - time.monotonic())
            if remaining <= wait:
                raise RequestError('rate_limited' if wait else 'retry_exhausted', retry_after=wait)
            if wait:
                time.sleep(wait)
            if self.throttle is not None:
                # Retries queue like first attempts: a burst of failures must
                # not spend more of the key's quota than a burst of successes.
                self.throttle.reserve(deadline - time.monotonic())
            remaining = deadline - time.monotonic()
            route = routes[attempt % len(routes)]
            attempt += 1
            print(json.dumps({'http': method, 'host': host, 'route': route, 'attempt': attempt}), file=sys.stderr, flush=True)
            try:
                request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
                with self.routes[route].open(request, timeout=min(self.timeout, remaining)) as reply:
                    chunks = []
                    received = 0
                    progress_at = time.monotonic()
                    while True:
                        if time.monotonic() >= deadline:
                            raise TimeoutError('response deadline')
                        chunk = reply.read1(65536)
                        if not chunk:
                            if reply.length:
                                raise http.client.IncompleteRead(b'')
                            break
                        chunks.append(chunk)
                        received += len(chunk)
                        if max_bytes is not None and received > max_bytes:
                            raise RequestError('too_large', reply.status)
                        if time.monotonic() - progress_at >= 20:
                            print(json.dumps({'http': method, 'host': host, 'stage': 'receiving'}), file=sys.stderr, flush=True)
                            progress_at = time.monotonic()
                    raw = b''.join(chunks)
                    result = Response(reply.status, raw, reply.headers)
                self.preferred[host] = (route, time.monotonic() + 300)
                self.not_before[host] = time.monotonic() + delay_seconds(result.headers.get('Backoff'))
                return result
            except urllib.error.HTTPError as error:
                status = error.code
                wait = max(delay_seconds(error.headers.get('Retry-After')), delay_seconds(error.headers.get('Backoff')))
                error.close()
                if status == 429:
                    diagnosed = RequestError('rate_limited', status, max(wait, 1))
                    self.not_before[host] = time.monotonic() + max(wait, 1)
                    if self.throttle is not None:
                        # The service just said the shared key is going too
                        # fast; every entry point behind it has to slow down.
                        self.throttle.defer(max(wait, 1))
                    if not read_only or time.monotonic() + max(wait, 1) >= deadline:
                        raise RequestError('rate_limited', status, max(wait, 1)) from None
                elif status < 500:
                    kind = {401: 'authentication_required', 403: 'permission_denied', 404: 'not_found', 409: 'conflict', 412: 'conflict'}.get(status, 'invalid_request')
                    raise RequestError(kind, status) from None
                elif not read_only:
                    raise RequestError('outcome_unknown', status) from None
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
                if not read_only:
                    raise RequestError('outcome_unknown') from None
            if max_attempts is not None and attempt >= max_attempts:
                # Some callers have somewhere else to try. A PDF with four
                # candidate URLs is served better by the next URL than by a
                # fourth attempt at a host that is not answering.
                raise diagnosed or RequestError('retry_exhausted')
            pause = min(2 ** min(attempt - 1, 3) + random.random(), 8)
            if time.monotonic() + pause >= deadline:
                raise diagnosed or RequestError('retry_exhausted')
            print(json.dumps({'http': method, 'host': host, 'retry_in': round(pause, 2)}), file=sys.stderr, flush=True)
            time.sleep(pause)
