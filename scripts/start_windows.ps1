<#
.SYNOPSIS
    Start FinAlly. Idempotent: safe to run repeatedly.
.EXAMPLE
    .\scripts\start_windows.ps1 -Build
#>
[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'

$Image  = 'finally:latest'
$Name   = 'finally'
$Volume = 'finally-data'
$Port   = 8000
$Root   = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'docker not found on PATH. Is Docker Desktop installed and running?'
}

if (-not (Test-Path '.env')) {
    Write-Warning '.env not found - creating it from .env.example.'
    Write-Warning 'AI chat runs in mock mode until you add OPENROUTER_API_KEY.'
    Copy-Item '.env.example' '.env'
}

# Use --format/--filter queries rather than `inspect`: a missing image or
# container makes `inspect` write to stderr, which PowerShell 5.1 turns into a
# fatal NativeCommandError under $ErrorActionPreference = 'Stop'.
$imageMissing = [string]::IsNullOrWhiteSpace((docker images -q $Image))
if ($Build -or $imageMissing) {
    Write-Host "Building $Image ..."
    docker build -t $Image .
    if ($LASTEXITCODE -ne 0) { throw 'docker build failed.' }
}

$existing = docker ps -a --filter "name=^/$Name$" --format '{{.Names}}'
if (-not [string]::IsNullOrWhiteSpace($existing)) {
    Write-Host "Removing existing container '$Name' ..."
    docker rm -f $Name | Out-Null
}

docker volume create $Volume | Out-Null

Write-Host "Starting $Name ..."
docker run -d --name $Name -p "$($Port):8000" -v "$($Volume):/app/db" --env-file .env --restart unless-stopped $Image | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'docker run failed.' }

$url = "http://localhost:$Port"
Write-Host -NoNewline "Waiting for $url/api/health "
foreach ($i in 1..60) {
    try {
        Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 3 | Out-Null
        Write-Host ''
        Write-Host "FinAlly is up:  $url" -ForegroundColor Green
        if (-not $NoOpen) { Start-Process $url }
        exit 0
    } catch {
        # A crashed container will never become healthy - fail fast with its logs.
        $running = docker ps --filter "name=^/$Name$" --format '{{.Names}}'
        if ([string]::IsNullOrWhiteSpace($running)) {
            Write-Host ''
            Write-Error 'Container exited. Logs:'
            docker logs $Name
            exit 1
        }
        Write-Host -NoNewline '.'
        Start-Sleep -Seconds 1
    }
}

Write-Host ''
Write-Error 'Timed out waiting for health. Last 50 log lines:'
docker logs --tail 50 $Name
exit 1
