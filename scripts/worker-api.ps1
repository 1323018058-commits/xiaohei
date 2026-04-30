param(
    [switch]$Once,
    [double]$PollInterval = 2.0,
    [double]$IdleLogInterval = 60.0,
    [string]$PythonExe = "python",
    [string]$LogDir = $(if ($env:XH_WORKER_LOG_DIR) { $env:XH_WORKER_LOG_DIR } else { "reports/runtime" }),
    [int]$RetentionDays = $(if ($env:XH_WORKER_LOG_RETENTION_DAYS) { [int]$env:XH_WORKER_LOG_RETENTION_DAYS } else { 14 }),
    [switch]$NoLog
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$arguments = @("apps/api/worker_main.py")
if ($Once) {
    $arguments += "--once"
} else {
    $arguments += "--poll-interval"
    $arguments += $PollInterval.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    $arguments += "--idle-log-interval"
    $arguments += $IdleLogInterval.ToString([System.Globalization.CultureInfo]::InvariantCulture)
}

Write-Host "Starting store worker from $root"
Write-Host "$PythonExe $($arguments -join ' ')"

if ($NoLog) {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $PythonExe @arguments
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    exit $exitCode
}

$resolvedLogDir = if ([System.IO.Path]::IsPathRooted($LogDir)) { $LogDir } else { Join-Path $root $LogDir }
New-Item -ItemType Directory -Path $resolvedLogDir -Force | Out-Null

$cutoff = (Get-Date).AddDays(-1 * $RetentionDays)
Get-ChildItem -Path $resolvedLogDir -Filter "worker*.log" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    Remove-Item -Force

$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$supervisorLogPath = Join-Path $resolvedLogDir ("worker-supervisor-{0}.log" -f (Get-Date -Format "yyyyMMdd"))
$stdoutPath = Join-Path $resolvedLogDir ("worker-{0}.out.log" -f $runId)
$stderrPath = Join-Path $resolvedLogDir ("worker-{0}.err.log" -f $runId)
$startRecord = @{
    event = "worker.process_start"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    once = [bool]$Once
    poll_interval = $PollInterval
    idle_log_interval = $IdleLogInterval
    retention_days = $RetentionDays
    stdout_path = $stdoutPath
    stderr_path = $stderrPath
} | ConvertTo-Json -Compress
Add-Content -Path $supervisorLogPath -Value $startRecord -Encoding UTF8
Write-Host "Supervisor log: $supervisorLogPath"
Write-Host "Worker stdout: $stdoutPath"
Write-Host "Worker stderr: $stderrPath"

$process = Start-Process `
    -FilePath $PythonExe `
    -ArgumentList $arguments `
    -WorkingDirectory $root `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -NoNewWindow `
    -Wait `
    -PassThru
$exitCode = $process.ExitCode

$stopRecord = @{
    event = "worker.process_stop"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    exit_code = $exitCode
} | ConvertTo-Json -Compress
Add-Content -Path $supervisorLogPath -Value $stopRecord -Encoding UTF8

exit $exitCode
