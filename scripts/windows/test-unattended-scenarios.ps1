<#
.SYNOPSIS
  Fixture-only unattended-safety scenarios on THIS PC (no LIVE, no external HTTP).

  .\scripts\windows\test-unattended-scenarios.ps1

  Uses the real scheduled-fixture-run.ps1, the real AICP-LocalPostgres task and the local DB.
  The AICP-Crawler-Fixture task is disabled while the scenarios run and its previous state is
  restored at the end. Scenario 9b temporarily marks the DB schedule enabled (mode stays fixture)
  and restores it. Evidence: <AICP_DATA_ROOT>\logs\scenarios-<stamp>\scenarios.json
#>
[CmdletBinding()] param()
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
$ErrorActionPreference = 'Continue'
Set-Location $RepoRoot
$out = Join-Path $LogRoot ("scenarios-" + (Get-Date -Format 'yyyyMMdd-HHmmss')); New-Item -ItemType Directory -Path $out -Force | Out-Null
$runScript = Join-Path $PSScriptRoot 'scheduled-fixture-run.ps1'
$ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$results = [ordered]@{}
$fixtureTask = Get-ScheduledTask -TaskName 'AICP-Crawler-Fixture' -ErrorAction SilentlyContinue
$restoreTaskEnabled = $fixtureTask -and $fixtureTask.State -ne 'Disabled'
if ($fixtureTask) { Disable-ScheduledTask -TaskName 'AICP-Crawler-Fixture' | Out-Null }

function Entry-For([int]$ProcId) {
    $f = Join-Path $LogRoot ("scheduler\fixture-" + (Get-Date -Format 'yyyyMMdd') + '.jsonl')
    Get-Content $f | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.pid -eq $ProcId } | Select-Object -Last 1
}
function Start-Fixture([string]$Extra = '', [switch]$NoWait) {
    $p = Start-Process $ps -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runScript`" $Extra" -WindowStyle Hidden -PassThru
    if ($NoWait) { return $p }
    $p.WaitForExit(); $e = Entry-For $p.Id
    return [ordered]@{ exit = $p.ExitCode; status = $e.status; reason = $e.reason; run_id = $e.manual_fixture.result.run_id
        dispatch = $e.dispatch.result.status; night = $e.dispatch.result.night.night; slack = $e.manual_fixture.result.slack
        recovered_abandoned_lock = [bool]$e.recovered_abandoned_lock; python_processes = $e.python_processes; egress = $e.egress_attempts }
}
function Snapshot { $f = Join-Path $out "snap-$(Get-Random).json"; & cmd /d /c "`"$VenvPy`" `"$(Join-Path $PSScriptRoot 'verify_local_db.py')`" --snapshot > `"$f`" 2>&1"; Get-Content $f -Raw | ConvertFrom-Json }
function PyJson([string[]]$a) { $f = Join-Path $out "py-$(Get-Random).out"; & cmd /d /c "`"$VenvPy`" $($a -join ' ') > `"$f`" 2>&1"; $code = $LASTEXITCODE
    $lines = @(Get-Content $f -Encoding utf8 | Where-Object { $_ -notmatch '^EGRESS_ATTEMPTS=' })
    $obj = $null
    try { $obj = ($lines -join "`n") | ConvertFrom-Json } catch {                     # multi-line JSON document
        $j = $lines | Where-Object { $_ -match '^\s*[\{\[]' } | Select-Object -Last 1  # or one JSON line among other output
        if ($j) { try { $obj = $j | ConvertFrom-Json } catch {} } }
    [pscustomobject]@{ exit = $code; json = $obj } }

