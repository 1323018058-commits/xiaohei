param(
    [string]$TaskName = "XiaoheiERPWorker",
    [string]$OpsTaskName = "XiaoheiERPOpsGuardrails",
    [string]$RuntimeDir = $(if ($env:XH_WORKER_LOG_DIR) { $env:XH_WORKER_LOG_DIR } else { "reports/runtime" }),
    [string]$OutputDir = $(if ($env:XH_RELEASE_OUTPUT_DIR) { $env:XH_RELEASE_OUTPUT_DIR } else { "reports/release" }),
    [int]$MaxWorkerHeartbeatSeconds = $(if ($env:XH_WORKER_MAX_HEARTBEAT_SECONDS) { [int]$env:XH_WORKER_MAX_HEARTBEAT_SECONDS } else { 180 }),
    [double]$MaxBackupAgeHours = $(if ($env:XH_BACKUP_MAX_AGE_HOURS) { [double]$env:XH_BACKUP_MAX_AGE_HOURS } else { 24 }),
    [switch]$NoFail
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

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

function Get-LatestJsonFile {
    param(
        [string]$Directory,
        [string]$Filter
    )
    if (-not (Test-Path $Directory)) {
        return $null
    }
    Get-ChildItem -Path $Directory -Filter $Filter -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

function Get-LastJsonLine {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return $null
    }
    $lines = Get-Content -Tail 20 -LiteralPath $Path -Encoding UTF8
    for ($index = $lines.Count - 1; $index -ge 0; $index--) {
        $line = [string]$lines[$index]
        if ($line.TrimStart().StartsWith("{")) {
            try {
                return $line | ConvertFrom-Json
            } catch {
                continue
            }
        }
    }
    return $null
}

function Get-LatestWorkerHeartbeat {
    param([string]$Directory)
    if (-not (Test-Path $Directory)) {
        return $null
    }
    $files = Get-ChildItem -Path $Directory -Filter "worker-*.out.log" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 20
    foreach ($file in $files) {
        $heartbeat = Get-LastJsonLine -Path $file.FullName
        if ($null -ne $heartbeat -and $heartbeat.generated_at) {
            return [ordered]@{
                path = $file.FullName
                heartbeat = $heartbeat
            }
        }
    }
    return $null
}

function Get-ReportAgeHours {
    param([object]$Report)
    if ($null -eq $Report -or -not $Report.generated_at) {
        return $null
    }
    try {
        $generatedAt = [DateTimeOffset]::Parse($Report.generated_at)
        return ([DateTimeOffset]::UtcNow - $generatedAt.ToUniversalTime()).TotalHours
    } catch {
        return $null
    }
}

$checks = New-Object System.Collections.Generic.List[object]

try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName
    $taskDetails = [ordered]@{
        task_name = $task.TaskName
        state = $task.State.ToString()
        task_path = $task.TaskPath
        last_run_time = $taskInfo.LastRunTime
        last_task_result = $taskInfo.LastTaskResult
        number_of_missed_runs = $taskInfo.NumberOfMissedRuns
    }
    $taskStatus = if ($task.State.ToString() -eq "Running") { "ok" } else { "warn" }
    $taskMessage = if ($taskStatus -eq "ok") { "scheduled worker is running" } else { "scheduled worker exists but is not running" }
    $checks.Add((New-Check -Name "scheduled_task" -Status $taskStatus -Message $taskMessage -Details $taskDetails))
} catch {
    $checks.Add((New-Check -Name "scheduled_task" -Status "fail" -Message "scheduled worker task is not installed"))
}

try {
    $opsTask = Get-ScheduledTask -TaskName $OpsTaskName -ErrorAction Stop
    $opsTaskInfo = Get-ScheduledTaskInfo -TaskName $OpsTaskName
    $opsDetails = [ordered]@{
        task_name = $opsTask.TaskName
        state = $opsTask.State.ToString()
        task_path = $opsTask.TaskPath
        last_run_time = $opsTaskInfo.LastRunTime
        last_task_result = $opsTaskInfo.LastTaskResult
        next_run_time = $opsTaskInfo.NextRunTime
        number_of_missed_runs = $opsTaskInfo.NumberOfMissedRuns
    }
    $opsStatus = if ($opsTaskInfo.LastTaskResult -eq 0) { "ok" } else { "warn" }
    $opsMessage = if ($opsStatus -eq "ok") { "ops guardrails task is installed and last run succeeded" } else { "ops guardrails task is installed but last result is not clean" }
    $checks.Add((New-Check -Name "ops_scheduled_task" -Status $opsStatus -Message $opsMessage -Details $opsDetails))
} catch {
    $checks.Add((New-Check -Name "ops_scheduled_task" -Status "fail" -Message "ops guardrails scheduled task is not installed"))
}

