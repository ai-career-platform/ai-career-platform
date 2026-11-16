<#
.SYNOPSIS
  Register (or remove) the Windows Task Scheduler jobs for the FIXTURE-only local crawler.

  .\scripts\windows\register-fixture-task.ps1 -IntervalMinutes 5 -ValidHours 24     # register
  .\scripts\windows\register-fixture-task.ps1 -Unregister                           # remove both

  Tasks (current user, "run only when user is logged on", limited rights - no admin needed):
    AICP-Crawler-Fixture        every N minutes until the approval expires -> scheduled-fixture-run.ps1
    AICP-LocalPostgres-AtLogon  at logon of this user -> start-local-postgres.ps1
  Overlap protection: Task Scheduler MultipleInstances=IgnoreNew + a named mutex in the script.
  Expiry: writes <AICP_DATA_ROOT>\scheduler\fixture-task.json (mode=fixture, expires_at) and sets the
  trigger EndBoundary to the same time; the script also disables the task itself when expired.
  LIVE is never registered by this script. Running while logged off needs a stored password or S4U,
  which requires an elevated (administrator) PowerShell - see the verification document.
#>
[CmdletBinding()] param(
    [int]$IntervalMinutes = 5,
    [double]$ValidHours = 24,
    [switch]$Unregister
)
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
$ErrorActionPreference = 'Stop'
$fixtureTask = 'AICP-Crawler-Fixture'; $pgTask = 'AICP-LocalPostgres-AtLogon'
if ($Unregister) {
    foreach ($t in $fixtureTask, $pgTask) { Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue }
    Write-Host '[register-fixture-task] removed'; return
}
$ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$user = "$env:USERDOMAIN\$env:USERNAME"
$expires = (Get-Date).AddHours($ValidHours)
New-Item -ItemType Directory -Path (Join-Path $DataRoot 'scheduler') -Force | Out-Null
[ordered]@{ mode = 'fixture'; approved_for = 'local Windows fixture scheduler only (no LIVE, no GCP, no Slack)'
            registered_at = (Get-Date).ToString('o'); expires_at = $expires.ToString('o') } |
    ConvertTo-Json | Set-Content -Path (Join-Path $DataRoot 'scheduler\fixture-task.json') -Encoding utf8

$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Hidden
$action = New-ScheduledTaskAction -Execute $ps -WorkingDirectory $RepoRoot `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $PSScriptRoot 'scheduled-fixture-run.ps1')`" -TaskName $fixtureTask"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Hours $ValidHours)
$trigger.EndBoundary = $expires.ToString('s')
Register-ScheduledTask -TaskName $fixtureTask -Description 'AI Career crawler FIXTURE-only local cycle (no LIVE). scripts/windows/register-fixture-task.ps1' `
    -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

$pgAction = New-ScheduledTaskAction -Execute $ps -WorkingDirectory $RepoRoot `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $PSScriptRoot 'start-local-postgres.ps1')`""
$pgTrigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$pgSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Hidden
Register-ScheduledTask -TaskName $pgTask -Description 'Start the isolated local crawler PostgreSQL at logon (127.0.0.1 only).' `
    -Action $pgAction -Trigger $pgTrigger -Principal $principal -Settings $pgSettings -Force | Out-Null
Write-Host "[register-fixture-task] registered $fixtureTask (every $IntervalMinutes min, expires $($expires.ToString('s'))) and $pgTask"
