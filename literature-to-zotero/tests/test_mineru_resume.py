import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import mineru_parse
from http_fixture import server
from test_cli import SCRIPTS, ROOT, run_script
from test_workflow_resume import selected_run


@pytest.mark.parametrize('remote', ['waiting-file', 'running', 'done', 'missing'])
def test_parse_recovers_lost_upload_addresses_only_for_confirmed_empty_batch(tmp_path, monkeypatch, remote):
    source = tmp_path / 'source.pdf'
    source.write_bytes(b'%PDF-fixture')
    monkeypatch.setenv('MINERU_TOKEN', 'fixture-token')
    submissions, uploads = [], []
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('full.md', 'Recovered full text')
    def respond(method, path, body, headers):
        if path == '/api/v4/file-urls/batch':
            submissions.append(json.loads(body)['files'])
            return 200, {'code': 0, 'data': {'batch_id': str(len(submissions)), 'file_urls': [base + '/upload']}}, {}
        if path == '/api/v4/extract-results/batch/1':
            results = [] if remote == 'missing' else [dict(submissions[0][0], state=remote)]
            return 200, {'code': 0, 'data': {'extract_result': results}}, {}
        if path == '/upload':
            uploads.append(body)
            return 200, b'', {}
        if path == '/api/v4/extract-results/batch/2':
            return 200, {'code': 0, 'data': {'extract_result': [dict(submissions[1][0], state='done', full_zip_url=base + '/zip')]}}, {}
        if path == '/zip':
            return 200, archive.getvalue(), {}
        return 404, {}, {}
    original = Path.replace
    def fail_private_write(path, target):
        if str(target).endswith('.private.json'):
            raise OSError('fixture interrupted private write')
        return original(path, target)
    with server(respond) as base:
        request = mineru_parse.ParseRequest(pdfs=[source], consent_source='message:fixture', api_base=base, poll_timeout=1)
        with monkeypatch.context() as fault:
            fault.setattr(Path, 'replace', fail_private_write)
            with pytest.raises(OSError):
                mineru_parse.parse(request)
        if remote == 'waiting-file':
            result = mineru_parse.parse(request)
            assert result['status'] == 'ok'
            assert Path(result['files'][0]['markdown']).read_text() == 'Recovered full text'
            assert len(submissions) == 2 and uploads == [source.read_bytes()]
        else:
            with pytest.raises(ValueError, match='upload URLs unavailable'):
                mineru_parse.parse(request)
            assert len(submissions) == 1 and not uploads


def test_poll_failure_resumes_original_batch_and_keeps_images(tmp_path: Path):
    run = selected_run(tmp_path)
    source = run / 'source.pdf'
    source.write_bytes((ROOT / 'tests/fixtures/probe.pdf').read_bytes())
    run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha', '--state', 'metadata_verified')
    run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha', '--state', 'pdf_acquired', '--artifact', 'pdf=' + str(source))
    run_script('workflow.py', 'consent', '--run-dir', str(run), '--service', 'mineru', '--decision', 'approved', '--source', 'message:175')
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('full.md', '# Paper\n![figure](images/1.png)')
        z.writestr('images/1.png', b'PNG')
    submissions, uploads = [], []
    fail_poll = True
    def respond(method, path, body, headers):
        if path == '/api/v4/file-urls/batch':
            submissions.append(json.loads(body))
            return 200, {'code': 0, 'data': {'batch_id': 'BATCH1', 'file_urls': [base + '/upload?secret=signed']}}, {}
        if path.startswith('/upload'):
            uploads.append(body)
            return 200, b'', {}
        if path == '/api/v4/extract-results/batch/BATCH1':
            if fail_poll:
                return 503, {}, {}
            return 200, {'code': 0, 'data': {'extract_result': [{'data_id': submissions[0]['files'][0]['data_id'], 'state': 'done', 'full_zip_url': base + '/zip?secret=signed'}]}}, {}
        if path.startswith('/zip'):
            return 200, archive.getvalue(), {}
        return 404, {}, {}
    def execute(base):
        return subprocess.run([sys.executable, str(SCRIPTS / 'mineru_parse.py'), '--run-dir', str(run), '--pdf', str(source), '--api-base', base, '--retry-budget', '.1', '--poll-timeout', '1'],
                              env={**os.environ, 'MINERU_TOKEN': 'test-token'}, text=True, capture_output=True)
    with server(respond) as base:
        first = execute(base)
        fail_poll = False
        second = execute(base)
    assert first.returncode == 2
    assert second.returncode == 0, second.stdout + second.stderr
    assert len(submissions) == 1
    assert len(uploads) == 1
    output = json.loads(second.stdout)['files'][0]['markdown']
    assert Path(output).read_text().startswith('# Paper')
    assert (Path(output).parent / 'images/1.png').read_bytes() == b'PNG'
    assert 'secret=signed' not in first.stdout + first.stderr + second.stdout + second.stderr


