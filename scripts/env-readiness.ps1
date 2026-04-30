param(
    [string]$OutputDir = $(if ($env:XH_RELEASE_OUTPUT_DIR) { $env:XH_RELEASE_OUTPUT_DIR } else { "reports/release" }),
    [switch]$RequireWebhook,
    [switch]$RequireAlertWebhook,
    [switch]$RequireHttps,
    [switch]$NoFail
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$defaultCredentialKey = "xiaohei-erp-dev-store-credential-key"
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

function New-Check {
    param(
        [string]$Name,
        [string]$Status,
        [string]$Message,
        [object]$Details = $null
    )
    [ordered]@{
        name = $Name
        status = $Status
        message = $Message
        details = $Details
    }
}

function Test-PresentSecret {
    param(
        [string]$Name,
        [string]$Key,
        [int]$MinLength = 1,
        [string]$DefaultValue = "",
        [switch]$WarnOnly
    )
    $value = Get-EnvValue $Key
    if ([string]::IsNullOrWhiteSpace($value)) {
        return New-Check -Name $Name -Status $(if ($WarnOnly) { "warn" } else { "fail" }) -Message "$Key is not configured"
    }
    if ($DefaultValue -and $value -eq $DefaultValue) {
        return New-Check -Name $Name -Status $(if ($WarnOnly) { "warn" } else { "fail" }) -Message "$Key still uses the development default"
    }
    if ($value.Length -lt $MinLength) {
        return New-Check -Name $Name -Status $(if ($WarnOnly) { "warn" } else { "fail" }) -Message "$Key is shorter than $MinLength characters" -Details @{ length = $value.Length; min_length = $MinLength }
    }
    return New-Check -Name $Name -Status "ok" -Message "$Key is configured" -Details @{ length = $value.Length }
}

$checks = New-Object System.Collections.Generic.List[object]
$checks.Add((Test-PresentSecret -Name "database_url" -Key "XH_DATABASE_URL" -MinLength 10))
$checks.Add((Test-PresentSecret -Name "store_credential_encryption_key" -Key "XH_STORE_CREDENTIAL_ENCRYPTION_KEY" -MinLength 32 -DefaultValue $defaultCredentialKey))
$checks.Add((Test-PresentSecret -Name "takealot_api_key" -Key "XH_TAKEALOT_API_KEY" -MinLength 32))

$sessionSecure = Get-EnvValue "XH_SESSION_COOKIE_SECURE"
if ($sessionSecure -and $sessionSecure.ToLowerInvariant() -eq "true") {
    $checks.Add((New-Check -Name "session_cookie_secure" -Status "ok" -Message "XH_SESSION_COOKIE_SECURE is true"))
} else {
    $checks.Add((New-Check -Name "session_cookie_secure" -Status $(if ($RequireHttps) { "fail" } else { "warn" }) -Message "Set XH_SESSION_COOKIE_SECURE=true before HTTPS production traffic"))
}

$bootstrapDemo = Get-EnvValue "XH_DB_BOOTSTRAP_DEMO_DATA"
if ($bootstrapDemo -and $bootstrapDemo.ToLowerInvariant() -eq "false") {
    $checks.Add((New-Check -Name "demo_bootstrap" -Status "ok" -Message "Demo bootstrap is disabled"))
} else {
    $checks.Add((New-Check -Name "demo_bootstrap" -Status "warn" -Message "Set XH_DB_BOOTSTRAP_DEMO_DATA=false for paid production traffic"))
}

foreach ($webhookKey in @("XH_TAKEALOT_WEBHOOK_SECRET", "XH_TAKEALOT_WEBHOOK_PUBLIC_URL", "XH_TAKEALOT_WEBHOOK_STORE_ID")) {
    $checks.Add((Test-PresentSecret -Name $webhookKey.ToLowerInvariant() -Key $webhookKey -MinLength 8 -WarnOnly:(!$RequireWebhook)))
}

$checks.Add((Test-PresentSecret -Name "alert_webhook_url" -Key "XH_ALERT_WEBHOOK_URL" -MinLength 10 -WarnOnly:(!$RequireAlertWebhook)))

$failCount = @($checks | Where-Object { $_.status -eq "fail" }).Count
$warnCount = @($checks | Where-Object { $_.status -eq "warn" }).Count
$report = [ordered]@{
    passed = ($failCount -eq 0)
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    summary = [ordered]@{
        ok = @($checks | Where-Object { $_.status -eq "ok" }).Count
        warn = $warnCount
        fail = $failCount
    }
    checks = $checks
}

$resolvedOutputDir = if ([System.IO.Path]::IsPathRooted($OutputDir)) { $OutputDir } else { Join-Path $root $OutputDir }
New-Item -ItemType Directory -Path $resolvedOutputDir -Force | Out-Null
$reportPath = Join-Path $resolvedOutputDir ("env-readiness-{0}.json" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$report | ConvertTo-Json -Depth 8 | Set-Content -Path $reportPath -Encoding UTF8
Write-Host "Environment readiness report: $reportPath"
Get-Content -Raw -LiteralPath $reportPath -Encoding UTF8

if (-not $report.passed -and -not $NoFail) {
    exit 1
}
