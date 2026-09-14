"""Replay the failures from the Windows three-paper run, without live services."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow
import mineru_parse
import paper_artifacts
import zotero_ingest
from http_fixture import server
import acquire
import configure
import sources
import capability


def test_conversion_interface_owns_mutual_exclusion(tmp_path):
    request = mineru_parse.ParseRequest(pdfs=[tmp_path / 'source.pdf'], run_dir=tmp_path)
    with workflow.run_lock(tmp_path, 'conversion'):
        with pytest.raises(ValueError, match='active'):
            mineru_parse.parse(request)


def test_reordered_cross_directory_pdfs_share_the_conversion_workspace_lock(tmp_path):
    a, b = tmp_path / 'a/source.pdf', tmp_path / 'b/source.pdf'
    a.parent.mkdir()
    b.parent.mkdir()
    a.write_bytes(b'%PDF-a')
    b.write_bytes(b'%PDF-b')
    with workflow.run_lock(a.parent, 'conversion'):
        with pytest.raises(ValueError, match='active'):
            mineru_parse.parse(mineru_parse.ParseRequest(pdfs=[b, a], consent_source='message:fixture'))


def test_run_lock_excludes_second_writer_and_releases(tmp_path):
    with workflow.run_lock(tmp_path):
        with pytest.raises(ValueError, match='active'):
            with workflow.run_lock(tmp_path):
                pytest.fail('two writers entered the same run')
    with workflow.run_lock(tmp_path):
        pass


def test_private_upload_urls_can_be_saved_on_windows(tmp_path):
    path = tmp_path / '.mineru-fixture.private'
    mineru_parse.private_write(path, ['https://example.org/upload?fixture=1'])
    assert json.loads(path.read_text(encoding='utf-8')) == ['https://example.org/upload?fixture=1']


def test_poppler_utf8_output_is_not_decoded_with_windows_locale(tmp_path, monkeypatch):
    text = 'Paper with Unicode — psychology and resilience 测量结果'
    monkeypatch.setattr(paper_artifacts.shutil, 'which', lambda _: 'pdftotext')
    def run(args, **kw):
        # Reproduce a Chinese Windows parent reading the extractor's UTF-8 pipe.
        decoded = text.encode('utf-8').decode(kw.get('encoding') or 'cp936', errors=kw.get('errors', 'strict'))
        return subprocess.CompletedProcess(args, 0, decoded, '')
    monkeypatch.setattr(paper_artifacts.subprocess, 'run', run)
    assert paper_artifacts.poppler_text(tmp_path / 'paper.pdf') == text


def test_utf8_summary_validation_ignores_machine_locale(tmp_path, monkeypatch):
    pdf, summary = tmp_path / 'source.pdf', tmp_path / 'summary.md'
    pdf.write_bytes(b'%PDF-fixture')
    summary.write_bytes('provider: `test`\ntemplate_version: `4`\nsource_basis: `pdf`\n结果 — effect'.encode('utf-8'))
    paper = workflow.Paper(tmp_path, 'paper', {'artifacts': {'pdf': str(pdf), 'summary': str(summary)}})
    original = Path.read_text
    def local_read(path, encoding=None, errors=None):
        return original(path, encoding=encoding or 'cp936', errors=errors)
    monkeypatch.setattr(Path, 'read_text', local_read)
    monkeypatch.setattr(paper_artifacts, 'verify', lambda *a: ({}, 0))
    zotero_ingest.validate_artifacts({'title': 'paper'}, paper)


def test_crlf_summary_readback_uses_same_hash_as_note_writer(tmp_path):
    pdf, summary = tmp_path / 'source.pdf', tmp_path / 'summary.md'
    pdf.write_bytes(b'%PDF-fixture')
    summary.write_bytes('研究 — result\r\nsecond line\r\n'.encode('utf-8'))
    paper = workflow.Paper(tmp_path, 'paper', {'artifacts': {'pdf': str(pdf), 'summary': str(summary)}})
    evidence = {'collection_verified': True, 'note_key': 'NOTE', 'cloud_verified_at': 'now',
                'note_sha256': hashlib.sha256(summary.read_text(encoding='utf-8').encode('utf-8')).hexdigest(),
                'attachments': {'source.pdf': {'state': 'binary_verified', 'sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(),
                                               'local_path': str(pdf)}}}
    paper.validate_read_back(evidence)


def test_public_pdf_cookie_redirect_needs_no_browser(tmp_path):
    pdf = Path(__file__).parent / 'fixtures/probe.pdf'
    def respond(method, path, body, headers):
        if path == '/paper.pdf' and 'session=fixture' not in headers.get('Cookie', ''):
            return 303, b'', {'Location': '/establish-session'}
        if path == '/establish-session':
            return 303, b'', {'Set-Cookie': 'session=fixture; Path=/', 'Location': '/paper.pdf'}
        return 200, pdf.read_bytes(), {'Content-Type': 'application/pdf'}
    with server(respond) as base:
        result = acquire.acquire(acquire.AcquireRequest(
            candidate={'id': 'doi:10.1000/alpha', 'doi': '10.1000/alpha', 'title': 'Zotero MCP Write Probe',
                       'oa_pdf_url': base + '/paper.pdf'}, output=tmp_path / 'source.pdf', lookup=False))
    assert result['ok'], result
    assert result['channel'] == 'http'


def test_setup_does_not_claim_search_ready_when_all_sources_fail(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    monkeypatch.setattr(configure.credentials, 'SKILL_ENV_FILE', tmp_path / 'missing')
    monkeypatch.setattr(configure, 'probe', lambda _: {'ok': True, 'name': 'fixture'})
    monkeypatch.setattr(configure.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess([], 0))
    class ClosedSources:
        def __init__(self, **kw): pass
        def search(self, source, query, **kw):
            return SimpleNamespace(ok=False, status='rate_limited' if source == 'openalex' else 'not_configured')
    monkeypatch.setattr(sources, 'Sources', ClosedSources)
    assert configure.check(as_json=True) == 1
    result = json.loads(capsys.readouterr().out)
    missing = [row for row in result['items'] if not row['ok']]
    assert len(missing) == 1 and missing[0]['name'] == '论文检索'
    assert 'OpenAlex' in missing[0]['action']


@pytest.mark.skipif(os.name != 'nt', reason='Windows uses managed copies')
def test_updating_one_agent_updates_all_existing_managed_copies(tmp_path, monkeypatch):
    import install
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.delenv('CODEX_HOME', raising=False)
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    source = tmp_path / 'download'
    (source / 'scripts').mkdir(parents=True)
    (source / 'SKILL.md').write_text('fixture')
    code = source / 'scripts/runtime.py'
    code.write_text('version = 1')
    monkeypatch.setattr(install, 'SOURCE', source)
    install.install('all')
    code.write_text('version = 2')
    install.install('claude-code')
    for root in ('.claude', '.codex', '.pi/agent'):
        assert (tmp_path / root / 'skills/literature-to-zotero/scripts/runtime.py').read_text() == 'version = 2'


def test_native_lock_released_after_process_exit(tmp_path):
    script = '''import pathlib, sys
from workflow import run_lock
try:
    with run_lock(pathlib.Path(sys.argv[1])):
        print('acquired', flush=True)
        sys.stdin.readline()
except ValueError:
    raise SystemExit(3)
'''
    env = {**os.environ, 'PYTHONPATH': str(Path(workflow.__file__).parent)}
    command = [sys.executable, '-c', script, str(tmp_path)]
    first = subprocess.Popen(command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert first.stdout.readline().strip() == 'acquired'
        second = subprocess.run(command, env=env, input='', capture_output=True, text=True, timeout=5)
        assert second.returncode == 3
    finally:
        first.communicate('\n', timeout=5)
    assert subprocess.run(command, env=env, input='', capture_output=True, timeout=5, text=True).returncode == 0


def test_private_file_failure_preserves_original_and_closes_temporary(tmp_path, monkeypatch):
    import runtime_io
    path = tmp_path / 'private.json'
    path.write_text('original', encoding='utf-8')
    original_replace = Path.replace
    def fail(source, destination):
        if destination == path:
            raise OSError('fixture disk failure')
        return original_replace(source, destination)
    monkeypatch.setattr(Path, 'replace', fail)
    with pytest.raises(OSError, match='fixture disk failure'):
        runtime_io.private_text(path, 'new value')
    assert path.read_text() == 'original'
    assert list(tmp_path.iterdir()) == [path]