def test_adding_and_reordering_pdfs_reuses_conversion_without_overwriting_outputs(tmp_path: Path):
    a, b = tmp_path / 'a.pdf', tmp_path / 'b.pdf'
    a.write_bytes(b'%PDF-A')
    b.write_bytes(b'%PDF-B')
    batches = {}
    uploads = {}
    def respond(method, path, body, headers):
        if path == '/api/v4/file-urls/batch':
            batch = str(len(batches) + 1)
            batches[batch] = json.loads(body)['files']
            return 200, {'code': 0, 'data': {'batch_id': batch, 'file_urls': [base + '/upload/' + entry['data_id'] for entry in batches[batch]]}}, {}
        if path.startswith('/upload/'):
            uploads[path.rsplit('/', 1)[1]] = body
            return 200, b'', {}
        if path.startswith('/api/v4/extract-results/batch/'):
            return 200, {'code': 0, 'data': {'extract_result': [dict(entry, state='done', full_zip_url=base + '/zip/' + entry['data_id']) for entry in batches[path.rsplit('/', 1)[1]]]}}, {}
        if path.startswith('/zip/'):
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('full.md', uploads[path.rsplit('/', 1)[1]].decode())
            return 200, archive.getvalue(), {}
        return 404, {}, {}
    def execute(base, pdfs):
        return subprocess.run([sys.executable, str(SCRIPTS / 'mineru_parse.py'), '--consent-source', 'explicit-test-approval', '--api-base', base,
                               *[arg for pdf in pdfs for arg in ('--pdf', str(pdf))]], env={**os.environ, 'MINERU_TOKEN': 'test-token'}, text=True, capture_output=True)
    with server(respond) as base:
        first = execute(base, [a])
        second = execute(base, [a, b])
        third = execute(base, [b, a])
    assert all(result.returncode == 0 for result in (first, second, third)), second.stdout + second.stderr
    assert sum(len(entries) for entries in batches.values()) == 2
    paths = [Path(item['markdown']) for item in json.loads(second.stdout)['files']]
    assert len(set(paths)) == 2
    assert {path.read_text() for path in paths} == {'%PDF-A', '%PDF-B'}


def test_failed_paper_does_not_stop_collection_of_remaining_results(tmp_path: Path):
    paths = [tmp_path / 'bad.pdf', tmp_path / 'good.pdf']
    for i, path in enumerate(paths):
        path.write_bytes(f'%PDF-{i}'.encode())
    files = []
    polls = 0
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('full.md', 'Successful second paper')
    def respond(method, path, body, headers):
        nonlocal polls
        if path == '/api/v4/file-urls/batch':
            files.extend(json.loads(body)['files'])
            return 200, {'code': 0, 'data': {'batch_id': 'PARTIAL', 'file_urls': [base + '/upload'] * 2}}, {}
        if path == '/upload':
            return 200, b'', {}
        if path.endswith('/PARTIAL'):
            polls += 1
            results = [dict(files[0], state='failed'), dict(files[1], state='running' if polls == 1 else 'done', full_zip_url=base + '/zip')]
            return 200, {'code': 0, 'data': {'extract_result': results}}, {}
        return 200, archive.getvalue(), {}
    with server(respond) as base:
        result = subprocess.run([sys.executable, str(SCRIPTS / 'mineru_parse.py'), '--consent-source', 'test', '--api-base', base, '--poll-timeout', '10',
                                 *[arg for pdf in paths for arg in ('--pdf', str(pdf))]], env={**os.environ, 'MINERU_TOKEN': 'test-token'}, text=True, capture_output=True)
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload['status'] == 'partial'
    assert [item['state'] for item in payload['files']] == ['failed', 'done']
    assert Path(payload['files'][1]['markdown']).read_text() == 'Successful second paper'


