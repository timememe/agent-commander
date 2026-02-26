"""Build orchestrator for Agent Commander GUI installer.

Usage:
    python build/build_installer.py [--skip-inno] [--clean]

Produces:
    dist/AgentCommander/AgentCommander.exe         (standalone app)
    dist/AgentCommander_Setup_X.Y.Z.exe            (Inno Setup installer, if available)
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BUILD_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BUILD_DIR.parent
DIST_DIR = PROJECT_ROOT / "dist"
DIST_APP_DIR = DIST_DIR / "AgentCommander"
SPEC_FILE = BUILD_DIR / "agent_commander.spec"
INNO_SCRIPT = BUILD_DIR / "installer.iss"
ICON_FILE = BUILD_DIR / "agent_commander.ico"
LOGO_PNG = PROJECT_ROOT / "agent_commander_logo.png"
CLIPROXYAPI_DIR = PROJECT_ROOT / "cliproxyapi"


def log(msg: str) -> None:
    print(f"[BUILD] {msg}")


def log_ok(msg: str) -> None:
    print(f"[OK]    {msg}")


def log_err(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------
def read_version() -> str:
    """Read project version from pyproject.toml."""
    pyproject = PROJECT_ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r'version\s*=\s*"([^"]+)"', text)
    if match:
        return match.group(1)
    return "0.0.0"


# ---------------------------------------------------------------------------
# Icon generation
# ---------------------------------------------------------------------------
def ensure_icon() -> Path | None:
    """Generate .ico from agent_commander_logo.png if possible."""
    if ICON_FILE.exists():
        log(f"Icon already exists: {ICON_FILE}")
        return ICON_FILE

    if not LOGO_PNG.exists():
        log("No agent_commander_logo.png found — building without icon")
        return None

    try:
        from PIL import Image

        img = Image.open(LOGO_PNG)
        # Standard Windows icon sizes
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        img.save(ICON_FILE, format="ICO", sizes=sizes)
        log_ok(f"Generated icon: {ICON_FILE}")
        return ICON_FILE
    except ImportError:
        log("Pillow not installed — building without icon (pip install Pillow to enable)")
        return None
    except Exception as exc:
        log(f"Icon generation failed: {exc} — building without icon")
        return None


# ---------------------------------------------------------------------------
# PyInstaller
# ---------------------------------------------------------------------------
def ensure_pyinstaller() -> bool:
    """Check PyInstaller is available, install if not."""
    try:
        import PyInstaller  # noqa: F401

        log(f"PyInstaller {PyInstaller.__version__} found")
        return True
    except ImportError:
        pass

    log("PyInstaller not found — installing...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "pyinstaller"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log_err(f"Failed to install PyInstaller:\n{result.stderr}")
        return False
    log_ok("PyInstaller installed")
    return True


def run_pyinstaller() -> bool:
    """Run PyInstaller with the spec file."""
    log("Running PyInstaller...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC_FILE),
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(PROJECT_ROOT / "build" / "pyinstaller_work"),
        "--noconfirm",
    ]
    log(f"  {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        log_err("PyInstaller failed")
        return False
    log_ok(f"PyInstaller output: {DIST_APP_DIR}")
    return True


# ---------------------------------------------------------------------------
# Post-build: copy CLIProxyAPI and extras
# ---------------------------------------------------------------------------
def copy_cliproxyapi() -> None:
    """Copy CLIProxyAPI binary and config into dist."""
    dest = DIST_APP_DIR / "cliproxyapi"
    dest.mkdir(parents=True, exist_ok=True)

    binary_name = "cli-proxy-api.exe" if os.name == "nt" else "cli-proxy-api"
    src_binary = CLIPROXYAPI_DIR / binary_name
    if src_binary.is_file():
        shutil.copy2(str(src_binary), str(dest / binary_name))
        log_ok(f"Copied {binary_name} to dist")
    else:
        log(f"CLIProxyAPI binary not found at {src_binary} — skipping")
        log("  Users will need to configure binaryPath manually")

    src_config = CLIPROXYAPI_DIR / "config.yaml"
    if src_config.is_file():
        shutil.copy2(str(src_config), str(dest / "config.yaml"))
        log_ok("Copied config.yaml to dist")
    else:
        # Create a default config
        default_config = dest / "config.yaml"
        default_config.write_text(
            'host: "127.0.0.1"\n'
            "port: 8317\n"
            '\nauth-dir: "~/.cli-proxy-api"\n'
            "\napi-keys:\n"
            '  - "agent-commander-local"\n'
            "\ndebug: false\n",
            encoding="utf-8",
        )
        log("Created default config.yaml in dist")


def copy_workspace_templates() -> None:
    """Copy workspace templates into dist/_internal/workspace/."""
    src = PROJECT_ROOT / "workspace"
    if not src.exists():
        log("No workspace/ directory found — skipping")
        return

    dest = DIST_APP_DIR / "_internal" / "workspace"
    if dest.exists():
        shutil.rmtree(str(dest))
    shutil.copytree(str(src), str(dest))
    log_ok("Copied workspace templates to dist")


# ---------------------------------------------------------------------------
# Inno Setup
# ---------------------------------------------------------------------------
def find_inno_compiler() -> str | None:
    """Find Inno Setup compiler (iscc.exe)."""
    # Check PATH
    iscc = shutil.which("iscc")
    if iscc:
        return iscc

    # Check common install locations
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 5" / "ISCC.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def run_inno_setup(version: str) -> bool:
    """Compile the Inno Setup installer."""
    iscc = find_inno_compiler()
    if iscc is None:
        log("Inno Setup not found — skipping installer creation")
        log("  Install from https://jrsoftware.org/isdl.php to enable")
        return False

    log("Running Inno Setup compiler...")
    cmd = [
        iscc,
        f"/DAppVersion={version}",
        f"/DProjectRoot={PROJECT_ROOT}",
        f"/DDistDir={DIST_APP_DIR}",
        f"/DOutputDir={DIST_DIR}",
        str(INNO_SCRIPT),
    ]
    log(f"  {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        log_err("Inno Setup compilation failed")
        return False

    installer = DIST_DIR / f"AgentCommander_Setup_{version}.exe"
    if installer.exists():
        log_ok(f"Installer created: {installer}")
        log_ok(f"  Size: {installer.stat().st_size / (1024 * 1024):.1f} MB")
    return True


# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------
def clean() -> None:
    """Remove build artifacts."""
    for d in [DIST_DIR, PROJECT_ROOT / "build" / "pyinstaller_work"]:
        if d.exists():
            log(f"Removing {d}")
            shutil.rmtree(str(d))
    if ICON_FILE.exists():
        ICON_FILE.unlink()
    log_ok("Clean complete")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Build Agent Commander GUI installer")
    parser.add_argument("--skip-inno", action="store_true", help="Skip Inno Setup step")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts and exit")
    args = parser.parse_args()

    if args.clean:
        clean()
        return 0

    version = read_version()
    log(f"Building Agent Commander GUI v{version}")
    log(f"Project root: {PROJECT_ROOT}")

    # Step 1: Icon
    ensure_icon()

    # Step 2: PyInstaller
    if not ensure_pyinstaller():
        return 1

    if not run_pyinstaller():
        return 1

    # Step 3: Copy CLIProxyAPI
    copy_cliproxyapi()

    # Step 4: Copy workspace templates
    copy_workspace_templates()

    # Step 5: Inno Setup (optional)
    if not args.skip_inno:
        run_inno_setup(version)

    # Summary
    print()
    log_ok("Build complete!")
    exe = DIST_APP_DIR / "AgentCommander.exe"
    if exe.exists():
        log_ok(f"  Executable: {exe}")
        log_ok(f"  Size: {exe.stat().st_size / (1024 * 1024):.1f} MB")

    # Total dist size
    total = sum(f.stat().st_size for f in DIST_APP_DIR.rglob("*") if f.is_file())
    log_ok(f"  Total dist: {total / (1024 * 1024):.1f} MB")

    return 0


if __name__ == "__main__":
    sys.exit(main())
