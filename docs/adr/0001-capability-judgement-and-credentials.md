# ADR-0001: Share capability judgements and credential resolution

Status: Accepted. Stage-specific requirements are described in [ADR-0003](0003-one-confirmation-and-independent-artifacts.md) and [ADR-0004](0004-http-first-discovery-and-acquisition.md).

Duplicated probes made setup and runtime checks disagree about the same machine. Reading credentials independently also caused some commands to miss configuration saved by the wizard.

Service probes and their judgements therefore live in `scripts/capability.py`, returning `{ok, detail, remediation}` records. `preflight.py` combines records for the requested stage; `verify.py` exposes individual checks. `credentials.py` resolves credentials for every service caller without printing their values.

The user-facing completion report is `configure.py --check`. The broader `setup.py` doctor is a developer diagnostic and includes optional integrations; its overall result is not a prerequisite for every task. Human wording may differ between the wizard and diagnostics, while the underlying capability judgement stays shared.

A capability change belongs in this shared implementation and its tests. Requiring a browser connection or Desktop sync for a stage that does not use them would reintroduce unnecessary setup dependencies.
