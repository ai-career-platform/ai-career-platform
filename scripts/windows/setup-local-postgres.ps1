<#
.SYNOPSIS
  One-time, idempotent setup of the isolated LOCAL crawler training PostgreSQL on Windows.

  .\scripts\windows\setup-local-postgres.ps1

  * Uses the EDB PostgreSQL 18 binaries ZIP (no installer, no Windows service, no admin rights).
  * Cluster listens on 127.0.0.1 only, scram-sha-256 for every connection, no trust lines.
  * Generates NEW random passwords (never reuses staging/GCP credentials) and writes them ONLY to
    an ACL-restricted pgpass file outside the repository. Passwords are never printed.
  * Creates DB ai_career_crawler_training owned by non-superuser crawler_student, a DML-only
    runtime role crawler_staging, and applies crawler/storage/local_training_schema.sql plus
    migrations 0002-0012 exactly like .github/workflows/crawler-mvp.yml.
#>
[CmdletBinding()] param()
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')

function Write-Step($m) { Write-Host "[setup-local-postgres] $m" }
function New-Secret { $b = New-Object byte[] 24; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); ([Convert]::ToBase64String($b)).Replace('+','A').Replace('/','B').TrimEnd('=') }
function Protect-Path($p) { & icacls $p /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F" "SYSTEM:(OI)(CI)F" | Out-Null }
function Protect-File($p) { & icacls $p /inheritance:r /grant:r "$($env:USERNAME):F" "SYSTEM:F" | Out-Null }
function Invoke-Psql([string]$User, [string]$Db, [string]$Sql, [string]$File) {
    $a = @('-X','-q','-v','ON_ERROR_STOP=1','-h','127.0.0.1','-p',"$PgPort",'-U',$User,'-d',$Db)
    if ($File) { & "$PgBin\psql.exe" @a -f $File } else { $Sql | & "$PgBin\psql.exe" @a -f - }
    if ($LASTEXITCODE -ne 0) { throw "psql failed (user=$User db=$Db)" }
}

if (-not (Test-Path "$PgBin\initdb.exe")) { throw "PostgreSQL binaries not found at $PgBin" }
foreach ($d in @($DataRoot, $Secrets, $LogRoot)) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null } }
Protect-Path $Secrets

# --- pgpass (created once; passwords generated here, never echoed) -------------------------
$pgpass = $env:PGPASSFILE
if (-not (Test-Path $pgpass)) {
    $pw = @{ postgres = New-Secret; crawler_student = New-Secret; crawler_staging = New-Secret }
    $lines = foreach ($u in $pw.Keys) { foreach ($h in '127.0.0.1','localhost','db') { "${h}:${PgPort}:*:${u}:$($pw[$u])" } }
    Set-Content -Path $pgpass -Value $lines -Encoding ascii
    Protect-File $pgpass
    Write-Step 'generated new local-only passwords into restricted pgpass file'
}
function Get-Pw($u) { ((Get-Content $pgpass) | Where-Object { $_ -like "127.0.0.1:${PgPort}:*:${u}:*" } | Select-Object -First 1).Split(':', 5)[4] }

# --- initdb ---------------------------------------------------------------------------------
if (-not (Test-Path (Join-Path $PgData 'PG_VERSION'))) {
    $pwFile = Join-Path $Secrets 'initdb.pw.tmp'
    try {
        Set-Content -Path $pwFile -Value (Get-Pw 'postgres') -Encoding ascii -NoNewline
        & "$PgBin\initdb.exe" -D $PgData -U postgres --pwfile=$pwFile -A scram-sha-256 -E UTF8 --no-locale | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'initdb failed' }
    } finally { Remove-Item $pwFile -Force -ErrorAction SilentlyContinue }
    Add-Content -Path (Join-Path $PgData 'postgresql.conf') -Encoding ascii -Value @(
        '', '# --- ai-career local crawler (scripts/windows/setup-local-postgres.ps1) ---',
        "listen_addresses = '127.0.0.1'", "port = $PgPort", "password_encryption = 'scram-sha-256'",
        'logging_collector = on', "log_directory = 'log'", "log_filename = 'postgresql-%Y-%m-%d.log'",
        'log_rotation_age = 1d', "log_line_prefix = '%m [%p] %u@%d '", 'log_connections = on')
    Set-Content -Path (Join-Path $PgData 'pg_hba.conf') -Encoding ascii -Value @(
        '# Loopback only, password (scram) required for everyone. No trust, no remote hosts.',
        'host all all 127.0.0.1/32 scram-sha-256',
        'host all all ::1/128      scram-sha-256')
    Protect-Path $PgData
    Write-Step "initialized cluster at $PgData"
}

& (Join-Path $PSScriptRoot 'start-local-postgres.ps1')

# --- roles & database -----------------------------------------------------------------------
$sql = @"
DO `$`$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='crawler_student') THEN CREATE ROLE crawler_student LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='crawler_staging') THEN CREATE ROLE crawler_staging LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION; END IF;
END `$`$;
ALTER ROLE crawler_student PASSWORD '$(Get-Pw 'crawler_student')';
ALTER ROLE crawler_staging PASSWORD '$(Get-Pw 'crawler_staging')';
"@
Invoke-Psql -User postgres -Db postgres -Sql $sql
$exists = ('SELECT 1 FROM pg_database WHERE datname=''ai_career_crawler_training''' | & "$PgBin\psql.exe" -X -tA -h 127.0.0.1 -p $PgPort -U postgres -d postgres -f -)
if ($exists -ne '1') {
    Invoke-Psql -User postgres -Db postgres -Sql 'CREATE DATABASE ai_career_crawler_training OWNER crawler_student;'
    $db = 'ai_career_crawler_training'
    Invoke-Psql -User crawler_student -Db $db -File (Join-Path $RepoRoot 'crawler\storage\local_training_schema.sql')
    Invoke-Psql -User crawler_student -Db $db -Sql 'GRANT USAGE ON SCHEMA crawler_training TO crawler_staging; GRANT SELECT, INSERT, UPDATE ON crawler_training.postings TO crawler_staging;'
    Get-ChildItem (Join-Path $RepoRoot 'crawler\storage\migrations') -Filter '00*.sql' | Sort-Object Name | ForEach-Object {
        Invoke-Psql -User crawler_student -Db $db -File $_.FullName
        Write-Step "applied $($_.Name)"
    }
    Write-Step 'created ai_career_crawler_training with schema crawler_training'
} else { Write-Step 'database already exists; schema/migrations not re-applied' }
Write-Step 'done'