$resolvedRuntimeDir = if ([System.IO.Path]::IsPathRooted($RuntimeDir)) { $RuntimeDir } else { Join-Path $root $RuntimeDir }
$latestWorkerHeartbeat = Get-LatestWorkerHeartbeat -Directory $resolvedRuntimeDir
if ($null -eq $latestWorkerHeartbeat) {
    $checks.Add((New-Check -Name "worker_heartbeat" -Status "fail" -Message "no worker stdout log found"))
} else {
    $heartbeat = $latestWorkerHeartbeat.heartbeat
    if ($null -eq $heartbeat -or -not $heartbeat.generated_at) {
        $checks.Add((New-Check -Name "worker_heartbeat" -Status "fail" -Message "worker stdout log does not contain a JSON heartbeat" -Details @{ path = $latestWorkerHeartbeat.path }))
    } else {
        $generatedAt = [DateTimeOffset]::Parse($heartbeat.generated_at)
        $ageSeconds = ([DateTimeOffset]::UtcNow - $generatedAt.ToUniversalTime()).TotalSeconds
        $status = if ($ageSeconds -le $MaxWorkerHeartbeatSeconds) { "ok" } else { "fail" }
        $message = if ($status -eq "ok") { "worker heartbeat is fresh" } else { "worker heartbeat is stale" }
        $checks.Add((New-Check -Name "worker_heartbeat" -Status $status -Message $message -Details ([ordered]@{
            path = $latestWorkerHeartbeat.path
            generated_at = $heartbeat.generated_at
            age_seconds = [Math]::Round($ageSeconds, 2)
            max_age_seconds = $MaxWorkerHeartbeatSeconds
            processed_count = $heartbeat.processed_count
        })))
    }
}

$latestOps = Get-LatestJsonFile -Directory (Join-Path $root "reports/ops") -Filter "commercial-ops-*.json"
if ($null -eq $latestOps) {
    $checks.Add((New-Check -Name "ops_guardrails" -Status "fail" -Message "no ops guardrail report found"))
} else {
    $opsReport = Get-Content -Raw -LiteralPath $latestOps.FullName -Encoding UTF8 | ConvertFrom-Json
    $status = if ($opsReport.passed -and [int]$opsReport.summary.fail -eq 0 -and [int]$opsReport.summary.warn -eq 0) { "ok" } else { "fail" }
    $checks.Add((New-Check -Name "ops_guardrails" -Status $status -Message "latest ops guardrail report checked" -Details ([ordered]@{
        path = $latestOps.FullName
        passed = $opsReport.passed
        strict = $opsReport.strict
        summary = $opsReport.summary
    })))
}

$latestRelease = Get-LatestJsonFile -Directory (Join-Path $root "reports/release") -Filter "release-preflight-*.json"
if ($null -eq $latestRelease) {
    $checks.Add((New-Check -Name "release_preflight" -Status "warn" -Message "no release preflight report found"))
} else {
    $releaseReport = Get-Content -Raw -LiteralPath $latestRelease.FullName -Encoding UTF8 | ConvertFrom-Json
    $status = if ($releaseReport.passed) { "ok" } else { "fail" }
    $checks.Add((New-Check -Name "release_preflight" -Status $status -Message "latest release preflight report checked" -Details ([ordered]@{
        path = $latestRelease.FullName
        passed = $releaseReport.passed
        summary = $releaseReport.summary
    })))
}

$latestEnvReadiness = Get-LatestJsonFile -Directory (Join-Path $root "reports/release") -Filter "env-readiness-*.json"
if ($null -eq $latestEnvReadiness) {
    $checks.Add((New-Check -Name "env_readiness" -Status "warn" -Message "no environment readiness report found"))
} else {
    $envReport = Get-Content -Raw -LiteralPath $latestEnvReadiness.FullName -Encoding UTF8 | ConvertFrom-Json
    $envStatus = if (-not $envReport.passed) { "fail" } elseif ([int]$envReport.summary.warn -gt 0) { "warn" } else { "ok" }
    $checks.Add((New-Check -Name "env_readiness" -Status $envStatus -Message "latest environment readiness report checked" -Details ([ordered]@{
        path = $latestEnvReadiness.FullName
        passed = $envReport.passed
        summary = $envReport.summary
    })))
}

