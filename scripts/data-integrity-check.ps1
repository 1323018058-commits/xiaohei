param(
    [string]$OutputDir = $(if ($env:XH_OPS_OUTPUT_DIR) { $env:XH_OPS_OUTPUT_DIR } else { "reports/ops" }),
    [string]$PythonExe = $(if ($env:PYTHON) { $env:PYTHON } else { "python" }),
    [switch]$Strict,
    [switch]$NoFail
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutputDir = if ([System.IO.Path]::IsPathRooted($OutputDir)) { $OutputDir } else { Join-Path $root $OutputDir }
New-Item -ItemType Directory -Path $resolvedOutputDir -Force | Out-Null
$outputPath = Join-Path $resolvedOutputDir "data-integrity-$timestamp.json"

$arguments = @(
    "packages/db/scripts/data_integrity_check.py",
    "--output", $outputPath
)

if ($Strict) {
    $arguments += "--strict"
}

if ($NoFail) {
    $arguments += "--no-fail"
}

Write-Host "Data integrity check"
Write-Host "Output: $outputPath"
& $PythonExe @arguments
exit $LASTEXITCODE
