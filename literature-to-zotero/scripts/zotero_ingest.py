#!/usr/bin/env python3
"""Resume selected papers into Zotero through a journaled Web API write path."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import html
import json
from pathlib import Path
import secrets
import sys
import time
import re
from typing import Any, Sequence
import urllib.parse

import credentials
import paper_artifacts
from http_client import Client, RequestError
from workflow import Paper, Run, read_json, run_lock, utc_now, write_json


def doi(value: str | None) -> str:
    return (value or "").lower().strip().removeprefix('https://doi.org/').removeprefix('http://doi.org/').removeprefix('doi:')


def item_data(candidate: dict[str, Any]) -> dict[str, Any]:
    csl = candidate.get('csl', {})
    selected_doi = doi(candidate['id']) if candidate['id'].startswith('doi:') else doi(candidate.get('doi'))
    if selected_doi and any(doi(value) != selected_doi for value in (csl.get('DOI'), candidate.get('doi')) if value):
        raise ValueError('candidate metadata DOI differs from selected identity')
    kind = {'article-journal': 'journalArticle', 'paper-conference': 'conferencePaper',
            'proceedings-article': 'conferencePaper', 'book': 'book', 'chapter': 'bookSection', 'report': 'report'}.get(str(csl.get('type') or candidate.get('work_type') or ''), 'journalArticle')
    item: dict[str, Any] = {'itemType': kind, 'title': csl.get('title') or candidate['title'],
        'DOI': doi(csl.get('DOI') or candidate.get('doi') or candidate['id'].removeprefix('doi:')),
        'date': str(candidate.get('year') or (csl.get('issued', {}).get('date-parts') or [['']])[0][0]),
        'collections': [], 'tags': [], 'creators': []}
    if not candidate['id'].startswith('doi:') and not candidate.get('doi') and not csl.get('DOI'):
        item.pop('DOI')
    venue = csl.get('container-title') or candidate.get('venue')
    if venue:
        field = {'journalArticle': 'publicationTitle', 'conferencePaper': 'proceedingsTitle', 'bookSection': 'bookTitle'}.get(kind)
        if field:
            item[field] = venue[0] if isinstance(venue, list) else venue
    for source, target in [('page', 'pages'), ('URL', 'url'), ('abstract', 'abstractNote'), ('volume', 'volume'), ('issue', 'issue')]:
        if csl.get(source):
            item[target] = csl[source]
    if candidate.get('abstract') and not item.get('abstractNote'):
        item['abstractNote'] = candidate['abstract']
    for author in csl.get('author', candidate.get('authors', [])):
        if isinstance(author, str):
            item['creators'].append({'creatorType': 'author', 'name': author})
        elif author.get('family'):
            item['creators'].append({'creatorType': 'author', 'lastName': author['family'], 'firstName': author.get('given', '')})
        elif author.get('literal') or author.get('name') or author.get('display_name'):
            item['creators'].append({'creatorType': 'author', 'name': author.get('literal') or author.get('name') or author['display_name']})
    return item


def same_work(expected: dict[str, Any], other: dict[str, Any]) -> bool:
    if expected.get('DOI'):
        return doi(other.get('DOI', '')) == expected['DOI']
    def words(value: str) -> str:
        return re.sub(r'\W+', '', value).casefold()
    def author(data: dict[str, Any]) -> str:
        first: dict[str, Any] = next(iter(data.get('creators', [])), {})
        return words(first.get('name') or (first.get('firstName', '') + first.get('lastName', '')))
    return bool(author(expected) and words(expected['title']) == words(other.get('title', ''))
                and expected.get('date', '')[:4] == other.get('date', '')[:4]
                and author(expected) == author(other))


class Writer:
    def __init__(self, run: Path, account: dict[str, str], api_base: str, budget: float):
        self.run, self.client = run, Client(budget=budget)
        self.base = f"{api_base.rstrip('/')}/{account['library_type']}s/{account['library_id']}"
        self.headers = {'Zotero-API-Key': account['api_key'], 'Zotero-API-Version': '3'}
        self.path = run / 'zotero-state.json'
        self.inventory: list[dict[str, Any]] | None = None
        self.doi_index: dict[str, list[dict[str, Any]]] = {}
        self.state = read_json(self.path) if self.path.exists() else {'operations': {}, 'papers': {}}
        if self.state.get('library', self.base) != self.base:
            raise ValueError('run is bound to another Zotero library')
        self.state['library'] = self.base
        if self.state.get('retry_at', 0) > time.time():
            raise RequestError('rate_limited', retry_after=self.state['retry_at'] - time.time())

    def save(self) -> None:
        write_json(self.path, self.state)

    def call(self, method: str, path: str, payload: Any = None, extra: dict[str, str] | None = None) -> Any:
        headers = {**self.headers, **(extra or {})}
        body = None
        if payload is not None:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(payload).encode()
        response = self.client.request(method, self.base + path, headers=headers, body=body)
        return response.json() if response.body else None

    def get(self, path: str) -> Any:
        try:
            return self.call('GET', path)
        except RequestError as error:
            if error.status == 404:
                return None
            raise

    def all(self, path: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        start = 0
        while True:
            page = self.call('GET', f'{path}?limit=100&start={start}')
            if not isinstance(page, list):
                raise ValueError('invalid Zotero listing')
            found.extend(page)
            if len(page) < 100:
                return found
            start += len(page)

    def create(self, operation: str, plural: str, data: dict[str, Any]) -> str:
        if plural == 'items':
            data = {'tags': [], 'relations': {}, **data}
        ops = self.state['operations']
        if operation not in ops:
            key = ''.join(secrets.choice('23456789ABCDEFGHIJKLMNPQRSTUVWXYZ') for _ in range(8))
            ops[operation] = {'key': key, 'payload': data, 'state': 'prepared', 'token': secrets.token_hex(16)}
            self.save()
        op = ops[operation]
        if op['payload'] != data:
            raise ValueError('operation input changed; reconcile existing object before replacing it')
        existing = self.get(f"/{plural}/{op['key']}")
        if existing is None:
            # Stable client key + version=0 prevents a response-loss retry from
            # creating another object or overwriting an existing version.
            op['state'] = 'outcome_unknown'
            self.save()
            result = self.call('POST', f'/{plural}', [{**data, 'key': op['key'], 'version': 0}], {'Zotero-Write-Token': op['token']})
            if not isinstance(result, dict) or not result.get('successful', {}).get('0'):
                # A replayed token or a version conflict may still mean success.
                existing = self.get(f"/{plural}/{op['key']}")
                if existing is None:
                    raise ValueError('Zotero rejected object creation; inspect item schema')
        op['state'] = 'confirmed'
        self.save()
        return str(op['key'])

    def collection(self, key: str | None, name: str | None) -> str:
        saved = self.state.get('collection')
        if saved:
            if key and key != saved:
                raise ValueError('run is bound to another collection')
            key = saved
        if not key:
            name = name or self.state['operations'].get('collection', {}).get('payload', {}).get('name')
            if not name:
                raise ValueError('supply --collection-key or --collection-name on the first run')
            key = self.create('collection', 'collections', {'name': name, 'parentCollection': False})
        if self.get('/collections/' + key) is None:
            raise ValueError('target collection is missing')
        self.state['collection'] = key
        self.save()
        return key

    def parent(self, candidate: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        """The parent item key, plus the item itself when it was just read."""
        identity = candidate['id']
        saved = self.state['papers'].setdefault(identity, {})
        if saved.get('key'):
            item = self.get('/items/' + saved['key'])
            if item is None:
                raise ValueError('saved parent was deleted; explicit reconciliation required')
            return str(saved['key']), item
        data = item_data(candidate)
        if self.inventory is None:
            self.inventory = [item for item in self.all('/items')
                              if item.get('data', {}).get('itemType') not in ('attachment', 'note')]
            for item in self.inventory:
                self.doi_index.setdefault(doi(item.get('data', {}).get('DOI')), []).append(item)
        candidates = self.doi_index.get(data['DOI'], []) if data.get('DOI') else self.inventory
        matches = [item['key'] for item in candidates if same_work(data, item.get('data', {}))]
        if len(matches) > 1:
            raise ValueError('multiple DOI matches; resolve existing duplicates before writing')
        if not data.get('DOI') and (not data.get('date') or not data.get('creators')):
            raise ValueError('paper without DOI needs title, year and first author for identity matching')
        key = matches[0] if matches else self.create('parent:' + identity, 'items', data)
        if not matches:
            created = {'key': key, 'data': data}
            self.inventory.append(created)
            self.doi_index.setdefault(doi(data.get('DOI')), []).append(created)
        saved['key'] = key
        self.save()
        return str(key), None

    def file_into(self, key: str, collection: str, candidate: dict[str, Any],
                  item: dict[str, Any] | None = None) -> None:
        item = item or self.get('/items/' + key)
        if not item:
            raise ValueError('parent missing')
        expected = item_data(candidate)
        patch = {field: value for field, value in expected.items() if value and not item['data'].get(field)
                 and field not in ('itemType', 'collections', 'tags') and item['data']['itemType'] == expected['itemType']}
        if collection not in item['data'].get('collections', []):
            patch['collections'] = [*item['data'].get('collections', []), collection]
        tags = item['data'].get('tags', [])
        new_tags = [tag for tag in candidate.get('tags', []) if tag not in [t['tag'] for t in tags]]
        if new_tags:
            patch['tags'] = tags + [{'tag': tag} for tag in new_tags]
        if patch:
            self.call('PATCH', '/items/' + key, patch, {'If-Unmodified-Since-Version': str(item['version'])})
        # With nothing patched, the item just read *is* the confirmation: a
        # second identical read proves nothing the first did not.
        confirmed = self.get('/items/' + key)['data'] if patch else item['data']
        if collection not in confirmed.get('collections', []):
            raise ValueError('collection membership not verified')
        if any(tag not in [value['tag'] for value in confirmed.get('tags', [])] for tag in candidate.get('tags', [])):
            raise ValueError('requested tags not verified')


    def fetch_file(self, key: str) -> bytes | None:
        try:
            return self.client.request('GET', self.base + '/items/' + key + '/file', headers=self.headers).body
        except RequestError as error:
            if error.status != 404:
                raise
            return None

    def attach(self, identity: str, parent: str, source: Path, content_type: str,
               children: list[dict[str, Any]]) -> dict[str, Any]:
        """Attach one artifact, reusing an identical file already in the cloud.

        The caller supplies this parent's children, so one listing serves every
        attachment and the summary note. Bytes fetched to compare a candidate
        are kept: hashing them already proved the file is the one we wanted, so
        downloading it again to prove it twice is pure cost, and on a
        multi-megabyte PDF that cost is paid on every resume.
        """
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        operation = f'attachment:{identity}:{source.name}:{digest}'
        matches = [item for item in children
                   if item.get('data', {}).get('itemType') == 'attachment'
                   and item['data'].get('filename') == source.name
                   and item['data'].get('linkMode') == 'imported_file']
        key, known, cloud, absent = None, None, None, False
        for existing in matches:
            body = self.fetch_file(existing['key'])
            if body is not None and hashlib.sha256(body).hexdigest() == digest:
                key, known, cloud = existing['key'], existing, body
                break
            if body is None and len(matches) == 1:
                # A record with no file: known to be empty, so do not ask again.
                key, known, absent = existing['key'], existing, True
        if key is None:
            key = self.create(operation, 'items', {'itemType': 'attachment', 'parentItem': parent,
                'linkMode': 'imported_file', 'contentType': content_type,
                'title': source.name, 'filename': source.name})
        record = self.state['papers'][identity].setdefault('attachments', {}).setdefault(source.name, {})
        record.update({'key': key, 'source': str(source), 'sha256': digest, 'state': 'record_created'})
        self.save()
        file_action = 'reused'
        if cloud is None:
            # A key from `create` may name an object an earlier attempt already
            # filled, so that one is still asked.
            cloud = None if absent else self.fetch_file(key)
            if cloud is None:
                self.upload(key, source, content_type)
                file_action = 'uploaded'
                cloud = self.fetch_file(key)
            known = None  # the object changed under us; re-read its metadata
        if cloud is None or hashlib.sha256(cloud).hexdigest() != digest:
            raise ValueError('cloud attachment hash mismatch; existing file preserved')
        item = known if known is not None else self.get('/items/' + key)
        if item['data'].get('contentType') != content_type:
            # A cached listing is fine for deciding whether to write, but not
            # for the precondition: downloading the file above took long enough
            # for the object to move, and a stale version turns a correction
            # into a 412 that fails the paper.
            item = self.get('/items/' + key)
            self.call('PATCH', '/items/' + key, {'contentType': content_type},
                      {'If-Unmodified-Since-Version': str(item['version'])})
        filename = item['data'].get('filename')
        if not filename or Path(filename).name != filename:
            raise ValueError('invalid attachment filename')
        record['file_action'] = file_action
        record['filename'] = filename
        record['state'] = 'binary_verified'
        self.save()
        return record

    def upload(self, key: str, source: Path, content_type: str) -> None:
        raw = source.read_bytes()
        headers = {**self.headers, 'Content-Type': 'application/x-www-form-urlencoded', 'If-None-Match': '*'}
        url = self.base + '/items/' + key + '/file'
        fields = {'md5': hashlib.md5(raw).hexdigest(), 'filename': source.name,
                  'filesize': len(raw), 'mtime': int(source.stat().st_mtime * 1000), 'contentType': content_type}
        auth = self.client.request('POST', url, body=urllib.parse.urlencode(fields).encode(), headers=headers).json()
        if not auth.get('exists'):
            # The API supplies the multipart envelope; no library credential is
            # sent to the signed storage URL, and signed URLs are not journaled.
            body = auth['prefix'].encode() + raw + auth['suffix'].encode()
            self.client.request('POST', auth['url'], body=body, headers={'Content-Type': auth['contentType']})
            self.client.request('POST', url, body=urllib.parse.urlencode({'upload': auth['uploadKey']}).encode(), headers=headers)

    def finish_paper(self, key: str, candidate: dict[str, Any], paper: Paper, storage: Path | None) -> str:
        """Write whatever this paper actually has, and name what it still lacks.

        The artifacts are independent: a verified PDF is written and read back
        even when Markdown conversion failed and no summary exists yet. A later
        run adds the missing pieces to the same parent instead of redoing work.
        """
        identity = paper.id
        result = self.state['papers'][identity]
        if not paper.pdf:
            if not paper.is_metadata_only:
                raise ValueError('source PDF missing; explicitly record metadata_only or acquire it')
            result['state'] = 'metadata_only'
            result.pop('error', None)
            return 'metadata_only'
        result['markdown_status'] = 'available' if paper.markdown else 'markdown_unavailable'
        pending: list[str] = []
        attachments = []
        # One listing of this parent's children serves every attachment and
        # the summary note below.
        children = self.all('/items/' + key + '/children')
        for source, mime in [(paper.pdf, 'application/pdf'), (paper.markdown, 'text/markdown')]:
            if source:
                attachments.append(self.attach(identity, key, source, mime, children))
        if not paper.markdown:
            pending.append('markdown_unavailable')
        if paper.summary:
            self.write_summary(identity, key, paper.summary, result, children)
        else:
            pending.append('summary pending')
        if self.state['collection'] not in self.get('/items/' + key)['data'].get('collections', []):
            raise ValueError('collection membership changed before read-back')
        result['collection_verified'] = self.state['collection']
        result['cloud_verified_at'] = utc_now()
        local_ok = bool(storage)
        result['local_checked'] = bool(storage)
        for record in attachments:
            # `attach` verified this filename against the written object.
            filename = record['filename']
            local = storage / 'storage' / record['key'] / filename if storage else None
            present = bool(local and local.is_file() and hashlib.sha256(local.read_bytes()).hexdigest() == record['sha256'])
            record['local_verified'] = present
            record['local_path'] = str(local) if local else None
            local_ok = local_ok and present
        if not local_ok:
            # Without a storage root the local copy was never looked at, which
            # is a different statement from "Desktop has not downloaded it".
            pending.append('local sync pending' if storage else 'local sync not checked')
        result['pending'] = pending
        # A cloud-verified paper is deliverable now. `partial` means an artifact
        # is still missing; `sync_pending` means only Desktop has yet to catch
        # up. Neither is a failure, and neither reruns the batch.
        if not paper.summary:
            result['state'] = 'partial'
        else:
            result['state'] = 'read_back_verified' if local_ok else 'sync_pending'
        result.pop('error', None)
        self.save()
        if result['state'] == 'read_back_verified':
            paper.validate_read_back(result)
        return str(result['state'])

    def write_summary(self, identity: str, key: str, source: Path, result: dict[str, Any],
                      children: list[dict[str, Any]]) -> None:
        summary = source.read_text(encoding='utf-8')
        from runtime_io import text_hash
        summary_hash = text_hash(summary)
        marker = f'literature-to-zotero:{self.run.name}:{summary_hash}'
        note = '<p>' + marker + '</p><pre>' + html.escape(summary) + '</pre>'
        matches = [item for item in children if item.get('data', {}).get('note') == note]
        note_key = matches[0]['key'] if matches else self.create('summary:' + identity + ':' + summary_hash, 'items',
                                {'itemType': 'note', 'parentItem': key, 'note': note})
        readback = self.get('/items/' + note_key)
        if readback['data'].get('note') != note:
            raise ValueError('summary note read-back mismatch')
        result['note_action'] = 'reused' if matches else 'created_or_recovered'
        result['note_key'] = note_key
        result['note_sha256'] = summary_hash


def validate_artifacts(candidate: dict[str, Any], paper: Paper) -> None:
    """Check what this paper has. Absent derived artifacts are not errors.

    Only the source PDF gates ingestion, because it is the one artifact whose
    identity must be proven before anything is written. Markdown and the
    summary are checked when present and simply reported as pending when not.
    """
    if not paper.path('pdf'):
        if not paper.is_metadata_only:
            raise ValueError('source PDF missing; acquire it or explicitly record metadata_only')
        return
    pdf = paper.pdf
    if not pdf:
        raise ValueError('pdf artifact missing')
    _, status = paper_artifacts.verify(pdf, candidate['title'], candidate.get('doi'))
    if status != 0:
        raise ValueError('source PDF identity not verified')
    if paper.path('markdown') and not paper.markdown:
        raise ValueError('Markdown artifact missing')
    if not paper.path('summary'):
        return
    if not paper.summary:
        raise ValueError('summary artifact missing')
    summary = paper.summary.read_text(encoding='utf-8')
    for field in ('provider: `', 'template_version: `', 'source_basis: `'):
        if field not in summary:
            raise ValueError('summary provider contract missing')
    if 'source_basis: `markdown`' in summary and not paper.markdown:
        raise ValueError('Markdown-based summary requires its source Markdown')


@dataclass(frozen=True)
class IngestRequest:
    """What to write, stated in types a caller can be checked against.

    The CLI builds one of these; so does any other caller. Passing an
    `argparse.Namespace` instead would put the parser's field names into this
    module's interface, where a typo is invisible to the type checker and
    surfaces as an AttributeError partway through a batch.
    """
    run_dir: Path
    collection_key: str | None = None
    collection_name: str | None = None
    ids: Sequence[str] | None = None
    storage_root: Path | None = None
    reuse_map: Path | None = None
    api_base: str = 'https://api.zotero.org'
    retry_budget: float = 90
    dry_run: bool = False

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> IngestRequest:
        return cls(
            run_dir=Path(args.run_dir).resolve(),
            collection_key=args.collection_key, collection_name=args.collection_name,
            ids=[value.strip() for value in args.ids.split(',') if value.strip()] if args.ids else None,
            storage_root=Path(args.storage_root).resolve() if args.storage_root else None,
            reuse_map=Path(args.reuse_map) if args.reuse_map else None,
            api_base=args.api_base, retry_budget=args.retry_budget, dry_run=args.dry_run,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--collection-key')
    parser.add_argument('--collection-name')
    parser.add_argument('--api-base', default='https://api.zotero.org')
    parser.add_argument('--retry-budget', type=float, default=90)
    parser.add_argument('--storage-root')
    parser.add_argument('--ids', help='Comma-separated selected IDs; default is every selected paper')
    parser.add_argument('--reuse-map', help='JSON map of candidate IDs to verified existing item keys')
    parser.add_argument('--dry-run', action='store_true')
    return parser


def artifact_snapshot(paper: Paper) -> dict[str, tuple[str, str]]:
    return {field: (str(path), hashlib.sha256(path.read_bytes()).hexdigest())
            for field in Paper.ARTIFACTS if (path := paper.artifact(field)) is not None}


def ingest(request: IngestRequest) -> dict[str, Any]:
    """Write the requested papers and return one structured result.

    Errors and pending artifacts are different outcomes: `pending` means a
    caller should retry this service, while `partial` is delivered work whose
    remaining artifacts are named per paper.
    """
    run = request.run_dir
    package = Run.open(run)
    package.require_confirmed()
    if not package.selected:
        raise ValueError('no selected papers')
    identities = package.resolve_ids(request.ids)
    candidates = package.require_candidates(identities)
    if request.dry_run:
        invalid = {}
        for paper in package.papers(identities):
            try:
                validate_artifacts(candidates[paper.id], paper)
            except (ValueError, OSError) as error:
                invalid[paper.id] = str(error)
        return {'status': 'invalid_artifacts' if invalid else 'planned', 'ids': identities,
                'collection': request.collection_key or request.collection_name, 'errors': invalid}
    account = credentials.zotero_credentials()
    if not account['api_key'] or not account['library_id']:
        raise ValueError('Zotero credentials missing')
    # One remote writer owns its journal, but HTTP never owns the manifest
    # lock: acquisition/conversion of other papers can commit while we wait.
    with run_lock(run, "zotero"):
        package = Run.open(run)
        package.require_confirmed()
        writer = Writer(run, account, request.api_base, request.retry_budget)
        if request.reuse_map:
            for identity, key in read_json(request.reuse_map).items():
                if identity not in package.selected:
                    raise ValueError('reuse map must contain selected IDs only')
                item = writer.get('/items/' + key)
                expected = item_data(candidates[identity])
                if not item or not same_work(expected, item.get('data', {})):
                    raise ValueError('reuse map identity mismatch')
                previous = writer.state['papers'].setdefault(identity, {}).get('key')
                if previous and previous != key:
                    raise ValueError('reuse key conflicts with saved parent')
                writer.state['papers'][identity]['key'] = key
            writer.save()
        collection = writer.collection(request.collection_key, request.collection_name)
        with Run.locked(run) as latest:
            latest.collection = collection
            latest.save()
        errors, pending = 0, 0
        for identity in identities:
            print(json.dumps({'paper': identity, 'stage': 'zotero'}), file=sys.stderr, flush=True)
            try:
                package = Run.open(run)
                package.require_confirmed()
                package.resolve_ids([identity])
                paper = package.paper(identity)
                before = artifact_snapshot(paper)
                validate_artifacts(candidates[identity], paper)
                key, existing = writer.parent(candidates[identity])
                writer.file_into(key, collection, candidates[identity], existing)
                state = writer.finish_paper(key, candidates[identity], paper, request.storage_root)
                # The writer's read-back evidence is the authority for a state
                # it just proved, so it is recorded directly rather than
                # re-derived from a transition rule.
                with Run.locked(run) as latest:
                    latest.resolve_ids([identity])
                    current = latest.paper(identity)
                    if artifact_snapshot(current) != before:
                        # Keep the new artifact pending; this read-back only
                        # describes the snapshot uploaded above.
                        raise ValueError('paper artifacts changed during upload; resume to write the new artifacts')
                    current.record['state'] = state
                    current.record['zotero'] = writer.state['papers'][identity]
                    latest.save()
                if state in ('sync_pending', 'partial'):
                    pending += 1
            except (RequestError, ValueError) as error:
                errors += 1
                writer.state['papers'].setdefault(identity, {})['error'] = str(error)
                if isinstance(error, RequestError) and error.retry_after:
                    writer.state['retry_at'] = time.time() + error.retry_after
                writer.save()
                # Shared transient/auth failure pauses this service once.
                if isinstance(error, RequestError) and error.kind not in ('invalid_request', 'not_found', 'conflict'):
                    break
            writer.save()
        status = 'pending' if errors else ('partial' if pending else 'complete')
        return {'status': status, 'collection': collection, 'ids': identities,
                'errors': errors, 'incomplete': pending,
                'papers': {key: writer.state['papers'][key] for key in identities if key in writer.state['papers']}}


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = ingest(IngestRequest.from_args(args))
    except (RequestError, ValueError, OSError) as error:
        print(json.dumps({'status': 'pending', 'reason': str(error) if not isinstance(error, OSError) else type(error).__name__}))
        raise SystemExit(2)
    print(json.dumps(result, ensure_ascii=False))
    if result['status'] in ('pending', 'invalid_artifacts'):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
