<#
.SYNOPSIS  Cleanly stop the isolated local crawler PostgreSQL (data is kept).
#>
[CmdletBinding()] param()
. (Join-Path $PSScriptRoot 'crawler-local-env.ps1')
& "$PgBin\pg_ctl.exe" stop -D $PgData -m fast -w | Out-Host
