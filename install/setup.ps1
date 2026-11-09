[CmdletBinding()]
param([switch]$DependenciesOnly, [switch]$Check, [switch]$Group, [switch]$LaunchWizard, [switch]$Advanced,
      [switch]$Modules, [ValidateSet('runtime','skills','zotero','mineru','kimi')][string[]]$Module = @(),
      [ValidateSet('auto','codex','claude-code','pi','all')][string]$Agent = 'auto')
$ErrorActionPreference = 'Stop'
# Prepare Windows tools, then open the native GUI.
if ($env:OS -ne 'Windows_NT') { throw 'Use bash setup.sh on macOS or Linux.' }
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$env:PYTHONUTF8 = '1'
$env:PAPER2ZOTERO_AGENT = $Agent
if ($DependenciesOnly -and $Check) { throw 'Choose only one of -DependenciesOnly or -Check.' }
Write-Host 'System: Windows - checking installed tools first.' -ForegroundColor Cyan
function Refresh-ToolPath {
    $env:PATH = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
        [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:PATH
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
function Start-Wizard {
    $gui = Join-Path $PSScriptRoot '..\paper-to-zotero\scripts\setup_gui.py'
    $pythonw = Join-Path (Split-Path $pythonPath) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonw)) { $pythonw = $pythonPath }
    $guiArgs = @(('"' + $gui + '"'), '--agent', $Agent)
    if ($Group) { $guiArgs += '--group' }
    if ($Advanced) { $guiArgs += '--advanced' }
    Write-Host '正在打开 Windows 图形向导。先打开 Zotero Desktop。可选授权码在后面的页面粘贴，Ctrl+V。' -ForegroundColor Cyan
    if ($LaunchWizard) {
        $startup = Join-Path ([IO.Path]::GetTempPath()) ('paper2zotero-gui-' + [guid]::NewGuid().ToString('N'))
        $guiArgs += @('--ready-file', ('"' + $startup + '"'))
        try {
            $process = Start-Process -FilePath $pythonw -ArgumentList $guiArgs -PassThru
            $deadline = [DateTime]::UtcNow.AddSeconds(15)
            while ([DateTime]::UtcNow -lt $deadline) {
                if (Test-Path -LiteralPath $startup) {
                    Write-Host 'Native setup window is ready (Windows GUI v2).' -ForegroundColor Green
                    return 0
                }
                if ($process.HasExited) { throw '图形向导未能启动。请重跑 setup.cmd。' }
                Start-Sleep -Milliseconds 100
            }
            throw '图形向导启动未获确认。请重跑 setup.cmd。'
        } finally {
            Remove-Item -LiteralPath $startup -ErrorAction SilentlyContinue
        }
    }
    $process = Start-Process -FilePath $pythonw -ArgumentList $guiArgs -PassThru -Wait
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
    # An offline bundle ships Python next to install\; never download Python for it.
    $bundledPython = Join-Path $PSScriptRoot '..\runtime\python\python.exe'
    if (Test-Path -LiteralPath $bundledPython) {
        Write-Host 'Offline bundle: using its bundled Python.' -ForegroundColor Cyan
        $pythonPath = (Resolve-Path -LiteralPath $bundledPython).Path
    } else {
        $pythonPath = Find-Python
    }
    if ($pythonPath) { Write-Host 'Python 3.11+: OK, skipping installation.' -ForegroundColor Green }
    if ($Check) {
        if (-not $pythonPath) { throw 'Python 3.11+ is missing; run setup.cmd to install it.' }
    } else {
        if (-not $pythonPath) { Install-Tool 'Python.Python.3.13'; $pythonPath = Find-Python }
        if (-not $pythonPath) { throw 'Tool verification failed. Close this window and re-run setup.cmd.' }
    }
    if ($pythonPath) { $env:PYTHON_BIN = $pythonPath }
    $scripts = Join-Path $PSScriptRoot '..\paper-to-zotero\scripts'
    if ($Modules) {
        # Not piped: the module runner reads answers from this console.
        & $pythonPath (Join-Path $scripts 'modules.py') --agent $Agent @Module
        exit $LASTEXITCODE
    }
    if ($DependenciesOnly) {
        & $pythonPath (Join-Path $scripts 'setup_connection.py') $Agent | Out-Host
        exit $LASTEXITCODE
    }
    if ($Check) {
        $config = Join-Path $env:USERPROFILE '.config\literature-to-zotero\python-path'
        $runtime = $pythonPath
        if (Test-Path -LiteralPath $config) { $runtime = (Get-Content -LiteralPath $config -Raw -Encoding UTF8).Trim() }
        $checkArgs = @((Join-Path $scripts 'configure.py'), '--check')
        if ($Group) { $checkArgs += '--group' }
        & $runtime @checkArgs | Out-Host
        exit $LASTEXITCODE
    }
    $result = Start-Wizard
    exit $result
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
