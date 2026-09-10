param([switch]$DependenciesOnly, [switch]$Check, [switch]$LaunchWizard, [switch]$Advanced,
      [ValidateSet('auto','codex','claude-code','pi','all')][string]$Agent = 'auto')
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Use the macOS/Linux installer.' }
$repo = 'https://github.com/Timisic/paper2zotero-skill.git'
$checkout = if ($env:PAPER2ZOTERO_SOURCE_DIR) { $env:PAPER2ZOTERO_SOURCE_DIR } else { Join-Path $env:LOCALAPPDATA 'paper2zotero-source' }
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        Start-Process 'ms-windows-store://pdp/?ProductId=9NBLGGH4NNS1'
        throw 'Install/update App Installer in Microsoft Store, then run this command again.'
    }
    & winget.exe install --id Git.Git --exact --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Git installation failed; re-run to continue.' }
    $env:PATH = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:PATH
}
if (Test-Path -LiteralPath $checkout) {
    if (-not (Test-Path -LiteralPath (Join-Path $checkout '.git'))) { throw 'Installation cache is occupied; existing files were preserved.' }
    $origin = & git.exe -C $checkout config --get remote.origin.url
    if ($LASTEXITCODE -ne 0 -or $origin -ne $repo) { throw 'Installation cache has a different origin; preserved.' }
    $changes = & git.exe -C $checkout status --porcelain
    if ($LASTEXITCODE -ne 0 -or $changes) { throw 'Installation cache has local changes; preserved.' }
    & git.exe -C $checkout pull --ff-only origin main
} else {
    & git.exe clone --depth 1 --branch main $repo $checkout
}
if ($LASTEXITCODE -ne 0) { throw 'Repository download failed; re-run to continue.' }
$setupArgs = @('-Agent', $Agent)
if ($Advanced) { $setupArgs += '-Advanced' }
if ($DependenciesOnly) { $setupArgs += '-DependenciesOnly' }
if ($Check) { $setupArgs += '-Check' }
if ($LaunchWizard) { $setupArgs += '-LaunchWizard' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $checkout 'install\setup.ps1') @setupArgs
if ($LASTEXITCODE -ne 0) { throw 'Setup is incomplete; saved settings are preserved. Re-run to continue.' }
