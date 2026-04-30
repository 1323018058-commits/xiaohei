param(
    [switch]$Install,
    [string]$TaskName = "XiaoheiERPOpsGuardrails",
    [int]$IntervalMinutes = $(if ($env:XH_OPS_SCHEDULE_INTERVAL_MINUTES) { [int]$env:XH_OPS_SCHEDULE_INTERVAL_MINUTES } else { 15 })
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $root "scripts/ops-guardrails.ps1"
$arguments = @(
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    "`"$scriptPath`"",
    "-Strict"
) -join " "

Write-Host "Ops guardrails supervisor: Windows Task Scheduler"
Write-Host "TaskName: $TaskName"
Write-Host "WorkingDirectory: $root"
Write-Host "IntervalMinutes: $IntervalMinutes"
Write-Host "Command: powershell $arguments"

if (-not $Install) {
    Write-Host "Dry run only. Re-run with -Install from an elevated PowerShell to register the task."
    exit 0
}

$action = New-ScheduledTaskAction `
    -Execute "powershell" `
    -Argument $arguments `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "Registered $TaskName. Start it with:"
Write-Host "Start-ScheduledTask -TaskName `"$TaskName`""
