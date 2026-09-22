$ErrorActionPreference = 'Stop'
function Find-Zotero {
    foreach ($path in @("$env:ProgramFiles\Zotero\zotero.exe", "${env:ProgramFiles(x86)}\Zotero\zotero.exe", "$env:LOCALAPPDATA\Zotero\zotero.exe")) {
        if (Test-Path -LiteralPath $path) { return $path }
    }
    return $null
}
$zotero = Find-Zotero
if (-not $zotero) {
    & winget.exe install --id DigitalScholar.Zotero --exact --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { exit 1 }
    $zotero = Find-Zotero
}
if (-not $zotero) { Write-Error 'Please open Zotero from the Start menu.'; exit 1 }
Start-Process -FilePath $zotero
