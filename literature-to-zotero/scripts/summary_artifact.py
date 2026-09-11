#!/usr/bin/env python3
"""Persist a summary-provider result with explicit provenance metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
from typing import Any

from workflow import Run, read_json, write_json

TEMPLATE_VERSION = "4"


def render(content: str, provider: str, version: str, basis: str) -> str:
    return ("# Core Summary\n\n" f"- provider: `{provider}`\n"
            f"- template_version: `{version}`\n" f"- source_basis: `{basis}`\n\n"
            f"{content.strip()}\n")


def prepare_handoff(run: Path, papers: list[dict[str, Any]], resume: list[str]) -> Path:
    """One source outline and one body path per paper; no second PDF derivation."""
    entries = []
    for paper in papers:
        source = Path(paper['source'])
        Path(paper['output']).parent.mkdir(parents=True, exist_ok=True)
        entry = {**paper, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                 'content_file': str(Path(paper['output']).with_name('summary-body.md'))}
        if paper['source_basis'] == 'markdown':
            lines = source.read_text(encoding='utf-8').splitlines()
            sections: list[dict[str, Any]] = [{'line': n, 'heading': line.lstrip('#').strip()}
                        for n, line in enumerate(lines, 1) if re.match(r'^#{1,6}\s', line)]
            end = next((s['line'] - 1 for s in sections
                        if re.fullmatch(r'(?:\d+\.?\s+)?(?:references|bibliography|参考文献)',
                                        s['heading'], re.I)), len(lines))
            entry['reading'] = {'line_count': len(lines), 'main_text_end_line': end,
                                'sections': sections}
        entries.append(entry)
    handoff = {'run_dir': str(run.resolve()), 'summaries': entries, 'resume_command': resume,
               'resume_shell': shlex.join(resume)}
    fingerprint = hashlib.sha256(json.dumps(handoff, sort_keys=True).encode()).hexdigest()[:12]
    path = run / f'summary-handoff-{fingerprint}.json'
    write_json(path, handoff)
    return path


def save_batch(batch_file: Path, provider: str) -> dict[str, Any]:
    """Validate the entire batch before saving; identical retries only register."""
    handoff = read_json(batch_file)
    package = Run.open(handoff['run_dir'])
    package.require_confirmed()
    entries = handoff['summaries']
    if not entries or len({e['id'] for e in entries}) != len(entries):
        raise ValueError('summary batch must contain distinct selected IDs')
    package.resolve_ids([entry['id'] for entry in entries])
    prepared = []
    for entry in entries:
        paper = package.paper(entry['id'])
        basis = entry['source_basis']
        if basis not in ('pdf', 'markdown'):
            raise ValueError('summary requires PDF or MinerU Markdown full text')
        source = paper.artifact(basis)
        if (source is None or source.resolve() != Path(entry['source']).resolve()
                or hashlib.sha256(source.read_bytes()).hexdigest() != entry['source_sha256']):
            raise ValueError('summary source changed; read the current full text before summarizing')
        body = Path(entry['content_file'])
        if not body.is_absolute():
            body = batch_file.parent / body
        content = body.read_text(encoding='utf-8').strip()
        if not content:
            raise ValueError('summary content is empty')
        output = Path(entry['output']).resolve()
        output.relative_to(package.directory / 'papers')
        if output.name != 'summary.md':
            raise ValueError('batch summary must target summary.md')
        if paper.summary and paper.summary.resolve() != output:
            raise ValueError('existing summary uses another path; preserve it')
        # A saved handoff keeps its original contract when resumed after an update.
        version = str(entry.get('template_version', TEMPLATE_VERSION))
        rendered = render(content, provider, version, basis)
        if output.exists() and output.read_text(encoding='utf-8') != rendered:
            raise ValueError('existing summary differs; preserve it and request an explicit replacement')
        prepared.append((entry, output, rendered))
    if len({output for _, output, _ in prepared}) != len(prepared):
        raise ValueError('summary output paths must be distinct')
    with Run.locked(package.directory) as current:
        current.require_confirmed()
        current.resolve_ids([entry['id'] for entry, _, _ in prepared])
        for entry, output, rendered in prepared:
            paper = current.paper(entry['id'])
            if paper.summary and paper.summary.resolve() != output:
                raise ValueError('existing summary uses another path; preserve it')
            source = paper.artifact(entry['source_basis'])
            if (source is None or source.resolve() != Path(entry['source']).resolve()
                    or hashlib.sha256(source.read_bytes()).hexdigest() != entry['source_sha256']):
                raise ValueError('summary source changed during batch preparation')
            if output.exists() and output.read_text(encoding='utf-8') != rendered:
                raise ValueError('existing summary differs; preserve it and request an explicit replacement')
        for entry, output, rendered in prepared:
            output.parent.mkdir(parents=True, exist_ok=True)
            if not output.exists():
                temporary = output.with_suffix('.md.tmp')
                temporary.write_text(rendered, encoding='utf-8')
                temporary.replace(output)
            # A repeat of a registered batch must not rewind a delivered paper.
            if current.paper(entry['id']).summary != output:
                current.advance(entry['id'], 'summary_generated', artifact='summary=' + str(output))
        current.save()
    return {'status': 'summaries_recorded', 'ids': [e['id'] for e in entries],
            'resume_command': handoff['resume_command'], 'resume_shell': handoff['resume_shell']}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-file", help="Summary handoff returned by process_run; saves and records every body")
    parser.add_argument("--content-file")
    parser.add_argument("--output")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--template-version", default=TEMPLATE_VERSION)
    parser.add_argument("--source-basis", choices=("markdown", "pdf"))
    args = parser.parse_args()

    if args.batch_file:
        if args.content_file or args.output or args.source_basis:
            parser.error('--batch-file cannot be combined with single-summary paths or basis')
        try:
            print(json.dumps(save_batch(Path(args.batch_file).resolve(), args.provider), ensure_ascii=False))
        except (OSError, ValueError, KeyError, TypeError) as error:
            reason = type(error).__name__ if isinstance(error, OSError) else str(error)
            print(json.dumps({'status': 'failed', 'reason': reason}))
            raise SystemExit(2)
        return
    if not (args.content_file and args.output and args.source_basis):
        parser.error('single-summary mode needs --content-file, --output and --source-basis')

    content = Path(args.content_file).read_text(encoding="utf-8").strip()
    if not content:
        print(json.dumps({"status": "failed", "reason": "summary content is empty"}))
        raise SystemExit(2)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render(content, args.provider, args.template_version, args.source_basis),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "summary_generated",
        "provider": args.provider,
        "template_version": args.template_version,
        "source_basis": args.source_basis,
        "output": str(output.resolve()),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
