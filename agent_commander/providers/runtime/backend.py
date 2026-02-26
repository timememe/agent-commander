"""PTY backends for running interactive CLI agents."""

from __future__ import annotations

import os
import subprocess
from typing import Optional, Protocol


class PTYBackend(Protocol):
    """Minimal PTY backend contract."""

    def read(self) -> str:
        """Read stdout/stderr chunk."""

    def write(self, data: str) -> None:
        """Write input data."""

    def resize(self, cols: int, rows: int) -> None:
        """Apply terminal resize."""

    def close(self) -> None:
        """Close process resources."""


class UnixPexpectBackend:
    """PTY backend for Unix-like systems via pexpect."""

    def __init__(
        self,
        command: str,
        cols: int = 80,
        rows: int = 24,
        cwd: str | None = None,
    ) -> None:
        import pexpect

        self._pexpect = pexpect
        self._proc = pexpect.spawn(
            command,
            encoding="utf-8",
            codec_errors="ignore",
            echo=False,
            dimensions=(rows, cols),
            cwd=cwd,
        )

    def read(self) -> str:
        try:
            return self._proc.read_nonblocking(size=4096, timeout=0.1)
        except self._pexpect.TIMEOUT:
            return ""
        except self._pexpect.EOF:
            return ""

    def write(self, data: str) -> None:
        self._proc.send(data)

    def resize(self, cols: int, rows: int) -> None:
        self._proc.setwinsize(rows, cols)

    def close(self) -> None:
        if self._proc.isalive():
            self._proc.close(force=True)


class WinptyBackend:
    """PTY backend for Windows via pywinpty."""

    def __init__(
        self,
        command: str,
        cols: int = 80,
        rows: int = 24,
        cwd: str | None = None,
    ) -> None:
        from winpty import Backend, PtyProcess

        env = dict(os.environ)
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLORTERM", "truecolor")

        launch_attempts = (
            {"backend": Backend.ConPTY},
            {"backend": Backend.WinPTY},
            {},
        )

        self._proc = None
        last_error: Optional[Exception] = None
        for extra in launch_attempts:
            try:
                self._proc = PtyProcess.spawn(
                    command,
                    dimensions=(rows, cols),
                    env=env,
                    cwd=cwd,
                    **extra,
                )
                break
            except Exception as exc:  # pragma: no cover - platform specific
                last_error = exc

        if self._proc is None:
            raise RuntimeError("Failed to start PTY backend") from last_error

    def read(self) -> str:
        try:
            return self._proc.read(4096)
        except Exception:
            return ""

    def write(self, data: str) -> None:
        self._proc.write(data)

    def resize(self, cols: int, rows: int) -> None:
        try:
            self._proc.setwinsize(rows, cols)
        except Exception:
            pass

    def close(self) -> None:
        pid: int | None = None
        try:
            pid = getattr(self._proc, "pid", None)
            self._proc.close()
        except Exception:
            pass
        # On Windows, kill the entire process tree so child processes don't linger.
        if pid is not None:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    timeout=3,
                )
            except Exception:
                pass


class SubprocessFallbackBackend:
    """Fallback backend when PTY is unavailable."""

    def __init__(
        self,
        command: str,
        cols: int = 80,
        rows: int = 24,
        cwd: str | None = None,
    ) -> None:
        del cols, rows
        self._proc = subprocess.Popen(
            command,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
            cwd=cwd,
        )

    def read(self) -> str:
        if not self._proc.stdout:
            return ""
        chunk = self._proc.stdout.read(1)
        return chunk or ""

    def write(self, data: str) -> None:
        if self._proc.stdin:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()

    def resize(self, cols: int, rows: int) -> None:
        del cols, rows

    def close(self) -> None:
        pid: int | None = getattr(self._proc, "pid", None)
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
        except Exception:
            pass
        if pid is not None:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    timeout=3,
                )
            except Exception:
                pass


def build_backend(
    command: str,
    cols: int = 80,
    rows: int = 24,
    cwd: str | None = None,
) -> PTYBackend:
    """Build the best available backend for the current platform."""
    from loguru import logger

    if os.name == "nt":
        try:
            backend = WinptyBackend(command, cols=cols, rows=rows, cwd=cwd)
            logger.info(f"[pty] Using WinptyBackend for: {command[:60]}")
            return backend
        except Exception as exc:
            logger.warning(f"[pty] WinptyBackend failed ({exc}), falling back to SubprocessFallbackBackend")
            return SubprocessFallbackBackend(command, cols=cols, rows=rows, cwd=cwd)
    backend = UnixPexpectBackend(command, cols=cols, rows=rows, cwd=cwd)
    logger.info(f"[pty] Using UnixPexpectBackend for: {command[:60]}")
    return backend
