<#
.SYNOPSIS
  One night of the JobKorea harvest (Task Scheduler action of AICP-JobKorea-Nightly, 21:00 KST daily).

  .\scripts\windows\nightly-jobkorea.ps1                    # mode from <AICP_DATA_ROOT>\scheduler\nightly-task.json (default test)
  .\scripts\windows\nightly-jobkorea.ps1 -Mode test         # no external HTTP, no DB writes (window/lock/counter check)

  Config <AICP_DATA_ROOT>\scheduler\nightly-task.json (no secrets):
    { "mode": "test" | "live",
      "live_activated": false,          # PM switch -> CRAWLER_LIVE_SCHEDULE_APPROVED=1 for this process only
      "policy_file": "<private T61 harvest approval JSON>",
      "night_config": "<optional JSON with NightConfig fields>",
      "slack": false }                  # true: SLACK_WEBHOOK_URL / SLACK_WEBHOOK_RUL is read from the repo .env
  LIVE also needs a valid T61 harvest approval; without it crawler.jobs.nightly refuses before any request.
  test mode runs under the process-wide egress guard (no outbound connection at all).
  Overlap: MultipleInstances=IgnoreNew + a Global\ mutex + the harvest DB advisory lock.
  Log: <AICP_DATA_ROOT>\logs\scheduler\nightly-YYYYMMDD.jsonl (no secrets). Exit: 0 ok/skipped, 2 blocked, 1 failed.
#>
[CmdletBinding()] param([ValidateSet('', 'test', 'live')][string]$Mode = '')
$configPath = $null
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
$ErrorActionPreference = 'Continue'
Set-Location $RepoRoot
$stateDir = Join-Path $DataRoot 'scheduler'; New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$logDir = Join-Path $LogRoot 'scheduler'; New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logFile = Join-Path $logDir ("nightly-" + (Get-Date -Format 'yyyyMMdd') + '.jsonl')
$configPath = Join-Path $stateDir 'nightly-task.json'
$cfg = $null; if (Test-Path $configPath) { try { $cfg = Get-Content $configPath -Raw | ConvertFrom-Json } catch {} }
if (-not $Mode) { $Mode = if ($cfg -and $cfg.mode -eq 'live') { 'live' } else { 'test' } }
$me = [Security.Principal.WindowsIdentity]::GetCurrent()
$entry = [ordered]@{ started_at = (Get-Date).ToString('o'); mode = $Mode; host = $env:COMPUTERNAME; pid = $PID; user = $me.Name
    interactive_logon = [bool]($me.Groups | Where-Object { $_.Value -eq 'S-1-5-4' }); batch_logon = [bool]($me.Groups | Where-Object { $_.Value -eq 'S-1-5-3' }) }
function Finish([string]$Status, [int]$Code, $Result) {
    $entry.status = $Status; $entry.exit_code = $Code; $entry.ended_at = (Get-Date).ToString('o')
    if ($Result) { $entry.result = $Result }
    Add-Content -Path $logFile -Value ($entry | ConvertTo-Json -Compress -Depth 8) -Encoding utf8
    exit $Code
}

$mutex = New-Object Threading.Mutex($false, 'Global\AICP-JobKorea-Nightly')
if (-not $mutex.WaitOne(0)) { $entry.reason = 'ALREADY_RUNNING'; Finish 'SKIPPED' 0 $null }
try {
    & (Join-Path $PSScriptRoot 'start-local-postgres.ps1') | Out-Null
    $py = @('-m', 'crawler.jobs.nightly', 'run', '--mode', $Mode, '--state-dir', "`"$stateDir`"")
    if ($Mode -eq 'test') {
        $env:AICP_NO_EGRESS = '1'
        $env:PYTHONPATH = "$(Join-Path $PSScriptRoot 'egress_guard');$env:PYTHONPATH"
        $env:AICP_EGRESS_LOG = Join-Path $logDir 'nightly-egress.jsonl'
    } else {
        if ($cfg -and $cfg.policy_file) { $py += @('--policy-file', "`"$($cfg.policy_file)`"") }
        if ($cfg -and $cfg.night_config) { $py += @('--config', "`"$($cfg.night_config)`"") }
        if ($cfg -and $cfg.live_activated -eq $true) { $env:CRAWLER_LIVE_SCHEDULE_APPROVED = '1' }
    }
    if ($cfg -and $cfg.slack -eq $true -and $Mode -eq 'live') {
        # read ONLY the webhook key from the repo .env into this process (never printed, never logged)
        $envFile = Join-Path $RepoRoot '.env'
        if (Test-Path $envFile) {
            foreach ($line in Get-Content $envFile -Encoding utf8) {
                if ($line -match '^\s*(SLACK_WEBHOOK_URL|SLACK_WEBHOOK_RUL)\s*=\s*(.+?)\s*$') {
                    [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"').Trim("'"))
                }
            }
        }
    }
    $out = Join-Path $logDir ("nightly-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.out')
    & cmd /d /c "`"$VenvPy`" $($py -join ' ') > `"$out`" 2>&1"
    $code = $LASTEXITCODE
    $json = Get-Content $out -Encoding utf8 | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1
    $obj = $null; if ($json) { try { $obj = $json | ConvertFrom-Json } catch {} }
    $entry.output_file = $out
    if ($Mode -eq 'live' -and $obj -and $obj.night_date -and $code -ne 2) {
        # GCP step only after the window closed (08:00 KST); an early finish waits, inside the task's time limit
        $end = [datetime]::ParseExact($obj.night_date, 'yyyy-MM-dd', $null).AddDays(1).AddHours(8).AddMinutes(1)
        $wait = ($end - (Get-Date)).TotalSeconds
        if ($wait -gt 0 -and $wait -lt 11 * 3600) { Start-Sleep -Seconds ([int]$wait) }
        $entry.gcp_step = & (Join-Path $PSScriptRoot 'post-night-gcp.ps1') -Night $obj.night_date | Select-Object -Last 1
    }
    $status = if ($code -eq 0) { 'OK' } elseif ($code -eq 2) { 'BLOCKED' } else { 'FAILED' }
    Finish $status $code $obj
} finally {
    foreach ($k in 'SLACK_WEBHOOK_URL', 'SLACK_WEBHOOK_RUL', 'CRAWLER_LIVE_SCHEDULE_APPROVED') { [Environment]::SetEnvironmentVariable($k, $null) }
    $mutex.ReleaseMutex() | Out-Null
}
