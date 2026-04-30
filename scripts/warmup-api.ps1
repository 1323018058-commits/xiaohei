param(
    [string]$BaseUrl = $(if ($env:XH_WARMUP_BASE_URL) { $env:XH_WARMUP_BASE_URL } else { $env:XH_LOAD_BASE_URL }),
    [string]$Username = $(if ($env:XH_WARMUP_USERNAME) { $env:XH_WARMUP_USERNAME } elseif ($env:XH_LOAD_USERNAME) { $env:XH_LOAD_USERNAME } else { "tenant_admin" }),
    [int]$AccountPoolSize = $(if ($env:XH_WARMUP_ACCOUNT_POOL_SIZE) { [int]$env:XH_WARMUP_ACCOUNT_POOL_SIZE } elseif ($env:XH_LOAD_ACCOUNT_POOL_SIZE) { [int]$env:XH_LOAD_ACCOUNT_POOL_SIZE } else { 100 }),
    [int]$Users = $(if ($env:XH_WARMUP_USERS) { [int]$env:XH_WARMUP_USERS } else { 100 }),
    [int]$Iterations = $(if ($env:XH_WARMUP_ITERATIONS) { [int]$env:XH_WARMUP_ITERATIONS } else { 1 }),
    [int]$Concurrency = $(if ($env:XH_WARMUP_CONCURRENCY) { [int]$env:XH_WARMUP_CONCURRENCY } else { 20 }),
    [int]$WarmupUsers = $(if ($env:XH_WARMUP_WARMUP_USERS) { [int]$env:XH_WARMUP_WARMUP_USERS } else { 20 }),
    [int]$WarmupConcurrency = $(if ($env:XH_WARMUP_WARMUP_CONCURRENCY) { [int]$env:XH_WARMUP_WARMUP_CONCURRENCY } else { 10 }),
    [string]$PasswordEnv = $(if ($env:XH_WARMUP_PASSWORD) { "XH_WARMUP_PASSWORD" } else { "XH_LOAD_PASSWORD" }),
    [string]$OutputDir = $(if ($env:XH_WARMUP_OUTPUT_DIR) { $env:XH_WARMUP_OUTPUT_DIR } else { "reports/warmup" }),
    [string]$PythonExe = $(if ($env:PYTHON) { $env:PYTHON } else { "python" }),
    [switch]$NoFail
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    throw "Set XH_WARMUP_BASE_URL or XH_LOAD_BASE_URL before running API warmup."
}

if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($PasswordEnv))) {
    throw "Set $PasswordEnv in the environment. Do not pass real passwords on the command line."
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outputPath = Join-Path $OutputDir "api-warmup-$timestamp.json"
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$arguments = @(
    "packages/db/scripts/load_commercial_baseline.py",
    "--base-url", $BaseUrl,
    "--username", $Username,
    "--password-env", $PasswordEnv,
    "--account-pool-size", $AccountPoolSize.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "--users", $Users.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "--iterations", $Iterations.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "--concurrency", $Concurrency.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "--warmup-users", $WarmupUsers.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "--warmup-concurrency", $WarmupConcurrency.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "--output", $outputPath
)

if ($NoFail) {
    $arguments += "--no-fail"
}

Write-Host "API warmup target: $BaseUrl"
Write-Host "Users=$Users Iterations=$Iterations Concurrency=$Concurrency AccountPool=$AccountPoolSize"
Write-Host "Output: $outputPath"
Write-Host "Password source: $PasswordEnv"

& $PythonExe @arguments
exit $LASTEXITCODE
