# Paper2zotero verification map

Use the parent SKILL.md's doctor and run commands from the repository root. Every feature starts with a new isolated profile, copied current source and temporary run data; no existing account or library is reused. Fixtures create their own ephemeral peers. CLI stdout/stderr/exit codes and resulting state survive cleanup in the printed evidence directory.

| Feature | Safe recipe | Existing scenarios | Boundary |
|---|---|---:|---|
| [Discovery and shortlist](discovery.md) | `run --feature discovery` | 3 | Fixture responses; one failure check uses the production client directly |
| [Selection and upload consent](selection.md) | `run --feature selection` | 4 | Real CLI, synthetic decisions and library |
| [Import local PDF](local-pdf.md) | `run --feature local-pdf` | 2 | Real CLI and fixture PDF |
| [Acquire verified PDF](acquisition.md) | `run --feature acquisition` | 3 | Local HTTP; rejection checks also use production acquisition client |
| [Deliver and recover](delivery.md) | `run --feature delivery` | 3 | Real orchestration, mock Zotero/MinerU/browser/summary |
| [Local parser](local-parser.md) | not on this branch | 0 | `local_parse.py` is absent. The feature reports that and does not collect tests |
| [Unified local workflow](unified-local.md) | not on this branch | 0 | `zotero_local.py` and `local_parse.py` are absent. The feature reports that and does not collect tests |

The runnable starter map is the 15 tests whose modules are in this branch. A missing dependency, skipped test or failed assertion among those 15 is not a pass. `local-parser` and `unified-local` stay in the index so an agent does not invent the missing scripts. Every assertion's node ID is in `invocation.json` and `results.xml`; commands are in `commands.jsonl`. Inspect action plus resulting files/peer assertions. Real-agent interpretation, production services and Windows remain separate unverified entry points. This is not full-suite coverage.
