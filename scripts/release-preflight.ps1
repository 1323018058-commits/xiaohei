param(
    [string]$OutputDir = $(if ($env:XH_RELEASE_OUTPUT_DIR) { $env:XH_RELEASE_OUTPUT_DIR } else { "reports/release" }),
    [switch]$SkipSmoke,
    [switch]$SkipWarmup,
    [switch]$SkipBackup,
    [switch]$RequireWebhook,
    [switch]$RequireAlertWebhook,
    [switch]$RequireHttps,
    [switch]$NoFail
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutputDir = if ([System.IO.Path]::IsPathRooted($OutputDir)) { $OutputDir } else { Join-Path $root $OutputDir }
New-Item -ItemType Directory -Path $resolvedOutputDir -Force | Out-Null

$steps = New-Object System.Collections.Generic.List[object]

function Add-StepResult {
    param(
        [string]$Name,
        [string]$Status,
        [Nullable[int]]$ExitCode,
        [double]$DurationSeconds,
        [string]$LogPath,
        [string]$Message = ""
    )

    $steps.Add([ordered]@{
        name = $Name
        status = $Status
        exit_code = $ExitCode
        duration_seconds = [Math]::Round($DurationSeconds, 2)
        log_path = if ($LogPath) { Resolve-Path -LiteralPath $LogPath -Relative } else { $null }
        message = $Message
    })
}

function Invoke-PreflightStep {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    $logPath = Join-Path $resolvedOutputDir ("$timestamp-$Name.log")
    Write-Host "==> $Name"
    $started = Get-Date
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Command *> $logPath
        $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }
    } catch {
        $_ | Out-String | Add-Content -Path $logPath -Encoding UTF8
        $exitCode = 1
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $duration = ((Get-Date) - $started).TotalSeconds
    if ($exitCode -eq 0) {
        Add-StepResult -Name $Name -Status "passed" -ExitCode $exitCode -DurationSeconds $duration -LogPath $logPath
        return
    }

    Add-StepResult -Name $Name -Status "failed" -ExitCode $exitCode -DurationSeconds $duration -LogPath $logPath
    if (-not $NoFail) {
        throw "Release preflight step failed: $Name"
    }
}

function Add-SkippedStep {
    param(
        [string]$Name,
        [string]$Message
    )
    Add-StepResult -Name $Name -Status "skipped" -ExitCode $null -DurationSeconds 0 -LogPath $null -Message $Message
    Write-Host "==> $Name skipped: $Message"
}

$overallStarted = Get-Date

try {
    Invoke-PreflightStep -Name "compileall" -Command {
        python -m compileall apps/api packages/db/scripts
    }

    Invoke-PreflightStep -Name "env-readiness" -Command {
        $args = @("powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts/env-readiness.ps1")
        if ($RequireWebhook) {
            $args += "-RequireWebhook"
        }
        if ($RequireAlertWebhook) {
            $args += "-RequireAlertWebhook"
        }
        if ($RequireHttps) {
            $args += "-RequireHttps"
        }
        if ($NoFail) {
            $args += "-NoFail"
        }
        & $args[0] $args[1..($args.Length - 1)]
    }

    if ($SkipSmoke) {
        Add-SkippedStep -Name "db-smoke" -Message "Skipped by -SkipSmoke"
        Add-SkippedStep -Name "db-smoke-subscription" -Message "Skipped by -SkipSmoke"
    } else {
        Invoke-PreflightStep -Name "db-smoke" -Command {
            npm.cmd run db:smoke
        }

        Invoke-PreflightStep -Name "db-smoke-subscription" -Command {
            npm.cmd run db:smoke:subscription
        }
    }

    if ($SkipBackup) {
        Add-SkippedStep -Name "db-backup" -Message "Skipped by -SkipBackup"
        Add-SkippedStep -Name "db-restore-check" -Message "Skipped by -SkipBackup"
    } else {
        Invoke-PreflightStep -Name "db-backup" -Command {
            npm.cmd run db:backup
        }

        Invoke-PreflightStep -Name "db-restore-check" -Command {
            npm.cmd run db:restore:check
        }
    }

    Invoke-PreflightStep -Name "ops-data-check" -Command {
        npm.cmd run ops:data:check
    }

    Invoke-PreflightStep -Name "worker-once" -Command {
        npm.cmd run worker:api:ps:once
    }

    Invoke-PreflightStep -Name "worker-schedule-dry" -Command {
        npm.cmd run worker:schedule:dry
    }

    if ($SkipWarmup) {
        Add-SkippedStep -Name "api-warmup" -Message "Skipped by -SkipWarmup"
    } elseif ([string]::IsNullOrWhiteSpace($env:XH_LOAD_BASE_URL) -or [string]::IsNullOrWhiteSpace($env:XH_LOAD_PASSWORD)) {
        Add-SkippedStep -Name "api-warmup" -Message "Set XH_LOAD_BASE_URL and XH_LOAD_PASSWORD to include deploy warmup"
    } else {
        Invoke-PreflightStep -Name "api-warmup" -Command {
            npm.cmd run api:warmup -- -NoFail
        }
    }

    Invoke-PreflightStep -Name "ops-guardrails-strict" -Command {
        npm.cmd run ops:guardrails:strict
    }

    Invoke-PreflightStep -Name "alert-channel-test" -Command {
        $args = @("powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts/test-alert-channel.ps1")
        if ($RequireAlertWebhook) {
            $args += "-RequireWebhook"
        }
        & $args[0] $args[1..($args.Length - 1)]
    }
} finally {
    $overallDuration = ((Get-Date) - $overallStarted).TotalSeconds
    $failedCount = @($steps | Where-Object { $_.status -eq "failed" }).Count
    $skippedCount = @($steps | Where-Object { $_.status -eq "skipped" }).Count
    $report = [ordered]@{
        passed = ($failedCount -eq 0)
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        duration_seconds = [Math]::Round($overallDuration, 2)
        summary = [ordered]@{
            passed = @($steps | Where-Object { $_.status -eq "passed" }).Count
            failed = $failedCount
            skipped = $skippedCount
        }
        steps = $steps
    }
    $reportPath = Join-Path $resolvedOutputDir ("release-preflight-$timestamp.json")
    $report | ConvertTo-Json -Depth 8 | Set-Content -Path $reportPath -Encoding UTF8
    Write-Host "Release preflight report: $reportPath"
}
