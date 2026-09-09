# ADR-0001: Capability judgement and credential reads live in one place

Status: Accepted (round-2 architecture candidates C1 + C2, owner-approved)

Date: continuation session after `cbb275a`

## Context

"Can this machine run the skill?" was judged by three CLIs that each carried
its own copies of probes and semantics: `preflight.py` (report + ready),
`verify.py` (per-stage booleans), and `setup.py` (doctor checklist). A
two-week-old semantic change — `storage_sync_enabled=None` means Zotero 7
default ON — was applied to `preflight.py` and `verify.py` but not to the
doctor, so `verify` said OK while the doctor said MISSING.

Credential reads leaked past `credentials.py` as well: `zotero_markdown.py`
kept a private `credentials()` that read only env/codex (bypassing the skill
dotenv the wizard writes), and `preflight.py` parsed the Codex config itself
for `command` / `ZOTERO_LOCAL`.

## Decision

- New deep module `scripts/capability.py`: one **capability record**
  `{ok, detail, remediation}` per runtime precondition. Pure judgement
  functions turn measured facts into records; probe functions (files, local
  HTTP, daemon status, key endpoint) live in the same module. Judgement
  semantics are written and tested exactly once here.
- `preflight.py` = run probes, then combine records into the report plus one
  `ready` decision (`capability.ready` over zotero-local/sync/key + kimi).
- `verify.py` = one command per capability, a thin caller of the same
  records.
- `setup.py` doctor = render records as a human checklist; missing items
  print the record's remediation.
- All config/credential reads route through `credentials.py`, which now also
  exposes the non-secret MCP block facts (`zotero_mcp_config`: command,
  `ZOTERO_LOCAL` flag, env presence). `zotero_markdown.py` uses
  `credentials.zotero_credentials()`.

## Consequences

- A semantic change now lands in one file and all three UIs agree (tests at
  the capability seam guard this: `tests/test_capability.py`, storage-None
  semantics first).
- New users whose only config is the wizard-written dotenv are served by
  every script, not just preflight.
- The ready gate now requires Kimi's extension to be connected (was: daemon
  merely reachable), matching `verify.py kimi` and the documented "installed
  and connected" requirement.

## Not decided here

- C3 (single data source for wizard stage copy + doctor action text) was
  originally deferred but is now implemented as an update to this ADR: each
  capability in `capability.py` carries one canonical human fix
  (`GUIDE`: label/url/do); the doctor's missing-item action text and the
  setup wizard's stage copy both read it, and the wizard opens the shared
  `url`. The wizard's interactive mechanics (secret capture, re-checks,
  env writing) are unchanged.
- C4 (provider seam for OA/PDF acquisition) deferred until a second real
  provider exists.
