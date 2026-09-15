# Setup architecture

The default setup prepares tools, connects Zotero, requires an OpenAlex API key, enables full-text reading, checks the result, and presents expanded optional settings. `--advanced` opens optional settings without repeating basic account steps. OpenAlex setup succeeds only with an explicit key and a successful bounded query; another source cannot substitute for it. Runtime source fallback remains independent of setup completeness. Platform commands and completion criteria live in [AGENT_SETUP.md](../install/AGENT_SETUP.md); human instructions live in [HELP.md](../install/HELP.md).

## Ownership

Paths below are relative to the repository root.

| Owner | Responsibility |
| --- | --- |
| `install/setup.ps1`, `literature-to-zotero/scripts/bootstrap.sh` | Prepare native tools and save their verified paths |
| `literature-to-zotero/scripts/agent_installation.py`, `install.py` in the same directory | Select agent destinations, install runtime files and preserve conflicts |
| `literature-to-zotero/scripts/setup-wizard.sh` | Human steps using the existing terminal template |
| `literature-to-zotero/scripts/setup-input.sh` | Masked authorization input, control-character rejection and retry |
| `literature-to-zotero/scripts/setup_gui.py`, `setup_connection.py` | Default Windows native wizard; shared validated account connection and accepted saves for GUI and Bash |
| `literature-to-zotero/scripts/configure.py` | Atomic UTF-8 configuration writes and completion checks |
| `literature-to-zotero/scripts/credentials.py`, `capability.py` in the same directory | Resolve credentials and judge service capabilities |

Installation and verification share agent destinations and runtime evidence. Managed copies are used on Windows; links are used on macOS/Linux. Independent installations are preserved. All complete runtime copies are staged and hashed before any active directory changes. A durable publication journal records the original targets, prepared paths and backups before renaming. Rerunning any install entry finishes the pending publication first; it then applies the requested update. A process lock excludes simultaneous publishers. Backups and staging stay outside discoverable skill roots and on each target's volume. This is resumable publication, not an instantaneous multi-directory transaction: an interrupted switch can temporarily leave a target unavailable until setup resumes.

Each managed runtime carries a content manifest. Verification checks files and the shared version, so a missing script or mixed release cannot pass merely because SKILL.md exists. The documented customization of `references/paper-summary.md` is allowed for readiness; the file must still exist. Installation staging always checks every byte. Reinstalling identical complete content does not create another backup. Existing v1 ownership markers remain upgradeable; the first update adds manifests. Unmanaged skills retain their independent installation semantics.

The wizard sends configuration values to the Python writer through stdin. Empty input retains existing values; unrelated settings survive updates. Windows applies a current-user ACL. Terminal demo mode uses a temporary example configuration and simulated services, so it can run without account access or Python; its brief simulated guides are explicitly labeled. The Windows GUI demo requires Python/Tk.

Repairing an account inherits its existing personal/group target unless the caller explicitly chooses another target. A failed probe never turns a group library into a personal library. A damaged prepared runtime is rebuilt from the available complete source for the original publication targets; the recovery journal is replaced only once the replacement snapshots are ready.

## Windows constraints

PowerShell prepares native Python, Poppler and Git Bash. Basic interactive setup launches a Tk window through pythonw.exe; its completion page links to optional settings. `-Advanced` opens those settings directly in the same GUI. Check and dependency-only modes stay with the caller; `-Terminal` retains mintty, including `-Terminal -Advanced`. A temporary marker confirms that the selected UI is ready, not that account setup is complete. Both paths are tested with Chinese and spaced download paths.

`setup_connection.SERVICES` supplies service instructions to both frontends, and `BASIC_SERVICES` identifies the three basic accounts. Optional settings directly display Kimi WebBridge, Semantic Scholar, Crossref, Unpaywall and Zotero Desktop. Optional source credentials are privately saved with an explicit unverified status, then exercised by real discovery; Kimi/Desktop are enabled only after connection checks. Skipping does not write flags or change existing credentials. The GUI shows all optional cards in a scrollable page. The terminal visits the same optional services in sequence and preserves its platform installation helpers. Demo covers every optional pane without touching services or configuration. macOS/Linux keep the Bash entry and do not import Tk; Unix private writes do not call PowerShell.

Native entry fields use the OS clipboard shortcuts and an explicit Paste button. Keys remain in memory until remote validation succeeds. `capability.py` owns the key-info request and permission interpretation used by setup, self-id and runtime checks. `setup_connection.connect` returns verified account settings; `save_account` commits the accepted result using the private atomic writer and clears stale inherited account overrides. Only the live UI accepts a background result. Closing during a request cannot save a late result. Bash passes a key on stdin to `configure.py --connect`; it uses the same validation and accepted save, never persists a new key separately from its verified library ID, and clears its transient account variables after the attempt. Windows ACL protection uses .NET Framework directly, avoiding a PS7-inherited module path breaking PS5 Set-Acl. Browser launch uses Windows URL association rather than Explorer's process exit code.

The native demo has no credential discovery, account requests, installation or config writes. UI smoke tests use only dummy keys; successful demo output is never real authorization evidence. Updating GitHub does not update installed copies: setup.cmd runs its current source, while install.ps1 updates a clean canonical cache. Dirty caches must be preserved and repaired explicitly.

Bash and native Python use the same user profile. Both the Python executable and verified PDF-tool directory are saved; Bash and PowerShell launchers restore them on later runs. This prevents Git's bundled PDF tool from taking precedence in a new Claude Code session. Preserve quoted paths, UTF-8 handling and the LF/CRLF rules in `.gitattributes`.

The wizard's mintty process maps only Ctrl+V to paste, using `ShootFoot=yes` and `KeyFunctions=C+v:paste`; `CtrlExchangeShift=no` preserves Ctrl+C interruption. These command-line options never modify global mintty preferences. Authorization input shows a fixed mask on receipt, handles backspace, rejects control characters before persistence, and pauses on EOF. The writer also rejects controls for non-wizard callers. Personal library discovery reports safe errors on stderr and offers a retry; manual IDs are only requested for group libraries.

`tests/test_setup_input.py` exercises the real Bash input helper and retry stages with synthetic input and mocks Zotero identity responses. The native Windows launcher tests additionally check that mintty starts with the new options and that echo is disabled during entry and restored after success or interruption on a real TTY. Actual keyboard-to-clipboard integration still requires manual acceptance in the wizard window: Ctrl+V and Shift+Insert paste, Ctrl+C exits, backspace works, and no secret is echoed. Synthetic input is not a substitute for this keyboard check.

## Verification

Distribution tests cover repeat installation, conflicting directories, download removal, private writes and incomplete checks. Onboarding tests cover targeted installs, basic/advanced demo paths, tool-path restoration and service timeouts. Native Windows tests cover the PowerShell/mintty/Bash chain with Chinese and spaced paths. These tests do not replace fresh-system installation, human authorization or a real paper run; see the [maintenance entry](README.md#检查与打包).
