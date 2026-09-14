#!/usr/bin/env python3
"""Resume a consented MinerU batch; preserve batch IDs and per-file results."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field, replace
import hashlib
import io
import json
from pathlib import Path
import sys
import time
from typing import Any, Sequence
import zipfile

import credentials
from http_client import Client, RequestError
from workflow import Run, read_json, utc_now, write_json, run_lock
from runtime_io import private_text


@dataclass(frozen=True)
class ParseRequest:
    """One conversion request, stated in types a caller can be checked against.

    Consent comes from the run when `run_dir` is given, and only from an
    explicit `consent_source` otherwise — uploading a PDF to MinerU is never
    implied by the shape of this request.
    """
    pdfs: Sequence[Path]
    run_dir: Path | None = None
    output: Path | None = None
    consent_source: str | None = None
    model: str = 'vlm'
    ocr: bool = False
    extra_formats: Sequence[str] = field(default_factory=tuple)
    api_base: str = 'https://mineru.net'
    retry_budget: float = 90
    poll_timeout: float = 120

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> ParseRequest:
        return cls(
            pdfs=[Path(value) for value in args.pdf],
            run_dir=Path(args.run_dir).resolve() if args.run_dir else None,
            output=Path(args.output) if args.output else None,
            consent_source=args.consent_source, model=args.model, ocr=args.ocr,
            extra_formats=tuple(args.extra_formats), api_base=args.api_base,
            retry_budget=args.retry_budget, poll_timeout=args.poll_timeout,
        )

    def lock_root(self) -> Path:
        return Path(self.run_dir or self.output or Path(self.pdfs[0]).resolve().parent).resolve()


def private_write(path: Path, data: Any) -> None:
    private_text(path, json.dumps(data, ensure_ascii=False))


def unpack(raw: bytes, target: Path) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        md_names = [name for name in archive.namelist() if name.endswith('full.md')]
        if len(md_names) != 1:
            raise ValueError('MinerU result must contain exactly one full.md')
        root = Path(md_names[0]).parent
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            path = Path(entry.filename)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('unsafe archive path')
            if not path.is_relative_to(root):
                continue
            relative = path.relative_to(root)
            if relative.name == 'full.md':
                relative = relative.with_name('paper.md')
            output = target / relative
            if not output.resolve().is_relative_to(target.resolve()):
                raise ValueError('unsafe output path')
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(archive.read(entry))
    return str((target / 'paper.md').resolve())


def artifact_valid(record: dict[str, Any]) -> bool:
    if record.get('state') != 'done':
        return False
    hashes = record.get('output_hashes') or {record.get('markdown', ''): record.get('markdown_sha256')}
    return bool(hashes) and all(Path(path).is_file() and hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in hashes.items())


class Batch:
    def __init__(self, request: ParseRequest, journal: Path, state: dict[str, Any], token: str):
        self.request, self.journal, self.state = request, journal, state
        self.private = journal.with_name('.' + journal.stem + '.private.json')
        self.client = Client(budget=request.retry_budget, timeout=20)
        self.headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    def save(self) -> None:
        write_json(self.journal, self.state)

    def api(self, method: str, path: str, data: Any = None) -> Any:
        response = self.client.request(method, self.request.api_base.rstrip('/') + path, headers=self.headers,
                                      body=json.dumps(data).encode() if data is not None else None).json()
        if response.get('code') != 0:
            raise ValueError(f"MinerU API rejected request (code {response.get('code')})")
        return response.get('data') or {}

    def submit(self) -> None:
        if self.state.get('submission') == 'outcome_unknown':
            # An uncertain submission is only dangerous once files exist at
            # MinerU. With no batch id and nothing uploaded, whatever may have
            # been created there holds no file and expires unused, so the
            # reconciliation is this check itself — recorded, then one new
            # batch. Any upload already in flight still stops the run.
            if self.state.get('batch_id') or any(record['state'] != 'pending' for record in self.state['files']):
                raise ValueError('batch submission outcome unknown; reconcile with MinerU before starting another batch')
            self.state.setdefault('reconciliations', []).append({
                'at': utc_now(),
                'finding': 'submission outcome unknown, no batch id returned, no file uploaded',
                'action': 'resubmitted as a new batch',
            })
        self.state['submission'] = 'outcome_unknown'
        self.save()
        entries = [{key: record[key] for key in ('name', 'data_id')} for record in self.state['files']]
        try:
            data = self.api('POST', '/api/v4/file-urls/batch', {'files': entries, 'model_version': self.request.model,
                            'is_ocr': self.request.ocr, 'extra_formats': self.request.extra_formats})
        except RequestError as error:
            if error.kind not in ('outcome_unknown', 'invalid_response'):
                self.state['submission'] = 'rejected'
                self.save()
            raise
        if not data.get('batch_id') or len(data.get('file_urls', [])) != len(entries):
            raise ValueError('MinerU returned incomplete batch identity')
        self.state['batch_id'] = data['batch_id']
        self.state['submission'] = 'confirmed'
        self.save()
        private_write(self.private, data['file_urls'])

    def recover_empty_batch(self, requested: set[str]) -> None:
        """Reconcile a saved identity whose private upload URLs never survived."""
        records = self.state['files']
        if requested != {r['data_id'] for r in records} or any(r['state'] != 'pending' for r in records):
            raise ValueError('upload URLs unavailable; existing upload outcome requires reconciliation')
        previous = self.state['batch_id']
        results = self.api('GET', '/api/v4/extract-results/batch/' + previous).get('extract_result', [])
        if not isinstance(results, list) or len(results) != len(records):
            raise ValueError('upload URLs unavailable; MinerU has not confirmed every file is waiting')
        matches = [next((item for item in results if isinstance(item, dict) and
                         (item.get('data_id') == record['data_id'] or item.get('file_name') == record['name'])), {})
                   for record in records]
        if any(item.get('state') != 'waiting-file' for item in matches):
            raise ValueError('upload URLs unavailable; existing MinerU work must be preserved')
        self.state.setdefault('reconciliations', []).append({
            'at': utc_now(), 'previous_batch_id': previous,
            'finding': 'all consented files confirmed waiting-file; no local upload started',
            'action': 'replace empty batch after private upload URLs were lost',
        })
        self.state.pop('batch_id')
        self.state['submission'] = 'empty_batch_reconciled'
        self.save()
        self.submit()

    def resume(self, requested: set[str]) -> None:
        active = [record for record in self.state['files'] if record['data_id'] in requested]
        if all(artifact_valid(record) or record['state'] == 'failed' for record in active):
            return
        if not self.state.get('batch_id'):
            # An interrupted prepared batch cannot gain authorization for its
            # other members just because one member was requested again.
            if requested != {record['data_id'] for record in self.state['files']}:
                raise ValueError('resume the consented prepared batch before changing its membership')
            self.submit()
        try:
            urls = read_json(self.private) if self.private.exists() else []
        except (ValueError, UnicodeError):
            urls = []
        needs_upload = any(r['data_id'] in requested and r['state'] == 'pending' for r in self.state['files'])
        if needs_upload and (not isinstance(urls, list) or len(urls) != len(self.state['files'])):
            self.recover_empty_batch(requested)
            urls = read_json(self.private)
        for i, record in enumerate(self.state['files']):
            if record['data_id'] not in requested or record['state'] in ('uploaded', 'done', 'failed'):
                continue
            if len(urls) != len(self.state['files']):
                raise ValueError('upload URLs unavailable; preserve batch and reconcile with MinerU')
            signed = urls[i] if isinstance(urls[i], str) else urls[i].get('url') or urls[i].get('file_url')
            source = Path(record['path'])
            if hashlib.sha256(source.read_bytes()).hexdigest() != record['sha256']:
                raise ValueError('source changed since batch submission')
            record['state'] = 'uploading'
            self.save()
            self.client.request('PUT', signed, body=source.read_bytes(), headers={'Content-Type': ''})
            record['state'] = 'uploaded'
            self.save()
        for record in active:
            if record['state'] == 'done' and not artifact_valid(record):
                record['state'] = 'uploaded'
        deadline = time.monotonic() + self.request.poll_timeout
        while any(record['state'] not in ('done', 'failed') for record in active):
            results = self.api('GET', '/api/v4/extract-results/batch/' + self.state['batch_id']).get('extract_result', [])
            for record in active:
                if record['state'] in ('done', 'failed'):
                    continue
                result: dict[str, Any] = next((r for r in results if r.get('data_id') == record['data_id'] or r.get('file_name') == record['name']), {})
                if result.get('state') == 'failed':
                    record['state'] = 'failed'
                    self.save()
                    continue
                if result.get('state') != 'done' or not result.get('full_zip_url'):
                    continue
                raw = self.client.request('GET', result['full_zip_url']).body
                root = Path(self.request.output).resolve() if self.request.output else Path(record['path']).parent / 'mineru'
                target = root / record['data_id']
                try:
                    markdown = unpack(raw, target)
                    hashes = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in target.rglob('*') if path.is_file()}
                    record.update({'state': 'done', 'markdown': markdown, 'markdown_sha256': hashlib.sha256(Path(markdown).read_bytes()).hexdigest(), 'output_hashes': hashes})
                except (ValueError, zipfile.BadZipFile) as error:
                    record.update({'state': 'failed', 'reason': type(error).__name__})
                self.save()
            if all(record['state'] in ('done', 'failed') for record in active):
                break
            if time.monotonic() >= deadline:
                raise ValueError('MinerU still processing; rerun the same command to resume this batch')
            print(json.dumps({'batch_id': self.state['batch_id'], 'stage': 'processing', 'done': sum(r['state'] == 'done' for r in active)}), file=sys.stderr, flush=True)
            time.sleep(min(5, max(0, deadline - time.monotonic())))
        if all(record['state'] in ('done', 'failed') for record in self.state['files']):
            self.private.unlink(missing_ok=True)


def parse(request: ParseRequest) -> dict[str, Any]:
    """Convert under one lock, including consent, checkpoint lookup and recovery."""
    if not request.pdfs:
        raise ValueError('PDF file missing')
    request = replace(request, pdfs=tuple(sorted({Path(pdf).expanduser().resolve() for pdf in request.pdfs})))
    with run_lock(request.lock_root(), 'conversion'):
        return _parse(request)


def _parse(request: ParseRequest) -> dict[str, Any]:
    pdfs = list(request.pdfs)
    if any(not pdf.is_file() for pdf in pdfs):
        raise ValueError('PDF file missing')
    run = request.run_dir
    consent_sources = {}
    if run:
        package = Run.open(run)
        package.require_confirmed()
        mapped = {paper.path('pdf'): paper.id for paper in package.papers() if paper.path('pdf')}
        if any(pdf not in mapped for pdf in pdfs):
            raise ValueError('PDF is not recorded for a selected paper')
        identities = [mapped[pdf] for pdf in pdfs]
        package.require_consent('mineru', identities)
        consent_sources = {str(pdf): package.consent_source('mineru', mapped[pdf]) for pdf in pdfs}
    elif request.consent_source:
        consent_sources = {str(pdf): request.consent_source for pdf in pdfs}
    else:
        raise ValueError('supply --run-dir with recorded consent or --consent-source for explicit standalone upload approval')
    token = credentials.mineru_token()
    if not token:
        raise ValueError('MinerU token missing')
    config = {'model': request.model, 'ocr': request.ocr, 'extra_formats': sorted(request.extra_formats), 'api_base': request.api_base}
    workspace = run or Path(request.output or pdfs[0].parent).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    # The run contains only a small number of batches. Its existing checkpoints
    # are the index: reordering or extending a request cannot create new work
    # for a source already assigned to an in-flight or completed batch.
    known: dict[str, tuple[Path, dict[str, Any], dict[str, Any]]] = {}
    for journal in sorted(workspace.glob('mineru-*.json')):
        state = read_json(journal)
        if any(state.get(key) != value for key, value in config.items()):
            continue
        for record in state.get('files', []):
            if record.get('sha256'):
                previous = known.get(record['sha256'])
                if previous is None or artifact_valid(record):
                    known[record['sha256']] = (journal, state, record)
    new_records = []
    groups: dict[Path, tuple[dict[str, Any], set[str]]] = {}
    outputs = []
    for pdf in pdfs:
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if digest in known:
            journal, state, record = known[digest]
            groups.setdefault(journal, (state, set()))[1].add(record['data_id'])
        else:
            data_id = 'pdf-' + hashlib.sha256((digest + json.dumps(config, sort_keys=True)).encode()).hexdigest()[:24]
            record = {'path': str(pdf), 'sha256': digest, 'name': data_id + '.pdf', 'data_id': data_id,
                      'state': 'pending', 'consent_source': consent_sources[str(pdf)]}
            new_records.append(record)
        outputs.append(record)
    if new_records:
        # Identical content selected through two paths needs only one parse.
        new_records = list({record['data_id']: record for record in new_records}.values())
        job_id = hashlib.sha256(json.dumps([r['data_id'] for r in new_records]).encode()).hexdigest()[:24]
        journal = workspace / f'mineru-{job_id}.json'
        state = {**config, 'at': utc_now(), 'files': new_records}
        groups[journal] = (state, {record['data_id'] for record in new_records})
    for journal, (state, requested) in groups.items():
        Batch(request, journal, state, token).resume(requested)
    # Resolve shared duplicate-content entries back to the completed record.
    resolved = {record['data_id']: record for state, _ in groups.values() for record in state['files']}
    result_files = [resolved[record['data_id']] for record in outputs]
    batches = [state.get('batch_id') for state, _ in groups.values()]
    return {'status': 'partial' if any(r['state'] == 'failed' for r in result_files) else 'ok',
            'converter': 'mineru', 'model': request.model, 'batch_id': batches[0] if len(batches) == 1 else None,
            'batch_ids': batches, 'files': result_files, 'journals': [str(path) for path in groups]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', action='append', required=True)
    parser.add_argument('--run-dir')
    parser.add_argument('--output', help='Optional root; outputs use a source/config ID under this root or <PDF parent>/mineru')
    parser.add_argument('--consent-source', help='Explicit standalone consent message reference')
    parser.add_argument('--model', default='vlm', choices=('pipeline', 'vlm'))
    parser.add_argument('--ocr', action='store_true')
    parser.add_argument('--extra-formats', nargs='*', default=[], choices=('docx', 'html', 'latex'))
    parser.add_argument('--api-base', default='https://mineru.net')
    parser.add_argument('--retry-budget', type=float, default=90)
    parser.add_argument('--poll-timeout', type=float, default=120)
    args = parser.parse_args()
    try:
        request = ParseRequest.from_args(args)
        result = parse(request)
        print(json.dumps(result, ensure_ascii=False))
        if result['status'] != 'ok':
            raise SystemExit(2)
    except (RequestError, ValueError, OSError, zipfile.BadZipFile) as error:
        print(json.dumps({'status': 'pending', 'reason': str(error) if isinstance(error, (RequestError, ValueError)) else type(error).__name__}))
        raise SystemExit(2)


if __name__ == '__main__':
    main()