def lost_submission_run(tmp_path: Path):
    """A run whose batch POST lost its response before any upload."""
    run = selected_run(tmp_path)
    source = run / 'source.pdf'
    source.write_bytes((ROOT / 'tests/fixtures/probe.pdf').read_bytes())
    run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha', '--state', 'pdf_acquired', '--artifact', 'pdf=' + str(source))
    run_script('workflow.py', 'consent', '--run-dir', str(run), '--service', 'mineru', '--decision', 'approved', '--source', 'message:1')
    return run, source


def test_a_submission_that_lost_its_response_reconciles_and_retries(tmp_path: Path):
    """Nothing was uploaded, so no work exists at MinerU to collide with.

    Found in a live acceptance run: the batch POST returned no response, and
    the journal then refused every later attempt, stranding the run with no
    way forward but hand-editing its files.
    """
    run, source = lost_submission_run(tmp_path)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('full.md', '# Paper\n')
    attempts = []

    def respond(method, path, body, headers):
        if path == '/api/v4/file-urls/batch':
            attempts.append(body)
            if len(attempts) == 1:
                return None  # response lost
            return 200, {'code': 0, 'data': {'batch_id': 'BATCH9', 'file_urls': [base + '/upload?s=1']}}, {}
        if path.startswith('/upload'):
            return 200, b'', {}
        if path == '/api/v4/extract-results/batch/BATCH9':
            return 200, {'code': 0, 'data': {'extract_result': [
                {'file_name': json.loads(attempts[1])['files'][0]['name'], 'state': 'done', 'full_zip_url': base + '/zip'}]}}, {}
        if path.startswith('/zip'):
            return 200, archive.getvalue(), {}
        return 404, {}, {}

    env = {**os.environ, 'MINERU_TOKEN': 'test-token'}
    with server(respond) as base:
        command = [sys.executable, str(SCRIPTS / 'mineru_parse.py'), '--run-dir', str(run),
                   '--pdf', str(source), '--api-base', base, '--retry-budget', '1', '--poll-timeout', '20']
        first = subprocess.run(command, env=env, capture_output=True, text=True)
        second = subprocess.run(command, env=env, capture_output=True, text=True)

    assert first.returncode == 2
    assert second.returncode == 0, second.stdout + second.stderr
    assert len(attempts) == 2
    journal = json.loads(next(run.glob('mineru-*.json')).read_text())
    assert journal['batch_id'] == 'BATCH9'
    assert journal['reconciliations'][0]['finding'].startswith('submission outcome unknown')


def test_an_uncertain_submission_after_an_upload_still_refuses(tmp_path: Path):
    """Once a file may exist at MinerU, only a human reconciles it."""
    run, source = lost_submission_run(tmp_path)
    journal_path = run / 'mineru-manual.json'
    import hashlib
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    journal_path.write_text(json.dumps({
        'model': 'vlm', 'ocr': False, 'extra_formats': [], 'api_base': 'http://127.0.0.1:1',
        'submission': 'outcome_unknown',
        'files': [{'path': str(source), 'sha256': digest, 'name': 'x.pdf', 'data_id': 'x',
                   'state': 'uploaded', 'consent_source': 'message:1'}],
    }))
    env = {**os.environ, 'MINERU_TOKEN': 'test-token'}
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / 'mineru_parse.py'), '--run-dir', str(run), '--pdf', str(source),
         '--api-base', 'http://127.0.0.1:1', '--retry-budget', '0.2'],
        env=env, capture_output=True, text=True)
    assert result.returncode == 2
    assert 'reconcile with MinerU' in result.stdout
