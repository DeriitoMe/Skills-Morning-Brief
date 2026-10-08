param([string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) { $PythonPath = (Get-Command python.exe -ErrorAction Stop).Source }
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$runtimeDirectory = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Force -Path $runtimeDirectory | Out-Null
$logPath = Join-Path $runtimeDirectory ('tibo-' + (Get-Date -Format 'yyyy-MM-dd') + '.log')
& $PythonPath -m morningpaper tibo-monitor *>> $logPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $PythonPath -m morningpaper reader-start
exit $LASTEXITCODE
