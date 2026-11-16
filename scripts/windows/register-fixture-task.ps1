<#
.SYNOPSIS
  Register (or remove) the Windows Task Scheduler jobs for the local PostgreSQL host and the
  FIXTURE-only crawler cycle. LIVE is never registered by this script.

  .\scripts\windows\register-fixture-task.ps1 -IntervalMinutes 5 -ValidHours 24            # logged-on mode
  .\scripts\windows\register-fixture-task.ps1 -Unattended -IntervalMinutes 5 -ValidHours 24 # ELEVATED only
  .\scripts\windows\register-fixture-task.ps1 -Unregister

  Tasks:
    AICP-LocalPostgres     run-postgres-supervised.ps1 (foreground host, crash restart, no time limit)
                           logged-on mode: at logon of this user | -Unattended: at system startup
    AICP-Crawler-Fixture   scheduled-fixture-run.ps1 every N minutes until the approval expires

  Logon types:
    default      Interactive - runs only while this user is logged on; no admin needed.
    -Unattended  S4U ("Run whether user is logged on or not" + "Do not store password") as this
                 same user, limited rights. No password is stored; S4U has no network credentials.
                 Windows only lets an ELEVATED (administrator) PowerShell register S4U and
                 at-startup tasks - the script refuses early otherwise (nothing is bypassed).
  Overlap protection: MultipleInstances=IgnoreNew + named Global\ mutexes inside both scripts.
  Expiry: <AICP_DATA_ROOT>\scheduler\fixture-task.json (mode=fixture, expires_at) = trigger EndBoundary;
  the fixture script also disables its own task when the approval is missing or expired.
#>
[CmdletBinding()] param(
    [int]$IntervalMinutes = 5,
    [double]$ValidHours = 24,
    [switch]$Unattended,
    [switch]$Unregister
)
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
$ErrorActionPreference = 'Stop'
$fixtureTask = 'AICP-Crawler-Fixture'; $pgTask = 'AICP-LocalPostgres'; $legacyPgTask = 'AICP-LocalPostgres-AtLogon'
if ($Unregister) {
    foreach ($t in $fixtureTask, $pgTask, $legacyPgTask) { Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue }
    Write-Host '[register-fixture-task] removed'; return
}
$elevated = (New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($Unattended -and -not $elevated) {
    throw 'BLOCKED: -Unattended (S4U + at-startup) must be run from an elevated PowerShell (Run as administrator). Nothing was changed.'
}
$ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$user = "$env:USERDOMAIN\$env:USERNAME"
$logonType = if ($Unattended) { 'S4U' } else { 'Interactive' }
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType $logonType -RunLevel Limited

# --- PostgreSQL host -----------------------------------------------------------------------
$pgTrigger = if ($Unattended) { New-ScheduledTaskTrigger -AtStartup } else { New-ScheduledTaskTrigger -AtLogOn -User $user }
$pgSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Hidden
$pgAction = New-ScheduledTaskAction -Execute $ps -WorkingDirectory $RepoRoot `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $PSScriptRoot 'run-postgres-supervised.ps1')`""
Register-ScheduledTask -TaskName $pgTask -Description "Local crawler PostgreSQL 127.0.0.1:$PgPort, supervised foreground host ($logonType). scripts/windows/register-fixture-task.ps1" `
    -Action $pgAction -Trigger $pgTrigger -Principal $principal -Settings $pgSettings -Force | Out-Null
Unregister-ScheduledTask -TaskName $legacyPgTask -Confirm:$false -ErrorAction SilentlyContinue

# --- FIXTURE crawler cycle -----------------------------------------------------------------
$expires = (Get-Date).AddHours($ValidHours)
New-Item -ItemType Directory -Path (Join-Path $DataRoot 'scheduler') -Force | Out-Null
[ordered]@{ mode = 'fixture'; approved_for = 'local Windows fixture scheduler only (no LIVE, no GCP, no Slack)'
            logon_type = $logonType; registered_at = (Get-Date).ToString('o'); expires_at = $expires.ToString('o') } |
    ConvertTo-Json | Set-Content -Path (Join-Path $DataRoot 'scheduler\fixture-task.json') -Encoding utf8
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Hidden
$action = New-ScheduledTaskAction -Execute $ps -WorkingDirectory $RepoRoot `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $PSScriptRoot 'scheduled-fixture-run.ps1')`" -TaskName $fixtureTask"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Hours $ValidHours)
$trigger.EndBoundary = $expires.ToString('s')
Register-ScheduledTask -TaskName $fixtureTask -Description "AI Career crawler FIXTURE-only local cycle (no LIVE, $logonType). scripts/windows/register-fixture-task.ps1" `
    -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "[register-fixture-task] registered $pgTask and $fixtureTask ($logonType, every $IntervalMinutes min, expires $($expires.ToString('s')))"
