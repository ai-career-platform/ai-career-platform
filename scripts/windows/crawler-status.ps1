<#
.SYNOPSIS
  Local operations status report for the Windows crawler PC (no Slack, no network).

  .\scripts\windows\crawler-status.ps1            # print + write JSON
  .\scripts\windows\crawler-status.ps1 -Quiet     # write JSON only (called after every fixture run)

  Output: <AICP_DATA_ROOT>\status\crawler-status.json with tasks, PostgreSQL, DB connectivity,
  recent runs (inserted/updated/duplicates/failed), warning/error event types (skip reasons),
  night outcomes, LIVE flags, disk usage, log sizes and the last scheduler error. `health` is OK only
  if PostgreSQL is reachable, the last fixture cycle did not fail and no LIVE schedule/run exists.
#>
[CmdletBinding()] param([switch]$Quiet)
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
$ErrorActionPreference = 'Continue'
Set-Location $RepoRoot
$report = [ordered]@{ generated_at = (Get-Date).ToString('o'); host = $env:COMPUTERNAME }

$report.tasks = @(Get-ScheduledTask -TaskName 'AICP-*' -ErrorAction SilentlyContinue | ForEach-Object {
    $i = Get-ScheduledTaskInfo -TaskName $_.TaskName -ErrorAction SilentlyContinue
    [ordered]@{ name = $_.TaskName; state = "$($_.State)"; logon_type = "$($_.Principal.LogonType)"; run_level = "$($_.Principal.RunLevel)"
                last_run = $(if ($i.LastRunTime.Year -gt 2000) { $i.LastRunTime.ToString('o') }); last_result = $i.LastTaskResult
                next_run = $(if ($i.NextRunTime -is [datetime]) { $i.NextRunTime.ToString('o') } else { $null }); missed_runs = $i.NumberOfMissedRuns } })

$null = & "$PgBin\pg_ctl.exe" status -D $PgData; $pgRunning = ($LASTEXITCODE -eq 0)
$null = & "$PgBin\pg_isready.exe" -q -h 127.0.0.1 -p $PgPort; $pgReady = ($LASTEXITCODE -eq 0)
$pidFile = Join-Path $PgData 'postmaster.pid'
$pm = if ($pgRunning -and (Test-Path $pidFile)) { Get-Process -Id ([int]((Get-Content $pidFile -TotalCount 1).Trim())) -ErrorAction SilentlyContinue }
$supLog = Join-Path $LogRoot 'postgres-supervisor.jsonl'
$report.postgres = [ordered]@{ port = $PgPort; running = $pgRunning; accepting_connections = $pgReady
    postmaster_pid = $pm.Id; postmaster_session = $pm.SessionId; postmaster_started = $(if ($pm) { $pm.StartTime.ToString('o') })
    supervisor_last_event = $(if (Test-Path $supLog) { Get-Content $supLog -Tail 1 | ConvertFrom-Json }) }

$dbOut = Join-Path $env:TEMP "aicp-status-$PID.json"
& cmd /d /c "`"$VenvPy`" `"$(Join-Path $PSScriptRoot 'verify_local_db.py')`" --status > `"$dbOut`" 2>&1"
$report.db_connection = if ($LASTEXITCODE -eq 0) { 'OK' } else { 'FAILED' }
$report.db = if ($LASTEXITCODE -eq 0) { Get-Content $dbOut -Raw -Encoding utf8 | ConvertFrom-Json } else { [ordered]@{ error = ((Get-Content $dbOut -Tail 1) -replace 'postgresql://\S+', '<dsn>') } }
Remove-Item $dbOut -ErrorAction SilentlyContinue

$schedLogs = Get-ChildItem (Join-Path $LogRoot 'scheduler') -Filter 'fixture-*.jsonl' -ErrorAction SilentlyContinue | Sort-Object Name
$entries = @($schedLogs | Select-Object -Last 2 | ForEach-Object { Get-Content $_.FullName } | ForEach-Object { $_ | ConvertFrom-Json })
$last = $entries | Select-Object -Last 1
$lastErr = $entries | Where-Object { $_.status -in 'FAILED', 'REFUSED' } | Select-Object -Last 1
$report.fixture_scheduler = [ordered]@{ last_started_at = $last.started_at; last_status = $last.status; last_exit_code = $last.exit_code
    last_session = $last.session; last_batch_logon = $last.batch_logon; last_egress_attempts = $last.egress_attempts
    last_error = $(if ($lastErr) { [ordered]@{ at = $lastErr.started_at; status = $lastErr.status; reason = $lastErr.reason } }) }

$live = Get-ChildItem env: | Where-Object { $_.Name -match '^(CRAWLER_LIVE_SCHEDULE_APPROVED|CRAWLER_NIGHT_ENABLED|GCP_SYNC_PUBLISH|SLACK_WEBHOOK_URL|SLACK_WEBHOOK_RUL)$' }
$report.live_flags = [ordered]@{ session_env_live_vars = @($live | ForEach-Object { $_.Name })
    live_or_enabled_schedules = @($report.db.schedules | Where-Object { $_.mode -ne 'fixture' -or $_.enabled }).Count
    live_runs_total = $report.db.live_runs_total }

$drive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$((Split-Path $DataRoot -Qualifier))'"
function SizeMB($p) { if (Test-Path $p) { [math]::Round(((Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum) / 1MB, 1) } }
$report.disk = [ordered]@{ drive = $drive.DeviceID; free_gb = [math]::Round($drive.FreeSpace / 1GB, 1); used_percent = [math]::Round(100 - 100 * $drive.FreeSpace / $drive.Size, 1)
    pg_data_mb = $(SizeMB $PgData); logs_mb = $(SizeMB $LogRoot); pg_server_log_mb = $(SizeMB (Join-Path $PgData 'log')) }

$problems = @()
if (-not $pgReady) { $problems += 'POSTGRES_NOT_ACCEPTING' }
if ($report.db_connection -ne 'OK') { $problems += 'DB_CONNECTION_FAILED' }
if ($last.status -in 'FAILED', 'REFUSED') { $problems += "LAST_FIXTURE_$($last.status)" }
if ($report.live_flags.live_or_enabled_schedules -gt 0 -or $report.live_flags.live_runs_total -gt 0 -or $live) { $problems += 'LIVE_PRESENT' }
if ($report.disk.used_percent -gt 90) { $problems += 'DISK_ABOVE_90_PERCENT' }
$report.health = if ($problems) { 'ATTENTION' } else { 'OK' }; $report.problems = $problems

$dir = Join-Path $DataRoot 'status'; New-Item -ItemType Directory -Path $dir -Force | Out-Null
$json = $report | ConvertTo-Json -Depth 8
Set-Content -Path (Join-Path $dir 'crawler-status.json') -Value $json -Encoding utf8
if (-not $Quiet) { $json }
