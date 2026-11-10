# AstrBot watchdog: if the dashboard port is down and no AstrBot process is
# running, restart it through the controller API (preferred) or directly.
$ErrorActionPreference = 'SilentlyContinue'
$root = 'D:\chengyin'
$log = Join-Path $root 'logs\watchdog.log'

function Write-WatchdogLog([string]$message) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message
    Add-Content -Path $log -Value $line -Encoding UTF8
}

# A deliberate stop from the manager must not be undone by the watchdog.
$statePath = Join-Path $root 'state.json'
if (Test-Path $statePath) {
    try {
        $state = Get-Content $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($state.services_stopped) { exit 0 }
    } catch {
        Write-WatchdogLog "state.json unreadable: $($_.Exception.Message)"
    }
}

# Healthy when the dashboard is listening.
$listener = Get-NetTCPConnection -LocalPort 6185 -State Listen -ErrorAction SilentlyContinue
if ($listener) { exit 0 }

# If an AstrBot process already exists, it may be starting or wedged. Do not
# create a second instance; log it so the situation is visible.
$astrbotExe = Join-Path $root 'runtime\python\python.exe'
$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object {
        $_.ExecutablePath -eq $astrbotExe -and
        $_.CommandLine -match '(^|\s)main\.py(\s|$)'
    }
if ($running) {
    Write-WatchdogLog "port 6185 down, AstrBot process $($running.ProcessId) exists; skip start"
    exit 0
}

# Preferred: ask the manager to start the service so pids and logs stay managed.
try {
    $page = Invoke-WebRequest -Uri 'http://127.0.0.1:2848/' -TimeoutSec 3 -UseBasicParsing
    $match = [regex]::Match($page.Content, 'window\.TOKEN\s*=\s*"([^"]+)"')
    if ($match.Success) {
        $headers = @{ 'X-Token' = $match.Groups[1].Value }
        Invoke-RestMethod -Uri 'http://127.0.0.1:2848/api/start' -Method Post -Headers $headers -ContentType 'application/json' -Body '{}' -TimeoutSec 60 | Out-Null
        Write-WatchdogLog 'started AstrBot through manager API'
        exit 0
    }
} catch {
    # Manager is not running; fall through to a direct start.
}

# Fallback: start AstrBot directly with the same environment the manager uses.
$env:ASTRBOT_ROOT = Join-Path $root 'astrbot'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
Start-Process -FilePath $astrbotExe `
    -ArgumentList 'main.py' `
    -WorkingDirectory (Join-Path $root 'astrbot') `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $root 'logs\watchdog_astrbot.out') `
    -RedirectStandardError (Join-Path $root 'logs\watchdog_astrbot.err')
Write-WatchdogLog 'started AstrBot directly (manager API unavailable)'
