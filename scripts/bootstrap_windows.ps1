param(
    [switch]$SetupOnly,
    [switch]$InstallDev,
    [switch]$ForceOnboard,
    [switch]$SkipOnboard,
    [switch]$AutoConfigure = $true,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$script:LOG_FILE = ""

function Write-Step {
    param([string]$Message)
    Write-Host "[SETUP] $Message" -ForegroundColor Cyan
    if ($script:LOG_FILE) {
        Add-Content -LiteralPath $script:LOG_FILE -Value "[SETUP] $Message"
    }
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN]  $Message" -ForegroundColor Yellow
    if ($script:LOG_FILE) {
        Add-Content -LiteralPath $script:LOG_FILE -Value "[WARN]  $Message"
    }
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[OK]    $Message" -ForegroundColor Green
    if ($script:LOG_FILE) {
        Add-Content -LiteralPath $script:LOG_FILE -Value "[OK]    $Message"
    }
}

function Invoke-ProcessLogged {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Label
    )
    Write-Step $Label
    $outFile = Join-Path $env:TEMP ("agent-commander-bootstrap-out-" + [guid]::NewGuid().ToString() + ".log")
    $errFile = Join-Path $env:TEMP ("agent-commander-bootstrap-err-" + [guid]::NewGuid().ToString() + ".log")
    try {
        $proc = Start-Process -FilePath $FilePath -ArgumentList $Arguments -Wait -PassThru -NoNewWindow -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        if (Test-Path -LiteralPath $outFile) {
            $outText = Get-Content -LiteralPath $outFile -Raw -ErrorAction SilentlyContinue
            if ($outText) {
                if ($script:LOG_FILE) { Add-Content -LiteralPath $script:LOG_FILE -Value $outText }
            }
        }
        if (Test-Path -LiteralPath $errFile) {
            $errText = Get-Content -LiteralPath $errFile -Raw -ErrorAction SilentlyContinue
            if ($errText) {
                if ($script:LOG_FILE) { Add-Content -LiteralPath $script:LOG_FILE -Value $errText }
            }
        }
        return $proc.ExitCode
    } finally {
        Remove-Item -LiteralPath $outFile -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $errFile -Force -ErrorAction SilentlyContinue
    }
}

function Stop-ProjectPythonProcesses {
    param([string]$ProjectRoot)
    $projectLower = $ProjectRoot.ToLowerInvariant()
    $venvLower = (Join-Path $ProjectRoot ".venv").ToLowerInvariant()
    $stopped = 0
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue
        foreach ($p in $procs) {
            $pid = [int]$p.ProcessId
            if ($pid -eq $PID) {
                continue
            }
            $cmd = (($p.CommandLine | Out-String).Trim()).ToLowerInvariant()
            $exe = (($p.ExecutablePath | Out-String).Trim()).ToLowerInvariant()
            $isProjectProcess = $false
            if ($cmd -and $cmd.Contains($projectLower)) {
                $isProjectProcess = $true
            }
            if (-not $isProjectProcess -and $exe -and $exe.StartsWith($venvLower)) {
                $isProjectProcess = $true
            }
            if (-not $isProjectProcess) {
                continue
            }
            try {
                Stop-Process -Id $pid -Force -ErrorAction Stop
                $stopped += 1
            } catch {
            }
        }
    } catch {
    }
    if ($stopped -gt 0) {
        Write-Warn "Stopped $stopped running Python process(es) from this project to unlock .venv files"
        Start-Sleep -Milliseconds 600
    }
}

function LogContains {
    param([string]$Pattern)
    try {
        if (-not (Test-Path -LiteralPath $script:LOG_FILE)) {
            return $false
        }
        $content = Get-Content -LiteralPath $script:LOG_FILE -Raw -ErrorAction SilentlyContinue
        if (-not $content) {
            return $false
        }
        return $content -match $Pattern
    } catch {
        return $false
    }
}

