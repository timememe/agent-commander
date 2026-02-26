"""CLIProxyAPI server lifecycle manager."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger


class ProxyServerManager:
    """Manages CLIProxyAPI process lifecycle and OAuth login commands."""

    def __init__(
        self,
        binary_path: str = "",
        config_path: str = "",
        base_url: str = "http://127.0.0.1:8317",
        api_key: str = "",
        project_root: str = "",
    ) -> None:
        self.binary_path = (binary_path or "").strip()
        self.config_path = (config_path or "").strip()
        self.base_url = (base_url or "http://127.0.0.1:8317").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.project_root = (project_root or "").strip()

        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def start(
        self,
        timeout_s: float = 5.0,
        force_restart: bool = False,
        take_over_existing: bool = False,
    ) -> bool:
        """
        Start CLIProxyAPI.

        Args:
            timeout_s: startup health-check timeout.
            force_restart: stop managed process first.
            take_over_existing: stop any process on proxy port, then start ours.
        """
        with self._lock:
            if force_restart:
                self._stop_locked(force=False)
            if take_over_existing:
                self._stop_locked(force=True)

            proc = self._process
            if proc is not None and proc.poll() is None:
                return self.health_check() is not None

            models = self.health_check()
            if models is not None:
                logger.info(f"CLIProxyAPI already running ({len(models)} models available)")
                return True

            binary = self._resolve_binary_path()
            if binary is None:
                logger.error("CLIProxyAPI binary not found. Set config.proxyApi.binaryPath.")
                return False

            cmd = [str(binary)]
            config_file = self._resolve_config_path(binary)
            if config_file is not None:
                cmd.extend(["--config", str(config_file)])

            logger.info(f"Starting CLIProxyAPI: {' '.join(cmd)}")
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(binary.parent),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError as exc:
                logger.error(f"Failed to start CLIProxyAPI: {exc}")
                self._process = None
                return False

            deadline = time.monotonic() + timeout_s
            interval = 0.25
            while time.monotonic() < deadline:
                time.sleep(interval)
                proc = self._process
                if proc is None:
                    return False
                if proc.poll() is not None:
                    logger.error(f"CLIProxyAPI exited immediately (code {proc.returncode})")
                    self._process = None
                    return False
                if self.health_check() is not None:
                    logger.info("CLIProxyAPI started and healthy")
                    return True
                interval = min(interval * 1.4, 1.0)

            logger.warning("CLIProxyAPI process started but health check timed out")
            proc = self._process
            return bool(proc is not None and proc.poll() is None)

    def stop(self, force: bool = False) -> bool:
        """
        Stop CLIProxyAPI.

        Args:
            force: also kill any listener on proxy port (attach/take-over mode).
        """
        with self._lock:
            return self._stop_locked(force=force)

    def restart(self, timeout_s: float = 8.0, force: bool = True) -> bool:
        """Restart CLIProxyAPI."""
        with self._lock:
            stopped = self._stop_locked(force=force)
            if force and not stopped and self.health_check() is not None and self._process is None:
                logger.warning("Unable to restart proxy: existing listener could not be stopped")
                return False
        return self.start(timeout_s=timeout_s, force_restart=False, take_over_existing=False)

    @property
    def is_running(self) -> bool:
        """Return True if process is healthy/running."""
        models = self.health_check()
        return models is not None

    def is_managed(self) -> bool:
        """Return True if this manager instance owns a live child process."""
        proc = self._process
        return bool(proc is not None and proc.poll() is None)

    def runtime_state(self) -> dict[str, object]:
        """Return runtime diagnostics for UI/status output."""
        models = self.health_check()
        running = models is not None
        managed = self.is_managed()
        binary = self._resolve_binary_path()
        config_file = self._resolve_config_path(binary)
        return {
            "running": running,
            "managed": managed,
            "attached": bool(running and not managed),
            "models": models or [],
            "binary_path": str(binary) if binary is not None else "",
            "config_path": str(config_file) if config_file is not None else "",
            "base_url": self.base_url,
        }

    def health_check(self) -> list[str] | None:
        """GET /v1/models and return list of model IDs, or None on failure."""
        url = f"{self.base_url}/v1/models"
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                models_list = data.get("data", [])
                return [m.get("id", "") for m in models_list if isinstance(m, dict)]
        except Exception:
            return None

    def get_provider_status(self) -> dict[str, bool]:
        """
        Check which providers have models available.

        Returns dict like {"claude": True, "gemini": False, "codex": False}.
        """
        models = self.health_check()
        if models is None:
            return {"claude": False, "gemini": False, "codex": False}

        status: dict[str, bool] = {"claude": False, "gemini": False, "codex": False}
        for model_id in models:
            mid = model_id.lower()
            if mid.startswith("claude"):
                status["claude"] = True
            elif mid.startswith("gemini"):
                status["gemini"] = True
            elif any(mid.startswith(p) for p in ("gpt-", "codex", "o1-", "o3-", "o4-")):
                status["codex"] = True
        return status

    def run_login(self, provider: str, *, no_browser: bool = True) -> subprocess.Popen | None:
        """
        Run OAuth login for a provider.

        Args:
            provider: One of "claude", "gemini", "codex".
        """
        return self.run_login_extended(provider, no_browser=no_browser)

    def run_login_extended(
        self,
        provider: str,
        *,
        no_browser: bool = True,
        capture_output: bool = False,
        interactive_stdin: bool = False,
        new_console: bool = True,
    ) -> subprocess.Popen | None:
        """
        Run OAuth login for a provider with configurable process I/O.

        Args:
            provider: One of "claude", "gemini", "codex".
            no_browser: pass --no-browser to CLIProxyAPI.
            capture_output: pipe stdout/stderr for UI parsing.
            interactive_stdin: enable writing to process stdin.
            new_console: open dedicated terminal window on Windows.
        """
        provider_key = (provider or "").strip().lower()
        if provider_key not in {"claude", "gemini", "codex"}:
            logger.error(f"Unsupported provider for login: {provider}")
            return None

        binary = self._resolve_binary_path()
        if binary is None:
            logger.error("CLIProxyAPI binary not found. Cannot run login.")
            return None

        flag_map = {
            "claude": "--claude-login",
            "codex": "--codex-login",
            # CLIProxyAPI uses --login for Gemini OAuth.
            "gemini": "--login",
        }
        flag = flag_map[provider_key]
        cmd = [str(binary), flag]
        config_file = self._resolve_config_path(binary)
        if config_file is not None:
            cmd.extend(["--config", str(config_file)])

        if no_browser:
            cmd.append("--no-browser")

        logger.info(f"Running OAuth login: {' '.join(cmd)}")
        kwargs: dict[str, object] = {
            "cwd": str(binary.parent),
        }
        if capture_output:
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.STDOUT
            kwargs["text"] = True
            kwargs["encoding"] = "utf-8"
            kwargs["errors"] = "ignore"
        if interactive_stdin:
            kwargs["stdin"] = subprocess.PIPE
        if os.name == "nt" and new_console:
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        try:
            return subprocess.Popen(cmd, **kwargs)
        except OSError as exc:
            logger.error(f"Failed to run login: {exc}")
            return None

    def disconnect_provider(self, provider: str) -> tuple[bool, int]:
        """
        Remove stored auth tokens for one provider from CLIProxyAPI auth-dir.

        Returns:
            (success, removed_files_count)
        """
        provider_key = (provider or "").strip().lower()
        if provider_key not in {"claude", "gemini", "codex"}:
            logger.error(f"Unsupported provider for disconnect: {provider}")
            return (False, 0)

        auth_dir = self._resolve_auth_dir()
        if auth_dir is None:
            logger.error("Cannot resolve CLIProxyAPI auth-dir for disconnect")
            return (False, 0)

        removed = 0
        patterns = self._provider_auth_patterns(provider_key)
        for pattern in patterns:
            for token_file in auth_dir.glob(pattern):
                if not token_file.is_file():
                    continue
                try:
                    token_file.unlink()
                    removed += 1
                except OSError as exc:
                    logger.warning(f"Failed to remove token file {token_file}: {exc}")

        logger.info(f"Disconnect {provider_key}: removed {removed} file(s) from {auth_dir}")
        return (True, removed)

    def provider_auth_snapshot(self, provider: str) -> tuple[str, ...]:
        """
        Return a stable snapshot of provider auth token files.

        Each entry is encoded as: "<name>|<size>|<mtime_ns>".
        """
        provider_key = (provider or "").strip().lower()
        if provider_key not in {"claude", "gemini", "codex"}:
            return ()
        auth_dir = self._resolve_auth_dir()
        if auth_dir is None:
            return ()

        rows: list[str] = []
        for pattern in self._provider_auth_patterns(provider_key):
            for path in sorted(auth_dir.glob(pattern)):
                if not path.is_file():
                    continue
                try:
                    st = path.stat()
                    rows.append(f"{path.name}|{int(st.st_size)}|{int(st.st_mtime_ns)}")
                except OSError:
                    continue
        return tuple(sorted(rows))

    def is_codex_cli_logged_in(self) -> bool:
        """
        Check Codex CLI auth status via `codex login status`.
        """
        cmd = self._resolve_codex_status_cmd()
        completed: subprocess.CompletedProcess[str] | None = None
        if cmd:
            try:
                completed = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=6.0,
                    check=False,
                )
            except Exception:
                completed = None

        # Windows/npm shim fallback when codex is not resolvable by CreateProcess.
        if completed is None and os.name == "nt":
            try:
                completed = subprocess.run(
                    ["cmd", "/c", "codex login status"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=8.0,
                    check=False,
                )
            except Exception:
                completed = None

        if completed is None:
            return False

        output = f"{completed.stdout or ''}\n{completed.stderr or ''}".lower()
        return "logged in" in output and "not logged in" not in output

    def _stop_locked(self, force: bool) -> bool:
        stopped = False

        proc = self._process
        if proc is not None:
            if proc.poll() is None:
                logger.info("Stopping managed CLIProxyAPI process")
                try:
                    # On Windows, force-stop should terminate the whole process tree
                    # (proxy + spawned child CLIs) to avoid leaked sessions.
                    if force and os.name == "nt":
                        if not self._terminate_pid(proc.pid):
                            proc.terminate()
                            proc.wait(timeout=5.0)
                    else:
                        proc.terminate()
                        proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)
                except OSError:
                    pass
                stopped = True
            self._process = None

        if force:
            listener_pids = sorted(self._find_listener_pids())
            if listener_pids:
                logger.info(f"Stopping proxy listeners on port: {listener_pids}")
            for pid in listener_pids:
                if pid <= 0 or pid == os.getpid():
                    continue
                if self._terminate_pid(pid):
                    stopped = True
            if not listener_pids:
                logger.info("No proxy listener PID found to stop")

        return stopped

    def _resolve_binary_path(self) -> Path | None:
        candidates: list[Path] = []
        configured = self._expand_path(self.binary_path)
        if configured is not None:
            candidates.append(configured)

        root = self._project_root_path()
        names = ["cli-proxy-api.exe", "cli-proxy-api"] if os.name == "nt" else ["cli-proxy-api"]
        if root is not None:
            for name in names:
                candidates.append(root / "cliproxyapi" / name)
                candidates.append(root / "bin" / name)
                candidates.append(root / name)

        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        return None

    def _resolve_config_path(self, binary: Path | None) -> Path | None:
        configured = self._expand_path(self.config_path)
        if configured is not None and configured.is_file():
            return configured.resolve()

        if binary is not None:
            for name in ("config.yaml", "config.yml"):
                adjacent = binary.parent / name
                if adjacent.is_file():
                    return adjacent.resolve()

        root = self._project_root_path()
        if root is not None:
            for name in ("config.yaml", "config.yml"):
                candidate = root / "cliproxyapi" / name
                if candidate.is_file():
                    return candidate.resolve()
        return None

    def _resolve_auth_dir(self) -> Path | None:
        """
        Resolve CLIProxyAPI auth-dir from config, fallback to ~/.cli-proxy-api.
        """
        binary = self._resolve_binary_path()
        config_file = self._resolve_config_path(binary)
        raw_value = ""
        if config_file is not None:
            try:
                text = config_file.read_text(encoding="utf-8", errors="ignore")
                match = re.search(r"^\s*auth-dir\s*:\s*(.+?)\s*$", text, flags=re.MULTILINE)
                if match:
                    raw_value = match.group(1).strip().strip('"\'')
            except OSError:
                raw_value = ""

        if not raw_value:
            raw_value = "~/.cli-proxy-api"

        p = Path(raw_value).expanduser()
        if not p.is_absolute() and config_file is not None:
            p = (config_file.parent / p).resolve()
        return p.resolve()

    def _resolve_codex_status_cmd(self) -> list[str]:
        """
        Resolve command for `codex login status` using env override when available.
        """
        raw = os.environ.get("AGENT_COMMANDER_CODEX_CMD", "").strip()
        if raw:
            try:
                import shlex

                parts = shlex.split(raw, posix=os.name != "nt")
            except Exception:
                parts = raw.split()
            if parts:
                return [*parts, "login", "status"]
        try:
            import shutil

            found = shutil.which("codex") or shutil.which("codex.cmd")
            if found:
                return [found, "login", "status"]
        except Exception:
            pass

        npm_codex = Path.home() / "AppData" / "Roaming" / "npm" / "codex.cmd"
        if npm_codex.is_file():
            return [str(npm_codex), "login", "status"]
        return []

    @staticmethod
    def _provider_auth_patterns(provider_key: str) -> tuple[str, ...]:
        if provider_key == "claude":
            return ("claude-*.json",)
        if provider_key == "gemini":
            return ("gemini-*.json", "google-*.json")
        if provider_key == "codex":
            return ("codex-*.json", "openai-*.json")
        return ()

    def _project_root_path(self) -> Path | None:
        value = self.project_root.strip()
        if not value:
            return None
        return Path(value).expanduser().resolve()

    def _expand_path(self, raw: str) -> Path | None:
        value = (raw or "").strip()
        if not value:
            return None
        p = Path(value).expanduser()
        if p.is_absolute():
            return p
        root = self._project_root_path()
        if root is not None:
            return (root / p).resolve()
        return p.resolve()

    def _find_listener_pids(self) -> set[int]:
        port = self._extract_port()
        if port is None:
            return set()
        if os.name == "nt":
            return self._find_listener_pids_windows(port)
        return self._find_listener_pids_posix(port)

    def _extract_port(self) -> int | None:
        raw = self.base_url.strip()
        if not raw:
            return None
        if "://" not in raw:
            raw = f"http://{raw}"
        parsed = urlparse(raw)
        if parsed.port is not None:
            return parsed.port
        if parsed.scheme == "https":
            return 443
        if parsed.scheme == "http":
            return 80
        return None

    def _find_listener_pids_windows(self, port: int) -> set[int]:
        pids: set[int] = set()
        try:
            result = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
        except Exception:
            return pids

        for line in (result.stdout or "").splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            proto, local_addr, _, state, pid_text = parts[0], parts[1], parts[2], parts[3], parts[4]
            if proto.upper() != "TCP":
                continue
            if state.upper() != "LISTENING":
                continue
            if not self._address_matches_port(local_addr, port):
                continue
            try:
                pids.add(int(pid_text))
            except ValueError:
                continue
        return pids

    def _find_listener_pids_posix(self, port: int) -> set[int]:
        pids: set[int] = set()
        try:
            result = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
        except Exception:
            return pids
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                pids.add(int(line))
            except ValueError:
                continue
        return pids

    @staticmethod
    def _address_matches_port(address: str, port: int) -> bool:
        text = (address or "").strip()
        if not text:
            return False
        if text.startswith("[") and "]:" in text:
            tail = text.rsplit("]:", 1)[-1]
        else:
            tail = text.rsplit(":", 1)[-1]
        try:
            return int(tail) == port
        except ValueError:
            return False

    @staticmethod
    def _terminate_pid(pid: int) -> bool:
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=5.0,
                    check=False,
                )
                if result.returncode == 0:
                    return True

                stderr = (result.stderr or "").strip()
                if stderr:
                    logger.warning(f"taskkill failed for PID {pid}: {stderr}")

                # Fallback: native PowerShell Stop-Process often works when taskkill does not.
                ps = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        f"Stop-Process -Id {pid} -Force",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5.0,
                    check=False,
                )
                if ps.returncode != 0:
                    ps_err = (ps.stderr or "").strip()
                    if ps_err:
                        logger.warning(f"Stop-Process failed for PID {pid}: {ps_err}")
                return ps.returncode == 0
            os.kill(pid, signal.SIGTERM)
            return True
        except Exception:
            return False
