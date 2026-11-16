<#
.SYNOPSIS
  GOAL_2 end-to-end rehearsal of approval C on a DISPOSABLE local cluster (never Cloud SQL, never port 5432).

  $env:AICP_DATA_ROOT='C:\dev\crawler-data-goal3'; $env:AICP_PG_PORT='5434'
  .\scripts\windows\rehearse-gcp-sync.ps1

  1. Self-signed rehearsal CA + server certificate for the name 'gcp-sync-rehearsal.local' (openssl from
     Git for Windows); the disposable server switches to TLS with ALTER SYSTEM + reload.
  2. Target DB ai_career_poc with the real career schema, create_career_sync_role.sql, target_grants.sql.
  3. Source: a synthetic REHEARSAL "live" harvest run plus fixture / ledger-less decoys.
  4. <DataRoot>\secrets\gcp-sync.env (random password, ACL this user + SYSTEM) + CA file, exactly the
     layout run-gcp-sync-local.ps1 expects for the real run.
  5. run-gcp-sync-local.ps1: dry-run -> run -> verify -> rerun; negative cases (fixture run id, wrong
     certificate name, admin user); run-scoped rollback SQL; evidence JSON.
  Network: loopback only. Secrets: generated locally, never printed.
#>
[CmdletBinding()] param([int]$Rows = 1050)
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
$ErrorActionPreference = 'Continue'
if ($PgPort -eq 5432 -or -not $env:AICP_DATA_ROOT) { throw 'Rehearsal runs only on a disposable cluster (set AICP_DATA_ROOT and AICP_PG_PORT, not 5432)' }
Set-Location $RepoRoot
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$out = Join-Path $LogRoot "gcp-rehearsal-$stamp"; New-Item -ItemType Directory $out -Force | Out-Null
$secrets = Join-Path $DataRoot 'secrets'; $tls = Join-Path $DataRoot 'rehearsal-tls'; New-Item -ItemType Directory $tls -Force | Out-Null
$certName = 'gcp-sync-rehearsal.local'
$openssl = 'C:\Program Files\Git\usr\bin\openssl.exe'
$env:MSYS2_ARG_CONV_EXCL = '*'
function Restrict($Path) { & icacls $Path /inheritance:r /grant:r "$($env:USERNAME):F" /grant:r 'SYSTEM:F' | Out-Null }
function New-Secret { $b = New-Object byte[] 24; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); ([Convert]::ToBase64String($b)).Replace('+','A').Replace('/','B').TrimEnd('=') }
$evidence = [ordered]@{ started_at = (Get-Date).ToString('o'); target = "127.0.0.1:$PgPort/ai_career_poc (disposable, not Cloud SQL)"; cert_name = $certName }

# 1. TLS
Push-Location $tls
"subjectAltName=DNS:$certName" | Set-Content ext.cnf -Encoding ascii
& $openssl req -x509 -newkey rsa:2048 -nodes -keyout ca.key -out ca.pem -days 2 -subj '/CN=AICP Rehearsal CA' 2>$null
& $openssl req -newkey rsa:2048 -nodes -keyout server.key -out server.csr -subj "/CN=$certName" 2>$null
& $openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial -out server.crt -days 2 -extfile ext.cnf 2>$null
Pop-Location
$evidence.tls_files = @('ca.pem','server.crt','server.key' | ForEach-Object { Test-Path (Join-Path $tls $_) })
$cert = ($tls -replace '\\','/')
# one -c per statement: psql runs a multi-statement -c as one transaction, which ALTER SYSTEM refuses
$tlsArgs = ("ALTER SYSTEM SET ssl_cert_file = '$cert/server.crt'", "ALTER SYSTEM SET ssl_key_file = '$cert/server.key'",
            'ALTER SYSTEM SET ssl = on', 'SELECT pg_reload_conf()') | ForEach-Object { "-c `"$_`"" }
& cmd /d /c "`"$PgBin\psql.exe`" -h 127.0.0.1 -p $PgPort -U postgres -d postgres -X -q -v ON_ERROR_STOP=1 $($tlsArgs -join ' ') > `"$out\tls.out`" 2>&1"
Start-Sleep 2
$evidence.server_ssl = (& "$PgBin\psql.exe" -h 127.0.0.1 -p $PgPort -U postgres -d postgres -X -A -t -c 'SHOW ssl' 2>$null)

# 2-3. target + source
$pwFile = Join-Path $secrets 'rehearsal-career-sync.pw'; New-Secret | Set-Content $pwFile -Encoding ascii -NoNewline; Restrict $pwFile
$setupOut = Join-Path $out 'setup.json'
& cmd /d /c "`"$VenvPy`" `"$PSScriptRoot\rehearsal\gcp_sync_rehearsal_setup.py`" --port $PgPort --sync-password-file `"$pwFile`" --rows $Rows > `"$setupOut`" 2> `"$out\setup.err`""
$setup = Get-Content $setupOut -Raw | ConvertFrom-Json; $evidence.setup = $setup
if ($setup.status -ne 'READY') { $evidence | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $out 'evidence.json'); throw 'setup failed; see setup.err' }

# 4. secrets layout used by the real run
$envFile = Join-Path $secrets 'gcp-sync.env'
function Write-SyncEnv([string]$HostName, [string]$User) {
    @("GCP_SYNC_TARGET_HOST=$HostName", 'GCP_SYNC_TARGET_HOSTADDR=127.0.0.1', "GCP_SYNC_TARGET_PORT=$PgPort",
      'GCP_SYNC_TARGET_DB=ai_career_poc', "GCP_SYNC_TARGET_USER=$User",
      "GCP_SYNC_TARGET_PASSWORD=$((Get-Content $pwFile -Raw).Trim())", 'GCP_SYNC_PUBLISH=0') | Set-Content $envFile -Encoding utf8
    Restrict $envFile }