function Get-PythonLauncher {
    if (-not [string]::IsNullOrWhiteSpace($PythonExe)) {
        if (Test-Path -LiteralPath $PythonExe) {
            try {
                & $PythonExe -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
                if ($LASTEXITCODE -eq 0) {
                    return @($PythonExe)
                }
            } catch {
            }
        }
    }

    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            & py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
            if ($LASTEXITCODE -eq 0) {
                return @("py", "-3.11")
            }
        } catch {
        }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        try {
            & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
            if ($LASTEXITCODE -eq 0) {
                return @("python")
            }
        } catch {
        }
    }

    return $null
}

function Invoke-Launcher {
    param(
        [string[]]$Launcher,
        [string[]]$Args
    )
    $prefix = @()
    if ($Launcher.Length -gt 1) {
        $prefix = $Launcher[1..($Launcher.Length - 1)]
    }
    & $Launcher[0] @prefix @Args
    return $LASTEXITCODE
}

function Get-PythonVersionFromLauncher {
    param([string[]]$Launcher)
    try {
        $prefix = @()
        if ($Launcher.Length -gt 1) {
            $prefix = $Launcher[1..($Launcher.Length - 1)]
        }
        $v = & $Launcher[0] @prefix -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
        $s = ($v | Select-Object -First 1).Trim()
        if ([string]::IsNullOrWhiteSpace($s)) {
            return $null
        }
        return [version]$s
    } catch {
        return $null
    }
}

function Get-PythonVersionFromExe {
    param([string]$PythonExe)
    try {
        $v = & $PythonExe -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
        $s = ($v | Select-Object -First 1).Trim()
        if ([string]::IsNullOrWhiteSpace($s)) {
            return $null
        }
        return [version]$s
    } catch {
        return $null
    }
}

function Get-FirstExistingPath {
    param([string[]]$Candidates)
    foreach ($candidate in $Candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return ""
}

function Get-CommandPath {
    param([string]$CommandName)
    $cmd = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        return ""
    }
    return $cmd.Source
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
Set-Location $projectRoot

$logDir = Join-Path $projectRoot "logs\installer"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$script:LOG_FILE = Join-Path $logDir ("bootstrap-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
Write-Ok "Bootstrap log: $script:LOG_FILE"

Write-Step "Project root: $projectRoot"
Stop-ProjectPythonProcesses -ProjectRoot $projectRoot

$launcher = Get-PythonLauncher
if ($null -eq $launcher) {
    Write-Host "[ERROR] Python 3.11+ was not found." -ForegroundColor Red
    Write-Host "Install Python 3.11+ and rerun this script."
    Write-Host "https://www.python.org/downloads/windows/"
    exit 1
}

Write-Step "Using Python launcher: $($launcher -join ' ')"
$launcherVersion = Get-PythonVersionFromLauncher -Launcher $launcher
if ($launcherVersion -ne $null) {
    Write-Step "Launcher Python version: $launcherVersion"
}

$venvDir = Join-Path $projectRoot ".venv"
$venvPy = Join-Path $venvDir "Scripts\python.exe"
$venvCfg = Join-Path $venvDir "pyvenv.cfg"
$rebuildVenv = $false

if (Test-Path -LiteralPath $venvPy) {
    $venvVersion = Get-PythonVersionFromExe -PythonExe $venvPy
    if ($venvVersion -eq $null) {
        Write-Warn "Existing .venv python version could not be determined; recreating .venv"
        $rebuildVenv = $true
    } else {
        Write-Step "Existing .venv Python version: $venvVersion"
        $needsRecreate = $false
        if ($venvVersion -lt [version]"3.11.0") {
            $needsRecreate = $true
            Write-Warn "Existing .venv uses Python $venvVersion (<3.11); recreating .venv"
        } elseif ($launcherVersion -ne $null -and ($venvVersion.Major -ne $launcherVersion.Major -or $venvVersion.Minor -ne $launcherVersion.Minor)) {
            $needsRecreate = $true
            Write-Warn "Existing .venv uses Python $venvVersion, launcher is $launcherVersion; recreating .venv"
        }
        if ($needsRecreate) {
            $rebuildVenv = $true
        }
    }
}

if ((Test-Path -LiteralPath $venvPy) -and (-not (Test-Path -LiteralPath $venvCfg))) {
    Write-Warn "Existing .venv is invalid (missing pyvenv.cfg); recreating .venv"
    $rebuildVenv = $true
}

if ($rebuildVenv -or (-not (Test-Path -LiteralPath $venvPy)) -or (-not (Test-Path -LiteralPath $venvCfg))) {
    Write-Step "Creating virtual environment (.venv)"
    Invoke-Launcher -Launcher $launcher -Args @("-m", "venv", "--clear", ".venv") | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "venv --clear failed (code $LASTEXITCODE). Trying remove + create..."
        Remove-Item -LiteralPath $venvDir -Recurse -Force -ErrorAction SilentlyContinue
        Invoke-Launcher -Launcher $launcher -Args @("-m", "venv", ".venv") | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Failed to create .venv" -ForegroundColor Red
            exit 1
        }
    }
}

