param(
    [string]$OutputDir = $(if ($env:XH_BACKUP_OUTPUT_DIR) { $env:XH_BACKUP_OUTPUT_DIR } else { "reports/backups" }),
    [int]$RetentionDays = $(if ($env:XH_BACKUP_RETENTION_DAYS) { [int]$env:XH_BACKUP_RETENTION_DAYS } else { 14 }),
    [string]$PgDumpExe = $(if ($env:PG_DUMP) { $env:PG_DUMP } else { "pg_dump" }),
    [string]$PythonExe = $(if ($env:PYTHON) { $env:PYTHON } else { "python" }),
    [switch]$LogicalOnly,
    [switch]$RequirePgDump,
    [switch]$NoFail
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutputDir = if ([System.IO.Path]::IsPathRooted($OutputDir)) { $OutputDir } else { Join-Path $root $OutputDir }
New-Item -ItemType Directory -Path $resolvedOutputDir -Force | Out-Null
$envPath = Join-Path $root ".env"

function Get-EnvValue {
    param([string]$Key)
    $processValue = [Environment]::GetEnvironmentVariable($Key)
    if (-not [string]::IsNullOrWhiteSpace($processValue)) {
        return $processValue
    }
    if (-not (Test-Path $envPath)) {
        return $null
    }
    foreach ($rawLine in Get-Content -LiteralPath $envPath -Encoding UTF8) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            continue
        }
        $parts = $line.Split("=", 2)
        if ($parts[0].Trim() -eq $Key) {
            return $parts[1].Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

function ConvertFrom-DatabaseUrl {
    param([string]$DatabaseUrl)
    $uri = [Uri]$DatabaseUrl
    $userInfoParts = $uri.UserInfo.Split(":", 2)
    $query = @{}
    if ($uri.Query) {
        foreach ($item in $uri.Query.TrimStart("?").Split("&")) {
            if ([string]::IsNullOrWhiteSpace($item)) {
                continue
            }
            $parts = $item.Split("=", 2)
            $key = [Uri]::UnescapeDataString($parts[0])
            $value = if ($parts.Count -gt 1) { [Uri]::UnescapeDataString($parts[1]) } else { "" }
            $query[$key] = $value
        }
    }
    [ordered]@{
        host = $uri.Host
        port = if ($uri.Port -gt 0) { $uri.Port } else { 5432 }
        database = [Uri]::UnescapeDataString($uri.AbsolutePath.TrimStart("/"))
        username = if ($userInfoParts.Count -ge 1) { [Uri]::UnescapeDataString($userInfoParts[0]) } else { "" }
        password = if ($userInfoParts.Count -ge 2) { [Uri]::UnescapeDataString($userInfoParts[1]) } else { "" }
        sslmode = if ($query.ContainsKey("sslmode")) { $query["sslmode"] } else { $null }
    }
}

function Get-FileSha256 {
    param([string]$Path)
    (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Remove-OldBackups {
    param(
        [string]$Directory,
        [int]$Days
    )
    if ($Days -le 0) {
        return @()
    }
    $resolvedDirectory = (Resolve-Path -LiteralPath $Directory).Path
    $cutoff = (Get-Date).AddDays(-1 * $Days)
    $deleted = New-Object System.Collections.Generic.List[string]
    foreach ($pattern in @("xiaohei-pgdump-*.dump", "pgdump-backup-*.json")) {
        Get-ChildItem -LiteralPath $resolvedDirectory -Filter $pattern -File -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -lt $cutoff } |
            ForEach-Object {
                $candidate = $_.FullName
                if ($candidate.StartsWith($resolvedDirectory, [StringComparison]::OrdinalIgnoreCase)) {
                    Remove-Item -LiteralPath $candidate -Force
                    $deleted.Add($candidate)
                }
            }
    }
    return $deleted
}

function Invoke-LogicalBackup {
    $reportPath = Join-Path $resolvedOutputDir ("logical-backup-$timestamp.json")
    & $PythonExe "packages/db/scripts/db_logical_backup.py" `
        --output-dir $resolvedOutputDir `
        --retention-days $RetentionDays `
        --report-path $reportPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -and -not $NoFail) {
        exit $exitCode
    }
    exit 0
}

$pgDumpCommand = if ($LogicalOnly) { $null } else { Get-Command $PgDumpExe -ErrorAction SilentlyContinue }
if ($null -eq $pgDumpCommand) {
    if ($RequirePgDump) {
        Write-Error "pg_dump is not available and -RequirePgDump was set"
        if (-not $NoFail) { exit 1 }
        exit 0
    }
    Write-Warning "pg_dump is not available; using encrypted-credential-safe logical backup fallback"
    Invoke-LogicalBackup
}

$databaseUrl = Get-EnvValue "XH_DATABASE_URL"
if ([string]::IsNullOrWhiteSpace($databaseUrl)) {
    Write-Error "XH_DATABASE_URL is not configured"
    if (-not $NoFail) { exit 1 }
    exit 0
}

$backupPath = Join-Path $resolvedOutputDir ("xiaohei-pgdump-$timestamp.dump")
$reportPath = Join-Path $resolvedOutputDir ("pgdump-backup-$timestamp.json")
$logPath = Join-Path $resolvedOutputDir ("pgdump-backup-$timestamp.log")
$started = Get-Date

$previousPgPassword = $env:PGPASSWORD
$previousPgSslMode = $env:PGSSLMODE
try {
    $pg = ConvertFrom-DatabaseUrl -DatabaseUrl $databaseUrl
    $env:PGPASSWORD = $pg.password
    if ($pg.sslmode) {
        $env:PGSSLMODE = $pg.sslmode
    }
    $arguments = @(
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file", $backupPath,
        "--host", $pg.host,
        "--port", "$($pg.port)",
        "--username", $pg.username,
        "--dbname", $pg.database
    )
    & $pgDumpCommand.Source @arguments *> $logPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        if ($RequirePgDump) {
            throw "pg_dump failed with exit code $exitCode"
        }
        Write-Warning "pg_dump failed; falling back to logical backup"
        Invoke-LogicalBackup
    }

    $duration = ((Get-Date) - $started).TotalSeconds
    $deleted = Remove-OldBackups -Directory $resolvedOutputDir -Days $RetentionDays
    $report = [ordered]@{
        passed = $true
        format = "postgres.custom"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        duration_seconds = [Math]::Round($duration, 2)
        backup_path = $backupPath
        log_path = $logPath
        size_bytes = (Get-Item -LiteralPath $backupPath).Length
        sha256 = Get-FileSha256 -Path $backupPath
        retention_days = $RetentionDays
        deleted_old_files = $deleted
    }
    $report | ConvertTo-Json -Depth 8 | Set-Content -Path $reportPath -Encoding UTF8
    Get-Content -Raw -LiteralPath $reportPath -Encoding UTF8
} catch {
    $report = [ordered]@{
        passed = $false
        format = "postgres.custom"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        error = $_.Exception.GetType().Name
        message = $_.Exception.Message
    }
    $report | ConvertTo-Json -Depth 8 | Set-Content -Path $reportPath -Encoding UTF8
    Get-Content -Raw -LiteralPath $reportPath -Encoding UTF8
    if (-not $NoFail) {
        exit 1
    }
} finally {
    $env:PGPASSWORD = $previousPgPassword
    $env:PGSSLMODE = $previousPgSslMode
}
