param(
    [switch]$SetupOnly,
    [switch]$SkipLaunch,
    [switch]$ForceOnboard
)

$ErrorActionPreference = "Stop"

function Log-Step([string]$m) { Write-Host "[INSTALL] $m" -ForegroundColor Cyan }
function Log-Ok([string]$m) { Write-Host "[OK]      $m" -ForegroundColor Green }
function Log-Warn([string]$m) { Write-Host "[WARN]    $m" -ForegroundColor Yellow }
function Log-Err([string]$m) { Write-Host "[ERROR]   $m" -ForegroundColor Red }

$script:INSTALL_LOG = ""

function Get-PythonExe {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            & py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" *> $null
            if ($LASTEXITCODE -eq 0) {
                $p = & py -3.11 -c "import sys; print(sys.executable)"
                return ($p | Select-Object -First 1).Trim()
            }
        } catch {}
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        try {
            & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" *> $null
            if ($LASTEXITCODE -eq 0) {
                $p = & python -c "import sys; print(sys.executable)"
                return ($p | Select-Object -First 1).Trim()
            }
        } catch {}
    }
    $base = Join-Path $env:LocalAppData "Programs\Python"
    if (Test-Path -LiteralPath $base) {
        $dirs = Get-ChildItem $base -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match "^Python3\d+$" } |
            Sort-Object Name -Descending
        foreach ($d in $dirs) {
            $exe = Join-Path $d.FullName "python.exe"
            if (-not (Test-Path -LiteralPath $exe)) { continue }
            try {
                & $exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" *> $null
                if ($LASTEXITCODE -eq 0) { return $exe }
            } catch {}
        }
    }
    return ""
}

function Install-Python {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Log-Err "winget not found. Install App Installer and rerun."
        Write-Host "https://apps.microsoft.com/detail/9NBLGGH4NNS1"
        return $false
    }
    Log-Step "Installing Python 3.11 via winget..."
    $args = @("install","-e","--id","Python.Python.3.11","--scope","user","--accept-package-agreements","--accept-source-agreements","--silent")
    $p = Start-Process -FilePath "winget" -ArgumentList $args -Wait -PassThru -NoNewWindow
    if ($p.ExitCode -ne 0) {
        Log-Warn "Python 3.11 install failed (code $($p.ExitCode)); trying 3.12..."
        $args = @("install","-e","--id","Python.Python.3.12","--scope","user","--accept-package-agreements","--accept-source-agreements","--silent")
        $p2 = Start-Process -FilePath "winget" -ArgumentList $args -Wait -PassThru -NoNewWindow
        if ($p2.ExitCode -ne 0) { return $false }
    }
    Start-Sleep -Seconds 2
    return $true
}

function Ensure-CLIProxy([string]$projectRoot) {
    $dir = Join-Path $projectRoot "cliproxyapi"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $exe = Join-Path $dir "cli-proxy-api.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        Log-Step "Downloading CLIProxyAPI..."
        $headers = @{ "User-Agent" = "agent-commander-gui-installer"; "Accept" = "application/vnd.github+json" }
        $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/router-for-me/CLIProxyAPI/releases/latest" -Headers $headers -TimeoutSec 30
        $asset = @($rel.assets) |
            Where-Object { $_.name -match "(?i)windows" -and $_.name -match "(?i)\.(zip|exe)$" } |
            Select-Object -First 1
        if (-not $asset) { throw "No Windows release asset found for CLIProxyAPI." }
        $tmp = Join-Path $env:TEMP ("cliproxyapi-" + [guid]::NewGuid().ToString() + [IO.Path]::GetExtension($asset.name))
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tmp -UseBasicParsing -TimeoutSec 120
        if ($tmp.ToLower().EndsWith(".exe")) {
            Copy-Item -LiteralPath $tmp -Destination $exe -Force
        } else {
            $out = Join-Path $env:TEMP ("cliproxyapi-extract-" + [guid]::NewGuid().ToString())
            New-Item -ItemType Directory -Force -Path $out | Out-Null
            Expand-Archive -LiteralPath $tmp -DestinationPath $out -Force
            $found = Get-ChildItem -Path $out -Recurse -File | Where-Object { $_.Name -match "(?i)^cli-proxy-api.*\.exe$" } | Select-Object -First 1
            if (-not $found) { throw "cli-proxy-api.exe not found inside downloaded archive." }
            Copy-Item -LiteralPath $found.FullName -Destination $exe -Force
        }
    }
    $cfg = Join-Path $dir "config.yaml"
    if (-not (Test-Path -LiteralPath $cfg)) {
        @'
host: "127.0.0.1"
port: 8317

auth-dir: "~/.cli-proxy-api"

api-keys:
  - "agent-commander-local"

debug: false
'@ | Set-Content -LiteralPath $cfg -Encoding UTF8
    }
    return $exe
}