if ((-not (Test-Path -LiteralPath $venvPy)) -or (-not (Test-Path -LiteralPath $venvCfg))) {
    Write-Host "[ERROR] Broken .venv after create (python or pyvenv.cfg missing): $venvDir" -ForegroundColor Red
    Write-Host "Close any running terminals/apps using this folder, delete .venv manually, then rerun installer." -ForegroundColor Red
    exit 1
}

Write-Step "Validating venv pip"
$pipCheckExit = Invoke-ProcessLogged -FilePath $venvPy -Arguments @("-m", "pip", "--version") -Label "python -m pip --version"
if ($pipCheckExit -ne 0) {
    Write-Warn "pip is missing in venv (code $pipCheckExit). Bootstrapping with ensurepip..."
    $ensurePipExit = Invoke-ProcessLogged -FilePath $venvPy -Arguments @("-m", "ensurepip", "--upgrade") -Label "python -m ensurepip --upgrade"
    if ($ensurePipExit -ne 0) {
        Write-Host "[ERROR] Failed to bootstrap pip in venv. See log: $script:LOG_FILE" -ForegroundColor Red
        exit 1
    }
    $pipCheckExit2 = Invoke-ProcessLogged -FilePath $venvPy -Arguments @("-m", "pip", "--version") -Label "python -m pip --version (recheck)"
    if ($pipCheckExit2 -ne 0) {
        Write-Host "[ERROR] pip is still unavailable in venv. See log: $script:LOG_FILE" -ForegroundColor Red
        exit 1
    }
}

Write-Step "Upgrading pip tooling"
Stop-ProjectPythonProcesses -ProjectRoot $projectRoot
$pipUpgradeExit = Invoke-ProcessLogged -FilePath $venvPy -Arguments @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel") -Label "pip install --upgrade pip setuptools wheel"
if ($pipUpgradeExit -ne 0) {
    Write-Warn "pip/setuptools/wheel upgrade failed (code $pipUpgradeExit). Retrying with pip only..."
    $pipOnlyExit = Invoke-ProcessLogged -FilePath $venvPy -Arguments @("-m", "pip", "install", "--upgrade", "pip") -Label "pip install --upgrade pip"
    if ($pipOnlyExit -ne 0) {
        Write-Host "[ERROR] Failed to upgrade pip. See log: $script:LOG_FILE" -ForegroundColor Red
        exit 1
    }
}

