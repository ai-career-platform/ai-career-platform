<#
.SYNOPSIS
  One scheduled FIXTURE crawler cycle on the Windows PC (Task Scheduler action). Never LIVE.

  Order: safe env -> task approval/expiry (auto-OFF) -> single-instance mutex -> start local PG ->
  refuse if any DB schedule is LIVE/enabled -> `dispatcher dispatch` (same command as the Ubuntu
  systemd unit; expected IDLE + night DISABLED) -> `dispatcher manual-fixture` (one FIXTURE job,
  recorded in crawler_training.runs/run_events) -> JSONL log line.

  * Every Python process (including the dispatcher's worker child) runs with the process-wide
    egress guard (scripts/windows/egress_guard), so any outbound attempt is blocked and counted.
  * Approval file: <AICP_DATA_ROOT>\scheduler\fixture-task.json  {"mode":"fixture","expires_at":"<ISO>"}
    Missing/expired/non-fixture -> the task disables itself (AUTO_OFF) and exits.
  * Log: <AICP_DATA_ROOT>\logs\scheduler\fixture-YYYYMMDD.jsonl (no secrets).
  Exit codes: 0 ok / skipped-locked, 3 auto-off, 4 refused (LIVE present), 1 failure.
#>
[CmdletBinding()] param([string]$TaskName = 'AICP-Crawler-Fixture')
$env:AICP_NO_EGRESS = '1'
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
$ErrorActionPreference = 'Continue'
Set-Location $RepoRoot
$logDir = Join-Path $LogRoot 'scheduler'; New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$runDir = Join-Path $logDir ("run-" + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')); New-Item -ItemType Directory -Path $runDir -Force | Out-Null
$logFile = Join-Path $logDir ("fixture-" + (Get-Date -Format 'yyyyMMdd') + '.jsonl')
$entry = [ordered]@{ started_at = (Get-Date).ToString('o'); task = $TaskName; host = $env:COMPUTERNAME; pid = $PID; run_dir = $runDir }
$env:AICP_EGRESS_LOG = Join-Path $runDir 'egress.jsonl'

function Finish([string]$Status, [int]$Code) {
    $entry.status = $Status; $entry.exit_code = $Code; $entry.ended_at = (Get-Date).ToString('o')
    if (Test-Path $env:AICP_EGRESS_LOG) {
        $e = Get-Content $env:AICP_EGRESS_LOG | ForEach-Object { $_ | ConvertFrom-Json }
        $entry.python_processes = @($e).Count; $entry.egress_attempts = ($e | Measure-Object -Property attempts -Sum).Sum
    } else { $entry.python_processes = 0; $entry.egress_attempts = 0 }
    Add-Content -Path $logFile -Value ($entry | ConvertTo-Json -Compress -Depth 6) -Encoding utf8
    exit $Code
}
function Py([string]$Name, [string[]]$PyArgs) {
    $out = Join-Path $runDir "$Name.out"
    & cmd /d /c "`"$VenvPy`" $($PyArgs -join ' ') > `"$out`" 2>&1"
    $code = $LASTEXITCODE
    $json = Get-Content $out -Encoding utf8 | Where-Object { $_ -match '^\s*[\{\[]' } | Select-Object -Last 1
    $obj = $null; if ($json) { try { $obj = $json | ConvertFrom-Json } catch {} }
    return [pscustomobject]@{ exit = $code; json = $obj; raw = $json }
}

# 1. Task-level approval with expiry -> automatic OFF.
$policyPath = Join-Path $DataRoot 'scheduler\fixture-task.json'
$policy = $null; if (Test-Path $policyPath) { try { $policy = Get-Content $policyPath -Raw | ConvertFrom-Json } catch {} }
$expired = (-not $policy) -or ($policy.mode -ne 'fixture') -or (-not $policy.expires_at) -or ([datetimeoffset]::Parse($policy.expires_at) -le [datetimeoffset]::Now)
if ($expired) {
    try { Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null; $entry.task_disabled = $true } catch { $entry.task_disabled = $false }
    $entry.reason = 'APPROVAL_MISSING_EXPIRED_OR_NOT_FIXTURE'
    Finish 'AUTO_OFF' 3
}
$entry.approval_expires_at = $policy.expires_at

# 2. Single instance (named mutex is released by Windows even if this process crashes).
$mutex = New-Object Threading.Mutex($false, 'Local\AICP-Crawler-Fixture')
$owned = $false
try { $owned = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned = $true; $entry.recovered_abandoned_lock = $true }
if (-not $owned) { $entry.reason = 'ANOTHER_RUN_IN_PROGRESS'; Finish 'SKIPPED_LOCKED' 0 }
try {
    if ($env:AICP_TEST_HOLD_SECONDS) { Start-Sleep -Seconds ([int]$env:AICP_TEST_HOLD_SECONDS) }  # test hook for overlap checks
    try { Assert-CrawlerSafeSession } catch { $entry.reason = 'UNSAFE_ENVIRONMENT'; Finish 'REFUSED' 4 }

    # 3. Local DB.
    try { & (Join-Path $PSScriptRoot 'start-local-postgres.ps1') *> (Join-Path $runDir 'pg-start.out') } catch { $entry.reason = 'POSTGRES_START_FAILED'; Finish 'FAILED' 1 }

    # 4. Refuse if any schedule is LIVE or enabled (LIVE stays OFF until PM approval).
    $s = Py 'schedules' @('-m','crawler.jobs.dispatcher','schedules')
    if ($s.exit -ne 0 -or $null -eq $s.json) { $entry.reason = 'SCHEDULE_READ_FAILED'; Finish 'FAILED' 1 }
    $entry.schedules = @($s.json | ForEach-Object { [ordered]@{ id = $_.schedule_id; mode = $_.mode; enabled = $_.enabled } })
    if (@($s.json | Where-Object { $_.mode -ne 'fixture' -or $_.enabled }).Count -gt 0) { $entry.reason = 'LIVE_OR_ENABLED_SCHEDULE_PRESENT'; Finish 'REFUSED' 4 }

    # 5. Production-equivalent dispatcher tick (systemd ExecStart equivalent).
    $d = Py 'dispatch' @('-m','crawler.jobs.dispatcher','dispatch')
    $entry.dispatch = [ordered]@{ exit = $d.exit; result = $d.json }
    # 6. One FIXTURE job now, recorded as a run.
    $m = Py 'manual-fixture' @('-m','crawler.jobs.dispatcher','manual-fixture')
    $entry.manual_fixture = [ordered]@{ exit = $m.exit; result = $m.json }
    if ($m.json -and $m.json.run_id) {
        $r = Py 'run' @('-m','crawler.jobs.dispatcher','run','--run-id',$m.json.run_id)
        $entry.run_row = @($r.json)[0]
    }
    $ok = ($d.exit -eq 0) -and ($m.exit -eq 0) -and ($m.json.status -eq 'SUCCEEDED')
    if ($ok) { Finish 'SUCCEEDED' 0 } else { $entry.reason = 'DISPATCH_OR_FIXTURE_FAILED'; Finish 'FAILED' 1 }
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
