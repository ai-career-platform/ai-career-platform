<#
.SYNOPSIS
  After 08:00 KST: hand the finished night's LIVE runs to the official GCP sync (dry-run, then run, then verify)
  and report the result to Slack once. Called by nightly-jobkorea.ps1 after a LIVE night, or by hand:

  .\scripts\windows\post-night-gcp.ps1 [-Night 2026-11-17]      # default: the night that ended this morning

  Runs the sync ONLY when nightly-task.json has "gcp_sync": true AND secrets\gcp-sync.env (career_sync, password
  set) AND secrets\gcp-server-ca.pem exist. Otherwise the step is recorded as BLOCKED/NOT_RUN with the reason.
  Never passes the one-time cutover flags: the first cutover is a separate, PM-approved manual run
  (run-gcp-sync-local.ps1 -CutoverConfirmed -CutoverEvidence ...). The sync itself refuses a second writer.
  Result: <AICP_DATA_ROOT>\logs\gcp-sync\post-night-<night>.json (no secrets).
#>
[CmdletBinding()] param([string]$Night = '')
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
$ErrorActionPreference = 'Continue'
Set-Location $RepoRoot
$now = Get-Date
if (-not $Night) { $Night = $now.AddDays(-1).ToString('yyyy-MM-dd') }
$stateDir = Join-Path $DataRoot 'scheduler'
$logDir = Join-Path $LogRoot 'gcp-sync'; New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$resultFile = Join-Path $logDir "post-night-$Night.json"
$cfg = $null; $cfgPath = Join-Path $stateDir 'nightly-task.json'
if (Test-Path $cfgPath) { try { $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json } catch {} }

function Save($obj) { $obj | ConvertTo-Json -Depth 6 | Set-Content -Path $resultFile -Encoding utf8; $obj }
function PyJson([string[]]$PyArgs) {
    $raw = & cmd /d /c "`"$VenvPy`" -m crawler.jobs.nightly $($PyArgs -join ' ') 2>&1"
    $line = $raw | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1
    if ($line) { $line | ConvertFrom-Json } else { $null }
}

$windowEnd = [datetime]::ParseExact($Night, 'yyyy-MM-dd', $null).AddDays(1).AddHours(8)
if ($now -lt $windowEnd) { $r = Save ([ordered]@{ status = 'NOT_RUN'; reason = 'NIGHT_WINDOW_NOT_ENDED'; night = $Night }) }
else {
    $runs = PyJson @('night-runs', '--night', $Night)
    $ids = @($runs.live_run_ids | Where-Object { $_ })
    $conf = Join-Path $DataRoot 'secrets\gcp-sync.env'; $ca = Join-Path $DataRoot 'secrets\gcp-server-ca.pem'
    $pwSet = (Test-Path $conf) -and [bool](Get-Content $conf | Where-Object { $_ -match '^\s*GCP_SYNC_TARGET_PASSWORD\s*=\s*\S' })
    $reason = if (-not $runs) { 'NIGHT_RUNS_UNREADABLE' } elseif ($ids.Count -eq 0) { 'NO_LIVE_RUNS' }
              elseif (-not ($cfg -and $cfg.gcp_sync -eq $true)) { 'GCP_SYNC_NOT_ENABLED' }
              elseif (-not (Test-Path $ca)) { 'GCP_CA_MISSING' } elseif (-not $pwSet) { 'CAREER_SYNC_PASSWORD_MISSING' } else { $null }
    if ($reason) {
        $r = Save ([ordered]@{ status = $(if ($reason -eq 'NO_LIVE_RUNS') { 'NOT_RUN' } else { 'BLOCKED' }); reason = $reason
                               night = $Night; live_run_ids = $ids; gcp_writes = 0 })
    } else {
        $wrapper = Join-Path $PSScriptRoot 'run-gcp-sync-local.ps1'
        $dry = & $wrapper -Mode dry-run -LiveRunId $ids | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1 | ConvertFrom-Json
        if (-not $dry -or $dry.status -ne 'DRY_RUN') { $r = Save ([ordered]@{ status = 'BLOCKED'; reason = "DRY_RUN_$($dry.status)_$($dry.error_code)"; night = $Night; live_run_ids = $ids; dry_run = $dry }) }
        else {
            $run = & $wrapper -Mode run -LiveRunId $ids | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1 | ConvertFrom-Json
            $verify = & $wrapper -Mode verify -LiveRunId $ids | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1 | ConvertFrom-Json
            $o = [ordered]@{ night = $Night; live_run_ids = $ids; verify = $verify }
            foreach ($p in $run.PSObject.Properties) { $o[$p.Name] = $p.Value }
            $r = Save $o
        }
    }
}
if ($cfg -and $cfg.slack -eq $true) {
    $envFile = Join-Path $RepoRoot '.env'
    foreach ($line in Get-Content $envFile -Encoding utf8) {
        if ($line -match '^\s*(SLACK_WEBHOOK_URL|SLACK_WEBHOOK_RUL)\s*=\s*(.+?)\s*$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"').Trim("'")) }
    }
    try { PyJson @('notify', '--kind', 'gcp', '--night', $Night, '--result-file', "`"$resultFile`"", '--state-dir', "`"$stateDir`"") | Out-Null }
    finally { foreach ($k in 'SLACK_WEBHOOK_URL', 'SLACK_WEBHOOK_RUL') { [Environment]::SetEnvironmentVariable($k, $null) } }
}
$r | ConvertTo-Json -Compress -Depth 6