$editableSpec = if ($InstallDev) { ".[dev]" } else { "." }
Write-Step "Installing project into venv (pip install -e $editableSpec)"
Stop-ProjectPythonProcesses -ProjectRoot $projectRoot
$installExit = Invoke-ProcessLogged -FilePath $venvPy -Arguments @("-m", "pip", "install", "-e", $editableSpec) -Label "pip install -e $editableSpec"
if ($installExit -ne 0) {
    Write-Warn "Editable install failed (code $installExit). Installing build backend and retrying..."
    Stop-ProjectPythonProcesses -ProjectRoot $projectRoot
    $hatchExit = Invoke-ProcessLogged -FilePath $venvPy -Arguments @("-m", "pip", "install", "hatchling") -Label "pip install hatchling"
    if ($hatchExit -eq 0) {
        Stop-ProjectPythonProcesses -ProjectRoot $projectRoot
        $retryExit = Invoke-ProcessLogged -FilePath $venvPy -Arguments @("-m", "pip", "install", "--no-cache-dir", "-e", $editableSpec) -Label "pip install --no-cache-dir -e $editableSpec (retry)"
        if ($retryExit -eq 0) {
            $installExit = 0
        } else {
            Write-Warn "Second editable install attempt failed (code $retryExit). Final retry after unlocking files..."
            Stop-ProjectPythonProcesses -ProjectRoot $projectRoot
            Start-Sleep -Seconds 2
            $finalExit = Invoke-ProcessLogged -FilePath $venvPy -Arguments @("-m", "pip", "install", "--no-cache-dir", "--force-reinstall", "tkinterdnd2") -Label "pip install --force-reinstall tkinterdnd2"
            if ($finalExit -eq 0) {
                $retry2Exit = Invoke-ProcessLogged -FilePath $venvPy -Arguments @("-m", "pip", "install", "--no-cache-dir", "-e", $editableSpec) -Label "pip install --no-cache-dir -e $editableSpec (final retry)"
                if ($retry2Exit -eq 0) {
                    $installExit = 0
                }
            }
        }
    }
}
if ($installExit -ne 0) {
    $tkdndLocked = (LogContains -Pattern "libtkdnd2\.9\.4\.dll") -or (LogContains -Pattern "tkinterdnd2")
    if ($tkdndLocked) {
        Write-Warn "Detected tkinterdnd2 file lock on Windows. Falling back to install without tkinterdnd2..."
        Stop-ProjectPythonProcesses -ProjectRoot $projectRoot
        $depsExit = Invoke-ProcessLogged -FilePath $venvPy -Arguments @(
            "-m", "pip", "install", "--no-cache-dir",
            "typer>=0.9.0",
            "pydantic>=2.0.0",
            "pydantic-settings>=2.0.0",
            "loguru>=0.7.0",
            "rich>=13.0.0",
            "croniter>=2.0.0",
            "prompt-toolkit>=3.0.0",
            "customtkinter>=5.2.0",
            "pyte>=0.8.2",
            "plyer>=2.1.0",
            "win10toast>=0.9",
            "pywinpty>=2.0.13"
        ) -Label "pip install runtime deps (without tkinterdnd2)"
        if ($depsExit -eq 0) {
            $editableNoDepsExit = Invoke-ProcessLogged -FilePath $venvPy -Arguments @("-m", "pip", "install", "-e", ".", "--no-deps") -Label "pip install -e . --no-deps"
            if ($editableNoDepsExit -eq 0) {
                Write-Warn "Installed without tkinterdnd2 (file drag-and-drop disabled on this machine)."
                $installExit = 0
            }
        }
    }
}
if ($installExit -ne 0) {
    Write-Host "[ERROR] Failed to install project dependencies. See log: $script:LOG_FILE" -ForegroundColor Red
    exit 1
}

if (-not $SkipOnboard) {
    $onboardArgs = @("-m", "agent-commander", "onboard", "--non-interactive")
    if ($ForceOnboard) {
        $onboardArgs += "--force"
    }
    Write-Step "Running initial onboarding"
    & $venvPy @onboardArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Onboarding failed" -ForegroundColor Red
        exit 1
    }
}

$parentRoot = (Split-Path -Parent $projectRoot)
$proxyBinary = Get-FirstExistingPath @(
    (Join-Path $projectRoot "cliproxyapi\cli-proxy-api.exe"),
    (Join-Path $projectRoot "cliproxyapi\cli-proxy-api"),
    (Join-Path $parentRoot "CLIProxyAPI\cli-proxy-api.exe"),
    (Join-Path $parentRoot "CLIProxyAPI\cli-proxy-api")
)

$proxyConfig = ""
if ($proxyBinary) {
    $proxyDir = Split-Path -Parent $proxyBinary
    $proxyConfig = Get-FirstExistingPath @(
        (Join-Path $proxyDir "config.yaml"),
        (Join-Path $proxyDir "config.yml")
    )
}

$claudePath = Get-CommandPath "claude"
$geminiPath = Get-CommandPath "gemini"
$codexPath = Get-CommandPath "codex"

