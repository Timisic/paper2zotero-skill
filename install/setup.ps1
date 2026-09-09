[CmdletBinding()]
param([switch]$Demo, [switch]$DependenciesOnly, [switch]$Check, [switch]$Group)
$ErrorActionPreference = 'Stop'
# This launcher prepares native Windows tools, then reuses the Bash Wizard UI.
if ($env:OS -ne 'Windows_NT') { throw 'Use bash setup.sh on macOS or Linux.' }
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$env:PYTHONUTF8 = '1'
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
    $wizardArgs = @()
    if ($Demo) { $wizardArgs += '--demo' }
    elseif ($Check) { $wizardArgs += '--check' }
    elseif ($DependenciesOnly) { $wizardArgs += '--dependencies-only' }
    elseif ($Group) { $wizardArgs += '--group' }
    & $bashPath ($PSScriptRoot.Replace('\', '/') + '/setup.sh') @wizardArgs
    exit $LASTEXITCODE
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
