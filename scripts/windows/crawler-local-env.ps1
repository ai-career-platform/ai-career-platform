<#
.SYNOPSIS
  Dot-source this file to prepare a SAFE local crawler session on a Windows PC.

  . .\scripts\windows\crawler-local-env.ps1

  - Never reads the repository-root .env (it may hold staging/GCP/Slack secrets).
  - Removes every LIVE / GCP sync / Slack variable from this process.
  - Points the crawler at the isolated local training DB on 127.0.0.1 only.
  - Passwords live only in the ACL-restricted pgpass file outside the repository.

  Override locations with AICP_PG_BIN / AICP_DATA_ROOT before dot-sourcing if needed.
#>
$ErrorActionPreference = 'Stop'

$script:RepoRoot  = if ($env:AICP_REPO_ROOT) { $env:AICP_REPO_ROOT } else { (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path }
$script:PgBin     = if ($env:AICP_PG_BIN)   { $env:AICP_PG_BIN }   else { 'C:\dev\tools\pgsql18\bin' }
$script:DataRoot  = if ($env:AICP_DATA_ROOT){ $env:AICP_DATA_ROOT }else { 'C:\dev\crawler-data' }
$script:PgData    = Join-Path $DataRoot 'pg18'
$script:Secrets   = Join-Path $DataRoot 'secrets'
$script:LogRoot   = Join-Path $DataRoot 'logs'
$script:PgPort    = if ($env:AICP_PG_PORT) { [int]$env:AICP_PG_PORT } else { 5432 }
$script:VenvPy    = if ($env:AICP_VENV_PY) { $env:AICP_VENV_PY } else { Join-Path $RepoRoot '.venv\Scripts\python.exe' }

# 1. Strip anything that could reach the outside world or a non-local DB.
$unsafe = Get-ChildItem env: | Where-Object {
    $_.Name -match '^(SLACK_|GCP_SYNC_|CRAWLER_LIVE_|CRAWLER_NIGHT_POLICY_FILE$|CRAWLER_NIGHT_ENABLED$|CRAWLER_STAGING_DATABASE_URL$|STAGING_SSH_|DATABASE_URL$|PGHOST|PGHOSTADDR$|PGSERVICE|PGUSER$|PGPASSWORD$|PGDATABASE$|Password|Host_GCP|Password_GCP)'
}
foreach ($v in $unsafe) { Remove-Item -Path "env:$($v.Name)" -ErrorAction SilentlyContinue }

# 2. Local-only settings (no secrets here).
$env:CRAWLER_DB_MODE            = 'local'
# Runtime role: crawler_local (DML only, inherits crawler_staging grants). Password comes from pgpass.
$runtimeRole = if ($env:AICP_RUNTIME_ROLE) { $env:AICP_RUNTIME_ROLE } else { 'crawler_local' }
$env:CRAWLER_LOCAL_DATABASE_URL = "postgresql://$runtimeRole@127.0.0.1:$PgPort/ai_career_crawler_training"
$env:PGPASSFILE                 = Join-Path $Secrets 'pgpass.conf'
$env:PGCONNECT_TIMEOUT          = '5'
$env:PYTHONPATH                 = "$RepoRoot;$(Join-Path $RepoRoot 'backend')"
# Process-wide egress guard (also for child Python processes) when requested by the caller.
if ($env:AICP_NO_EGRESS -eq '1') { $env:PYTHONPATH = "$(Join-Path $PSScriptRoot 'egress_guard');$env:PYTHONPATH" }
$env:PYTHONUTF8                 = '1'
$env:PYTHONIOENCODING           = 'utf-8'
# Smart App Control blocks the unsigned DLLs bundled in psycopg-binary on this PC.
# Use psycopg's pure-Python implementation with the signed libpq.dll from the EDB PostgreSQL build.
$env:PSYCOPG_IMPL               = 'python'
if (($env:PATH -split ';') -notcontains $PgBin) { $env:PATH = "$PgBin;$env:PATH" }

function Assert-CrawlerSafeSession {
    $bad = Get-ChildItem env: | Where-Object { $_.Name -match '^(SLACK_WEBHOOK|GCP_SYNC_|CRAWLER_LIVE_SCHEDULE_APPROVED|CRAWLER_NIGHT_ENABLED|CRAWLER_STAGING_DATABASE_URL)' }
    if ($bad) { throw "Unsafe variables present: $($bad.Name -join ', ')" }
    if ($env:CRAWLER_DB_MODE -ne 'local') { throw 'CRAWLER_DB_MODE must be local' }
    if ($env:CRAWLER_LOCAL_DATABASE_URL -notmatch '^postgresql://[a-z_]+@127\.0\.0\.1:\d+/ai_career_crawler_training$') { throw 'Local DB URL is not loopback/training-only' }
}
Assert-CrawlerSafeSession
Write-Host "[crawler-local-env] local-only session ready (LIVE/GCP/Slack variables removed)."
