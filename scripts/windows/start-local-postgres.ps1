<#
.SYNOPSIS  Start (if not running) the isolated local crawler PostgreSQL. No admin rights needed.
#>
[CmdletBinding()] param()
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
$null = & "$PgBin\pg_ctl.exe" status -D $PgData
if ($LASTEXITCODE -eq 0) { Write-Host '[start-local-postgres] already running'; return }
if (-not (Test-Path $LogRoot)) { New-Item -ItemType Directory -Path $LogRoot | Out-Null }
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
