# Paper2zotero verification map

Use the parent SKILL.md's doctor and run commands from the repository root. Every feature starts with a new isolated profile, copied current source and temporary run data; no existing account or library is reused. Fixtures create their own ephemeral peers. CLI stdout/stderr/exit codes and resulting state survive cleanup in the printed evidence directory.

| Feature | Safe recipe | Boundary |
|---|---|---|
| [Discovery and shortlist](discovery.md) | `run --feature discovery` | Fixture JSON and local peers. These nodes do not start Kimi |
| [ScanSci search and download](scansci.md) | `run --feature scansci` | Mocked `scansci-pdf` 1.19.0. Not a live library download |
| [Selection and upload consent](selection.md) | `run --feature selection` | Real CLI. The no-consent node skips a MinerU upload. markitdown does not read consent |
| [Import local PDF](local-pdf.md) | `run --feature local-pdf` | Real CLI and fixture PDF. These nodes do not run the converter chain |
| [Acquire verified PDF](acquisition.md) | `run --feature acquisition` | HTTP fallback. The suite disables scansci |
| [Deliver and recover](delivery.md) | `run --feature delivery` | Fixture Zotero and MinerU v4 peers. Not the self-hosted Tasks API or a Desktop file attach |
| [Backend defaults](backend-defaults.md) | `run --feature backend-defaults` | Loopback only, including one-page Kimi fixture failures. Does not dial a MinerU host, Kimi, or Desktop, and does not prove file attach |

The runnable starter map is the tests whose modules are in this branch. A missing dependency, skipped test or failed assertion among them is not a pass. Every assertion's node ID is in `invocation.json` and `results.xml`; commands are in `commands.jsonl`. Inspect action plus resulting files/peer assertions. Real-agent interpretation, production services and Windows remain separate unverified entry points. This is not full-suite coverage.
