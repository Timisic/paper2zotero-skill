# Paper2zotero verification map

Use the parent SKILL.md's doctor and run commands from the repository root. Every feature starts with a new isolated profile, copied current source and temporary run data; no existing account or library is reused. Fixtures create their own ephemeral peers. CLI stdout/stderr/exit codes and resulting state survive cleanup in the printed evidence directory.

| Feature | Safe recipe | Existing scenarios | Boundary |
|---|---|---:|---|
| [Discovery and shortlist](discovery.md) | `run --feature discovery` | 4 | Fixture JSON and local peers. These nodes do not start Kimi |
| [ScanSci search and download](scansci.md) | `run --feature scansci` | 34 | Mocked `scansci-pdf` 1.19.0. Not a live library download |
| [Selection and upload consent](selection.md) | `run --feature selection` | 4 | Real CLI. The no-consent node skips a MinerU upload. markitdown does not read consent |
| [Import local PDF](local-pdf.md) | `run --feature local-pdf` | 2 | Real CLI and fixture PDF. These nodes do not run the converter chain |
| [Acquire verified PDF](acquisition.md) | `run --feature acquisition` | 3 | HTTP fallback. The suite disables scansci |
| [Deliver and recover](delivery.md) | `run --feature delivery` | 3 | Fixture Zotero and MinerU v4 peers. Not the LAN Tasks API or a Desktop file attach |
| [Lab defaults](lab-defaults.md) | `run --feature lab-defaults` | 14 | Loopback only, including one-page Kimi fixture failures. Does not dial the lab host, Kimi, or Desktop, and does not prove file attach |
| [Local parser](local-parser.md) | not on this branch | 0 | `local_parse.py` is absent. The feature reports that and does not collect tests |
| [Unified local workflow](unified-local.md) | not on this branch | 0 | `zotero_local.py` and `local_parse.py` are absent. The feature reports that and does not collect tests |

The runnable starter map is the 64 tests whose modules are in this branch. A missing dependency, skipped test or failed assertion among those 64 is not a pass. `local-parser` and `unified-local` stay in the index so an agent does not invent the missing scripts. `lab-defaults` is a different entry point from those two absent modules. Every assertion's node ID is in `invocation.json` and `results.xml`; commands are in `commands.jsonl`. Inspect action plus resulting files/peer assertions. Real-agent interpretation, production services and Windows remain separate unverified entry points. This is not full-suite coverage.
