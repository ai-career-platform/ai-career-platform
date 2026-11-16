<#
.SYNOPSIS
  Service-like foreground host for the local crawler PostgreSQL (Task Scheduler action).

  Runs postgres.exe in the foreground and stays alive while it runs:
  * duplicate start  -> a cross-session mutex (Global\AICP-PG-Supervisor-<port>) and a live
                        postmaster.pid check; a second supervisor or an already running server exits 0
                        with ALREADY_RUNNING and starts nothing.
  * clean stop       -> `stop-local-postgres.ps1` (pg_ctl stop -m fast) makes postgres exit 0; the
                        supervisor then exits 0 (STOPPED) and does not restart.
  * crash            -> non-zero exit is logged (CRASH) and postgres is restarted with backoff
                        (WAL crash recovery); more than -MaxCrashes within -WindowMinutes -> GAVE_UP, exit 1.
  * logs             -> <AICP_DATA_ROOT>\logs\postgres-supervisor.jsonl (events) and
                        <AICP_DATA_ROOT>\logs\postgres\postgres-*.log (server stderr per start).
  Never initializes, deletes or rewrites the data directory. No passwords are involved.
#>
[CmdletBinding()] param([int]$MaxCrashes = 5, [int]$WindowMinutes = 60)
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
$ErrorActionPreference = 'Continue'
$events = Join-Path $LogRoot 'postgres-supervisor.jsonl'
$serverLogs = Join-Path $LogRoot 'postgres'; New-Item -ItemType Directory -Path $serverLogs -Force | Out-Null
$session = (Get-Process -Id $PID).SessionId
function Log([string]$Event, [hashtable]$Extra = @{}) {
    $o = [ordered]@{ at = (Get-Date).ToString('o'); event = $Event; supervisor_pid = $PID; session = $session; user = $env:USERNAME; port = $PgPort }
    foreach ($k in $Extra.Keys) { $o[$k] = $Extra[$k] }
    Add-Content -Path $events -Value ($o | ConvertTo-Json -Compress) -Encoding utf8
}
function Test-PostmasterAlive {
    $pidFile = Join-Path $PgData 'postmaster.pid'
    if (-not (Test-Path $pidFile)) { return $false }
    $pmPid = [int]((Get-Content $pidFile -TotalCount 1).Trim())
    $p = Get-Process -Id $pmPid -ErrorAction SilentlyContinue
    return [bool]($p -and $p.ProcessName -eq 'postgres')
}

if (-not (Test-Path (Join-Path $PgData 'PG_VERSION'))) { Log 'REFUSED' @{ reason = 'DATA_DIRECTORY_MISSING' }; exit 2 }
$mutex = New-Object Threading.Mutex($false, "Global\AICP-PG-Supervisor-$PgPort")
$owned = $false
try { $owned = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned = $true; Log 'RECOVERED_ABANDONED_SUPERVISOR_LOCK' }
if (-not $owned) { Log 'ALREADY_RUNNING' @{ reason = 'ANOTHER_SUPERVISOR' }; exit 0 }
try {
    if (Test-PostmasterAlive) { Log 'ALREADY_RUNNING' @{ reason = 'POSTMASTER_ALIVE_NOT_SUPERVISED' }; exit 0 }
    $crashes = [System.Collections.Generic.List[datetime]]::new()
    while ($true) {
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $err = Join-Path $serverLogs "postgres-$stamp.log"
        $p = Start-Process -FilePath (Join-Path $PgBin 'postgres.exe') -ArgumentList @('-D', "`"$PgData`"") `
            -NoNewWindow -PassThru -RedirectStandardError $err -RedirectStandardOutput (Join-Path $serverLogs "postgres-$stamp.out")
        $null = $p.Handle   # keep a handle so ExitCode is available after exit (PowerShell 5.1)
        Log 'STARTED' @{ postmaster_pid = $p.Id; server_log = $err }
        $p.WaitForExit()
        $code = $p.ExitCode
        if ($code -eq 0) { Log 'STOPPED' @{ exit_code = 0 }; exit 0 }
        $now = Get-Date; $crashes.Add($now)
        $recent = @($crashes | Where-Object { $_ -gt $now.AddMinutes(-$WindowMinutes) })
        Log 'CRASH' @{ exit_code = $code; crashes_in_window = $recent.Count }
        if ($recent.Count -gt $MaxCrashes) { Log 'GAVE_UP' @{ reason = 'TOO_MANY_CRASHES'; crashes_in_window = $recent.Count }; exit 1 }
        Start-Sleep -Seconds ([Math]::Min(60, 5 * $recent.Count))
        if (Test-PostmasterAlive) { Log 'ALREADY_RUNNING' @{ reason = 'POSTMASTER_ALIVE_AFTER_CRASH' }; exit 0 }
    }
} finally {
    if ($owned) { try { $mutex.ReleaseMutex() } catch {} }
    $mutex.Dispose()
}
