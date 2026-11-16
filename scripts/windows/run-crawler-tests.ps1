<#
.SYNOPSIS
  Run the crawler test suites on Windows against the isolated local PostgreSQL,
  mirroring .github/workflows/crawler-mvp.yml (minus Docker/systemd/Node-only steps).

  .\scripts\windows\run-crawler-tests.ps1 [-Suite unit|pg|all]

  * Every Python step runs under scripts\windows\no_egress.py (non-loopback sockets/DNS blocked and
    counted), so the summary proves EXTERNAL_HTTP_REQUESTS=0 for the run.
  * DB roles follow CI: crawler_student (owner) for CRAWLER_LOCAL_DATABASE_URL, crawler_staging for
    the night/admin DSNs. Passwords come from the ACL-restricted pgpass file only.
  * local_gcp_sync_pg needs a SUPERUSER of a DISPOSABLE server (it creates/drops its own DB). It runs
    only when the pgpass file holds a postgres entry for this port (true for clusters created by
    setup-local-postgres.ps1, e.g. the port-5433 verification cluster); otherwise it is NOT_RUN.
  Summary: <AICP_DATA_ROOT>\logs\tests-<timestamp>\summary.json
#>
[CmdletBinding()] param([ValidateSet('unit','pg','all')] [string]$Suite = 'all')
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
$ErrorActionPreference = 'Continue'
Set-Location $RepoRoot
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$out = Join-Path $LogRoot "tests-$stamp"; New-Item -ItemType Directory -Path $out -Force | Out-Null
$env:AICP_EGRESS_LOG = Join-Path $out 'egress.jsonl'
$guard = Join-Path $PSScriptRoot 'no_egress.py'
$results = [System.Collections.Generic.List[object]]::new()
$student = "postgresql://crawler_student@127.0.0.1:$PgPort/ai_career_crawler_training"
$staging = "postgresql://crawler_staging@127.0.0.1:$PgPort/ai_career_crawler_training"

function Add-Result($Name, $Exit, $Tests, $Seconds, $Text, $Log) {
    $results.Add([pscustomobject]@{ step = $Name; exit = $Exit; tests = $Tests; seconds = $Seconds; result = $Text; log = $Log })
    Write-Host ("{0,-28} exit={1,-7} {2}" -f $Name, $Exit, $Text)
}
function Step([string]$Name, [hashtable]$Env, [string[]]$Modules) {
    $saved = @{}
    # step values override the default (hashtable '+' throws on a duplicate key)
    $merged = @{ CRAWLER_LOCAL_DATABASE_URL = $student }
    foreach ($k in $Env.Keys) { $merged[$k] = $Env[$k] }
    $Env = $merged
    foreach ($k in $Env.Keys) { $saved[$k] = [Environment]::GetEnvironmentVariable($k); [Environment]::SetEnvironmentVariable($k, $Env[$k]) }
    $log = Join-Path $out "$Name.log"
    $t = [Diagnostics.Stopwatch]::StartNew()
    & cmd /c "`"$VenvPy`" `"$guard`" -m unittest $($Modules -join ' ') -v > `"$log`" 2>&1"
    $code = $LASTEXITCODE; $t.Stop()
    foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) }
    $text = Get-Content $log -Encoding utf8
    $ran = ($text | Select-String -Pattern '^Ran (\d+) test' | Select-Object -Last 1)
    $final = ($text | Select-String -Pattern '^(OK|FAILED)' | Select-Object -Last 1)
    $egress = ($text | Select-String -Pattern '^EGRESS_ATTEMPTS=(\d+)' | Select-Object -Last 1)
    Add-Result $Name $code ($(if ($ran) { [int]$ran.Matches[0].Groups[1].Value })) ([math]::Round($t.Elapsed.TotalSeconds,1)) "$($final.Line) $($egress.Line)" $log
}

