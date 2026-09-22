import json
import os
from pathlib import Path
import subprocess
import sys
from http_fixture import server
from test_cli import SCRIPTS, ROOT, run_script
from test_workflow_resume import selected_run


# Big enough that a loaded machine's loopback GET never exhausts it, small
# enough that a test aimed at an unreachable host still fails quickly.
RETRY_BUDGET = '5'


def ingest(run, base, *extra):
    env = {**os.environ, 'ZOTERO_API_KEY': 'test-secret', 'ZOTERO_LIBRARY_ID': '123', 'ZOTERO_LIBRARY_TYPE': 'user'}
    return subprocess.run([sys.executable, str(SCRIPTS / 'zotero_ingest.py'), '--run-dir', str(run), '--api-base', base,
                           '--collection-key', 'COLLECT1', '--retry-budget', RETRY_BUDGET, *extra], env=env, capture_output=True, text=True)


class ZoteroPeer:
    def __init__(self):
        self.items = {}
        self.lost = True
        self.creations = 0

    def respond(self, method, path, body, headers):
        route = path.removeprefix('/users/123')
        if method == 'GET' and route.startswith('/collections/COLLECT1'):
            return 200, {'key': 'COLLECT1', 'data': {'name': 'Test'}}, {}
        if method == 'GET' and route.startswith('/items?'):
            return 200, list(self.items.values()), {}
        if method == 'GET' and route.startswith('/items/'):
            key = route.split('/')[2]
            if route.endswith('/children?limit=100&start=0'):
                return 200, [], {}
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
        if method == 'PATCH' and route.startswith('/items/'):
            self.items[route.split('/')[2]]['data'].update(json.loads(body))
            return 204, b'', {}
        return 400, {'unsupported': [method, route]}, {}


def test_lost_create_response_recovers_one_parent_without_new_approval(tmp_path: Path):
    run = selected_run(tmp_path)
    run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha', '--state', 'metadata_only')
    peer = ZoteroPeer()
    with server(peer.respond) as base:
        first = ingest(run, base)
        second = ingest(run, base)
    assert first.returncode == 2
    assert second.returncode == 0, second.stderr + second.stdout
    assert peer.creations == 1
    parent = next(iter(peer.items.values()))
    assert parent['data']['collections'] == ['COLLECT1']
    assert 'test-secret' not in first.stdout + first.stderr + second.stdout + second.stderr


def test_existing_empty_attachment_is_uploaded_on_resume(tmp_path: Path):
    run = selected_run(tmp_path)
    source = run / 'source.pdf'
    source.write_bytes((ROOT / 'tests/fixtures/probe.pdf').read_bytes())
    candidates = json.loads((run / 'candidates.json').read_text())
    candidates[0]['title'] = 'Zotero MCP Write Probe'
    (run / 'candidates.json').write_text(json.dumps(candidates))
    run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha', '--state', 'metadata_verified')
    run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha', '--state', 'pdf_acquired', '--artifact', 'pdf=' + str(source))
    summary = run / 'summary.md'
    summary.write_text('# Core Summary\n\n- provider: `agent-default`\n- template_version: `1`\n- source_basis: `pdf`\n\nVerified probe summary.')
    run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha', '--state', 'summary_generated', '--artifact', 'summary=' + str(summary))
    peer = ZoteroPeer()
    peer.lost = False
    files = {}
    attempts = []
    storage = tmp_path / 'Zotero'
    upload_key = None
    def respond(method, path, body, headers):
        nonlocal upload_key
        route = path.removeprefix('/users/123')
        if '/children?' in route:
            parent = route.split('/')[2]
            return 200, [item for item in peer.items.values() if item['data'].get('parentItem') == parent], {}
        if route.endswith('/file'):
            key = route.split('/')[2]
            if method == 'GET':
                return (200, files[key], {}) if key in files else (404, {}, {})
            if method == 'POST':
                if body.startswith(b'upload='):
                    files[key] = source.read_bytes()
                    target = storage / 'storage' / key / 'source.pdf'
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(files[key])
                    return 204, b'', {}
                upload_key = key
                return 200, {'url': base + '/storage', 'prefix': 'PREFIX', 'suffix': 'SUFFIX', 'contentType': 'multipart/form-data; boundary=test', 'uploadKey': 'upload-key'}, {}
        if path == '/storage':
            assert 'Zotero-API-Key' not in headers
            attempts.append(upload_key)
            if len(attempts) == 1:
                return None
            assert body == b'PREFIX' + source.read_bytes() + b'SUFFIX'
            return 201, b'', {}
        return peer.respond(method, path, body, headers)
    with server(respond) as base:
        first = ingest(run, base, '--storage-root', str(storage))
        second = ingest(run, base, '--storage-root', str(storage))
    assert first.returncode == 2
    assert second.returncode == 0, second.stdout + second.stderr
    assert attempts[0] == attempts[1]
    assert sum(item['data']['itemType'] == 'attachment' for item in peer.items.values()) == 1
    status = json.loads(run_script('workflow.py', 'status', '--run-dir', str(run)).stdout)
    assert status['paper_states'] == {'read_back_verified': 1}
    replacement = run / 'replacement.pdf'
    replacement.write_bytes(b'%PDF-different-source')
    change = run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha', '--state', 'read_back_verified', '--artifact', 'pdf=' + str(replacement), check=False)
    assert change.returncode == 2
    assert 'verification evidence' in change.stderr



def test_doi_match_on_later_page_is_reused(tmp_path: Path):
    run = selected_run(tmp_path)
    run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha', '--state', 'metadata_only')
    peer = ZoteroPeer()
    peer.items['OLDITEM1'] = {'key': 'OLDITEM1', 'version': 1, 'data': {'itemType': 'journalArticle', 'DOI': 'https://doi.org/10.1000/ALPHA', 'title': 'User title', 'collections': ['OTHER123']}}
    def respond(method, path, body, headers):
        if '/items?limit=100&start=0' in path:
            return 200, [{'key': str(i), 'data': {'itemType': 'note'}} for i in range(100)], {}
        if '/items?limit=100&start=100' in path:
            return 200, list(peer.items.values()), {}
        return peer.respond(method, path, body, headers)
    with server(respond) as base:
        result = ingest(run, base)
    assert result.returncode == 0, result.stderr + result.stdout
    assert peer.creations == 0
    assert peer.items['OLDITEM1']['data']['title'] == 'User title'
    assert peer.items['OLDITEM1']['data']['collections'] == ['OTHER123', 'COLLECT1']
