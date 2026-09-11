"""Regressions from the five-paper run: useful work must survive slow services."""
from argparse import Namespace
import json
from pathlib import Path

import pytest

from test_cli import SCRIPTS, run_script
import sys
sys.path.insert(0, str(SCRIPTS))

import browser_pdf
import credentials
from workflow import Run
from test_workflow_resume import selected_run
from test_acquisition import PROBE, PROBE_TITLE
from http_fixture import server
from zotero_peer import ZoteroLibrary
from zotero_ingest import Writer, IngestRequest, ingest
from test_full_chain import confirmed_run
from test_partial_delivery import run_with_pdf
from test_process_run import process, payload
from summary_artifact import save_batch


def configure_layers(monkeypatch, tmp_path, other_library="123"):
    for key in ("ZOTERO_API_KEY", "ZOTERO_LIBRARY_ID", "ZOTERO_LIBRARY_TYPE"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / "env"
    env.write_text("ZOTERO_API_KEY=***\nZOTERO_LIBRARY_ID=123\nZOTERO_LIBRARY_TYPE=user\n")
    monkeypatch.setattr(credentials, "SKILL_ENV_FILE", env)
    monkeypatch.setattr(credentials, "_codex_zotero_env", lambda: {
        "ZOTERO_API_KEY": "valid-existing-key", "ZOTERO_LIBRARY_ID": other_library,
        "ZOTERO_LIBRARY_TYPE": "user"})
    monkeypatch.setattr(credentials, "_claude_zotero_env", lambda: {})


def test_placeholder_does_not_hide_same_library_credentials(monkeypatch, tmp_path):
    configure_layers(monkeypatch, tmp_path)
    assert credentials.zotero_credentials() == {
        "api_key": "valid-existing-key", "library_id": "123", "library_type": "user"}


@pytest.mark.parametrize('placeholder', ['***', '...', 'k\\n', '<REDACTED>', '[REDACTED]'])
def test_redacted_or_truncated_values_are_not_live_keys(monkeypatch, tmp_path, placeholder):
    configure_layers(monkeypatch, tmp_path)
    credentials.SKILL_ENV_FILE.write_text('ZOTERO_API_KEY=' + placeholder + '\nZOTERO_LIBRARY_ID=123\n')
    assert credentials.zotero_credentials()['api_key'] == 'valid-existing-key'


def test_placeholder_fallback_cannot_borrow_another_library_key(monkeypatch, tmp_path):
    configure_layers(monkeypatch, tmp_path, other_library="456")
    assert credentials.zotero_credentials()["api_key"] == ""


def test_explicit_library_type_cannot_borrow_a_user_key(monkeypatch, tmp_path):
    configure_layers(monkeypatch, tmp_path)
    monkeypatch.setenv('ZOTERO_LIBRARY_TYPE', 'group')
    assert credentials.zotero_credentials()['api_key'] == ''


def test_capture_current_follows_observed_pdf_frame_only(monkeypatch, tmp_path):
    url = "https://bera-journals.onlinelibrary.wiley.com/doi/pdf/10.1111/bjet.13454"
    pdf = url.replace("/pdf/", "/pdfdirect/")
    monkeypatch.setattr(browser_pdf, "read_state", lambda _: {
        "url": url, "content_type": "text/html", "links": [],
        "embedded_pdf_urls": [pdf], "text": "", "title": PROBE_TITLE})
    visited = []
    def walk(target, session, rounds, settle):
        visited.append(target)
        return {"url": target, "kind": "pdf", "trail": []}
    monkeypatch.setattr(browser_pdf, "walk", walk)
    monkeypatch.setattr(browser_pdf, "capture_bytes", lambda *_: (PROBE.read_bytes(), {"content_type": "application/pdf"}))
    args = Namespace(current=True, url=None, session="fixture", rounds=2, settle=0,
                     chunk=1024, output=str(tmp_path / "source.pdf"), title=PROBE_TITLE, doi=None)
    assert browser_pdf.command_capture(args) == 0
    assert visited == [pdf]
    assert (tmp_path / "source.pdf").read_bytes() == PROBE.read_bytes()


def test_selected_access_wall_can_be_recorded_and_resumed(tmp_path):
    run = selected_run(tmp_path)
    Run.record(run, "doi:10.1000/alpha", "partial", warning="challenge_unsolved")
    Run.record(run, "doi:10.1000/alpha", "pdf_acquired", artifact="pdf=" + str(PROBE))
    assert Run.open(run).paper("doi:10.1000/alpha").pdf == PROBE


def test_a_batch_scans_library_once_and_reuses_new_parent(tmp_path):
    peer = ZoteroLibrary()
    with server(peer.respond) as base:
        writer = Writer(tmp_path, {"api_key": "fixture", "library_id": "123", "library_type": "user"}, base, 5)
        first = {"id": "doi:10.1000/first", "title": "First"}
        second = {"id": "doi:10.1000/second", "title": "Second"}
        one, _ = writer.parent(first)
        writer.parent(second)
        # Another candidate ID resolves to the same work created in this batch.
        alias = {"id": "openalex:alias", "doi": "10.1000/first", "title": "First"}
        assert writer.parent(alias)[0] == one
    assert peer.requests.count(("GET", "items")) == 1
    assert peer.creations == 2


def test_network_write_does_not_lock_out_another_papers_progress(monkeypatch, tmp_path):
    run = confirmed_run(tmp_path)
    Run.record(run, "doi:10.1000/alpha", "metadata_only")
    monkeypatch.setattr(credentials, "zotero_credentials", lambda: {
        "api_key": "fixture", "library_id": "123", "library_type": "user"})
    peer = ZoteroLibrary()
    recorded = []
    def respond(method, path, body, headers):
        if method == "POST" and path.endswith("/items") and not recorded:
            Run.record(run, "openalex:W3", "pdf_acquired", artifact="pdf=" + str(PROBE))
            recorded.append(True)
        return peer.respond(method, path, body, headers)
    with server(respond) as base:
        result = ingest(IngestRequest(run_dir=run, ids=["doi:10.1000/alpha"],
                        api_base=base, collection_key="COLLECT1", retry_budget=5))
    assert result["status"] == "complete", result
    assert recorded
    assert Run.open(run).paper("openalex:W3").pdf == PROBE


@pytest.mark.parametrize("frame", ["https://other.example/paper.pdf", "http://publisher.example/paper.pdf",
                                  "https://publisher.example/login?file=paper.pdf"])
def test_current_capture_ignores_foreign_and_non_pdf_frames(monkeypatch, tmp_path, frame):
    monkeypatch.setattr(browser_pdf, "read_state", lambda _: {
        "url": "https://publisher.example/article", "content_type": "text/html",
        "embedded_pdf_urls": [frame], "links": [], "text": "", "title": "Paper"})
    monkeypatch.setattr(browser_pdf, "walk", lambda *_: pytest.fail('unrelated frame followed'))
    args = Namespace(current=True, url=None, session="fixture", rounds=2, settle=0,
                     output=str(tmp_path / "source.pdf"))
    assert browser_pdf.command_capture(args) == 2
    assert not (tmp_path / "source.pdf").exists()


def batch_for(run):
    first = payload(process(run, '--stages', 'convert'))
    batch = Path(first['summary_batch_file'])
    handoff = json.loads(batch.read_text())
    for entry in handoff['summaries']:
        Path(entry['content_file']).write_text('研究设计、实测结果与局限；以下推论尚待验证。')
    return batch, handoff, first


def test_summary_handoff_registers_batch_and_preserves_resume_target(tmp_path):
    run, _ = run_with_pdf(tmp_path)
    batch, handoff, first = batch_for(run)
    result = save_batch(batch, 'fixture-agent')
    paper = Run.open(run).paper('doi:10.1000/alpha')
    assert paper.summary and 'source_basis: `pdf`' in paper.summary.read_text()
    assert result['resume_command'] == first['resume_command']
    assert '--collection-key' in result['resume_command']
    assert save_batch(batch, 'fixture-agent') == result
    Path(handoff['summaries'][0]['content_file']).write_text('Changed interpretation')
    with pytest.raises(ValueError, match='existing summary differs'):
        save_batch(batch, 'fixture-agent')
    assert 'Changed interpretation' not in paper.summary.read_text()


def test_new_analysis_keeps_source_language_hint_and_unbounded_body(tmp_path):
    run, _ = run_with_pdf(tmp_path)
    candidates = json.loads((run / 'candidates.json').read_text())
    candidates[0]['language'] = 'en'
    (run / 'candidates.json').write_text(json.dumps(candidates))
    batch, handoff, first = batch_for(run)
    entry = handoff['summaries'][0]
    assert entry['template_version'] == '4'
    assert entry['paper_language'] == 'en'
    assert first['pending_summaries'][0]['language_policy'] == entry['language_policy']
    body = '\n\n'.join('## ' + heading + '\n' + ('Evidence-grounded explanation. ' * 30)
                       for heading in ['Task', 'Challenge', 'Insight & Inspiration', 'Novelty', 'Potential flaw', 'Motivation'])
    Path(entry['content_file']).write_text(body)
    result = run_script('summary_artifact.py', '--batch-file', str(batch), '--provider', 'fixture-agent')
    assert json.loads(result.stdout)['status'] == 'summaries_recorded'
    note = Path(entry['output']).read_text()
    assert 'template_version: `4`' in note
    assert note.endswith(body.strip() + '\n')


def test_resuming_old_summary_handoff_keeps_its_template_version(tmp_path):
    run, _ = run_with_pdf(tmp_path)
    batch, handoff, _ = batch_for(run)
    handoff['summaries'][0]['template_version'] = '3'
    batch.write_text(json.dumps(handoff))
    save_batch(batch, 'fixture-agent')
    note = Path(handoff['summaries'][0]['output']).read_text()
    assert 'template_version: `3`' in note
    assert save_batch(batch, 'fixture-agent')['status'] == 'summaries_recorded'


def test_summary_batch_refuses_changed_source_before_writing(tmp_path):
    run, _ = run_with_pdf(tmp_path)
    batch, handoff, _ = batch_for(run)
    source = Path(handoff['summaries'][0]['source'])
    source.write_bytes(source.read_bytes() + b'\nchanged')
    with pytest.raises(ValueError, match='source changed'):
        save_batch(batch, 'fixture-agent')
    assert Run.open(run).paper('doi:10.1000/alpha').summary is None


def test_summary_batch_preserves_a_note_added_after_the_handoff(tmp_path):
    run, _ = run_with_pdf(tmp_path)
    batch, _, _ = batch_for(run)
    note = run / 'user-summary.md'
    note.write_text('User-owned interpretation')
    Run.record(run, 'doi:10.1000/alpha', 'summary_generated', artifact='summary=' + str(note))
    with pytest.raises(ValueError, match='existing summary'):
        save_batch(batch, 'fixture-agent')
    assert Run.open(run).paper('doi:10.1000/alpha').summary == note


def test_upload_commit_preserves_a_new_summary_for_the_same_paper(monkeypatch, tmp_path):
    run, _ = run_with_pdf(tmp_path)
    monkeypatch.setattr(credentials, 'zotero_credentials', lambda: {
        'api_key': 'fixture', 'library_id': '123', 'library_type': 'user'})
    peer = ZoteroLibrary()
    note = run / 'new-summary.md'
    note.write_text('New interpretation arrived during PDF upload')
    changed = []
    def respond(method, path, body, headers):
        if method == 'POST' and path.endswith('/items') and not changed:
            Run.record(run, 'doi:10.1000/alpha', 'summary_generated', artifact='summary=' + str(note))
            changed.append(True)
        return peer.respond(method, path, body, headers)
    with server(respond) as base:
        peer.base = base
        result = ingest(IngestRequest(run_dir=run, api_base=base, collection_key='COLLECT1', retry_budget=5))
    assert result['status'] == 'pending'
    assert Run.open(run).paper('doi:10.1000/alpha').summary == note
    assert Run.open(run).paper('doi:10.1000/alpha').state == 'summary_generated'


def test_advisory_auth_failure_preserves_local_summary_handoff(tmp_path):
    run, _ = run_with_pdf(tmp_path)
    calls = []
    def respond(method, path, body, headers):
        calls.append((method, path))
        return 403, {}, {}
    with server(respond) as base:
        result = payload(process(run, '--stages', 'convert', '--check-ingestion', '--api-base', base))
    assert calls == [('GET', '/keys/current')]
    assert result['ingestion_readiness']['ok'] is False
    assert result['pending_summaries'] and result['summary_batch_file']
    assert set(result['timings']) == {'convert'}


def test_browser_is_lazy_and_a_human_challenge_keeps_its_tab(monkeypatch, tmp_path):
    import process_run
    monkeypatch.delenv('LITERATURE_BROWSER_DISABLED', raising=False)
    probes, visits = [], []
    monkeypatch.setattr(process_run.capability, 'probe_kimi', lambda: probes.append(True) or {
        'installed': True, 'running': True, 'extension_connected': True})
    monkeypatch.setattr(process_run.capability, 'stage_missing', lambda *_: [])
    def browser(*args):
        visits.append(args)
        return 2, {'status': 'failed', 'kind': 'challenge_unsolved'}
    monkeypatch.setattr(process_run, 'browser', browser)
    channel, _ = process_run.browser_channel(process_run.ProcessRequest(run_dir=tmp_path))
    assert probes == []
    assert channel('capture', '--url', 'https://publisher.example/one')[1]['kind'] == 'challenge_unsolved'
    assert channel('capture', '--url', 'https://publisher.example/two')[1]['kind'] == 'challenge_unsolved'
    assert len(probes) == len(visits) == 1
