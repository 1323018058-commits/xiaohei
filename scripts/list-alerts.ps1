param(
    [string]$AlertDir = $(if ($env:XH_ALERT_OUTPUT_DIR) { $env:XH_ALERT_OUTPUT_DIR } else { "reports/alerts" }),
    [int]$Limit = 10,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$resolvedAlertDir = if ([System.IO.Path]::IsPathRooted($AlertDir)) { $AlertDir } else { Join-Path $root $AlertDir }
if (-not (Test-Path $resolvedAlertDir)) {
    if ($Json) {
        @() | ConvertTo-Json
    } else {
        Write-Host "No alert directory found: $resolvedAlertDir"
    }
    exit 0
}

$alerts = Get-ChildItem -Path $resolvedAlertDir -Filter "*.json" -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First $Limit |
    ForEach-Object {
        $payload = $null
        try {
            $payload = Get-Content -Raw -LiteralPath $_.FullName -Encoding UTF8 | ConvertFrom-Json
        } catch {
            $payload = $null
        }
        [ordered]@{
            path = $_.FullName
            last_write_time = $_.LastWriteTime.ToUniversalTime().ToString("o")
            event = if ($payload) { $payload.event } else { $null }
            severity = if ($payload) { $payload.severity } else { $null }
            generated_at = if ($payload) { $payload.generated_at } else { $null }
            summary = if ($payload) { $payload.summary } else { $null }
            message = if ($payload) { $payload.message } else { $null }
        }
    }

if ($Json) {
    $alerts | ConvertTo-Json -Depth 6
    exit 0
}

foreach ($alert in $alerts) {
    Write-Host ("[{0}] {1} {2}" -f $alert.severity, $alert.event, $alert.generated_at)
    Write-Host ("  {0}" -f $alert.path)
    if ($alert.message) {
        Write-Host ("  {0}" -f $alert.message)
    }
}
