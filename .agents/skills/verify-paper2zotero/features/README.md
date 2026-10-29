# Paper2zotero verification map

Use the parent SKILL.md's doctor and run commands from the repository root. Every feature starts with a new isolated profile, copied current source and temporary run data; no existing account or library is reused. Fixtures create their own ephemeral peers. CLI stdout/stderr/exit codes and resulting state survive cleanup in the printed evidence directory.

| Feature | Safe recipe | Existing scenarios | Boundary |
|---|---|---:|---|
| [Discovery and shortlist](discovery.md) | `run --feature discovery` | 3 | Fixture responses; one failure check uses the production client directly |
| [Selection and upload consent](selection.md) | `run --feature selection` | 4 | Real CLI, synthetic decisions and library |
| [Import local PDF](local-pdf.md) | `run --feature local-pdf` | 2 | Real CLI and fixture PDF |
| [Acquire verified PDF](acquisition.md) | `run --feature acquisition` | 3 | Local HTTP; rejection checks also use production acquisition client |
| [Deliver and recover](delivery.md) | `run --feature delivery` | 3 | Real orchestration, mock Zotero/MinerU/browser/summary |
| [Local parser](local-parser.md) | `run --feature local-parser` | 6 | Fake engine processes; real public-file checks are separate |

| [Unified local workflow](unified-local.md) | `run --feature unified-local` | 17 | Main CLI, native local protocol fixture, fake parser; authentic Zotero authorization/write remains separate |

All 38 are required for the starter map. A missing dependency, skipped test or failed assertion is not a pass. Every assertion's node ID is in `invocation.json` and `results.xml`; commands are in `commands.jsonl`. Inspect action plus resulting files/peer assertions. Real-agent interpretation, production services and Windows remain separate unverified entry points. This is not full-suite coverage.
