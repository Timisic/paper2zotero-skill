# Project documentation

- [User guide](../README.md): capabilities, configuration and use.
- [Agent setup instructions](../install/AGENT_SETUP.md): platform-specific installation, Wizard startup and completion checks.
- [Architecture and domain](../CONTEXT.md): module boundaries and invariants.
- [Agent skill](../literature-to-zotero/SKILL.md): execution instructions; its `references/` remain part of the portable skill.

## Architecture decisions

- [ADR-0001](adr/0001-capability-judgement-and-credentials.md): shared capability/credential handling.
- [ADR-0002](adr/0002-browser-acquisition-channel.md): browser transport; routing precedence updated by ADR-0004.
- [ADR-0003](adr/0003-one-confirmation-and-independent-artifacts.md): one confirmation and independent artifact delivery.
- [ADR-0004](adr/0004-http-first-discovery-and-acquisition.md): HTTP first, browser fallback.

## Distribution maintenance

Run `python3 scripts/build-distribution.py` from the repository root. The generated `dist/literature-to-zotero/` and ZIP contain only the user README, setup entry point, and runtime skill files. Generated packages are ignored by Git. Use `--output <new-directory>` for another build; existing packages are preserved.

`install/setup.sh` bootstraps Python 3.11+ and Poppler on macOS or Debian/Ubuntu, installs a persistent copy, then collects service credentials. `--dependencies-only` supports an agent preparing the machine before the human enters credentials; `--check` verifies core services and previously selected optional features. Python dependencies for the main workflow are all in the standard library. Setup does not install development test tools.

The distribution tests exercise installation into a temporary home, repeat installation, removal of the downloaded package, conflicting existing skills, private config updates, and incomplete setup exit codes. System package downloads and account/browser authorization still need fresh-machine acceptance on supported platforms.

The setup UI uses the wizard skill template verbatim above its STAGES section. Automatic dependency work lives in `bootstrap.sh`; `--demo` follows the same Bash stages with temporary example configuration, simulated service checks, and no browser launch. Wizard stages are statically traced; interactive acceptance is left to the human.

## Windows setup validation

Windows uses `install/setup.cmd` → PowerShell (`install/setup.ps1`) → a Git mintty terminal → `install/windows-wizard.sh` → the unchanged Bash Wizard library. Interactive setup gets a real terminal even when launched from Explorer or an agent; check/dependency-only modes stay in the caller. It runs native Windows Python and Poppler, without WSL. WinGet package IDs follow the [Microsoft install documentation](https://learn.microsoft.com/en-us/windows/package-manager/winget/install) and the [Poppler manifest](https://github.com/microsoft/winget-pkgs/blob/master/manifests/o/oschwartz10612/Poppler/25.07.0-0/oschwartz10612.Poppler.installer.yaml).

Configuration stays at `%USERPROFILE%\.config\literature-to-zotero\env`. Windows applies a current-user file ACL instead of relying on chmod. Runtime folders use marked managed copies so Developer Mode/symlink privileges are unnecessary. The interpreter is stored as a native path; Bash and Windows command launchers adapt it for their own shell.

The Windows launcher passes the verified native Poppler directory into Bash after Git initializes its own paths. Otherwise Git's bundled Xpdf `pdftotext -v` returns 99 and the bootstrap incorrectly reports a missing dependency. Paths passed to the terminal are explicitly quoted, the shell tool path is initialized, and the wizard is called by a native drive path. Shell files are checked out with LF via `.gitattributes`.

Agents use `install/install.ps1 -LaunchWizard` (or `install/setup.ps1 -LaunchWizard` for an existing checkout). The launcher returns only after the Bash wrapper confirms a TTY and a readable, syntactically valid wizard through a temporary, non-secret startup marker. This confirms startup only; the agent must wait for human completion and run `-Check`. Mintty can hand off to another process, so the first process exiting is not treated as failure. The online entry also forwards `-DependenciesOnly` and `-Check`, and supports `PAPER2ZOTERO_SOURCE_DIR` for a custom cache. Origin validation reads the saved remote URL rather than Git's expanded `insteadOf` URL.

Run `python literature-to-zotero/tests/test_windows_setup.py -v` on Windows with Git and Poppler installed. These standard-library tests build a distribution in a Chinese/spaced directory, install twice into an isolated Chinese/spaced home, check that backups remain outside agent skill roots, remove the download, and run the installed CLI. A second test substitutes only the account wizard in the temporary package and verifies that the actual PowerShell/mintty/Bash chain provides a TTY and a working Poppler. It never reads service credentials.

Additional tests traverse all eight real demo stages, verify that agent launch returns while the terminal is still working, and exercise the online download/update entry against a local Git fixture, including mode forwarding and preservation of a dirty cache. The tests use isolated homes and no account authorization.

Validated on this Windows machine: those native regression tests, PowerShell parsing, and real wizard startup. Still pending for full release acceptance: dependency installation on a fresh Windows 10/11 image, human credential entry and ACL read-back, optional browser/Desktop authorization, and one real PDF processing run. A missing App Installer requires the Microsoft Store step; optional Kimi Windows installation follows its product page. Preview never installs missing tools and needs Git Bash already present.
