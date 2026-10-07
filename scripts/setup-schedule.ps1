param([string]$PythonPath = '', [string]$Time = '08:30')
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) { $PythonPath = (Get-Command python.exe -ErrorAction Stop).Source }
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Python executable not found' }
if ((Get-TimeZone).Id -ne 'China Standard Time') { throw 'This schedule expects Asia/Shanghai; check the Windows time zone first.' }
$runnerPath = Join-Path $PSScriptRoot 'run-daily.ps1'
$powershellPath = (Get-Command powershell.exe).Source
$taskArguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $runnerPath + '" -PythonPath "' + $PythonPath + '"'
$action = New-ScheduledTaskAction -Execute $powershellPath -Argument $taskArguments -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 35) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$name = 'Skills Morning Brief - Daily'
$description = 'Skills Morning Brief public GitHub monitor: ' + [System.IO.Path]::GetFullPath($runnerPath)
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing -and $existing.Description -ne $description) { throw 'A different task uses this name; refusing to replace it.' }
Register-ScheduledTask -TaskName $name -Description $description -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
# Replace only this project's legacy task after the new task is registered successfully.
$legacy = Get-ScheduledTask -TaskName 'Agent Morning Paper - Daily' -ErrorAction SilentlyContinue
if ($legacy -and $legacy.Actions.Arguments.Contains($runnerPath)) {
    Unregister-ScheduledTask -TaskName $legacy.TaskName -Confirm:$false
}
Get-ScheduledTask -TaskName $name | Select-Object TaskName,State
Get-ScheduledTaskInfo -TaskName $name | Select-Object NextRunTime,LastTaskResult
