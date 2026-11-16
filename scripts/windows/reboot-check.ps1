<#
.SYNOPSIS
  Record the crawler PC state before a reboot / logoff and verify it afterwards (no network).

  .\scripts\windows\reboot-check.ps1 -Phase Before     # writes <AICP_DATA_ROOT>\reboot\before.json
  (reboot or log off; wait at least one fixture interval; log back on)
  .\scripts\windows\reboot-check.ps1 -Phase After      # writes after.json and prints PASS/FAIL per check

  After-checks: PostgreSQL started without manual action (postmaster started after boot), DB connects,
  postings md5/row counts preserved (counts may only grow), fixture cycles ran after the boot with
  egress 0 (and, for an unattended install, in a non-interactive BATCH logon), no overlapping runs,
  no LIVE schedule/run, LIVE env vars absent.
#>
[CmdletBinding()] param([Parameter(Mandatory)][ValidateSet('Before','After')] [string]$Phase)
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
$ErrorActionPreference = 'Continue'
Set-Location $RepoRoot
$dir = Join-Path $DataRoot 'reboot'; New-Item -ItemType Directory -Path $dir -Force | Out-Null
function Snapshot { $f = Join-Path $env:TEMP "aicp-snap-$PID.json"
    & cmd /d /c "`"$VenvPy`" `"$(Join-Path $PSScriptRoot 'verify_local_db.py')`" --snapshot > `"$f`" 2> `"$f.err`""
    $ok = $LASTEXITCODE -eq 0; $o = if ($ok) { Get-Content $f -Raw | ConvertFrom-Json }; Remove-Item $f, "$f.err" -ErrorAction SilentlyContinue; $o }
& (Join-Path $PSScriptRoot 'crawler-status.ps1') -Quiet
$status = Get-Content (Join-Path $DataRoot 'status\crawler-status.json') -Raw | ConvertFrom-Json
$state = [ordered]@{ phase = $Phase; at = (Get-Date).ToString('o'); last_boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o')
    git_head = (git rev-parse --short HEAD); git_branch = (git branch --show-current); snapshot = Snapshot
    tasks = $status.tasks; postgres = $status.postgres; fixture_scheduler = $status.fixture_scheduler; live_flags = $status.live_flags
    disk = $status.disk; runs_currently_running = $status.db.runs_currently_running; data_dir = $PgData }
$state | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $dir "$($Phase.ToLower()).json") -Encoding utf8
if ($Phase -eq 'Before') { Write-Host "[reboot-check] recorded $dir\before.json (boot $($state.last_boot))"; return }

$before = Get-Content (Join-Path $dir 'before.json') -Raw | ConvertFrom-Json
$boot = [datetimeoffset]::Parse($state.last_boot)
$log = Join-Path $LogRoot 'scheduler'
$since = @(Get-ChildItem $log -Filter 'fixture-*.jsonl' | ForEach-Object { Get-Content $_.FullName } | ForEach-Object { $_ | ConvertFrom-Json } |
    Where-Object { [datetimeoffset]::Parse($_.started_at) -gt $boot })
$cycles = @($since | Where-Object { $_.status -eq 'SUCCEEDED' })
$pmStart = if ($state.postgres.postmaster_started) { [datetimeoffset]::Parse($state.postgres.postmaster_started) }
$checks = [ordered]@{
    rebooted_since_before          = ($boot -gt [datetimeoffset]::Parse($before.last_boot))
    postgres_autostarted_after_boot = ($state.postgres.accepting_connections -and $pmStart -and $pmStart -gt $boot)
    db_connects                    = ($null -ne $state.snapshot)
    postings_preserved             = ($state.snapshot.row_counts.postings -ge $before.snapshot.row_counts.postings)
    postings_md5_unchanged_if_no_new_rows = (($state.snapshot.row_counts.postings -ne $before.snapshot.row_counts.postings) -or ($state.snapshot.postings_md5 -eq $before.snapshot.postings_md5))
    fixture_cycles_after_boot      = $cycles.Count
    fixture_ran_after_boot         = ($cycles.Count -ge 1)
    fixture_ran_unattended_batch   = [bool]($cycles | Where-Object { $_.batch_logon })
    no_failed_cycles_after_boot    = -not ($since | Where-Object { $_.status -in 'FAILED','REFUSED' })
    egress_zero_after_boot         = -not ($since | Where-Object { $_.egress_attempts -gt 0 })
    no_live                        = ($state.live_flags.live_or_enabled_schedules -eq 0 -and $state.live_flags.live_runs_total -eq 0 -and @($state.live_flags.session_env_live_vars | Where-Object { $_ }).Count -eq 0)
    no_stuck_running_runs          = ($state.runs_currently_running -eq 0)
}
$checks | ConvertTo-Json | Set-Content (Join-Path $dir 'after-checks.json') -Encoding utf8
$checks.GetEnumerator() | ForEach-Object { "{0,-40} {1}" -f $_.Key, $_.Value }
