#!/usr/bin/env python3
"""Run a fixed, reviewed set of existing CLI scenarios with disposable peers."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

CASES = {
    'unified-local': [
        'test_unified_local.py::test_missing_reused_unsynced_local_attachment_can_recover',
        'test_unified_local.py::test_new_summary_and_files_require_fresh_write_evidence',
        'test_unified_local.py::test_stale_markdown_does_not_block_a_valid_pdf_based_summary',
        'test_unified_local.py::test_native_synced_hash_allows_guarded_missing_file_recovery',
        'test_unified_local.py::test_metadata_then_pdf_and_local_parse_use_one_parent',
        'test_unified_local.py::test_missing_local_authorization_cannot_use_web_credentials',
        'test_unified_local.py::test_lost_local_create_response_recovers_without_duplicate',
        'test_unified_local.py::test_server_identity_change_and_external_storage_fail_closed',
        'test_unified_local.py::test_late_doi_enriches_existing_parent_and_preserves_human_fields',
        'test_unified_local.py::test_identity_conflicts_do_not_mutate_items',
        'test_unified_local.py::test_stale_derivatives_and_completed_pdf_recovery',
        'test_unified_local.py::test_alias_enrichment_keeps_selection_and_consent',
        'test_unified_local.py::test_local_backend_rejects_nonloopback_endpoint',
        'test_unified_local.py::test_lost_local_file_registration_recovers_existing_bytes',
        'test_unified_local.py::test_local_parser_failure_keeps_pdf_delivery_without_cloud_fallback',
        'test_unified_local.py::test_cli_defaults_are_local',
    ],
    'local-parser': [
        'test_local_parse.py::test_local_cli_uses_only_local_settings_and_preserves_input',
        'test_local_parse.py::test_existing_output_is_never_overwritten',
        'test_local_parse.py::test_failure_has_no_implicit_fallback',
        'test_local_parse.py::test_explicit_fallback_records_actual_engine',
        'test_local_parse.py::test_image_only_markdown_is_not_success',
        'test_local_parse.py::test_timeout_stops_owned_descendant_even_after_parent_exits'],
    'discovery': [
        'test_discovery.py::test_one_paper_found_twice_becomes_one_candidate_with_both_accounts',
        'test_discovery.py::test_a_failed_source_never_looks_like_an_empty_shelf',
        'test_candidate_list.py::test_a_short_list_is_returned_as_is_without_padding'],
    'selection': [
        'test_single_gate_flow.py::test_clear_intent_reaches_candidates_without_a_plan_gate',
        'test_process_run.py::test_processing_refuses_before_the_user_confirms_the_list',
        'test_process_run.py::test_unselected_papers_are_never_processed',
        'test_process_run.py::test_conversion_without_consent_is_recorded_and_never_blocks_the_pdf'],
    'local-pdf': [
        'test_import_pdfs.py::test_relative_mapping_import_and_resume_preserve_later_artifacts',
        'test_import_pdfs.py::test_selection_checked_before_any_copy_and_bad_pdf_stays_unrecorded'],
    'acquisition': [
        'test_http_acquisition.py::test_a_known_open_pdf_is_fetched_without_the_browser',
        'test_http_acquisition.py::test_an_html_page_served_as_a_pdf_is_not_a_source_pdf',
        'test_http_acquisition.py::test_a_valid_pdf_of_the_wrong_paper_leaves_nothing_behind'],
    'delivery': [
        'test_full_chain.py::test_one_invocation_carries_a_confirmed_selection_to_read_back[ordinary-path]',
        'test_full_chain.py::test_a_conversion_failure_still_delivers_the_pdf',
        'test_full_chain.py::test_a_lost_mineru_submission_does_not_strand_the_chain'],
    'lab-defaults': [
        'test_lab_defaults.py::test_search_backend_defaults_to_kimi',
        'test_lab_defaults.py::test_kimi_search_writes_browser_hits_and_a_block_is_unavailable',
        'test_lab_defaults.py::test_mineru_default_is_the_lan_host',
        'test_lab_defaults.py::test_unhealthy_self_host_drops_out_of_the_chain',
        'test_lab_defaults.py::test_tasks_api_unpacks_full_md',
        'test_lab_defaults.py::test_preflight_names_kimi_and_the_lan_host',
        'test_lab_defaults.py::test_ingestion_stage_is_ready_from_local_write_without_calling_the_web_key',
        'test_lab_defaults.py::test_ingest_uses_the_local_api_without_a_web_key'],
}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def pytest_configure(config):
    """Pytest plugin: retain actual CLI commands, results and exit codes."""
    original = subprocess.run
    transcript = Path(os.environ['P2Z_VERIFY_TRANSCRIPT'])

    def recorded(*args, **kwargs):
        started = time.time()
        try:
            result = original(*args, **kwargs)
        except subprocess.CalledProcessError as error:
            record(error.cmd, error.returncode, error.stdout, error.stderr, started)
            raise
        record(result.args, result.returncode, result.stdout, result.stderr, started)
        return result

    def record(command, code, stdout, stderr, started):
        def plain(value):
            return value.decode(errors='replace') if isinstance(value, bytes) else value
        entry = dict(command=command, exit_code=code, stdout=plain(stdout), stderr=plain(stderr), started=started)
        text = json.dumps(entry, ensure_ascii=False, default=str)
        for synthetic_secret in ('test-secret', 'test-token', 'super-secret', 's2-key'):
            text = text.replace(synthetic_secret, '<fixture-secret>')
        with transcript.open('a') as stream:
            stream.write(text + '\n')

    subprocess.run = recorded


def test_file(repo, node):
    return repo / 'paper-to-zotero' / 'tests' / node.split('::', 1)[0]


def runnable(repo, feature):
    return all(test_file(repo, node).is_file() for node in CASES[feature])


def doctor(repo):
    required = ['workflow.py', 'process_run.py', 'discovery.py', 'summary_artifact.py', 'zotero_ingest.py', 'local_pdf.py']
    files = [repo / 'paper-to-zotero/scripts' / name for name in required]
    checks = {
        'python': sys.version.split()[0], 'interpreter': sys.executable,
        'python_supported': sys.version_info >= (3, 11),
        'pytest': importlib.util.find_spec('pytest') is not None,
        'pdftotext': shutil.which('pdftotext'), 'pdfinfo': shutil.which('pdfinfo'),
        'scripts_present': all(path.is_file() for path in files),
        'source_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files if path.is_file()},
        'mode': 'offline fixtures; no persistent production instance',
    }
    checks['ok'] = all(checks[key] for key in ('python_supported', 'pytest', 'pdftotext', 'pdfinfo', 'scripts_present'))
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['doctor', 'run'])
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument('--feature', choices=['all', *CASES], default='all')
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    checks = doctor(repo)
    if args.action == 'doctor' or not checks['ok']:
        print(json.dumps(checks, indent=2))
        return 0 if checks['ok'] else 2
    if args.feature != 'all' and not runnable(repo, args.feature):
        print(json.dumps({
            'ok': False,
            'feature': args.feature,
            'reason': 'this branch does not ship the scripts or tests for this feature',
        }, indent=2))
        return 2
    selected = list(CASES) if args.feature == 'all' else [args.feature]
    features = [name for name in selected if runnable(repo, name)]
    evidence = (args.evidence or repo / 'literature-runs' / ('verification-' + time.strftime('%Y%m%d-%H%M%S'))).resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    save(evidence / 'doctor.json', checks)
    scratch = Path(tempfile.mkdtemp(prefix='p2z-verify-'))
    result_code = 2
    cleanup = {'scratch': str(scratch), 'removed': False, 'listening_ports_after': []}
    try:
        app = scratch / 'paper-to-zotero'
        for folder in ('scripts', 'tests'):
            shutil.copytree(repo / 'paper-to-zotero' / folder, app / folder,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copytree(repo / 'paper-to-zotero/references', app / 'references')
        profile = scratch / 'profile'
        profile.mkdir()
        temp = scratch / 'tmp'
        temp.mkdir()
        ports = evidence / 'ports.txt'
        ports.touch()
        # A fresh child environment, never a dump/filter of host credentials.
        env = {
            'PATH': os.defpath + os.pathsep + str(Path(sys.executable).parent) + ':/opt/homebrew/bin:/usr/local/bin',
            'HOME': str(profile), 'USERPROFILE': str(profile), 'CODEX_HOME': str(profile / '.codex'),
            'TMPDIR': str(temp), 'TMP': str(temp), 'TEMP': str(temp),
            'PYTHONPATH': str(Path(__file__).parent), 'PYTHONDONTWRITEBYTECODE': '1',
            'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTHONUTF8': '1',
            'P2Z_VERIFY_PORTS': str(ports), 'P2Z_VERIFY_NETWORK': str(evidence / 'network.jsonl'),
            'P2Z_VERIFY_TRANSCRIPT': str(evidence / 'commands.jsonl'),
        }
        nodes = [str(app / 'tests' / node) for feature in features for node in CASES[feature]]
        command = [sys.executable, '-m', 'pytest', '-p', 'verify_runner', '-p', 'no:cacheprovider',
                   '-vv', '--tb=short', '--basetemp', str(scratch / 'cases'),
                   '--junitxml', str(evidence / 'results.xml'), *nodes]
        save(evidence / 'invocation.json', {'command': command, 'features': features, 'fixture_only': True})
        # Assert that the child guard loaded before launching any application code.
        guard = subprocess.run([sys.executable, '-c',
            "import socket\ntry: socket.create_connection(('127.0.0.1',23119),timeout=.1)\nexcept OSError as e: assert 'verification blocked' in str(e)\nelse: raise AssertionError('guard missing')"],
            env=env, cwd=scratch, capture_output=True, text=True)
        save(evidence / 'guard.json', {'exit_code': guard.returncode, 'stderr': guard.stderr})
        if guard.returncode:
            raise RuntimeError('network guard self-check failed; see guard.json')
        with (evidence / 'pytest.log').open('w') as log:
            process = subprocess.Popen(command, env=env, cwd=scratch, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                result_code = process.wait(timeout=180)
            finally:
                # This process group belongs only to this run, including CLI children.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
    finally:
        cases = scratch / 'cases'
        if cases.exists():
            shutil.copytree(cases, evidence / 'state', symlinks=True)
        if (evidence / 'ports.txt').exists():
            for port in set((evidence / 'ports.txt').read_text().splitlines()):
                with socket.socket() as probe:
                    probe.settimeout(.2)
                    if probe.connect_ex(('127.0.0.1', int(port))) == 0:
                        cleanup['listening_ports_after'].append(int(port))
        shutil.rmtree(scratch)
        cleanup['removed'] = not scratch.exists()
        save(evidence / 'cleanup.json', cleanup)
        save(evidence / 'result.json', {'exit_code': result_code, 'fixture_only': True,
             'cleanup_ok': cleanup['removed'] and not cleanup['listening_ports_after']})
    print(json.dumps({'evidence': str(evidence), 'exit_code': result_code, 'cleanup': cleanup}, indent=2))
    return result_code if not cleanup['listening_ports_after'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
