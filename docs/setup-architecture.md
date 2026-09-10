# Setup architecture

The default setup has four stages: prepare tools, connect Zotero, enable full-text reading, and check the result. Extra search providers, Desktop sync and browser access are available through `--advanced`. Platform commands and completion criteria live in [AGENT_SETUP.md](../install/AGENT_SETUP.md); human instructions live in [HELP.md](../install/HELP.md).

## Ownership

Paths below are relative to the repository root.

| Owner | Responsibility |
| --- | --- |
| `install/setup.ps1`, `literature-to-zotero/scripts/bootstrap.sh` | Prepare native tools and save their verified paths |
| `literature-to-zotero/scripts/agent_installation.py`, `install.py` in the same directory | Select agent destinations, install runtime files and preserve conflicts |
| `literature-to-zotero/scripts/setup-wizard.sh` | Human steps using the existing terminal template |
| `literature-to-zotero/scripts/configure.py` | Atomic UTF-8 configuration writes and completion checks |
| `literature-to-zotero/scripts/credentials.py`, `capability.py` in the same directory | Resolve credentials and judge service capabilities |

Installation and verification share agent destinations. Explicit targets avoid installing into another assistant merely because its directory exists. Managed copies are used on Windows; links are used on macOS/Linux. Independent installations are preserved. Updating several runtime copies is not transactional: a mid-copy filesystem failure may require rerunning setup, and backups remain available.

The wizard sends configuration values to the Python writer through stdin. Empty input retains existing values; unrelated settings survive updates. Windows applies a current-user ACL. Demo mode uses a temporary example configuration and simulated services, so it can run without account access or Python.

## Windows constraints

PowerShell prepares native Python, Poppler and Git Bash. Interactive setup runs in a mintty terminal; check and dependency-only modes stay with the caller. A temporary marker confirms that the wizard has a terminal and can start, not that account setup is complete.

Bash and native Python use the same user profile. Both the Python executable and verified PDF-tool directory are saved; Bash and PowerShell launchers restore them on later runs. This prevents Git's bundled PDF tool from taking precedence in a new Claude Code session. Preserve quoted paths, UTF-8 handling and the LF/CRLF rules in `.gitattributes`.

## Verification

Distribution tests cover repeat installation, conflicting directories, download removal, private writes and incomplete checks. Onboarding tests cover targeted installs, basic/advanced demo paths, tool-path restoration and service timeouts. Native Windows tests cover the PowerShell/mintty/Bash chain with Chinese and spaced paths. These tests do not replace fresh-system installation, human authorization or a real paper run; see the [maintenance entry](README.md#检查与打包).
