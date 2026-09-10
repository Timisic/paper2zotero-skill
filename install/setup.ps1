[CmdletBinding()]
param([switch]$Demo, [switch]$DependenciesOnly, [switch]$Check, [switch]$Group, [switch]$LaunchWizard, [switch]$Advanced,
      [ValidateSet('auto','codex','claude-code','pi','all')][string]$Agent = 'auto')
$ErrorActionPreference = 'Stop'
# This launcher prepares native Windows tools, then reuses the Bash Wizard UI.
if ($env:OS -ne 'Windows_NT') { throw 'Use bash setup.sh on macOS or Linux.' }
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$env:PYTHONUTF8 = '1'
$env:PAPER2ZOTERO_AGENT = $Agent
if (([int][bool]$Demo + [int][bool]$DependenciesOnly + [int][bool]$Check) -gt 1) { throw 'Choose only one of -Demo, -DependenciesOnly or -Check.' }
Write-Host 'System: Windows - checking installed tools first.' -ForegroundColor Cyan
function Refresh-ToolPath {
    $env:PATH = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
        [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:PATH
}
function Find-GitBash {
    $paths = @("$env:ProgramFiles\Git\bin\bash.exe", "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe")
    $git = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($git) { $paths += Join-Path (Split-Path (Split-Path $git.Source)) 'bin\bash.exe' }
    foreach ($path in $paths) { if (Test-Path -LiteralPath $path) { return $path } }
    return $null
}
function Find-Python {
    $candidates = @()
    if ($env:PYTHON_BIN) { $candidates += $env:PYTHON_BIN }
    foreach ($name in @('python.exe', 'python3.exe', 'py.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and $command.Source -notlike '*\Microsoft\WindowsApps\python*') { $candidates += $command.Source }
    }
    $candidates += @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        try { $result = & $candidate -c 'import sys; print(sys.executable) if sys.version_info >= (3,11) else sys.exit(1)' 2>$null } catch { continue }
        if ($LASTEXITCODE -eq 0 -and $result) { return ($result | Select-Object -Last 1).Trim() }
    }
    return $null
}
function Test-Poppler {
    $tool = Get-Command pdftotext.exe -ErrorAction SilentlyContinue
    if (-not $tool) { return $false }
    # Native tools write version information to stderr; avoid PS5 treating it as an exception.
    try { $process = Start-Process -FilePath $tool.Source -ArgumentList '-v' -Wait -PassThru -NoNewWindow } catch { return $false }
    return $process.ExitCode -eq 0
}
function Start-Wizard([string]$BashPath, [string[]]$WizardArgs) {
    $entry = Join-Path $PSScriptRoot 'windows-wizard.sh'
    if (-not (Test-Path -LiteralPath $entry)) { throw "Wizard launcher missing: $entry" }
    # Check/dependency modes do not need a terminal or prompt for credentials.
    if ($Check -or $DependenciesOnly) {
        & $BashPath $entry.Replace('\', '/') @WizardArgs | Out-Host
        return $LASTEXITCODE
    }
    $gitRoot = Split-Path (Split-Path $BashPath)
    $terminal = Join-Path $gitRoot 'usr\bin\mintty.exe'
    if (-not (Test-Path -LiteralPath $terminal)) { throw "Git terminal missing: $terminal. Repair Git for Windows and retry." }
    # Start-Process joins its argument array into one Windows command line.
    # Quote each path explicitly; use a one-word title so it cannot become a command.
    $arguments = @('--hold', 'error', '--title', 'literature-to-zotero', '-e', '/usr/bin/bash', ('"' + $entry.Replace('\', '/') + '"')) + $WizardArgs
    Write-Host '正在打开配置向导。请在新窗口填写账号授权；粘贴时可按 Shift+Insert。' -ForegroundColor Cyan
    if ($LaunchWizard) {
        # Agent tool calls must be able to return while the human enters keys.
        $startup = Join-Path ([IO.Path]::GetTempPath()) ('paper2zotero-start-' + [guid]::NewGuid().ToString('N'))
        $env:PAPER2ZOTERO_STARTUP_FILE = $startup
        try {
            $process = Start-Process -FilePath $terminal -ArgumentList $arguments -PassThru
            $deadline = [DateTime]::UtcNow.AddSeconds(15)
            while ([DateTime]::UtcNow -lt $deadline) {
                if (Test-Path -LiteralPath $startup) {
                    Write-Host 'Wizard terminal is ready. Ask the user to complete it, then run setup.ps1 -Check.' -ForegroundColor Green
                    return 0
                }
                # mintty may hand off to another process before Bash starts;
                # its initial process exiting is not a startup failure.
                Start-Sleep -Milliseconds 100
            }
            throw 'Wizard startup was not confirmed. Check the terminal error; do not report setup complete.'
        } finally {
            Remove-Item Env:PAPER2ZOTERO_STARTUP_FILE -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $startup -ErrorAction SilentlyContinue
        }
    }
    $process = Start-Process -FilePath $terminal -ArgumentList $arguments -PassThru -Wait
    return $process.ExitCode
}
function Install-Tool([string]$Package) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        Write-Host 'Install/update App Installer in Microsoft Store, then run setup.cmd again.' -ForegroundColor Yellow
        Start-Process 'ms-windows-store://pdp/?ProductId=9NBLGGH4NNS1'
        throw 'WinGet is unavailable. No need to configure Python or PATH manually.'
    }
    Write-Host "Installing missing tool: $Package" -ForegroundColor Cyan
    & winget.exe install --id $Package --exact --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Installation failed: $Package. Re-run setup to continue." }
    Refresh-ToolPath
}
try {
    Refresh-ToolPath
    $bashPath = Find-GitBash
    $pythonPath = Find-Python
    $popplerReady = Test-Poppler
    if ($pythonPath) { Write-Host 'Python 3.11+: OK, skipping installation.' -ForegroundColor Green }
    if ($popplerReady) { Write-Host 'Poppler: OK, skipping installation.' -ForegroundColor Green }
    if ($bashPath) { Write-Host 'Wizard shell: OK, skipping installation.' -ForegroundColor Green }
    if ($Demo -or $Check) {
        if (-not $bashPath) { throw 'Git Bash is needed to display the Wizard. Run setup.cmd once first; this preview/check installed nothing.' }
        if ($Check -and -not $pythonPath) { throw 'Python 3.11+ is missing; run setup.cmd to install it.' }
    } else {
        if (-not $pythonPath) { Install-Tool 'Python.Python.3.13'; $pythonPath = Find-Python }
        if (-not $popplerReady) { Install-Tool 'oschwartz10612.Poppler'; $popplerReady = Test-Poppler }
        if (-not $bashPath) { Install-Tool 'Git.Git'; $bashPath = Find-GitBash }
        if (-not $pythonPath -or -not $popplerReady -or -not $bashPath) { throw 'Tool verification failed. Close this window and re-run setup.cmd.' }
    }
    if ($pythonPath) { $env:PYTHON_BIN = $pythonPath }
    if ($popplerReady) {
        # Git prepends its own bin directory on startup. Its bundled Xpdf
        # pdftotext returns 99 for -v, so carry the verified native tool to Bash.
        $env:PAPER2ZOTERO_PDF_BIN = Split-Path (Get-Command pdftotext.exe).Source
    }
    $wizardArgs = @()
    if ($Demo) { $wizardArgs += '--demo' }
    elseif ($Check) { $wizardArgs += '--check' }
    elseif ($DependenciesOnly) { $wizardArgs += '--dependencies-only' }
    if ($Group) { $wizardArgs += '--group' }
    if ($Advanced) { $wizardArgs += '--advanced' }
    $result = Start-Wizard $bashPath $wizardArgs
    exit $result
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
