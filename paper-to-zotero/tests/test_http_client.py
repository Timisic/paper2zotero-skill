import sys
from pathlib import Path
import pytest
from http_fixture import server
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from http_client import Client, RequestError


def test_invalid_requests_are_not_retried_and_writes_are_uncertain():
    received = []
    def respond(method, path, body, headers):
        received.append((method, path))
        return (400, {'error': 'invalid'}, {}) if path == '/invalid' else None
    with server(respond) as base:
        client = Client(budget=1)
        with pytest.raises(RequestError) as bad:
            client.request('POST', base + '/invalid', body=b'{}')
        assert bad.value.kind == 'invalid_request'
        with pytest.raises(RequestError) as lost:
            client.request('POST', base + '/create', body=b'{}')
        assert lost.value.kind == 'outcome_unknown'
    assert received == [('POST', '/invalid'), ('POST', '/create')]


def test_rate_limit_preserves_wait_instruction_without_switching_routes():
    with server(lambda *args: (429, {}, {'Retry-After': '60'})) as base:
        with pytest.raises(RequestError) as limited:
            Client(budget=.1).request('GET', base + '/items')
    assert limited.value.kind == 'rate_limited'
    assert limited.value.retry_after >= 59