try {
    # 1. normal run
    $results['01_normal_run'] = Start-Fixture
    # 2. overlap: holder keeps the mutex for 25 s, second run must be refused
    $env:AICP_TEST_HOLD_SECONDS = '25'; $holder = Start-Fixture -NoWait; Remove-Item env:AICP_TEST_HOLD_SECONDS; Start-Sleep 4
    $second = Start-Fixture; $holder.WaitForExit()
    $results['02_overlap'] = [ordered]@{ second = $second; holder = [ordered]@{ exit = $holder.ExitCode; status = (Entry-For $holder.Id).status } }
    # 3. DB connection failure (unreachable port)
    $results['03_db_connection_failure'] = Start-Fixture '-PgPortOverride 5499'
    # 4. DB down -> run recovers it via the AICP-LocalPostgres task; data preserved
    $before = Snapshot
    & (Join-Path $PSScriptRoot 'stop-local-postgres.ps1') *> (Join-Path $out 'pg-stop.out')
    $null = & "$PgBin\pg_isready.exe" -q -h 127.0.0.1 -p $PgPort; $downCode = $LASTEXITCODE
    Start-Sleep 2; $taskAfterStop = (Get-ScheduledTask -TaskName 'AICP-LocalPostgres' -ErrorAction SilentlyContinue).State
    $rec = Start-Fixture; $after = Snapshot
    $results['04_db_recovery'] = [ordered]@{ pg_isready_while_down = $downCode; pg_task_state_after_clean_stop = "$taskAfterStop"; run = $rec
        pg_task_state_after_recovery = "$((Get-ScheduledTask -TaskName 'AICP-LocalPostgres' -ErrorAction SilentlyContinue).State)"
        postings_md5_same = ($before.postings_md5 -eq $after.postings_md5); postings = "$($before.row_counts.postings)->$($after.row_counts.postings)"
        runs = "$($before.row_counts.runs)->$($after.row_counts.runs)"; postmaster_restarted = ($before.postmaster_started_at -ne $after.postmaster_started_at) }
    # 5/6. crawler cycle killed mid-run (abnormal termination) -> next run recovers the abandoned lock
    $env:AICP_TEST_HOLD_SECONDS = '60'; $victim = Start-Fixture -NoWait; Remove-Item env:AICP_TEST_HOLD_SECONDS; Start-Sleep 4
    Stop-Process -Id $victim.Id -Force; $victim.WaitForExit()
    $results['05_killed_mid_run'] = [ordered]@{ killed_exit = $victim.ExitCode; killed_wrote_log_entry = [bool](Entry-For $victim.Id); next_run = (Start-Fixture)
        running_runs_left = (PyJson @("`"$(Join-Path $PSScriptRoot 'verify_local_db.py')`"", '--status')).json.runs_currently_running }
    # 7. Windows Task failure recorded by Task Scheduler (temporary task, removed afterwards)
    $tmp = 'AICP-Scenario-FailProbe'
    $act = New-ScheduledTaskAction -Execute $ps -WorkingDirectory $RepoRoot -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runScript`" -TaskName $tmp -PgPortOverride 5499"
    Register-ScheduledTask -TaskName $tmp -Action $act -Principal (New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited) `
        -Settings (New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -Hidden) -Force | Out-Null
    Start-ScheduledTask -TaskName $tmp; $i = 0; do { Start-Sleep 2; $i++ } while ((Get-ScheduledTask -TaskName $tmp).State -eq 'Running' -and $i -lt 60)
    $info = Get-ScheduledTaskInfo -TaskName $tmp
    $results['07_task_failure'] = [ordered]@{ task_last_result = $info.LastTaskResult; task_state = "$((Get-ScheduledTask -TaskName $tmp).State)" }
    Unregister-ScheduledTask -TaskName $tmp -Confirm:$false
    # 9a. feature flags forced ON in the parent environment are stripped -> night DISABLED, Slack off
    $env:CRAWLER_NIGHT_ENABLED = '1'; $env:CRAWLER_LIVE_SCHEDULE_APPROVED = '1'; $env:SLACK_WEBHOOK_URL = 'https://hooks.slack.com/services/TFAKE/BFAKE/fake'
    $results['09a_flags_injected_are_stripped'] = Start-Fixture
    Remove-Item env:CRAWLER_NIGHT_ENABLED, env:CRAWLER_LIVE_SCHEDULE_APPROVED, env:SLACK_WEBHOOK_URL
    # 9b. an ENABLED DB schedule (still mode=fixture) makes the unattended cycle refuse to run
    $sched = @((PyJson @('-m', 'crawler.jobs.dispatcher', 'schedules')).json)[0]
    $origTime = ([string]$sched.local_time).Substring(0, 5)
    $cfgOn = PyJson @('-m', 'crawler.jobs.dispatcher', 'configure', '--enabled', '--mode', 'fixture', '--time', $origTime)
    $refused = Start-Fixture
    $cfgOff = PyJson @('-m', 'crawler.jobs.dispatcher', 'configure', '--mode', 'fixture', '--time', $origTime)
    $restored = @((PyJson @('-m', 'crawler.jobs.dispatcher', 'schedules')).json)[0]
    $results['09b_enabled_schedule_refused'] = [ordered]@{ configure_enabled_exit = $cfgOn.exit; run = $refused; restore_exit = $cfgOff.exit
        restored = [ordered]@{ enabled = $restored.enabled; mode = $restored.mode; local_time = $restored.local_time } }
    # 8. approval expired -> AUTO_OFF (scheduler task itself verified separately)
    $policyPath = Join-Path $DataRoot 'scheduler\fixture-task.json'; $policyBackup = Get-Content $policyPath -Raw
    $p = $policyBackup | ConvertFrom-Json; $p.expires_at = (Get-Date).AddMinutes(-1).ToString('o'); $p | ConvertTo-Json | Set-Content $policyPath -Encoding utf8
    $results['08_approval_expired'] = Start-Fixture
    Set-Content -Path $policyPath -Value $policyBackup -Encoding utf8 -NoNewline
    # 11/12. logs + re-query of a recorded run
    $rid = $results['01_normal_run'].run_id
    $row = @((PyJson @('-m', 'crawler.jobs.dispatcher', 'run', '--run-id', $rid)).json)[0]
    $ev = @((PyJson @('-m', 'crawler.jobs.dispatcher', 'events', '--run-id', $rid)).json)
    $results['12_requery_run'] = [ordered]@{ run_id = $rid; status = $row.status; mode = $row.mode; fetched = $row.fetched_count; duplicates = $row.duplicate_count
        events = @($ev | ForEach-Object { "$($_.level):$($_.event_type)" }) }
} finally {
    if ($restoreTaskEnabled) { Enable-ScheduledTask -TaskName 'AICP-Crawler-Fixture' | Out-Null }
    $results['task_restored_to'] = "$((Get-ScheduledTask -TaskName 'AICP-Crawler-Fixture' -ErrorAction SilentlyContinue).State)"
    $results | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $out 'scenarios.json') -Encoding utf8
    Write-Host "[test-unattended-scenarios] evidence: $out\scenarios.json"
}
