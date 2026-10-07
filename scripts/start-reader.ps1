param([string]$PythonPath = '')
if (-not $PythonPath) { $PythonPath = (Get-Command python.exe -ErrorAction Stop).Source }
& (Join-Path $PSScriptRoot 'run-daily.ps1') -PythonPath $PythonPath -ReadOnly
& $PythonPath -m morningpaper open
