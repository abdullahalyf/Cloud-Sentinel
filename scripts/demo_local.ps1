<#
.SYNOPSIS
  Starts the whole CloudSentinel demo on this PC, in one command.

.DESCRIPTION
  Starts four things, each in its own process, and keeps them running:
    1. the telemetry collector (OTLP receiver on :4318)
    2. the brain + C2 API on :8000 (with the simulated fleet, so there is
       something to watch without Docker)
    3. the React dashboard on :5173
    4. the demo agents: the LangGraph refund agent (goes rogue after 20 s)
       and, if Docker is up, the four agent containers

  Press Ctrl+C to stop everything. The script kills the processes it started
  and waits for them, so nothing is left behind.

.PARAMETER RogueAfter
  Seconds until the LangGraph refund agent starts its loop. Default 20.

.PARAMETER SkipInstall
  Do not run pip install / npm ci before starting. Default: install.

.PARAMETER Fresh
  Start from an empty local database (data/cloudsentinel.db is moved aside),
  so the demo begins with a clean fleet and a clean baseline.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts/demo_local.ps1
#>
[CmdletBinding()]
param(
  [int]$RogueAfter = 20,
  [switch]$SkipInstall,
  [switch]$Fresh
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$LogDir = Join-Path $Root '.demo_logs'
$Py = Join-Path $Root '.venv\Scripts\python.exe'

# ── the four things we start ───────────────────────────────────────────────────
$services = [ordered]@{}
$jobs = @()

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "    $msg" -ForegroundColor Yellow }

