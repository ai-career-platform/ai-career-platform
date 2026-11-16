<#
.SYNOPSIS  Start (if not running) the isolated local crawler PostgreSQL. No admin rights needed.

  * Already running (live postmaster.pid)      -> nothing is started.
  * Task 'AICP-LocalPostgres' registered       -> start it (supervised foreground host,
                                                  run-postgres-supervised.ps1) and wait for pg_isready.
  * Otherwise                                  -> pg_ctl start in its own hidden console.
#>
[CmdletBinding()] param([int]$WaitSeconds = 60)
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
$null = & "$PgBin\pg_ctl.exe" status -D $PgData
if ($LASTEXITCODE -eq 0) { Write-Host '[start-local-postgres] already running'; return }
if (-not (Test-Path $LogRoot)) { New-Item -ItemType Directory -Path $LogRoot | Out-Null }
# The task hosts the default cluster only; overridden data roots (disposable clusters) use pg_ctl.
$task = if (-not $env:AICP_DATA_ROOT) { Get-ScheduledTask -TaskName 'AICP-LocalPostgres' -ErrorAction SilentlyContinue }
if ($task -and $task.State -ne 'Disabled') {
    if ($task.State -ne 'Running') { Start-ScheduledTask -TaskName 'AICP-LocalPostgres' }
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    do { Start-Sleep -Milliseconds 500; $null = & "$PgBin\pg_isready.exe" -q -h 127.0.0.1 -p $PgPort } while ($LASTEXITCODE -ne 0 -and (Get-Date) -lt $deadline)
    if ($LASTEXITCODE -ne 0) { throw 'AICP-LocalPostgres task did not make the server ready; see logs\postgres-supervisor.jsonl' }
    Write-Host '[start-local-postgres] started via task AICP-LocalPostgres'; return
}
# The postmaster must not inherit this shell's console or stdout/stderr pipes: callers that pipe our
# output (or a closing parent console) would otherwise hang or kill new backends (0xC0000142).
# ShellExecute + hidden cmd window gives pg_ctl/postgres their own console and file-only handles.
$startOut = Join-Path $LogRoot 'pg_ctl_start.out'
$psi = New-Object Diagnostics.ProcessStartInfo "$env:SystemRoot\System32\cmd.exe"
$psi.Arguments = "/d /c `"`"$PgBin\pg_ctl.exe`" start -D `"$PgData`" -w -t 60 -l `"$(Join-Path $LogRoot 'pg_ctl.log')`" > `"$startOut`" 2>&1 < NUL`""
$psi.UseShellExecute = $true; $psi.WindowStyle = 'Hidden'
$p = [Diagnostics.Process]::Start($psi); $p.WaitForExit()
Get-Content $startOut -ErrorAction SilentlyContinue | Out-Host
if ($p.ExitCode -ne 0) { throw 'pg_ctl start failed; see logs' }
& "$PgBin\pg_isready.exe" -h 127.0.0.1 -p $PgPort | Out-Host
