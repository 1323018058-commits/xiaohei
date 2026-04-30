param(
    [string]$EnvPath = ".env",
    [string]$OldKey = "xiaohei-erp-dev-store-credential-key",
    [string]$NewKey = "",
    [switch]$Force,
    [switch]$NoRestartWorker
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$resolvedEnvPath = if ([System.IO.Path]::IsPathRooted($EnvPath)) { $EnvPath } else { Join-Path $root $EnvPath }

function Get-EnvFileValue {
    param([string]$Key)
    if (-not (Test-Path $resolvedEnvPath)) {
        return $null
    }
    foreach ($rawLine in Get-Content -LiteralPath $resolvedEnvPath -Encoding UTF8) {
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

function Set-EnvFileValue {
    param(
        [string]$Key,
        [string]$Value
    )
    $lines = New-Object System.Collections.Generic.List[string]
    $updated = $false
    if (Test-Path $resolvedEnvPath) {
        foreach ($rawLine in Get-Content -LiteralPath $resolvedEnvPath -Encoding UTF8) {
            if ($rawLine.TrimStart().StartsWith("$Key=")) {
                $lines.Add("$Key=$Value")
                $updated = $true
            } else {
                $lines.Add($rawLine)
            }
        }
    }
    if (-not $updated) {
        $lines.Add("$Key=$Value")
    }
    Set-Content -LiteralPath $resolvedEnvPath -Value $lines -Encoding UTF8
}

function New-RandomSecret {
    $bytes = New-Object byte[] 48
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($bytes)
}

$currentKey = Get-EnvFileValue "XH_STORE_CREDENTIAL_ENCRYPTION_KEY"
if (-not [string]::IsNullOrWhiteSpace($currentKey) -and -not $Force) {
    Write-Host "XH_STORE_CREDENTIAL_ENCRYPTION_KEY already exists in .env. Use -Force to rotate it."
    exit 0
}

if ([string]::IsNullOrWhiteSpace($NewKey)) {
    $NewKey = New-RandomSecret
}
if ($NewKey.Length -lt 32) {
    throw "New key must be at least 32 characters."
}
if ($NewKey -eq $OldKey) {
    throw "New key must be different from old key."
}

$wasWorkerRunning = $false
try {
    $workerTask = Get-ScheduledTask -TaskName "XiaoheiERPWorker" -ErrorAction Stop
    if ($workerTask.State.ToString() -eq "Running" -and -not $NoRestartWorker) {
        $wasWorkerRunning = $true
        Stop-ScheduledTask -TaskName "XiaoheiERPWorker"
        Start-Sleep -Seconds 3
    }
} catch {
    $wasWorkerRunning = $false
}

$env:XH_ROTATE_OLD_KEY = $OldKey
$env:XH_ROTATE_NEW_KEY = $NewKey
@'
import os
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "apps" / "api"))

from src.platform.db.session import get_db_session

old_key = os.environ["XH_ROTATE_OLD_KEY"]
new_key = os.environ["XH_ROTATE_NEW_KEY"]

with get_db_session() as connection:
    try:
        with connection.cursor() as cursor:
            total = cursor.execute(
                """
                select count(*) as count
                from store_credentials
                where api_key_encrypted like '-----BEGIN PGP MESSAGE-----%%'
                """
            ).fetchone()["count"]
            skipped = cursor.execute(
                """
                select count(*) as count
                from store_credentials
                where api_key_encrypted not like '-----BEGIN PGP MESSAGE-----%%'
                """
            ).fetchone()["count"]
            cursor.execute(
                """
                update store_credentials
                set api_key_encrypted = armor(
                      pgp_sym_encrypt(
                        pgp_sym_decrypt(dearmor(api_key_encrypted), %s),
                        %s
                      )
                    ),
                    updated_at = now()
                where api_key_encrypted like '-----BEGIN PGP MESSAGE-----%%'
                """,
                (old_key, new_key),
            )
            updated = cursor.rowcount
            verified = cursor.execute(
                """
                select count(*) as count
                from store_credentials
                where pgp_sym_decrypt(dearmor(api_key_encrypted), %s) is not null
                  and api_key_encrypted like '-----BEGIN PGP MESSAGE-----%%'
                """,
                (new_key,),
            ).fetchone()["count"]
        if verified != total:
            raise RuntimeError(f"Verified {verified} of {total} credentials after rotation")
        connection.commit()
        print({"credential_count": total, "updated_count": updated, "verified_count": verified, "skipped_non_pgp_count": skipped})
    except Exception:
        connection.rollback()
        raise
'@ | python -
$rotateExit = $LASTEXITCODE
Remove-Item Env:XH_ROTATE_OLD_KEY -ErrorAction SilentlyContinue
Remove-Item Env:XH_ROTATE_NEW_KEY -ErrorAction SilentlyContinue
if ($rotateExit -ne 0) {
    if ($wasWorkerRunning) {
        Start-ScheduledTask -TaskName "XiaoheiERPWorker"
    }
    exit $rotateExit
}

Set-EnvFileValue -Key "XH_STORE_CREDENTIAL_ENCRYPTION_KEY" -Value $NewKey
Write-Host "Store credential encryption key rotated and .env updated. Secret value was not printed."

if ($wasWorkerRunning) {
    Start-ScheduledTask -TaskName "XiaoheiERPWorker"
    Write-Host "XiaoheiERPWorker restarted."
}
