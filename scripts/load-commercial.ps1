param(
    [string]$BaseUrl = $env:XH_LOAD_BASE_URL,
    [string]$Username = $(if ($env:XH_LOAD_USERNAME) { $env:XH_LOAD_USERNAME } else { "tenant_admin" }),
    [int]$Users = $(if ($env:XH_LOAD_USERS) { [int]$env:XH_LOAD_USERS } else { 1000 }),
    [int]$Iterations = $(if ($env:XH_LOAD_ITERATIONS) { [int]$env:XH_LOAD_ITERATIONS } else { 3 }),
    [int]$Concurrency = $(if ($env:XH_LOAD_CONCURRENCY) { [int]$env:XH_LOAD_CONCURRENCY } else { 100 }),
    [int]$WarmupUsers = $(if ($env:XH_LOAD_WARMUP_USERS) { [int]$env:XH_LOAD_WARMUP_USERS } else { 20 }),
    [int]$WarmupConcurrency = $(if ($env:XH_LOAD_WARMUP_CONCURRENCY) { [int]$env:XH_LOAD_WARMUP_CONCURRENCY } else { 5 }),
    [string]$OutputDir = $(if ($env:XH_LOAD_OUTPUT_DIR) { $env:XH_LOAD_OUTPUT_DIR } else { "reports/load" }),
    [double]$MaxErrorRate = $(if ($env:XH_LOAD_MAX_ERROR_RATE) { [double]$env:XH_LOAD_MAX_ERROR_RATE } else { 0.01 }),
    [double]$MaxP95Ms = $(if ($env:XH_LOAD_MAX_P95_MS) { [double]$env:XH_LOAD_MAX_P95_MS } else { 1500 }),
    [double]$MaxP99Ms = $(if ($env:XH_LOAD_MAX_P99_MS) { [double]$env:XH_LOAD_MAX_P99_MS } else { 3000 }),
    [double]$MaxLoginP95Ms = $(if ($env:XH_LOAD_MAX_LOGIN_P95_MS) { [double]$env:XH_LOAD_MAX_LOGIN_P95_MS } else { 2000 }),
    [string]$PythonExe = $(if ($env:PYTHON) { $env:PYTHON } else { "python" }),
    [switch]$NoFail
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    throw "Set XH_LOAD_BASE_URL or pass -BaseUrl before running the real commercial load package."
}

if ([string]::IsNullOrWhiteSpace($env:XH_LOAD_PASSWORD)) {
    throw "Set XH_LOAD_PASSWORD in the environment. Do not pass real passwords on the command line."
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outputPath = Join-Path $OutputDir "commercial-load-$timestamp.json"
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$arguments = @(
    "packages/db/scripts/load_commercial_baseline.py",
    "--base-url", $BaseUrl,
    "--username", $Username,
    "--users", $Users.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "--iterations", $Iterations.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "--concurrency", $Concurrency.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "--warmup-users", $WarmupUsers.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "--warmup-concurrency", $WarmupConcurrency.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "--max-error-rate", $MaxErrorRate.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "--max-p95-ms", $MaxP95Ms.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "--max-p99-ms", $MaxP99Ms.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "--max-login-p95-ms", $MaxLoginP95Ms.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "--output", $outputPath
)

if ($NoFail) {
    $arguments += "--no-fail"
}

Write-Host "Commercial load target: $BaseUrl"
Write-Host "Users=$Users Iterations=$Iterations Concurrency=$Concurrency WarmupUsers=$WarmupUsers"
Write-Host "Output: $outputPath"
Write-Host "Password source: XH_LOAD_PASSWORD"

& $PythonExe @arguments
exit $LASTEXITCODE
