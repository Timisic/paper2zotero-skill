# Setup architecture

The default setup has four stages: prepare tools, connect Zotero, enable full-text reading, and check the result. Extra search providers, Desktop sync and browser access are available through `--advanced`. Platform commands and completion criteria live in [AGENT_SETUP.md](../install/AGENT_SETUP.md); human instructions live in [HELP.md](../install/HELP.md).

## Ownership

Paths below are relative to the repository root.

| Owner | Responsibility |
| --- | --- |
| `install/setup.ps1`, `literature-to-zotero/scripts/bootstrap.sh` | Prepare native tools and save their verified paths |
| `literature-to-zotero/scripts/agent_installation.py`, `install.py` in the same directory | Select agent destinations, install runtime files and preserve conflicts |
| `literature-to-zotero/scripts/setup-wizard.sh` | Human steps using the existing terminal template |
| `literature-to-zotero/scripts/setup-input.sh` | Masked authorization input, control-character rejection and retry |
| `literature-to-zotero/scripts/configure.py` | Atomic UTF-8 configuration writes and completion checks |
| `literature-to-zotero/scripts/credentials.py`, `capability.py` in the same directory | Resolve credentials and judge service capabilities |

Installation and verification share agent destinations. Explicit targets avoid installing into another assistant merely because its directory exists. Managed copies are used on Windows; links are used on macOS/Linux. Independent installations are preserved. Updating several runtime copies is not transactional: a mid-copy filesystem failure may require rerunning setup, and backups remain available.

The wizard sends configuration values to the Python writer through stdin. Empty input retains existing values; unrelated settings survive updates. Windows applies a current-user ACL. Demo mode uses a temporary example configuration and simulated services, so it can run without account access or Python.

## Windows constraints

PowerShell prepares native Python, Poppler and Git Bash. Interactive setup runs in a mintty terminal; check and dependency-only modes stay with the caller. A temporary marker confirms that the wizard has a terminal and can start, not that account setup is complete.

Bash and native Python use the same user profile. Both the Python executable and verified PDF-tool directory are saved; Bash and PowerShell launchers restore them on later runs. This prevents Git's bundled PDF tool from taking precedence in a new Claude Code session. Preserve quoted paths, UTF-8 handling and the LF/CRLF rules in `.gitattributes`.

The wizard's mintty process maps only Ctrl+V to paste, using `ShootFoot=yes` and `KeyFunctions=C+v:paste`; `CtrlExchangeShift=no` preserves Ctrl+C interruption. These command-line options never modify global mintty preferences. Authorization input shows a fixed mask on receipt, handles backspace, rejects control characters before persistence, and pauses on EOF. The writer also rejects controls for non-wizard callers. Personal library discovery reports safe errors on stderr and offers a retry; manual IDs are only requested for group libraries.

`tests/test_setup_input.py` exercises the real Bash input helper and retry stages with synthetic input and mocks Zotero identity responses. The native Windows launcher tests additionally check that mintty starts with the new options and that echo is disabled during entry and restored after success or interruption on a real TTY. Actual keyboard-to-clipboard integration still requires manual acceptance in the wizard window: Ctrl+V and Shift+Insert paste, Ctrl+C exits, backspace works, and no secret is echoed. Synthetic input is not a substitute for this keyboard check.

## Verification

Distribution tests cover repeat installation, conflicting directories, download removal, private writes and incomplete checks. Onboarding tests cover targeted installs, basic/advanced demo paths, tool-path restoration and service timeouts. Native Windows tests cover the PowerShell/mintty/Bash chain with Chinese and spaced paths. These tests do not replace fresh-system installation, human authorization or a real paper run; see the [maintenance entry](README.md#检查与打包).
