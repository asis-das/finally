<#
.SYNOPSIS
    Stop FinAlly. Idempotent. The finally-data volume is deliberately preserved.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Name = 'finally'

# A `docker container inspect` on a missing container writes to stderr, which
# PowerShell 5.1 escalates to a fatal NativeCommandError under 'Stop'.
$existing = docker ps -a --filter "name=^/$Name$" --format '{{.Names}}'
if (-not [string]::IsNullOrWhiteSpace($existing)) {
    docker rm -f $Name | Out-Null
    Write-Host "Stopped and removed container '$Name'. Data volume 'finally-data' kept."
} else {
    Write-Host "Container '$Name' is not present. Nothing to do."
}
