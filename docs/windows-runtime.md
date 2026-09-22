# Windows runtime reliability

The setup window is only the entry point. Regression coverage must also exercise a selected run through acquisition, conversion, summary handoff, ingestion and read-back.

## Platform contracts

- `runtime_io.file_lock` excludes competing writers on Windows with byte-range locks and on POSIX with flock. Workflow locks fail promptly; shared request pacing waits for its short critical section. Closing the process releases the lock.
- `mineru_parse.parse` owns the conversion lock, consent validation and checkpoint recovery together. CLI and pipeline callers do not need to acquire their own conversion lock. Recovery fixtures enter through this public interface and inject lost private writes at the filesystem.
- `runtime_io.private_text` creates a private temporary file, applies the Windows user-only ACL before writing, closes it before replacement, and cleans up after failure. POSIX files retain mode 0600. Account saves and signed conversion URLs share this implementation.
- Tool and content readers explicitly decode UTF-8. Poppler is asked for UTF-8. Missing extractor text remains eligible for the existing fallback.
- Summary-note evidence hashes normalized UTF-8 text on both write and read-back. PDF/Markdown attachments continue to hash exact bytes. Existing CRLF summaries remain valid without rewriting already stored notes.

## Recovery and interaction

- Lost MinerU upload URLs are reconciled by the normal resume command. Only the complete previously consented batch, with every local record pending and every remote result `waiting-file`, may replace its empty batch. Previous batch identity and the reason are journaled. An upload is marked in progress before sending bytes; uncertainty never silently becomes permission to start new work.
- Public PDF acquisition has a per-client, memory-only cookie jar for ordinary publisher redirects. It never reads a browser profile. Credential stripping, HTTPS downgrade rejection, transfer budgets and PDF identity checks remain in force.
- Setup performs a bounded search and requires one usable discovery source to report search readiness. Account setup happens in the normal UI; operational retries use the same run instead of independent curl loops.
- On Windows, updating one assistant also updates existing managed copies belonging to the other supported assistants. Independent installations and unselected new assistants remain outside that update.
- Technical recovery and summary handoff reuse recorded authorization. Human decisions remain selection, consent, account entry, login and material scope changes. Diagnostic artifacts belong under `debug/`; they do not create another housekeeping question at delivery.

## Regression entry

```bash
python -m pytest paper-to-zotero/tests/test_windows_pipeline.py -q
```

The original five platform failures went red together before their fixes. Additional tests exercise lost checkpoint recovery, cookie redirects, ambiguous remote states, real competing processes, failure cleanup, search readiness and managed-copy upgrades.

The `Cross-platform runtime` workflow runs the same pipeline fixtures on Windows, macOS and Linux. Fixture results certify these code paths, not a publisher's current access policy or a real user's account entitlement. Tests isolate both HOME and USERPROFILE; installer tests must not patch the developer's actual assistants.
