<#
.SYNOPSIS
  Runs an isolated PostgreSQL cluster for development, using PostgreSQL binaries already
  installed on this machine. It does not touch any existing PostgreSQL service or its data.

.DESCRIPTION
  Data directory : %LOCALAPPDATA%\ForceServiceCentre\pgdata   (outside OneDrive on purpose)
  Port           : 5544, listening on localhost only
  Auth           : "trust" for local connections - DEVELOPMENT ONLY
  Databases      : fsc_dev (application) and fsc_test (automated tests), owner "fsc"

.EXAMPLE
  .\scripts\dev-db.ps1 start
  .\scripts\dev-db.ps1 stop
  .\scripts\dev-db.ps1 status
#>
param([ValidateSet('start', 'stop', 'status')][string]$Action = 'start')

$ErrorActionPreference = 'Stop'
$Port = 5544
$Root = Join-Path $env:LOCALAPPDATA 'ForceServiceCentre'
$Data = Join-Path $Root 'pgdata'
$Log = Join-Path $Root 'pg.log'

$Bin = if ($env:PG_BIN) { $env:PG_BIN } else {
    Get-ChildItem 'C:\Program Files\PostgreSQL' -Directory -ErrorAction SilentlyContinue |
        Sort-Object { [int]($_.Name -replace '\D', '') } -Descending |
        ForEach-Object { Join-Path $_.FullName 'bin' } |
        Where-Object { Test-Path (Join-Path $_ 'pg_ctl.exe') } |
        Select-Object -First 1
}
if (-not $Bin) { throw 'PostgreSQL binaries not found. Install PostgreSQL 15+ or set $env:PG_BIN to its bin folder.' }

function Test-Running {
    & (Join-Path $Bin 'pg_isready.exe') -h localhost -p $Port -q
    return $LASTEXITCODE -eq 0
}

switch ($Action) {
    'status' {
        if (Test-Running) { "Running on localhost:$Port (data: $Data)" } else { 'Not running' }
    }
    'stop' {
        if (Test-Running) { & (Join-Path $Bin 'pg_ctl.exe') -D $Data -m fast stop | Out-Null; 'Stopped.' } else { 'Not running.' }
    }
    'start' {
        if (-not (Test-Path (Join-Path $Data 'PG_VERSION'))) {
            New-Item -ItemType Directory -Force $Data | Out-Null
            & (Join-Path $Bin 'initdb.exe') -D $Data -U fsc -A trust -E UTF8 --locale=C | Out-Null
            'Initialised a new development cluster.'
        }
        if (-not (Test-Running)) {
            # Start-Process detaches the server; piping pg_ctl output would block this shell, and
            # -Wait would wait for the server itself to exit, so poll until it accepts connections.
            Start-Process -FilePath (Join-Path $Bin 'pg_ctl.exe') -WindowStyle Hidden -ArgumentList @(
                '-D', "`"$Data`"", '-l', "`"$Log`"", '-o', "`"-p $Port -c listen_addresses=localhost`"", 'start')
            for ($i = 0; $i -lt 60 -and -not (Test-Running); $i++) { Start-Sleep -Milliseconds 500 }
        }
        if (-not (Test-Running)) { throw "PostgreSQL did not start. See $Log" }
        $existing = & (Join-Path $Bin 'psql.exe') -h localhost -p $Port -U fsc -d postgres -Atc 'select datname from pg_database'
        foreach ($db in 'fsc_dev', 'fsc_test') {
            if ($existing -notcontains $db) { & (Join-Path $Bin 'createdb.exe') -h localhost -p $Port -U fsc $db }
        }
        "PostgreSQL is running on localhost:$Port with databases fsc_dev and fsc_test."
    }
}
