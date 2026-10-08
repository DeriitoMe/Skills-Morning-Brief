param([string]$PythonPath = '', [string]$Time = '20:30')
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) { $PythonPath = (Get-Command python.exe -ErrorAction Stop).Source }
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Python executable not found' }
if ((Get-TimeZone).Id -ne 'China Standard Time') { throw 'This schedule expects Asia/Shanghai.' }
$runnerPath = Join-Path $PSScriptRoot 'run-tibo.ps1'
$taskArguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $runnerPath + '" -PythonPath "' + $PythonPath + '"'
$action = New-ScheduledTaskAction -Execute (Get-Command powershell.exe).Source -Argument $taskArguments -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$name = 'Skills Morning Brief - Tibo Evening'
$description = 'Skills Morning Brief evening quota-reset monitor: ' + [System.IO.Path]::GetFullPath($runnerPath)
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing -and $existing.Description -ne $description) { throw 'A different task uses this name; refusing to replace it.' }
Register-ScheduledTask -TaskName $name -Description $description -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At $Time) -Settings $settings -Principal $principal -Force | Out-Null
Get-ScheduledTask -TaskName $name | Select-Object TaskName,State
Get-ScheduledTaskInfo -TaskName $name | Select-Object NextRunTime,LastTaskResult
