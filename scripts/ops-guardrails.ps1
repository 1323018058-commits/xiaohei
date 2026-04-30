param(
    [string]$OutputDir = $(if ($env:XH_OPS_OUTPUT_DIR) { $env:XH_OPS_OUTPUT_DIR } else { "reports/ops" }),
    [string]$AlertDir = $(if ($env:XH_ALERT_OUTPUT_DIR) { $env:XH_ALERT_OUTPUT_DIR } else { "reports/alerts" }),
    [string]$AlertWebhookUrl = $env:XH_ALERT_WEBHOOK_URL,
    [string]$PythonExe = $(if ($env:PYTHON) { $env:PYTHON } else { "python" }),
    [switch]$Strict,
    [switch]$NoFail,
    [switch]$IncludeTestArtifacts,
    [switch]$AlertOnWarn = $(if ($env:XH_ALERT_ON_WARN) { [System.Convert]::ToBoolean($env:XH_ALERT_ON_WARN) } else { $true }),
    [switch]$RequireAlertDelivery = $(if ($env:XH_ALERT_REQUIRE_DELIVERY) { [System.Convert]::ToBoolean($env:XH_ALERT_REQUIRE_DELIVERY) } else { $false })
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outputPath = Join-Path $OutputDir "commercial-ops-$timestamp.json"
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$arguments = @(
    "packages/db/scripts/commercial_ops_guardrails.py",
    "--output", $outputPath
)

if ($Strict) {
    $arguments += "--strict"
}

if ($NoFail) {
    $arguments += "--no-fail"
}

if ($IncludeTestArtifacts) {
    $arguments += "--include-test-artifacts"
}

Write-Host "Commercial ops guardrails"
Write-Host "Output: $outputPath"

& $PythonExe @arguments
$exitCode = $LASTEXITCODE

if (-not (Test-Path $outputPath)) {
    exit $exitCode
}

$report = Get-Content -Raw -Path $outputPath -Encoding UTF8 | ConvertFrom-Json
$warnCount = [int]$report.summary.warn
$failCount = [int]$report.summary.fail
$shouldAlert = ($failCount -gt 0) -or ($AlertOnWarn -and $warnCount -gt 0)

if ($shouldAlert) {
    New-Item -ItemType Directory -Path $AlertDir -Force | Out-Null
    $severity = if ($failCount -gt 0) { "critical" } else { "warning" }
    $alertPath = Join-Path $AlertDir ("ops-alert-$timestamp.json")
    $alert = [ordered]@{
        event = "commercial_ops_guardrail_alert"
        severity = $severity
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        strict = [bool]$Strict
        report_path = $outputPath
        summary = $report.summary
        failed_checks = @(
            $report.checks |
                Where-Object { $_.status -eq "fail" } |
                ForEach-Object { [ordered]@{ name = $_.name; message = $_.message } }
        )
        warning_checks = @(
            $report.checks |
                Where-Object { $_.status -eq "warn" } |
                ForEach-Object { [ordered]@{ name = $_.name; message = $_.message } }
        )
    }
    $alertJson = $alert | ConvertTo-Json -Depth 8
    Set-Content -Path $alertPath -Value $alertJson -Encoding UTF8
    Write-Host "Alert: $alertPath"

    if (-not [string]::IsNullOrWhiteSpace($AlertWebhookUrl)) {
        try {
            Invoke-RestMethod `
                -Method Post `
                -Uri $AlertWebhookUrl `
                -ContentType "application/json" `
                -Body $alertJson `
                -TimeoutSec 10 | Out-Null
            Write-Host "Alert webhook delivered"
        } catch {
            Write-Warning "Alert webhook delivery failed"
            if ($RequireAlertDelivery) {
                exit 2
            }
        }
    }
}

exit $exitCode