$latestRestoreCheck = Get-LatestJsonFile -Directory (Join-Path $root "reports/backups") -Filter "db-restore-check-*.json"
if ($null -eq $latestRestoreCheck) {
    $checks.Add((New-Check -Name "backup_restore_check" -Status "warn" -Message "no backup restore-check report found"))
} else {
    $restoreReport = Get-Content -Raw -LiteralPath $latestRestoreCheck.FullName -Encoding UTF8 | ConvertFrom-Json
    $ageHours = Get-ReportAgeHours -Report $restoreReport
    $restoreStatus = if (-not $restoreReport.passed) { "fail" } elseif ($null -eq $ageHours -or $ageHours -gt $MaxBackupAgeHours) { "warn" } else { "ok" }
    $restoreMessage = if ($restoreStatus -eq "ok") { "latest backup restore-check is fresh and passed" } elseif ($restoreStatus -eq "warn") { "latest backup restore-check is stale or missing timestamp" } else { "latest backup restore-check failed" }
    $checks.Add((New-Check -Name "backup_restore_check" -Status $restoreStatus -Message $restoreMessage -Details ([ordered]@{
        path = $latestRestoreCheck.FullName
        passed = $restoreReport.passed
        age_hours = if ($null -ne $ageHours) { [Math]::Round($ageHours, 2) } else { $null }
        max_age_hours = $MaxBackupAgeHours
        backup_path = $restoreReport.backup_path
        table_count = $restoreReport.table_count
        total_rows = $restoreReport.total_rows
    })))
}

$latestDataIntegrity = Get-LatestJsonFile -Directory (Join-Path $root "reports/ops") -Filter "data-integrity-*.json"
if ($null -eq $latestDataIntegrity) {
    $checks.Add((New-Check -Name "data_integrity" -Status "warn" -Message "no data integrity report found"))
} else {
    $dataReport = Get-Content -Raw -LiteralPath $latestDataIntegrity.FullName -Encoding UTF8 | ConvertFrom-Json
    $dataStatus = if (-not $dataReport.passed) { "fail" } elseif ([int]$dataReport.summary.warn -gt 0) { "warn" } else { "ok" }
    $checks.Add((New-Check -Name "data_integrity" -Status $dataStatus -Message "latest data integrity report checked" -Details ([ordered]@{
        path = $latestDataIntegrity.FullName
        passed = $dataReport.passed
        summary = $dataReport.summary
    })))
}

if ([string]::IsNullOrWhiteSpace($env:XH_ALERT_WEBHOOK_URL)) {
    $checks.Add((New-Check -Name "alert_webhook" -Status "warn" -Message "XH_ALERT_WEBHOOK_URL is not configured; local alert files still work"))
} else {
    $checks.Add((New-Check -Name "alert_webhook" -Status "ok" -Message "XH_ALERT_WEBHOOK_URL is configured"))
}

$latestAlertTest = Get-LatestJsonFile -Directory (Join-Path $root "reports/release") -Filter "alert-channel-test-*.json"
if ($null -eq $latestAlertTest) {
    $checks.Add((New-Check -Name "alert_channel_test" -Status "warn" -Message "no alert channel test report found"))
} else {
    $alertTestReport = Get-Content -Raw -LiteralPath $latestAlertTest.FullName -Encoding UTF8 | ConvertFrom-Json
    $alertTestStatus = if ($alertTestReport.passed) { "ok" } else { "fail" }
    $checks.Add((New-Check -Name "alert_channel_test" -Status $alertTestStatus -Message "latest alert channel test checked" -Details ([ordered]@{
        path = $latestAlertTest.FullName
        passed = $alertTestReport.passed
        local_alert = $alertTestReport.local_alert
        webhook = $alertTestReport.webhook
    })))
}

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
$reportPath = Join-Path $resolvedOutputDir ("host-activation-{0}.json" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$report | ConvertTo-Json -Depth 8 | Set-Content -Path $reportPath -Encoding UTF8
Write-Host "Host activation report: $reportPath"
Get-Content -Raw -LiteralPath $reportPath -Encoding UTF8

if (-not $report.passed -and -not $NoFail) {
    exit 1
}
