param([string]$PythonPath = '', [switch]$ReadOnly)
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) { $PythonPath = (Get-Command python.exe -ErrorAction Stop).Source }
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$runtimeDirectory = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Force -Path $runtimeDirectory | Out-Null
if (-not $ReadOnly) {
    $logPath = Join-Path $runtimeDirectory ('daily-' + (Get-Date -Format 'yyyy-MM-dd') + '.log')
    & $PythonPath -m morningpaper refresh *>> $logPath
    $taskExitCode = $LASTEXITCODE
    if ($taskExitCode -ne 0) { exit $taskExitCode }
}
& $PythonPath -m morningpaper reader-start
exit $LASTEXITCODE
