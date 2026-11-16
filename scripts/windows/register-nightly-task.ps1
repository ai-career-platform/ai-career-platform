<#
.SYNOPSIS
  Register (or remove) the Windows task AICP-JobKorea-Nightly: daily 21:00 KST, hard stop by Task Scheduler at
  08:15 (11 h 15 min limit; the crawler itself stops requesting at 08:00).

  .\scripts\windows\register-nightly-task.ps1              # register/update, left DISABLED (default)
  .\scripts\windows\register-nightly-task.ps1 -Enable      # register/update and enable (PM decision)
  .\scripts\windows\register-nightly-task.ps1 -Unregister

  * Never duplicates: Register-ScheduledTask -Force updates the one task of that name.
  * Logon: Interactive (this user, no stored password) - runs only while the user is logged on. Unattended
    (S4U, logged off / after reboot without logon) needs an elevated shell, see register-fixture-task.ps1.
  * MultipleInstances=IgnoreNew, StartWhenAvailable (a 21:00 missed while asleep starts later; the script
    still refuses outside 21:00-08:00), no wake-from-sleep (power policy unchanged).
  * Creates <AICP_DATA_ROOT>\scheduler\nightly-task.json with mode=test if it does not exist yet.
#>
[CmdletBinding()] param([switch]$Enable, [switch]$Unregister)
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
$ErrorActionPreference = 'Stop'
$name = 'AICP-JobKorea-Nightly'
if ($Unregister) { Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue; Write-Host "[register-nightly-task] removed $name"; return }
if ((Get-TimeZone).Id -ne 'Korea Standard Time') { throw "BLOCKED: PC time zone is $((Get-TimeZone).Id); the 21:00 trigger is local time and must be KST." }
$stateDir = Join-Path $DataRoot 'scheduler'; New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$cfgPath = Join-Path $stateDir 'nightly-task.json'
if (-not (Test-Path $cfgPath)) {
    [ordered]@{ mode = 'test'; live_activated = $false; policy_file = $null; night_config = $null; slack = $false
                note = 'LIVE needs PM activation and a valid T61 harvest approval; see crawler/jobs/nightly.py' } |
        ConvertTo-Json | Set-Content -Path $cfgPath -Encoding utf8
}
$ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$user = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$trigger = New-ScheduledTaskTrigger -Daily -At '21:00'
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 11 -Minutes 15) `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$action = New-ScheduledTaskAction -Execute $ps -WorkingDirectory $RepoRoot `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $PSScriptRoot 'nightly-jobkorea.ps1')`""
Register-ScheduledTask -TaskName $name -Description 'AI Career JobKorea nightly harvest 21:00-08:00 KST (mode from nightly-task.json; LIVE needs PM activation + T61 approval). scripts/windows/register-nightly-task.ps1' `
    -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
if ($Enable) { Enable-ScheduledTask -TaskName $name | Out-Null } else { Disable-ScheduledTask -TaskName $name | Out-Null }
$t = Get-ScheduledTask -TaskName $name
Write-Host "[register-nightly-task] $name state=$($t.State) trigger=daily 21:00 limit=11h15m logon=Interactive"