function Start-Service([string]$name, [string]$title) {
  $log = Join-Path $LogDir "$name.log"
  if (Test-Path $log) { Remove-Item $log -Force }
  Write-Step "starting $title"
  $p = Start-Process -FilePath $Py -ArgumentList $script:serviceArgs[$name] -WorkingDirectory $Root `
      -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -NoNewWindow
  $services[$name] = @{ proc = $p; log = $log }
  Write-Ok "$title (pid $($p.Id)) -> $log"
}

# The arguments for each python service.
$script:serviceArgs = @{
  'collector' = @('-m', 'telemetry.collector')
  'brain'     = @('-m', 'brain', '--fake')
  'lgagent'   = @('telemetry/examples/langgraph_refund_agent.py', '--rogue-after', "$RogueAfter")
}

# ── 0. prerequisites ──────────────────────────────────────────────────────────
Write-Step 'checking the setup'
if (-not (Test-Path $Py)) {
  Write-Host "    no virtual environment at $Py" -ForegroundColor Red
  Write-Host '    create it first:  python -m venv .venv' -ForegroundColor Yellow
  exit 1
}
Write-Ok "python: $(& $Py --version 2>&1)"

if (-not $SkipInstall) {
  Write-Step 'installing the python packages'
  & $Py -m pip install -q -r requirements.txt
  & $Py -m pip install -q -e 'telemetry/sdk[langgraph]'
  Write-Ok 'python packages are up to date'

  if (Test-Path 'dashboard/web/package.json') {
    Write-Step 'installing the dashboard packages (npm ci)'
    Push-Location 'dashboard/web'
    try { npm ci --silent } finally { Pop-Location }
    Write-Ok 'dashboard packages are up to date'
  }
}

# ── 1. a clean slate ──────────────────────────────────────────────────────────
if ($Fresh) {
  $db = Join-Path $Root 'data\cloudsentinel.db'
  if (Test-Path $db) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Rename-Item $db "cloudsentinel.db.bak-$stamp"
    Write-Ok "moved the old database aside (cloudsentinel.db.bak-$stamp)"
  }
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# ── 2. stop everything cleanly ────────────────────────────────────────────────
function Stop-Pid([int]$processId, [string]$label) {
  if (-not $processId) { return }
  try {
    $p = Get-Process -Id $processId -ErrorAction Stop
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    # Give it a moment, then make sure it is really gone.
    try { $p.WaitForExit(5000) | Out-Null } catch { }
    Write-Ok "stopped $label (pid $processId)"
  } catch { }
}

function Stop-Everything {
  Write-Step 'stopping everything'

  # 1. the processes we started, children first: the agents should stop before the
  #    brain that judges them and the collector that receives their spans.
  foreach ($name in @('lgagent', 'brain', 'collector', 'dashboard')) {
    if ($services.Contains($name)) {
      Stop-Pid $services[$name].proc.Id $name
    }
  }

  # 2. anything left over on our ports. `npm run dev` spawns node as a child of
  #    npm, and killing npm can leave that node holding port 5173. Same for a
  #    python child that was started with a shell in between.
  foreach ($port in @(5173, 8000, 4318)) {
    try {
      $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop
      foreach ($c in $conns) {
        Stop-Pid $c.OwningProcess "the process on port $port"
      }
    } catch { }
  }

  # 3. and finally any leftover python running our modules from this folder.
  try {
    $mine = Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction Stop |
            Where-Object { $_.CommandLine -and $_.CommandLine -like "*$Root*" }
    foreach ($proc in $mine) {
      Stop-Pid $proc.ProcessId "a leftover python process"
    }
  } catch { }
}

# Ctrl+C in PowerShell does not end the script by itself, so we hook it.
try {
  [Console]::TreatControlCAsInput = $true
} catch { }

$cancel = $false
try {
  # ── 3. the collector ────────────────────────────────────────────────────────
  Start-Service 'collector' 'telemetry collector (:4318)'

  # ── 4. the brain + C2 API ──────────────────────────────────────────────────
  Start-Service 'brain' 'brain + C2 API (:8000)'

  # ── 5. the dashboard ────────────────────────────────────────────────────────
  if (Test-Path 'dashboard/web/package.json') {
    Write-Step 'starting the React dashboard (:5173)'
    $dashLog = Join-Path $LogDir 'dashboard.log'
    if (Test-Path $dashLog) { Remove-Item $dashLog -Force }
    $dash = Start-Process -FilePath 'npm.cmd' -ArgumentList 'run', 'dev' `
        -WorkingDirectory (Join-Path $Root 'dashboard/web') `
        -RedirectStandardOutput $dashLog -RedirectStandardError "$dashLog.err" -PassThru -NoNewWindow
    $services['dashboard'] = @{ proc = $dash; log = $dashLog }
    Write-Ok "dashboard (pid $($dash.Id)) -> $dashLog"
  }

  # ── 6. the demo agents ─────────────────────────────────────────────────────
  # The LangGraph refund agent runs as a local process: it emits OTel spans to the
  # collector and asks the brain for approval before a big refund.
  Start-Service 'lgagent' "LangGraph refund agent (goes rogue after $RogueAfter s)"

  # The four simulated agents live inside the brain process (--fake), so the fleet is
  # already there. Docker is only used if it is actually running.

  # ── 7. wait until everything answers ───────────────────────────────────────
  Write-Step 'waiting for the services to be ready'

  # A server that answers at all is up. The collector only accepts POST on /v1/traces,
  # so a GET there comes back 405 - that still means the port is serving, so the check
  # looks for ANY http response rather than a 200.
  function Wait-ForHttp($name, $url, $seconds) {
    $end = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $end) {
      if ($cancel) { return $false }
      try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        if ($r.StatusCode -lt 500) {
          Write-Ok "$name is ready ($url)"
          return $true
        }
      } catch {
        # A 4xx still means something is listening and speaking HTTP.
        $code = $null
        try { $code = $_.Exception.Response.StatusCode.value__ } catch { }
        if ($code -and $code -lt 500) {
          Write-Ok "$name is ready ($url)"
          return $true
        }
      }
      Start-Sleep -Milliseconds 800
    }
    Write-Warn2 "$name did not answer within $seconds s ($url)"
    return $false
  }

  # A plain TCP check: is anything listening on the port?
  function Wait-ForPort($name, $port, $seconds) {
    $end = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $end) {
      if ($cancel) { return $false }
      try {
        $c = New-Object System.Net.Sockets.TcpClient
        $c.Connect('127.0.0.1', $port)
        $c.Close()
        Write-Ok "$name is listening on :$port"
        return $true
      } catch { }
      Start-Sleep -Milliseconds 500
    }
    Write-Warn2 "$name is not listening on :$port after $seconds s"
    return $false
  }

  $okApi = Wait-ForHttp 'C2 API' 'http://localhost:8000/v1/health' 60
  $okCol = Wait-ForPort 'collector' 4318 30
  $okWeb = $false
  if ($services.Contains('dashboard')) {
    $okWeb = Wait-ForHttp 'dashboard' 'http://localhost:5173/' 60
  }

  # ── 8. the summary ─────────────────────────────────────────────────────────
  Write-Host ''
  Write-Host '  CloudSentinel is running.' -ForegroundColor Green
  Write-Host ''
  Write-Host '    Dashboard (watch this):  http://localhost:5173/' -ForegroundColor White
  Write-Host '    API docs:               http://localhost:8000/docs' -ForegroundColor White
  Write-Host '    Fleet API:              http://localhost:8000/v1/fleet' -ForegroundColor White
  Write-Host ''
  Write-Host '  What to watch:' -ForegroundColor White
  Write-Host '    1. About 20 s in, beta starts a paraphrase loop and is paused on its own.'
  Write-Host '    2. Open beta, fix the memory (order_4471), press Resume -> probation -> healthy.'
  Write-Host '    3. The LangGraph agent asks for the 50 000 BDT refund -> Approvals Inbox.'
  Write-Host '    4. Press "Run 3 AM Demo Incident" in the top bar for the scripted version.'
  Write-Host ''
  Write-Host '  Press Ctrl+C to stop everything.' -ForegroundColor Yellow
  Write-Host ''

  if (-not $okApi) { Write-Warn2 'the C2 API is not answering - check .demo_logs/brain.log' }

  # Keep the script alive so the children keep running, until Ctrl+C.
  while ($true) {
    Start-Sleep -Seconds 1
    foreach ($name in @('collector', 'brain', 'lgagent', 'dashboard')) {
      if ($services.Contains($name)) {
        $proc = $services[$name].proc
        if ($proc.HasExited) {
          Write-Warn2 "$name exited (code $($proc.ExitCode)) - see $($services[$name].log)"
          $services.Remove($name)
        }
      }
    }
    if ($services.Count -eq 0) {
      Write-Warn2 'every service has stopped'
      break
    }
  }
}
finally {
  Stop-Everything
  Write-Host ''
  Write-Host '  Stopped. Logs are in .demo_logs\.' -ForegroundColor Green
}
