# Setup architecture

The user-facing interface is one request to an agent and four wizard stages. The human supplies account authorization; the installer supplies operating-system and agent-specific behavior. Additional search providers, Desktop and browser settings are disclosed through `--advanced`, and never expanded in the default flow.

| Owner | Responsibility |
| --- | --- |
| `README.md`, `install/HELP.md` | User purpose, one-sentence entry, recovery and familiar-language help |
| `install/AGENT_SETUP.md` | Agent target, platform commands, terminal handoff, precise completion evidence |
| `install/setup.ps1`, `scripts/bootstrap.sh` | Native system tools and verified executable paths |
| `scripts/agent_installation.py`, `scripts/install.py` | One destination map, targeted installation, conflict preservation and runtime availability |
| `scripts/setup-wizard.sh` | Human sequence and account-specific instructions, using the existing terminal template |
| `scripts/configure.py` | Private configuration writes and a human-readable completion report |
| `scripts/credentials.py`, `scripts/capability.py` | Credential resolution, service probes and capability semantics |

Both installation and completion checks use the same target definitions. `auto` detects existing configuration directories; explicit agent parameters avoid guessing from the agent's shell. A Claude Code installation does not require an invented Claude YAML counterpart to `agents/openai.yaml`: the common `SKILL.md` is the execution contract. Externally managed skill directories remain protected.

Configuration writes from the real wizard use the same atomic UTF-8 writer as the Python entry point. Values arrive via stdin, retain unrelated settings and are never command arguments. Windows applies the existing ACL helper. The demo remains independent of credentials and can run without Python, using temporary example values only.

Windows uses native tools and Git Bash for the established wizard UI. The selected Python and PDF-tool directory are both saved: a later Claude Code Git Bash session must not accidentally select Git's bundled Xpdf instead of the verified Poppler. Shell and PowerShell runtime launchers restore those paths. This keeps per-paper commands independent of shell profiles and the original downloaded repository.

## Scope and verification

This change keeps the existing paper-processing modules and consent/recovery rules. It does not replace the wizard with a new GUI or introduce a second service-configuration system. The legacy `setup.py` remains a developer diagnostic, since its global checklist includes integrations that the core workflow does not require.

Tests should exercise targeted installs and conflicts, repeat installs after removal of the download, basic/advanced demo navigation, literal private writes, selected optional failures, and restored tool paths. Native Windows tests cover the PowerShell/mintty/Bash chain with Chinese/spaced paths; running those tests on macOS skips them and does not establish Windows acceptance.

Validation on macOS, 2026-09-10: 300 tests passed, 5 native Windows tests skipped; the focused setup regression suite passed again after final edits (43 tests). Mypy, Bash syntax, skill structure validation and `git diff --check` passed. Basic and advanced demos were executed with simulated services. An anonymous OpenAlex search also returned HTTP 200; that single probe is not a guarantee of ongoing service quotas.

Remaining release acceptance: a fresh native Windows image, actual package downloads, human account authorization, ACL read-back, agent skill discovery in both Claude Code and Codex, and a real PDF run. Historical Windows results in the documentation do not validate this revision.

## Further changes worth separating

The shared persistent runtime is updated by renaming directories and retaining backups. Making the whole multi-agent update transactional would require an installation manifest and rollback across copies; current conflict preflight protects existing user directories, but does not provide transactionality under mid-copy I/O failure. This is a concrete future improvement for updater work, not a reason to add a general plugin framework to onboarding.

Cross-platform download/launch logic remains in its platform adapter because package managers, path encoding and terminal ownership differ. Keep regression checks at the distributed entry points rather than extracting a generic shell abstraction solely to reduce line counts.
