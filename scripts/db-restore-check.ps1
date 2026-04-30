param(
    [string]$BackupPath,
    [string]$BackupDir = $(if ($env:XH_BACKUP_OUTPUT_DIR) { $env:XH_BACKUP_OUTPUT_DIR } else { "reports/backups" }),
    [string]$PythonExe = $(if ($env:PYTHON) { $env:PYTHON } else { "python" }),
    [switch]$NoFail
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedBackupDir = if ([System.IO.Path]::IsPathRooted($BackupDir)) { $BackupDir } else { Join-Path $root $BackupDir }
New-Item -ItemType Directory -Path $resolvedBackupDir -Force | Out-Null

$reportPath = Join-Path $resolvedBackupDir ("db-restore-check-$timestamp.json")
$arguments = @(
    "packages/db/scripts/db_restore_check.py",
    "--backup-dir", $resolvedBackupDir,
    "--report-path", $reportPath
)

if (-not [string]::IsNullOrWhiteSpace($BackupPath)) {
    $arguments += @("--backup-path", $BackupPath)
}

if ($NoFail) {
    $arguments += "--no-fail"
}

Write-Host "Database restore check"
Write-Host "Output: $reportPath"
& $PythonExe @arguments
exit $LASTEXITCODE
