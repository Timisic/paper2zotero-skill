$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PATH = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:PATH
$config = Join-Path $env:USERPROFILE '.config\literature-to-zotero\python-path'
$interpreter = (Get-Content -LiteralPath $config -Raw -Encoding UTF8).Trim()
$pdfConfig = Join-Path $env:USERPROFILE '.config\literature-to-zotero\pdf-bin'
if (Test-Path -LiteralPath $pdfConfig) {
    $pdfDirectory = (Get-Content -LiteralPath $pdfConfig -Raw -Encoding UTF8).Trim()
    $env:PATH = $pdfDirectory + ';' + $env:PATH
}
& $interpreter @args
exit $LASTEXITCODE