if ($Suite -in 'unit','all') {
    Step 'unit-crawler'          @{} @('discover','-s','crawler/tests')
    Step 'unit-backend-training' @{} @('discover','-s','backend/training_tests')
}
if ($Suite -in 'pg','all') {
    & (Join-Path $PSScriptRoot 'start-local-postgres.ps1')
    $hasDisposableAdmin = (Test-Path $env:PGPASSFILE) -and (Select-String -Path $env:PGPASSFILE -Pattern "^127\.0\.0\.1:${PgPort}:\*:postgres:" -Quiet)
    if ($hasDisposableAdmin) {
        Step 'pg-gcp-sync' @{ CRAWLER_GCP_SYNC_PG_TEST='1'; CRAWLER_GCP_SYNC_ADMIN_DSN="postgresql://postgres@127.0.0.1:$PgPort/postgres" } @('crawler.tests.local_gcp_sync_pg')
        Step 'pg-gcp-sync-local-source' @{ CRAWLER_GCP_SYNC_PG_TEST='1'; CRAWLER_GCP_SYNC_ADMIN_DSN="postgresql://postgres@127.0.0.1:$PgPort/postgres" } @('crawler.tests.local_gcp_sync_local_source_pg')
        Step 'pg-gcp-sync-staging-provenance' @{ CRAWLER_GCP_SYNC_PG_TEST='1'; CRAWLER_GCP_SYNC_ADMIN_DSN="postgresql://postgres@127.0.0.1:$PgPort/postgres" } @('crawler.tests.local_gcp_sync_staging_provenance_pg')
        # GOAL_3 harvest writes 1,000+ synthetic rows: disposable clusters only (the test also refuses 5432).
        Step 'pg-harvest-1000' @{ CRAWLER_HARVEST_PG_TEST='1'; CRAWLER_LOCAL_DATABASE_URL=$staging } @('crawler.tests.local_harvest_pg')
    } else {
        Add-Result 'pg-gcp-sync' 'NOT_RUN' $null 0 'needs disposable superuser cluster (see header)' $null
        Add-Result 'pg-gcp-sync-local-source' 'NOT_RUN' $null 0 'needs disposable superuser cluster (see header)' $null
        Add-Result 'pg-gcp-sync-staging-provenance' 'NOT_RUN' $null 0 'needs disposable superuser cluster (see header)' $null
        Add-Result 'pg-harvest-1000' 'NOT_RUN' $null 0 'disposable cluster only (writes 1,000+ synthetic rows)' $null
    }
    Step 'pg-html-integration'  @{ CRAWLER_LOCAL_PG_TEST='1' } @('crawler.tests.local_html_pg_integration')
    # These two tests hard-code the container DSN db:5432 (crawler/storage/staging.py), so they only
    # apply to the cluster on port 5432.
    if ($PgPort -eq 5432) { Step 'pg-staging-mode' @{ CRAWLER_STAGING_PG_TEST='1' } @('crawler.tests.local_staging_pg_integration') }
    else { Add-Result 'pg-staging-mode' 'NOT_APPLICABLE' $null 0 'test hard-codes db:5432' $null }
    Step 'pg-t64-integration'   @{ CRAWLER_T64_ISOLATED_TEST='1' } @('crawler.tests.local_t64_integration')
    if ($PgPort -eq 5432) { Step 'pg-t64-permissions' @{ CRAWLER_STAGING_PG_TEST='1' } @('crawler.tests.local_t64_permissions') }
    else { Add-Result 'pg-t64-permissions' 'NOT_APPLICABLE' $null 0 'test hard-codes db:5432' $null }
    $night = @{ CRAWLER_NIGHT_TEST_DSN=$staging; CRAWLER_NIGHT_PG_TEST='1' }
    Step 'pg-night-executor-caller' $night @('crawler.tests.local_t154_night_executor','crawler.tests.local_t154_night_caller')
    Step 'pg-night-integration' ($night + @{ CRAWLER_T64_ISOLATED_TEST='1' }) @('crawler.tests.local_night_integration')
    Step 'pg-t155-admin-read'   $night @('crawler.tests.local_t155_admin_read_pg')
    Step 'pg-t152-artifact-audit' $night @('crawler.tests.local_t152_artifact_audit_pg')
    Step 'pg-t155-admin-write'  $night @('crawler.tests.local_t155_admin_write_pg')
    Step 'pg-night-e2e'         ($night + @{ CRAWLER_NIGHT_E2E='1'; CRAWLER_NIGHT_E2E_OUT=(Join-Path $out 'night_e2e.json') }) @('crawler.tests.staging_night_e2e')
    Add-Result 'docker-caller-container' 'NOT_RUN' $null 0 'requires Docker (not installed on this PC)' $null
}
$results | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $out 'summary.json') -Encoding utf8
$failed = @($results | Where-Object { $_.exit -isnot [string] -and $_.exit -ne 0 }).Count
Write-Host "[run-crawler-tests] steps=$($results.Count) failed=$failed summary=$out\summary.json"
exit ([int]($failed -gt 0))
