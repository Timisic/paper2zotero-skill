"""Local PDF entry uses the same identity and selection boundary as ingestion."""
import json
from pathlib import Path
from test_cli import run_script, FIXTURES
from test_workflow_resume import selected_run


def prepared(tmp_path):
    run = selected_run(tmp_path)
    candidates = json.loads((run / 'candidates.json').read_text())
    candidates[0]['title'] = 'Zotero MCP Write Probe'
    (run / 'candidates.json').write_text(json.dumps(candidates))
    source = tmp_path / 'input.pdf'
    source.write_bytes((FIXTURES / 'probe.pdf').read_bytes())
    mapping = tmp_path / 'mapping.json'
    mapping.write_text(json.dumps([{'id': 'doi:10.1000/alpha', 'pdf': 'input.pdf'}]))
    return run, source, mapping


def test_relative_mapping_import_and_resume_preserve_later_artifacts(tmp_path):
    run, source, mapping = prepared(tmp_path)
    first = json.loads(run_script('workflow.py', 'import-pdfs', '--run-dir', str(run), '--file', str(mapping)).stdout)
    target = Path(first['papers'][0]['path'])
    assert target.is_relative_to(run) and target.read_bytes() == source.read_bytes()
    assert first['papers'][0]['action'] == 'imported'
    summary = run / 'summary.md'; summary.write_text('kept')
    run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha',
               '--state', 'summary_generated', '--artifact', 'summary=' + str(summary))
    before = (run / 'manifest.json').read_bytes(), target.stat().st_mtime_ns
    second = json.loads(run_script('workflow.py', 'import-pdfs', '--run-dir', str(run), '--file', str(mapping)).stdout)
    assert second['papers'][0]['action'] == 'reused'
    assert before == ((run / 'manifest.json').read_bytes(), target.stat().st_mtime_ns)
    source.write_bytes(source.read_bytes() + b'\n% modified but same paper\n')
    conflict = json.loads(run_script('workflow.py', 'import-pdfs', '--run-dir', str(run), '--file', str(mapping)).stdout)
    assert conflict['status'] == 'partial'
    assert before == ((run / 'manifest.json').read_bytes(), target.stat().st_mtime_ns)


def test_selection_checked_before_any_copy_and_bad_pdf_stays_unrecorded(tmp_path):
    run, source, mapping = prepared(tmp_path)
    mapping.write_text(json.dumps([{'id': 'openalex:W3', 'pdf': str(source)}]))
    result = run_script('workflow.py', 'import-pdfs', '--run-dir', str(run), '--file', str(mapping), check=False)
    assert result.returncode == 2 and not list((run / 'papers').iterdir())
    mapping.write_text(json.dumps([{'id': 'doi:10.1000/alpha', 'pdf': str(source)}]))
    source.write_text('<html>login</html>')
    result = json.loads(run_script('workflow.py', 'import-pdfs', '--run-dir', str(run), '--file', str(mapping)).stdout)
    assert result['papers'][0]['status'] == 'rejected'
    assert source.read_text() == '<html>login</html>'
    assert not list((run / 'papers').rglob('*.pdf'))
    assert not json.loads((run / 'manifest.json').read_text())['papers']['doi:10.1000/alpha'].get('artifacts')
