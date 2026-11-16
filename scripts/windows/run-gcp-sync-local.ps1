<#
.SYNOPSIS
  GOAL_2: one-shot GCP Cloud SQL sync of ONE approved LIVE harvest run from this PC's local DB.

  .\scripts\windows\run-gcp-sync-local.ps1 -Mode dry-run -LiveRunId <uuid>   # plan only, no target write
  .\scripts\windows\run-gcp-sync-local.ps1 -Mode run     -LiveRunId <uuid>   # needs PM approval C
  .\scripts\windows\run-gcp-sync-local.ps1 -Mode verify  -LiveRunId <uuid>   # read-only source/target match

  * Source: loopback crawler_local (READ ONLY). Only postings of the named LIVE harvest run are
    selected (crawler_training.harvest_items); fixture/test rows can never be copied.
  * Target settings come ONLY from <AICP_DATA_ROOT>\secrets\gcp-sync.env (KEY=VALUE, ACL: this user +
    SYSTEM + Administrators only) and the instance CA <AICP_DATA_ROOT>\secrets\gcp-server-ca.pem. The repository root .env
    is never read. Allowed keys: GCP_SYNC_TARGET_HOST (certificate name), GCP_SYNC_TARGET_HOSTADDR (IP),
    GCP_SYNC_TARGET_PORT, GCP_SYNC_TARGET_DB, GCP_SYNC_TARGET_USER (career_sync), GCP_SYNC_TARGET_PASSWORD,
    GCP_SYNC_PUBLISH (default 0 = draft), GCP_SYNC_CUTOVER_CONFIRMED (1 only after the PM confirms the
    Staging sync cron is stopped; otherwise a run refuses with OTHER_SYNC_SOURCE_ACTIVE). Even then the
    run refuses while the other writer has a sync running or ran within 26 h (OTHER_SYNC_RUNNING /
    OTHER_SYNC_RECENT), and GCP_SYNC_CUTOVER_EVIDENCE (a short reference to the cron-stop evidence)
    is required and recorded in ingestion_runs.error_summary.
    Admin users are refused by gcp_sync.py.
  * Secrets are passed by environment to the child only, never on argv or in logs.
  Evidence: <AICP_DATA_ROOT>\logs\gcp-sync\<stamp>-<mode>.json
#>
[CmdletBinding()] param(
    [Parameter(Mandatory)][ValidateSet('dry-run','run','verify')] [string]$Mode,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')]
    [string[]]$LiveRunId)
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
$ErrorActionPreference = 'Continue'
Set-Location $RepoRoot
$conf = Join-Path $DataRoot 'secrets\gcp-sync.env'
$ca = Join-Path $DataRoot 'secrets\gcp-server-ca.pem'
$logDir = Join-Path $LogRoot 'gcp-sync'; New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$evidence = Join-Path $logDir ("{0}-{1}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $Mode)
function Blocked([string]$Code) {
    $o = [ordered]@{ mode = $Mode; status = 'BLOCKED'; error_code = $Code; target_contacted = $false }
    $o | ConvertTo-Json | Set-Content $evidence -Encoding utf8; $o | ConvertTo-Json -Compress; exit 2 }
if (-not (Test-Path $conf)) { Blocked 'GCP_SYNC_ENV_FILE_MISSING' }
if (-not (Test-Path $ca)) { Blocked 'GCP_SYNC_CA_FILE_MISSING' }
$me = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$foreign = (Get-Acl $conf).Access | Where-Object {
    $sid = $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    $_.AccessControlType -eq 'Allow' -and $sid -notin @($me, 'S-1-5-18', 'S-1-5-32-544') }
if ($foreign) { Blocked 'GCP_SYNC_ENV_FILE_ACL_TOO_OPEN' }
$allowed = 'GCP_SYNC_TARGET_HOST','GCP_SYNC_TARGET_HOSTADDR','GCP_SYNC_TARGET_PORT','GCP_SYNC_TARGET_DB',
           'GCP_SYNC_TARGET_USER','GCP_SYNC_TARGET_PASSWORD','GCP_SYNC_PUBLISH','GCP_SYNC_CUTOVER_CONFIRMED','GCP_SYNC_CUTOVER_EVIDENCE'
$set = @()
try {
    foreach ($line in Get-Content $conf -Encoding utf8) {
        if ($line -match '^\s*(#|$)') { continue }
        if ($line -notmatch '^\s*([A-Z_]+)\s*=(.*)$' -or $Matches[1] -notin $allowed) { Blocked 'GCP_SYNC_ENV_FILE_UNEXPECTED_KEY' }
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim().Trim('"')); $set += $Matches[1]
    }
    $env:GCP_SYNC_SOURCE = 'local'; $env:GCP_SYNC_TARGET_SSLROOTCERT = $ca; $set += 'GCP_SYNC_SOURCE','GCP_SYNC_TARGET_SSLROOTCERT'
    $ids = ($LiveRunId | ForEach-Object { '--live-run-id', $_ }) -join ' '
    $raw = "$evidence.out"
    & cmd /d /c "`"$VenvPy`" -m crawler.jobs.gcp_sync $Mode $ids > `"$raw`" 2>&1"
    $code = $LASTEXITCODE
    $json = Get-Content $raw -Encoding utf8 | Where-Object { $_ -match '^\{' } | Select-Object -Last 1
    if ($json) { $json | Set-Content $evidence -Encoding utf8 } else { Copy-Item $raw $evidence -Force }
    Remove-Item $raw -ErrorAction SilentlyContinue
    Write-Host "[run-gcp-sync-local] exit=$code evidence=$evidence"
    if ($json) { $json }
    exit $code
} finally {
    foreach ($k in $set) { [Environment]::SetEnvironmentVariable($k, $null) }
}