if ($AutoConfigure) {
    Write-Step "Applying detected paths into ~/.agent-commander/config.json"
    $env:AGENT_COMMANDER_BOOTSTRAP_PROXY_BIN = $proxyBinary
    $env:AGENT_COMMANDER_BOOTSTRAP_PROXY_CFG = $proxyConfig
    $env:AGENT_COMMANDER_BOOTSTRAP_AGENT_CLAUDE = $claudePath
    $env:AGENT_COMMANDER_BOOTSTRAP_AGENT_GEMINI = $geminiPath
    $env:AGENT_COMMANDER_BOOTSTRAP_AGENT_CODEX = $codexPath
    & $venvPy -c @"
import json
import os
from pathlib import Path

path = Path.home() / ".agent-commander" / "config.json"
if not path.exists():
    raise SystemExit(0)

cfg = json.loads(path.read_text(encoding="utf-8"))
proxy_bin = os.getenv("AGENT_COMMANDER_BOOTSTRAP_PROXY_BIN", "").strip()
proxy_cfg = os.getenv("AGENT_COMMANDER_BOOTSTRAP_PROXY_CFG", "").strip()
claude = os.getenv("AGENT_COMMANDER_BOOTSTRAP_AGENT_CLAUDE", "").strip()
gemini = os.getenv("AGENT_COMMANDER_BOOTSTRAP_AGENT_GEMINI", "").strip()
codex = os.getenv("AGENT_COMMANDER_BOOTSTRAP_AGENT_CODEX", "").strip()

if proxy_bin:
    proxy = cfg.setdefault("proxyApi", {})
    proxy["enabled"] = True
    proxy.setdefault("baseUrl", "http://127.0.0.1:8317")
    proxy.setdefault("endpoint", "/v1/chat/completions")
    proxy.setdefault("apiKey", "agent-commander-local")
    proxy["binaryPath"] = proxy_bin
    if proxy_cfg:
        proxy["configPath"] = proxy_cfg
    proxy.setdefault("autoStart", True)
    proxy.setdefault("takeOverExisting", True)

agents = cfg.setdefault("agents", {})
defaults = agents.setdefault("defaults", {})

detected = []
for name, value in (("claude", claude), ("gemini", gemini), ("codex", codex)):
    if not value:
        continue
    item = agents.setdefault(name, {})
    item["enabled"] = True
    if not str(item.get("command", "")).strip():
        item["command"] = value
    detected.append(name)

if not str(defaults.get("active", "")).strip():
    for preferred in ("codex", "claude", "gemini"):
        if preferred in detected:
            defaults["active"] = preferred
            break

path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
"@
}

Write-Step "Runtime sanity check (Python/Tk modules)"
& $venvPy -c "import sys, tkinter, customtkinter, pyte, typer, pydantic; print(sys.version.split()[0])"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Runtime module check failed" -ForegroundColor Red
    exit 1
}

Write-Step "External dependency check"
if ($proxyBinary) { Write-Ok "CLIProxyAPI binary: $proxyBinary" } else { Write-Warn "CLIProxyAPI binary not found" }
if ($proxyConfig) { Write-Ok "CLIProxyAPI config: $proxyConfig" } else { Write-Warn "CLIProxyAPI config not found near binary" }
if ($claudePath) { Write-Ok "claude CLI: $claudePath" } else { Write-Warn "claude CLI not found in PATH" }
if ($geminiPath) { Write-Ok "gemini CLI: $geminiPath" } else { Write-Warn "gemini CLI not found in PATH" }
if ($codexPath) { Write-Ok "codex CLI: $codexPath" } else { Write-Warn "codex CLI not found in PATH" }

Write-Step "agent-commander status"
& $venvPy -m agent-commander status
if ($LASTEXITCODE -ne 0) {
    Write-Warn "status command returned non-zero exit code"
}

if ($SetupOnly) {
    Write-Ok "Setup completed"
    exit 0
}

Write-Host ""
Write-Host "Run GUI with:" -ForegroundColor White
Write-Host "  .\.venv\Scripts\python.exe -m agent-commander gui" -ForegroundColor White