function Stop-ProjectPythonProcesses([string]$projectRoot) {
    $projectLower = $projectRoot.ToLowerInvariant()
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue
        foreach ($p in $procs) {
            $pid = [int]$p.ProcessId
            if ($pid -eq $PID) { continue }
            $cmd = (($p.CommandLine | Out-String).Trim()).ToLowerInvariant()
            if ($cmd -and $cmd.Contains($projectLower)) {
                try { Stop-Process -Id $pid -Force -ErrorAction Stop } catch {}
            }
        }
    } catch {}
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
Set-Location $projectRoot
$logDir = Join-Path $projectRoot "logs\installer"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$script:INSTALL_LOG = Join-Path $logDir ("easy-install-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
Add-Content -LiteralPath $script:INSTALL_LOG -Value ("[INFO] install start " + (Get-Date -Format "s"))
Log-Step "Project root: $projectRoot"
Stop-ProjectPythonProcesses -projectRoot $projectRoot

$py = Get-PythonExe
if (-not $py) {
    if (-not (Install-Python)) {
        Log-Err "Failed to install Python automatically."
        exit 1
    }
    $py = Get-PythonExe
}
if (-not $py) {
    Log-Err "Python 3.11+ not found after install attempt."
    exit 1
}
Log-Ok "Python: $py"

try {
    $proxyExe = Ensure-CLIProxy -projectRoot $projectRoot
    Log-Ok "CLIProxyAPI: $proxyExe"
} catch {
    Log-Err $_.Exception.Message
    exit 1
}

$bootstrap = Join-Path $projectRoot "scripts\bootstrap_windows.ps1"
if (-not (Test-Path -LiteralPath $bootstrap)) {
    Log-Err "Bootstrap script missing: $bootstrap"
    exit 1
}

$args = @("-NoProfile","-ExecutionPolicy","Bypass","-File",$bootstrap,"-PythonExe",$py)
if ($SetupOnly) { $args += "-SetupOnly" }
if ($ForceOnboard) { $args += "-ForceOnboard" }

Log-Step "Running project bootstrap..."
& powershell @args 2>&1 | Tee-Object -FilePath $script:INSTALL_LOG -Append
$bootstrapExit = $LASTEXITCODE
if ($bootstrapExit -ne 0) {
    Log-Err "Bootstrap failed with code $bootstrapExit."
    Write-Host "Installer log: $script:INSTALL_LOG"
    exit $bootstrapExit
}

if ($SetupOnly -or $SkipLaunch) {
    Log-Ok "Installation completed."
    Write-Host "Run GUI: .\.venv\Scripts\python.exe -m agent-commander gui"
    exit 0
}

$pythonw = Join-Path (Split-Path -Parent $py) "pythonw.exe"
Log-Step "Launching GUI..."
$venvPyw = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$venvPy = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPyw) {
    Start-Process -FilePath $venvPyw -ArgumentList @("-m","agent-commander","gui") -WorkingDirectory $projectRoot
} elseif (Test-Path -LiteralPath $venvPy) {
    Start-Process -FilePath $venvPy -ArgumentList @("-m","agent-commander","gui") -WorkingDirectory $projectRoot
} elseif (Test-Path -LiteralPath $pythonw) {
    Start-Process -FilePath $pythonw -ArgumentList @("-m","agent-commander","gui") -WorkingDirectory $projectRoot
} else {
    Start-Process -FilePath $py -ArgumentList @("-m","agent-commander","gui") -WorkingDirectory $projectRoot
}
Log-Ok "Done."
Write-Host "Installer log: $script:INSTALL_LOG"
