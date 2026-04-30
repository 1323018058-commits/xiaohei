param(
    [string]$AlertDir = $(if ($env:XH_ALERT_OUTPUT_DIR) { $env:XH_ALERT_OUTPUT_DIR } else { "reports/alerts" }),
    [string]$WebhookUrl = $env:XH_ALERT_WEBHOOK_URL,
    [string]$OutputDir = $(if ($env:XH_RELEASE_OUTPUT_DIR) { $env:XH_RELEASE_OUTPUT_DIR } else { "reports/release" }),
    [switch]$RequireWebhook
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedAlertDir = if ([System.IO.Path]::IsPathRooted($AlertDir)) { $AlertDir } else { Join-Path $root $AlertDir }
$resolvedOutputDir = if ([System.IO.Path]::IsPathRooted($OutputDir)) { $OutputDir } else { Join-Path $root $OutputDir }
New-Item -ItemType Directory -Path $resolvedAlertDir -Force | Out-Null
New-Item -ItemType Directory -Path $resolvedOutputDir -Force | Out-Null

$alert = [ordered]@{
    event = "commercial_ops_alert_channel_test"
    severity = "info"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    source = "scripts/test-alert-channel.ps1"
    message = "Xiaohei ERP alert channel test"
    details = [ordered]@{
        host = $env:COMPUTERNAME
        cwd = $root
    }
}
$alertJson = $alert | ConvertTo-Json -Depth 6
$alertPath = Join-Path $resolvedAlertDir "ops-alert-channel-test-$timestamp.json"
Set-Content -Path $alertPath -Value $alertJson -Encoding UTF8

$webhookStatus = "skipped"
$webhookMessage = "XH_ALERT_WEBHOOK_URL is not configured"
if (-not [string]::IsNullOrWhiteSpace($WebhookUrl)) {
    try {
        Invoke-RestMethod `
            -Method Post `
            -Uri $WebhookUrl `
            -ContentType "application/json" `
            -Body $alertJson `
            -TimeoutSec 10 | Out-Null
        $webhookStatus = "delivered"
        $webhookMessage = "webhook delivered"
    } catch {
        $webhookStatus = "failed"
        $webhookMessage = "webhook delivery failed"
    }
}

$passed = ($webhookStatus -eq "delivered") -or (-not $RequireWebhook)
$report = [ordered]@{
    passed = $passed
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    local_alert = [ordered]@{
        status = "written"
        path = $alertPath
    }
    webhook = [ordered]@{
        configured = -not [string]::IsNullOrWhiteSpace($WebhookUrl)
        status = $webhookStatus
        message = $webhookMessage
        required = [bool]$RequireWebhook
    }
}
$reportPath = Join-Path $resolvedOutputDir "alert-channel-test-$timestamp.json"
$report | ConvertTo-Json -Depth 6 | Set-Content -Path $reportPath -Encoding UTF8

Write-Host "Alert channel report: $reportPath"
Get-Content -Raw -LiteralPath $reportPath -Encoding UTF8

if (-not $passed) {
    exit 1
}
