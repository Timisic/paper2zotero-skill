# Setup architecture

The default setup prepares tools, checks the current search backend, one conversion hop and local Zotero writes, then offers optional settings. `--advanced` opens optional settings and skips the aggregate check. Runtime source fallback stays independent of setup completeness. Platform commands and completion criteria live in [AGENT_SETUP.md](../install/AGENT_SETUP.md). Human instructions and the optional cards live in [HELP.md](../install/HELP.md).

## Ownership

Paths below are relative to the repository root.

| Owner | Responsibility |
| --- | --- |
| `install/setup.ps1`, `paper-to-zotero/scripts/bootstrap.sh` | Prepare native tools and save their verified paths |
| `setup_connection.ensure_default_tools` | Own the private Python runtime and record its interpreter in `python-path` |
| `scripts/build-distribution.py` | Build the release zip and, with `--platform`, offline zips |
| `paper-to-zotero/scripts/agent_installation.py`, `install.py` in the same directory | Select agent destinations, install runtime files and preserve conflicts |
| `paper-to-zotero/scripts/setup-wizard.sh` | Human steps using the existing terminal template |
| `paper-to-zotero/scripts/setup-input.sh` | Masked authorization input, control-character rejection and retry |
| `paper-to-zotero/scripts/setup_gui.py`, `setup_connection.py` | Default Windows native wizard; shared validated account connection and accepted saves for GUI and Bash |
| `paper-to-zotero/scripts/configure.py` | Atomic UTF-8 configuration writes and completion checks |
| `paper-to-zotero/scripts/credentials.py`, `capability.py` in the same directory | Resolve credentials and judge service capabilities |

Installation and verification share agent destinations and runtime evidence. All six skills (`paper-to-zotero`, `discussion-drafter`, `academic-paper`, `academic-paper-reviewer`, `nature-writing`, `nature-shared`) must be ready in the same selected agent. Managed copies are used on Windows; links are used on macOS/Linux. Independent installations are preserved. The installer checks every source and all destination conflicts before publishing. Each skill's complete runtime copies are staged and hashed, with a separate durable publication journal recording original targets, prepared paths and backups before renaming. Rerunning finishes pending publication and applies the update. A process lock excludes simultaneous publishers. Backups and staging stay outside discoverable skill roots and on each target's volume. This is resumable publication, not an instantaneous bundle transaction: interruption can leave some skills installed and others pending; the bundle readiness check then fails.

New runtimes live under `~/.local/share/paper-to-zotero/`. Existing managed `literature-to-zotero` installations join the migration, including previously managed shared roots; independent installs are not adopted. Old discoverable names move to recoverable backups only after all six skills publish successfully. The old shared runtime remains available to those backups. Customized summary prompts are carried forward; conflicting customizations stop the update. Credentials and verified tool paths continue using `~/.config/literature-to-zotero/`; cache paths, v1 ownership markers and Zotero note identity markers also retain their old identifiers to preserve settings and idempotency.

Each managed runtime carries a content manifest. Verification checks files and the shared version, so a missing script or mixed release cannot pass merely because SKILL.md exists. The documented customization of `references/paper-summary.md` is allowed for readiness; the file must still exist. Installation staging always checks every byte. Reinstalling identical complete content does not create another backup. Existing v1 ownership markers remain upgradeable; the first update adds manifests. Unmanaged skills retain their independent installation semantics.

The wizard sends configuration values to the Python writer through stdin. Empty input retains existing values; unrelated settings survive updates. Windows applies a current-user ACL.

Repairing an account inherits its existing personal/group target unless the caller explicitly chooses another target. A failed probe never turns a group library into a personal library. A damaged prepared runtime is rebuilt from the available complete source for the original publication targets; the recovery journal is replaced only once the replacement snapshots are ready.

## Private runtime and offline bundles

scansci-pdf and markitdown never go into a system Python; Homebrew and Debian/Ubuntu Pythons refuse that. `ensure_default_tools` keeps them in `~/.local/share/paper-to-zotero/runtime` and writes that interpreter to `python-path`, so every launcher runs the workflow there. A runtime that already imports the pinned packages is left alone. Otherwise it is rebuilt from the first available source:

