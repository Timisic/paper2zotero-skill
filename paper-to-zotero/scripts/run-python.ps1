$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PATH = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:PATH
$config = Join-Path $env:USERPROFILE '.config\literature-to-zotero\python-path'
$interpreter = (Get-Content -LiteralPath $config -Raw -Encoding UTF8).Trim()
& $interpreter @args
exit $LASTEXITCODE
