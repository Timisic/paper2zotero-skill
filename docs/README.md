# Project documentation

- [User guide](../README.md): capabilities, configuration and use.
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

Windows uses `install/setup.cmd` → PowerShell (`install/setup.ps1`) → the unchanged Bash Wizard library via Git Bash. It runs native Windows Python and Poppler, without WSL. WinGet package IDs follow the [Microsoft install documentation](https://learn.microsoft.com/en-us/windows/package-manager/winget/install) and the [Poppler manifest](https://github.com/microsoft/winget-pkgs/blob/master/manifests/o/oschwartz10612/Poppler/25.07.0-0/oschwartz10612.Poppler.installer.yaml).

Configuration stays at `%USERPROFILE%\.config\literature-to-zotero\env`. Windows applies a current-user file ACL instead of relying on chmod. Runtime folders use marked managed copies so Developer Mode/symlink privileges are unnecessary. The interpreter is stored as a native path; Bash and Windows command launchers adapt it for their own shell.

Validated on macOS: PowerShell syntax parsing, Bash syntax, temporary-home repeated managed-copy installation, package assembly, and capability tests. Still pending on Windows 10/11: WinGet installation on a fresh machine, Chinese/spaced profile paths, console rendering/input, file ACL read-back, and one real PDF processing run. Treat the Windows package as a test build until these pass. A missing App Installer requires the Microsoft Store step; optional Kimi Windows installation follows its product page. Preview never installs missing tools and needs Git Bash already present.