1. An offline bundle, recognized by `runtime/python` and `runtime/wheels` at the bundle root. The bundled Python is copied into the runtime directory and installs from the wheels with `--no-index`.
2. A venv from the base Python, installing from the configured index, then once from the Tsinghua mirror unless `PIP_INDEX_URL` is set.

In a bundle, `bootstrap.sh` and `setup.ps1` use `runtime/python` as the base interpreter and run no package manager. Poppler is optional in every mode. `--platform` builds bundle the zip's lite content plus `runtime/`, `VERSION` and `开始.md`. `.github/workflows/release.yml` publishes them per tag, and the runtime workflow installs each OS's bundle with the index unreachable.

## Windows constraints

PowerShell prepares native Python and, when it can, Poppler; Git Bash only for `-Terminal`. Basic interactive setup launches a Tk window through pythonw.exe; its completion page links to optional settings. `-Advanced` opens those settings directly in the same GUI. Check and dependency-only modes run Python directly, without Git Bash, and stay with the caller; `-Terminal` retains mintty, including `-Terminal -Advanced`. A temporary marker confirms that the selected UI is ready, not that account setup is complete. Both paths are tested with Chinese and spaced download paths.

`setup_connection.SERVICES` supplies service instructions to both frontends. `BASIC_SERVICES` is `('desktop',)`. Optional cards come from `wizard_extras()`. Optional source credentials are privately saved with an explicit unverified status, then exercised by real discovery. Kimi is enabled only after its connection check. Skipping does not write flags or change existing credentials. The GUI shows all optional cards in a scrollable page. The terminal visits the same optional services in sequence and preserves its platform installation helpers. macOS/Linux keep the Bash entry and do not import Tk; Unix private writes do not call PowerShell.

Native entry fields use the OS clipboard shortcuts and an explicit Paste button. Keys remain in memory until remote validation succeeds. `capability.py` owns the key-info request and permission interpretation used by setup, self-id and runtime checks. `setup_connection.connect` returns verified account settings; `save_account` commits the accepted result using the private atomic writer and clears stale inherited account overrides. Only the live UI accepts a background result. Closing during a request cannot save a late result. Bash passes a key on stdin to `configure.py --connect`; it uses the same validation and accepted save, never persists a new key separately from its verified library ID, and clears its transient account variables after the attempt. Windows ACL protection uses .NET Framework directly, avoiding a PS7-inherited module path breaking PS5 Set-Acl. Browser launch uses Windows URL association rather than Explorer's process exit code.

UI smoke tests use only dummy keys. Updating GitHub does not update installed copies: setup.cmd runs its current source, while install.ps1 updates a clean canonical cache. Dirty caches must be preserved and repaired explicitly.

Bash and native Python use the same user profile. Both the Python executable and verified PDF-tool directory are saved; Bash and PowerShell launchers restore them on later runs. This prevents Git's bundled PDF tool from taking precedence in a new Claude Code session. Preserve quoted paths, UTF-8 handling and the LF/CRLF rules in `.gitattributes`.

- `runtime_io.file_lock` excludes competing writers on Windows with byte-range locks and on POSIX with flock. Workflow locks fail promptly; shared request pacing waits for its short critical section. Closing the process releases the lock.
- `runtime_io.private_text` creates a private temporary file, applies the Windows user-only ACL before writing, closes it before replacement, and cleans up after failure. POSIX files keep mode 0600. Account saves and signed conversion URLs share this implementation.

The wizard's mintty process maps only Ctrl+V to paste, using `ShootFoot=yes` and `KeyFunctions=C+v:paste`; `CtrlExchangeShift=no` preserves Ctrl+C interruption. These command-line options never modify global mintty preferences. Authorization input shows a fixed mask on receipt, handles backspace, rejects control characters before persistence, and pauses on EOF. The writer also rejects controls for non-wizard callers. Personal library discovery reports safe errors on stderr and offers a retry; manual IDs are only requested for group libraries.

`tests/test_setup_input.py` exercises the real Bash input helper and retry stages with synthetic input and mocks Zotero identity responses. The native Windows launcher tests additionally check that mintty starts with the new options and that echo is disabled during entry and restored after success or interruption on a real TTY.

Workflow verification is [verify-paper2zotero](../.agents/skills/verify-paper2zotero/SKILL.md).
