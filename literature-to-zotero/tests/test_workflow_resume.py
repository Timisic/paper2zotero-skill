from pathlib import Path
import json

from test_cli import run_script, FIXTURES


def selected_run(tmp_path: Path) -> Path:
    result = run_script('workflow.py', 'init', '--run-root', str(tmp_path), '--slug', 'resume', '--intent', 'test')
    run = Path(json.loads(result.stdout)['run_dir'])
    run_script('workflow.py', 'import-candidates', '--run-dir', str(run), '--file', str(FIXTURES / 'normalized_candidates.json'))
    run_script('workflow.py', 'approve-candidates', '--run-dir', str(run), '--ids', 'doi:10.1000/alpha')
    return run


def test_reapproving_selection_preserves_progress(tmp_path: Path) -> None:
    run = selected_run(tmp_path)
    run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha', '--state', 'metadata_verified')
    for _ in range(3):
        run_script('workflow.py', 'approve-candidates', '--run-dir', str(run), '--ids', 'doi:10.1000/alpha')
    status = json.loads(run_script('workflow.py', 'status', '--run-dir', str(run)).stdout)
    assert status['paper_states'] == {'metadata_verified': 1}


def test_cloud_consent_is_scoped_and_survives_resume(tmp_path: Path) -> None:
    run = selected_run(tmp_path)
    run_script('workflow.py', 'consent', '--run-dir', str(run), '--service', 'mineru', '--decision', 'approved', '--source', 'message:175')
    status = json.loads(run_script('workflow.py', 'status', '--run-dir', str(run)).stdout)
    assert status['consents']['mineru']['ids'] == ['doi:10.1000/alpha']
    assert status['consents']['mineru']['source'] == 'message:175'
    run_script('workflow.py', 'approve-candidates', '--run-dir', str(run), '--ids', 'doi:10.1000/alpha,openalex:W3')
    status = json.loads(run_script('workflow.py', 'status', '--run-dir', str(run)).stdout)
    assert status['consents']['mineru']['ids'] == ['doi:10.1000/alpha']


def test_missing_artifact_cannot_be_recorded(tmp_path: Path) -> None:
    run = selected_run(tmp_path)
    run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha', '--state', 'metadata_verified')
    result = run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha', '--state', 'pdf_acquired', '--artifact', 'pdf=missing.pdf', check=False)
    assert result.returncode == 2
    assert 'artifact file' in result.stderr


def test_read_back_requires_local_evidence(tmp_path: Path) -> None:
    run = selected_run(tmp_path)
    for state in ['metadata_verified', 'pdf_acquired', 'zotero_written']:
        run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha', '--state', state)
    result = run_script('workflow.py', 'record-paper', '--run-dir', str(run), '--id', 'doi:10.1000/alpha', '--state', 'read_back_verified', check=False)
    assert result.returncode == 2
    assert 'verification evidence' in result.stderr


def test_incremental_consent_and_revocation_leave_other_papers_authorized(tmp_path: Path) -> None:
    run = selected_run(tmp_path)
    run_script('workflow.py', 'consent', '--run-dir', str(run), '--service', 'mineru', '--decision', 'approved', '--source', 'first')
    run_script('workflow.py', 'approve-candidates', '--run-dir', str(run), '--ids', 'doi:10.1000/alpha,openalex:W3')
    run_script('workflow.py', 'consent', '--run-dir', str(run), '--service', 'mineru', '--decision', 'approved', '--source', 'second', '--ids', 'openalex:W3')
    status = json.loads(run_script('workflow.py', 'status', '--run-dir', str(run)).stdout)
    assert set(status['consents']['mineru']['ids']) == {'doi:10.1000/alpha', 'openalex:W3'}
    run_script('workflow.py', 'consent', '--run-dir', str(run), '--service', 'mineru', '--decision', 'revoked', '--source', 'third', '--ids', 'openalex:W3')
    status = json.loads(run_script('workflow.py', 'status', '--run-dir', str(run)).stdout)
    assert status['consents']['mineru']['ids'] == ['doi:10.1000/alpha']
    assert status['consents']['mineru']['papers']['doi:10.1000/alpha']['source'] == 'first'