Copy-Item (Join-Path $tls 'ca.pem') (Join-Path $secrets 'gcp-server-ca.pem') -Force

# 5. wrapper runs (the wrapper itself uses AICP_RUNTIME_ROLE for the source login on this cluster)
$env:AICP_RUNTIME_ROLE = 'crawler_staging'
function Sync([string]$Mode, [string]$RunId) {
    $t = [Diagnostics.Stopwatch]::StartNew()
    $line = & (Join-Path $PSScriptRoot 'run-gcp-sync-local.ps1') -Mode $Mode -LiveRunId $RunId 2>$null | Where-Object { $_ -match '^\{' } | Select-Object -Last 1
    $t.Stop(); $o = if ($line) { $line | ConvertFrom-Json } else { [pscustomobject]@{ status = 'NO_OUTPUT' } }
    $o | Add-Member seconds ([math]::Round($t.Elapsed.TotalSeconds, 2)) -Force; $o }
function Short($o) { $o | Select-Object status, error_code, reason, fetched, inserted, updated, duplicate, skipped, failed, source_rows, target_matched, target_missing, target_mismatched, source_target_match, seconds }
Write-SyncEnv $certName 'career_sync'
$evidence.dry_run = Short (Sync 'dry-run' $setup.live_run_id)
$run = Sync 'run' $setup.live_run_id; $evidence.run = Short $run; $evidence.run_ingestion_run_id = $run.run_id
$evidence.inserted_ids_count = @($run.inserted_external_ids).Count
$evidence.verify = Short (Sync 'verify' $setup.live_run_id)
$evidence.rerun = Short (Sync 'run' $setup.live_run_id)
$evidence.neg_fixture_run = Short (Sync 'dry-run' $setup.fixture_run_id)
Write-SyncEnv 'wrong-name.example' 'career_sync'; $evidence.neg_wrong_cert_name = Short (Sync 'dry-run' $setup.live_run_id)
Write-SyncEnv $certName 'postgres'; $evidence.neg_admin_user = Short (Sync 'dry-run' $setup.live_run_id)
Write-SyncEnv $certName 'career_sync'

# target-side checks as the owner (rehearsal admin): drafts only, no decoys, privilege probe, then rollback
$q = @"
SELECT json_build_object(
 'live_postings', (SELECT count(*) FROM career.job_postings p JOIN career.data_sources s USING (source_id) WHERE s.code='jobkorea_live'),
 'non_draft', (SELECT count(*) FROM career.job_postings p JOIN career.data_sources s USING (source_id) WHERE s.code='jobkorea_live' AND p.status<>'draft'),
 'decoys_copied', (SELECT count(*) FROM career.job_posting_external_refs WHERE external_id::bigint >= $($setup.first_id + $Rows)),
 'ingestion_runs', (SELECT json_agg(status ORDER BY started_at) FROM career.ingestion_runs),
 'sync_can_delete', has_table_privilege('career_sync','career.job_postings','DELETE'),
 'sync_can_create', has_schema_privilege('career_sync','career','CREATE'),
 'sync_can_read_users', has_table_privilege('career_sync','career.users','SELECT'));
"@
& cmd /d /c "`"$PgBin\psql.exe`" -h 127.0.0.1 -p $PgPort -U postgres -d ai_career_poc -X -A -t -c `"$($q -replace "`r?`n",' ')`" > `"$out\target.json`" 2>&1"
$evidence.target_checks = Get-Content "$out\target.json" -Raw | ConvertFrom-Json
$ids = (@($run.inserted_external_ids) | ForEach-Object { "'$_'" }) -join ','
$rollback = "BEGIN; DELETE FROM career.job_postings p USING career.job_posting_external_refs r, career.data_sources s WHERE r.job_posting_id=p.job_posting_id AND r.source_id=s.source_id AND s.code='jobkorea_live' AND r.external_id IN ($ids); DELETE FROM career.companies c USING career.data_sources s WHERE c.source_id=s.source_id AND s.code='jobkorea_live' AND NOT EXISTS (SELECT 1 FROM career.job_postings p WHERE p.company_id=c.company_id); COMMIT; SELECT count(*) FROM career.job_posting_external_refs;"
$rollback | Set-Content "$out\rollback.sql" -Encoding utf8
& cmd /d /c "`"$PgBin\psql.exe`" -h 127.0.0.1 -p $PgPort -U postgres -d ai_career_poc -X -A -t -q -v ON_ERROR_STOP=1 -f `"$out\rollback.sql`" > `"$out\rollback.out`" 2>&1"
$evidence.rollback_exit = $LASTEXITCODE; $evidence.refs_after_rollback = [string](Get-Content "$out\rollback.out" | Where-Object { $_ -match '^\d+$' } | Select-Object -Last 1)
$evidence.verify_after_rollback = Short (Sync 'verify' $setup.live_run_id)

Remove-Item $envFile, $pwFile -ErrorAction SilentlyContinue   # rehearsal secret is not kept
Remove-Item env:AICP_RUNTIME_ROLE, env:MSYS2_ARG_CONV_EXCL -ErrorAction SilentlyContinue
$evidence.ended_at = (Get-Date).ToString('o')
$evidence | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $out 'evidence.json') -Encoding utf8
Write-Host "[rehearse-gcp-sync] evidence: $out\evidence.json"
$evidence | ConvertTo-Json -Depth 6
