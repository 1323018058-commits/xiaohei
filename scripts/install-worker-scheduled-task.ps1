param(
    [switch]$Install,
    [string]$TaskName = "XiaoheiERPWorker",
    [double]$PollInterval = 2.0,
    [double]$IdleLogInterval = 60.0,
    [string]$PythonExe = "python",
    [string]$LogDir = "reports/runtime"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $root "scripts/worker-api.ps1"
$arguments = @(
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    "`"$scriptPath`"",
    "-PollInterval",
    $PollInterval.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "-IdleLogInterval",
    $IdleLogInterval.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    "-PythonExe",
    "`"$PythonExe`"",
    "-LogDir",
    "`"$LogDir`""
) -join " "

Write-Host "Worker supervisor: Windows Task Scheduler"
Write-Host "TaskName: $TaskName"
Write-Host "WorkingDirectory: $root"
Write-Host "Command: powershell $arguments"

if (-not $Install) {
    Write-Host "Dry run only. Re-run with -Install from an elevated PowerShell to register the task."
    exit 0
}

$action = New-ScheduledTaskAction `
    -Execute "powershell" `
    -Argument $arguments `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
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
