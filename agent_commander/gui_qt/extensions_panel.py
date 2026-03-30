"""Extensions panel — manage external service integrations."""

from __future__ import annotations

import webbrowser
from datetime import datetime
from typing import Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from agent_commander.gui_qt import theme
from agent_commander.session.extension_store import ExtensionDef, ExtensionStore

# ---------------------------------------------------------------------------
# Provider definitions
# ---------------------------------------------------------------------------

_PROVIDERS: list[dict] = [
    {
        "id": "google",
        "name": "Google Workspace",
        "provider": "google",
        "badge_color": "#4285F4",
        "auth_type": "oauth2_gws",
        "services": ["Gmail", "Drive", "Calendar", "Sheets", "Docs", "Slides", "Tasks"],
        "gws_services": "gmail,drive,calendar,sheets,docs,slides,tasks",
        "fields": [
            {
                "key": "client_id",
                "label": "Client ID",
                "placeholder": "xxxx.apps.googleusercontent.com",
                "show": True,
            },
            {
                "key": "client_secret",
                "label": "Client Secret",
                "placeholder": "GOCSPX-...",
                "show": False,
            },
        ],
        "get_token_url": "https://console.cloud.google.com/apis/credentials",
        "steps": [
            "1. Нажми 'Get Credentials' — откроется Google Cloud Console",
            "2. Создай проект → включи нужные API (Gmail, Drive, Calendar, Sheets, Docs)",
            "3. Credentials → Create OAuth 2.0 Client ID → тип: Desktop app",
            "4. Вставь Client ID и Client Secret ниже",
            "5. Нажми 'Authorize with Google' — откроется браузер для входа",
        ],
    },
    {
        "id": "yandex",
        "name": "Яндекс",
        "provider": "yandex",
        "badge_color": "#FC3F1D",
        "auth_type": "app_password",
        "services": ["Яндекс Почта", "Яндекс Диск"],
        "fields": [
            {
                "key": "email",
                "label": "Яндекс email",
                "placeholder": "you@yandex.ru",
                "show": True,
            },
            {
                "key": "token",
                "label": "Пароль приложения",
                "placeholder": "xxxx xxxx xxxx xxxx",
                "show": False,
            },
        ],
        "get_token_url": "https://id.yandex.ru/security/app-passwords",
        "steps": [
            "1. Нажмите 'Get Token' — откроется раздел 'Пароли приложений' в Яндекс ID",
            "2. Нажмите 'Создать пароль приложения'",
            "3. Один пароль работает для Почты (IMAP) и Диска (WebDAV)",
            "4. Скопируйте пароль (показывается один раз) и вставьте ниже",
        ],
    },
    {
        "id": "worksection_user",
        "name": "Worksection User",
        "provider": "worksection_user",
        "badge_color": "#0066CC",
        "auth_type": "worksection_oauth",
        "services": ["Tasks", "Projects", "Comments"],
        "fields": [
            {
                "key": "account",
                "label": "Домен Worksection",
                "placeholder": "ws.company.com  или  mycompany.worksection.com",
                "show": True,
            },
            {
                "key": "client_id",
                "label": "OAuth Client ID",
                "placeholder": "Client ID from Worksection OAuth app",
                "show": True,
            },
            {
                "key": "client_secret",
                "label": "OAuth Client Secret",
                "placeholder": "Client Secret",
                "show": False,
            },
        ],
        "get_token_url": "https://worksection.com/en/faq/oauth.html",
        "steps": [
            "1. Войдите в Worksection → аватар → Настройки аккаунта → API/OAuth",
            "2. Создайте новое OAuth-приложение",
            "3. Redirect URI укажите: https://localhost:19876/",
            "4. Скопируйте Client ID и Client Secret",
            "5. Введите subdomain, Client ID, Client Secret ниже",
            "6. Нажмите 'Authorize with Worksection →'",
        ],
    },
    {
        "id": "worksection_admin",
        "name": "Worksection Admin",
        "provider": "worksection_admin",
        "badge_color": "#004499",
        "auth_type": "app_password",
        "services": ["Tasks", "Projects", "Users", "Time", "Admin"],
        "fields": [
            {
                "key": "account",
                "label": "Домен Worksection",
                "placeholder": "ws.company.com  или  mycompany.worksection.com",
                "show": True,
            },
            {
                "key": "email",
                "label": "Admin email",
                "placeholder": "admin@mycompany.com",
                "show": True,
            },
            {
                "key": "api_key",
                "label": "Admin API Key",
                "placeholder": "API key from Worksection settings",
                "show": False,
            },
        ],
        "get_token_url": "https://worksection.com/admin/account/api/",
        "steps": [
            "1. Нажмите 'Get Token' — откроется страница API в настройках Worksection",
            "2. Скопируйте API Key (или сгенерируйте новый)",
            "3. Введите subdomain аккаунта, email администратора и API Key",
            "4. Нажмите 'Сохранить'",
        ],
    },
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# gws (Google Workspace CLI) helpers
# ---------------------------------------------------------------------------

import os
import json as _json
import platform as _platform
import shutil as _shutil
import subprocess as _subprocess
import urllib.request as _urllib_request
import zipfile as _zipfile
import tarfile as _tarfile
from pathlib import Path as _Path

_GWS_VERSION = "0.18.1"
_GWS_DIR = _Path.home() / ".agent-commander" / "gws"


def _gws_bin_name() -> str:
    return "gws.exe" if os.name == "nt" else "gws"


def _find_gws() -> str | None:
    """Return path to gws binary, or None if not found."""
    managed = _GWS_DIR / "bin" / _gws_bin_name()
    if managed.is_file():
        return str(managed)
    found = _shutil.which("gws") or _shutil.which("gws.exe")
    return found or None


def _find_gcloud() -> str | None:
    """Return path to gcloud CLI, or None if not installed.

    Checks PATH first, then common installation directories (needed when
    gcloud was just installed and the current process PATH is stale).
    """
    found = _shutil.which("gcloud") or _shutil.which("gcloud.cmd")
    if found:
        return found

    system = _platform.system().lower()
    if system == "windows":
        candidates = []
        for base_var in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)", "USERPROFILE"):
            base = os.environ.get(base_var, "")
            if base:
                candidates.append(_Path(base) / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd")
        # Also check default install path reported by the SDK installer
        candidates.append(_Path.home() / "AppData" / "Local" / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd")
    elif system == "darwin":
        candidates = [
            _Path("/usr/lib/google-cloud-sdk/bin/gcloud"),
            _Path("/usr/local/lib/google-cloud-sdk/bin/gcloud"),
            _Path("/opt/homebrew/lib/google-cloud-sdk/bin/gcloud"),
            _Path.home() / "google-cloud-sdk" / "bin" / "gcloud",
        ]
    else:
        candidates = [
            _Path("/usr/lib/google-cloud-sdk/bin/gcloud"),
            _Path("/snap/bin/gcloud"),
            _Path.home() / "google-cloud-sdk" / "bin" / "gcloud",
        ]

    for cand in candidates:
        if cand.exists():
            return str(cand)
    return None


def _gcloud_account() -> str:
    """Return active gcloud account email, or empty string."""
    gcloud = _find_gcloud()
    if not gcloud:
        return ""
    try:
        r = _subprocess.run(
            [gcloud, "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip().splitlines()[0] if r.returncode == 0 else ""
    except Exception:
        return ""


def _gws_download_url() -> str:
    system = _platform.system().lower()
    machine = _platform.machine().lower()
    v = _GWS_VERSION
    if system == "windows":
        return f"https://github.com/googleworkspace/cli/releases/download/v{v}/gws-x86_64-pc-windows-msvc.zip"
    if system == "darwin":
        arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"https://github.com/googleworkspace/cli/releases/download/v{v}/gws-{arch}-apple-darwin.tar.gz"
    arch = "x86_64"
    return f"https://github.com/googleworkspace/cli/releases/download/v{v}/gws-{arch}-unknown-linux-gnu.tar.gz"


class _FullGoogleSetupThread(QThread):
    """One-click setup: install gcloud (if needed) → gcloud auth login → gws auth setup."""
    status = Signal(str)
    open_url = Signal(str)
    auth_success = Signal(dict)
    auth_failed = Signal(str)

    def __init__(self, gws_path: str, services: str) -> None:
        super().__init__()
        self._gws = gws_path
        self._services = services

    def run(self) -> None:
        import re as _re
        _url_re = _re.compile(r"https://accounts\.google\.com\S+|https://oauth2\.googleapis\.com\S+")

        config_dir = _GWS_DIR / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        gws_env = {
            **os.environ,
            "GOOGLE_WORKSPACE_CLI_CONFIG_DIR": str(config_dir),
            "GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND": "file",
        }

        # ── Step 1: install gcloud if missing ────────────────────────────
        gcloud = _find_gcloud()
        if not gcloud:
            self.status.emit("Устанавливаю Google Cloud SDK…")
            ok = self._install_gcloud()
            if not ok:
                self.auth_failed.emit(
                    "Не удалось установить gcloud автоматически.\n"
                    "Установи вручную: https://cloud.google.com/sdk/docs/install"
                )
                return
            gcloud = _find_gcloud()
            # Refresh PATH on Windows after install
            if not gcloud and os.name == "nt":
                for cand in [
                    _Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd",
                    _Path(os.environ.get("ProgramFiles", "")) / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd",
                ]:
                    if cand.exists():
                        gcloud = str(cand)
                        break
            if not gcloud:
                self.auth_failed.emit("gcloud установлен, но не найден в PATH. Перезапусти приложение.")
                return
            self.status.emit("✓  Google Cloud SDK установлен.")

        # ── Step 2: gcloud auth login ────────────────────────────────────
        # Use standard flow (no --no-launch-browser): gcloud opens browser
        # automatically and starts a local redirect server — no manual code entry.
        account = _gcloud_account()
        if not account:
            self.status.emit("Открываю браузер для входа в Google аккаунт…")
            _browser_opened = False
            proc = _subprocess.Popen(
                [gcloud, "auth", "login", "--brief"],
                stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT,
                stdin=_subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="ignore",
            )
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                m = _url_re.search(line)
                if m and not _browser_opened:
                    self.open_url.emit(m.group(0))
                    _browser_opened = True
                    self.status.emit("Браузер открыт. Войди в Google аккаунт и подтверди доступ…")
                elif "you are now logged in" in line.lower() or "logged in as" in line.lower():
                    self.status.emit(f"✓  {line}")
                else:
                    self.status.emit(line)
            proc.wait()
            if proc.returncode != 0:
                self.auth_failed.emit(
                    f"gcloud auth login завершился с ошибкой (код {proc.returncode}).\n"
                    "Попробуй запустить вручную: gcloud auth login"
                )
                return

        account = _gcloud_account()
        if account:
            self.status.emit(f"✓  Вошёл как {account}. Настраиваю доступ к сервисам…")

        # ── Step 3: gws auth setup ────────────────────────────────────────
        def _run_gws_setup(cmd: list) -> tuple[int, str]:
            """Run gws auth setup, stream output, return (returncode, last_lines)."""
            output_lines: list[str] = []
            _browser_opened = False
            proc = _subprocess.Popen(
                cmd, env=gws_env,
                stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT,
                stdin=_subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="ignore",
            )
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                output_lines.append(line)
                m = _url_re.search(line)
                if m and not _browser_opened:
                    self.open_url.emit(m.group(0))
                    _browser_opened = True
                    self.status.emit("Браузер открыт. Разреши доступ к сервисам Google…")
                else:
                    self.status.emit(line)
            proc.wait()
            tail = "\n".join(output_lines[-5:]) if output_lines else ""
            return proc.returncode, tail

        # Try with services list first, then without (in case service names differ)
        base_cmd = [self._gws, "auth", "setup", "--login"]
        cmd_with_svc = base_cmd + ["--services", self._services] if self._services else base_cmd
        rc, tail = _run_gws_setup(cmd_with_svc)

        if rc != 0 and self._services and cmd_with_svc != base_cmd:
            self.status.emit(f"gws setup --services завершился с кодом {rc}, пробую без --services…")
            rc, tail = _run_gws_setup(base_cmd)

        if rc != 0:
            self.auth_failed.emit(
                f"gws auth setup завершился с кодом {rc}.\n\nВывод gws:\n{tail or '(пусто)'}"
            )
            return

        # ── Done ─────────────────────────────────────────────────────────
        email = account or ""
        if not email:
            st = _subprocess.run([self._gws, "auth", "status"], env=gws_env,
                                 capture_output=True, text=True, encoding="utf-8")
            if st.returncode == 0:
                m = _re.search(r"[\w.+-]+@[\w.-]+\.\w+", st.stdout)
                email = m.group(0) if m else ""

        self.auth_success.emit({
            "email": email,
            "gws_config_dir": str(config_dir),
            "gws_bin": self._gws,
            "auth_method": "gcloud_setup",
        })

    def _install_gcloud(self) -> bool:
        """Try to install gcloud via winget (Windows) or brew (macOS), streaming progress."""
        system = _platform.system().lower()
        if system == "windows":
            winget = _shutil.which("winget")
            if winget:
                self.status.emit("Устанавливаю Google Cloud SDK через winget (это может занять 2–5 минут)…")
                last_line = ""
                proc = _subprocess.Popen(
                    [winget, "install", "Google.CloudSDK",
                     "--silent", "--accept-package-agreements", "--accept-source-agreements"],
                    stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="ignore",
                )
                for line in proc.stdout:
                    line = line.strip()
                    if line:
                        last_line = line
                        self.status.emit(f"winget: {line}")
                proc.wait()
                if proc.returncode == 0 or "already installed" in last_line.lower():
                    return True
                self.status.emit(f"winget не сработал ({last_line[-120:]}) — пробую installer…")
            # Fallback: download silent installer
            installer_url = "https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe"
            installer_path = _GWS_DIR / "GoogleCloudSDKInstaller.exe"
            self.status.emit("Скачиваю Google Cloud SDK installer (~300MB)…")
            _urllib_request.urlretrieve(installer_url, str(installer_path))
            self.status.emit("Запускаю установщик в тихом режиме…")
            r = _subprocess.run(
                [str(installer_path), "/S", "/allusers"],
                capture_output=True, encoding="utf-8", errors="ignore",
            )
            return r.returncode == 0
        elif system == "darwin":
            brew = _shutil.which("brew")
            if brew:
                self.status.emit("Устанавливаю через Homebrew (может занять несколько минут)…")
                proc = _subprocess.Popen(
                    [brew, "install", "google-cloud-sdk"],
                    stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="ignore",
                )
                for line in proc.stdout:
                    line = line.strip()
                    if line:
                        self.status.emit(f"brew: {line}")
                proc.wait()
                return proc.returncode == 0
        return False


class _GCloudInstallThread(QThread):
    """Installs gcloud CLI via winget (Windows) or Homebrew (macOS)."""
    status = Signal(str)
    done = Signal(str)   # path to gcloud binary
    failed = Signal(str)

    def run(self) -> None:
        try:
            system = _platform.system().lower()
            if system == "windows":
                winget = _shutil.which("winget")
                if winget:
                    self.status.emit("Устанавливаю Google Cloud SDK через winget (2–5 минут)…")
                    proc = _subprocess.Popen(
                        [winget, "install", "Google.CloudSDK",
                         "--silent", "--accept-package-agreements", "--accept-source-agreements"],
                        stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT,
                        stdin=_subprocess.DEVNULL,
                        text=True, encoding="utf-8", errors="ignore",
                    )
                    last = ""
                    for line in proc.stdout:
                        line = line.strip()
                        if line:
                            last = line
                            self.status.emit(f"winget: {line}")
                    proc.wait()
                    # Always check if gcloud is present after winget — it may be
                    # already installed (winget returns non-zero but gcloud is there)
                    gcloud = _find_gcloud()
                    if not gcloud:
                        for cand in [
                            _Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd",
                            _Path(os.environ.get("ProgramFiles", "")) / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd",
                            _Path(os.environ.get("ProgramFiles(x86)", "")) / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd",
                        ]:
                            if cand.exists():
                                gcloud = str(cand)
                                break
                    if gcloud:
                        self.done.emit(gcloud)
                        return
                    if proc.returncode != 0:
                        self.failed.emit(f"winget завершился с кодом {proc.returncode}:\n{last[-200:]}")
                        return
                    self.failed.emit("gcloud не найден после установки. Перезапусти приложение.")
                    return
                # Fallback: silent installer
                installer_url = "https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe"
                installer_path = _GWS_DIR / "GoogleCloudSDKInstaller.exe"
                self.status.emit("Скачиваю Google Cloud SDK installer (~300MB)…")
                _urllib_request.urlretrieve(installer_url, str(installer_path))
                self.status.emit("Запускаю установщик в тихом режиме…")
                r = _subprocess.run(
                    [str(installer_path), "/S", "/allusers"],
                    capture_output=True, encoding="utf-8", errors="ignore",
                )
                if r.returncode == 0:
                    gcloud = _find_gcloud()
                    if gcloud:
                        self.done.emit(gcloud)
                        return
                self.failed.emit("Установка завершилась, но gcloud не найден. Перезапусти приложение.")
            elif system == "darwin":
                brew = _shutil.which("brew")
                if brew:
                    self.status.emit("Устанавливаю через Homebrew (несколько минут)…")
                    proc = _subprocess.Popen(
                        [brew, "install", "google-cloud-sdk"],
                        stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT,
                        stdin=_subprocess.DEVNULL,
                        text=True, encoding="utf-8", errors="ignore",
                    )
                    for line in proc.stdout:
                        line = line.strip()
                        if line:
                            self.status.emit(f"brew: {line}")
                    proc.wait()
                    gcloud = _find_gcloud()
                    if gcloud:
                        self.done.emit(gcloud)
                        return
                self.failed.emit("Не удалось установить gcloud автоматически.")
            else:
                self.failed.emit("Автоустановка не поддерживается. Установи gcloud вручную.")
        except Exception as exc:
            self.failed.emit(str(exc))


class _GCloudLoginThread(QThread):
    """Runs `gcloud auth login` and returns the authenticated account."""
    status = Signal(str)
    open_url = Signal(str)
    done = Signal(str)   # account email
    failed = Signal(str)

    def __init__(self, gcloud_path: str) -> None:
        super().__init__()
        self._gcloud = gcloud_path

    def run(self) -> None:
        try:
            import re as _re
            _url_re = _re.compile(r"https://accounts\.google\.com\S+|https://oauth2\.googleapis\.com\S+")

            self.status.emit("Открываю браузер для входа в Google аккаунт…")
            _browser_opened = False

            proc = _subprocess.Popen(
                [self._gcloud, "auth", "login", "--brief"],
                stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT,
                stdin=_subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="ignore",
            )
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                m = _url_re.search(line)
                if m and not _browser_opened:
                    self.open_url.emit(m.group(0))
                    _browser_opened = True
                    self.status.emit("Браузер открыт. Войди и подтверди доступ…")
                elif "you are now logged in" in line.lower() or "logged in as" in line.lower():
                    self.status.emit(f"✓  {line}")
                else:
                    self.status.emit(line)
            proc.wait()

            if proc.returncode != 0:
                self.failed.emit(f"gcloud auth login завершился с кодом {proc.returncode}.")
                return

            # Use self._gcloud directly — shutil.which() may not find it if PATH wasn't refreshed
            account = ""
            try:
                r = _subprocess.run(
                    [self._gcloud, "auth", "list",
                     "--filter=status:ACTIVE", "--format=value(account)"],
                    capture_output=True, text=True, timeout=8,
                )
                lines = r.stdout.strip().splitlines()
                account = lines[0] if lines else ""
            except Exception:
                pass
            self.done.emit(account)
        except Exception as exc:
            self.failed.emit(str(exc))


class _GWSSetupThread(QThread):
    """Runs `gws auth setup --login` using the installed gcloud CLI."""
    status = Signal(str)
    open_url = Signal(str)
    auth_success = Signal(dict)
    auth_failed = Signal(str)

    def __init__(self, client_config: dict, email: str = "") -> None:
        super().__init__()
        self._client_config = client_config
        self._email = email

    def run(self) -> None:
        try:
            # ── Step 1: Ensure google-auth-oauthlib ───────────────────────
            try:
                from google_auth_oauthlib.flow import InstalledAppFlow as _Flow
            except ImportError:
                self.status.emit("Устанавливаю google-auth-oauthlib…")
                import sys as _sys
                r = _subprocess.run(
                    [_sys.executable, "-m", "pip", "install", "google-auth-oauthlib"],
                    capture_output=True, text=True,
                )
                if r.returncode != 0:
                    self.auth_failed.emit(
                        f"Не удалось установить google-auth-oauthlib:\n{r.stderr[:300]}"
                    )
                    return
                from google_auth_oauthlib.flow import InstalledAppFlow as _Flow

            # ── Step 2: Build flow from uploaded client_secrets.json ──────
            _SCOPES = [
                "openid",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile",
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/documents",
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/gmail.modify",
            ]
            flow = _Flow.from_client_config(self._client_config, scopes=_SCOPES)

            # ── Step 3: Run OAuth flow, intercept webbrowser.open ─────────
            import webbrowser as _wb
            _orig = _wb.open

            def _intercept(url, new=0, autoraise=True):
                self.open_url.emit(url)
                self.status.emit("Браузер открыт. Подтверди доступ…")
                return True

            _wb.open = _intercept
            try:
                self.status.emit("Открываю браузер для авторизации…")
                creds = flow.run_local_server(port=0, prompt="select_account consent")
            finally:
                _wb.open = _orig

            if not creds.refresh_token:
                self.auth_failed.emit(
                    "refresh_token не получен.\n"
                    "Попробуйте снова — выберите аккаунт в браузере."
                )
                return

            # ── Step 4: Get email ─────────────────────────────────────────
            email = self._email or ""
            try:
                import urllib.request as _ureq
                req = _ureq.Request(
                    "https://www.googleapis.com/oauth2/v1/userinfo",
                    headers={"Authorization": f"Bearer {creds.token}"},
                )
                with _ureq.urlopen(req, timeout=5) as resp:
                    info = _json.loads(resp.read())
                    email = info.get("email", "") or email
            except Exception:
                pass

            self.status.emit(f"✓  Подключено{' как ' + email if email else ''}!")
            self.auth_success.emit({
                "email": email,
                "token": creds.token or "",
                "refresh_token": creds.refresh_token,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "gws_bin": "",
                "gws_config_dir": "",
                "auth_method": "oauthlib",
            })
        except Exception as exc:
            self.auth_failed.emit(str(exc))


class _GWSDownloadThread(QThread):
    """Downloads gws binary from GitHub releases."""
    progress = Signal(str)
    done = Signal(str)    # path to binary
    failed = Signal(str)

    def run(self) -> None:
        try:
            url = _gws_download_url()
            bin_dir = _GWS_DIR / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            archive_name = url.split("/")[-1]
            archive_path = _GWS_DIR / archive_name

            self.progress.emit(f"Downloading gws v{_GWS_VERSION}…")
            _urllib_request.urlretrieve(url, str(archive_path))

            self.progress.emit("Extracting…")
            dest = bin_dir / _gws_bin_name()

            if archive_name.endswith(".zip"):
                with _zipfile.ZipFile(archive_path) as zf:
                    for member in zf.namelist():
                        if member.lower().endswith("gws.exe") or member == "gws.exe":
                            with zf.open(member) as src:
                                dest.write_bytes(src.read())
                            break
            else:
                with _tarfile.open(archive_path) as tf:
                    for member in tf.getmembers():
                        if member.name.endswith("/gws") or member.name == "gws":
                            f = tf.extractfile(member)
                            if f:
                                dest.write_bytes(f.read())
                            break

            archive_path.unlink(missing_ok=True)
            if os.name != "nt":
                dest.chmod(0o755)

            self.done.emit(str(dest))
        except Exception as exc:
            self.failed.emit(str(exc))


class _GWSAuthThread(QThread):
    """Runs `gws auth login` then exports credentials."""
    status = Signal(str)
    open_url = Signal(str)   # emitted when gws prints an auth URL to open
    auth_success = Signal(dict)
    auth_failed = Signal(str)

    def __init__(
        self, gws_path: str, client_id: str, client_secret: str,
        services: str, json_path: str = "",
    ) -> None:
        super().__init__()
        self._gws = gws_path
        self._client_id = client_id
        self._client_secret = client_secret
        self._services = services  # e.g. "gmail,drive,calendar,sheets,docs"
        self._json_path = json_path  # path to client_secret.json (optional)

    def run(self) -> None:
        try:
            config_dir = _GWS_DIR / "config"
            config_dir.mkdir(parents=True, exist_ok=True)

            env = {**os.environ, "GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND": "file"}
            env["GOOGLE_WORKSPACE_CLI_CONFIG_DIR"] = str(config_dir)

            # If JSON file provided, copy it into config dir so gws picks it up
            if self._json_path and _Path(self._json_path).is_file():
                dest_json = config_dir / "client_secret.json"
                import shutil as _shutil_local
                _shutil_local.copy2(self._json_path, str(dest_json))
            elif self._client_id and self._client_secret:
                env["GOOGLE_WORKSPACE_CLI_CLIENT_ID"] = self._client_id
                env["GOOGLE_WORKSPACE_CLI_CLIENT_SECRET"] = self._client_secret

            self.status.emit("Запускаю gws auth login…")

            cmd = [self._gws, "auth", "login", "--full"]
            if self._services:
                cmd += ["--services", self._services]

            import re as _re
            _url_re = _re.compile(r"https://accounts\.google\.com\S+|https://oauth2\.googleapis\.com\S+")
            _browser_opened = False

            proc = _subprocess.Popen(
                cmd, env=env,
                stdout=_subprocess.PIPE,
                stderr=_subprocess.STDOUT,
                text=True, encoding="utf-8", errors="ignore",
            )
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                # Detect auth URL in gws output and open browser ourselves
                m = _url_re.search(line)
                if m and not _browser_opened:
                    url = m.group(0)
                    self.open_url.emit(url)
                    _browser_opened = True
                    self.status.emit("Браузер открыт. Войди в Google и разреши доступ…")
                else:
                    self.status.emit(line)
            proc.wait()

            if proc.returncode != 0:
                self.auth_failed.emit(f"gws auth login завершился с кодом {proc.returncode}")
                return

            self.status.emit("Авторизация успешна, получаю данные аккаунта…")

            # Get email via auth status (try multiple output formats)
            email = ""
            for status_cmd in (
                [self._gws, "auth", "status", "--format", "json"],
                [self._gws, "auth", "status"],
            ):
                st = _subprocess.run(
                    status_cmd, env=env, capture_output=True, text=True, encoding="utf-8",
                )
                if st.returncode == 0 and st.stdout.strip():
                    try:
                        st_data = _json.loads(st.stdout)
                        email = st_data.get("email", st_data.get("account", ""))
                    except Exception:
                        # Plain text output — try to find email pattern
                        import re
                        m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", st.stdout)
                        if m:
                            email = m.group(0)
                    if email:
                        break

            # Try to export credentials for optional token storage
            refresh_token = ""
            access_token = ""
            token_expiry = ""
            for export_cmd in (
                [self._gws, "auth", "export", "--unmasked"],
                [self._gws, "auth", "export"],
                [self._gws, "auth", "token"],
            ):
                exp = _subprocess.run(
                    export_cmd, env=env, capture_output=True, text=True, encoding="utf-8",
                )
                if exp.returncode == 0 and exp.stdout.strip():
                    try:
                        creds_data = _json.loads(exp.stdout)
                        refresh_token = creds_data.get("refresh_token", "")
                        access_token = creds_data.get("token", creds_data.get("access_token", ""))
                        token_expiry = creds_data.get("expiry", creds_data.get("expires_at", ""))
                    except Exception:
                        pass
                    break

            # Also check for credential files directly in config_dir
            if not refresh_token:
                for fname in ("credentials.json", "auth.json", "token.json"):
                    cred_file = config_dir / fname
                    if cred_file.exists():
                        try:
                            data = _json.loads(cred_file.read_text(encoding="utf-8"))
                            refresh_token = data.get("refresh_token", "")
                            access_token = data.get("token", data.get("access_token", ""))
                            token_expiry = data.get("expiry", "")
                        except Exception:
                            pass
                        if refresh_token:
                            break

            self.auth_success.emit({
                "email": email,
                "token": access_token,
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "token_expiry": token_expiry,
                "gws_config_dir": str(config_dir),
                "gws_bin": self._gws,
            })
        except Exception as exc:
            self.auth_failed.emit(str(exc))


# ---------------------------------------------------------------------------
# Worksection OAuth2 helpers
# ---------------------------------------------------------------------------

def _ensure_localhost_cert() -> str:
    """Return path to a self-signed cert+key PEM for localhost (generate once, cache)."""
    from pathlib import Path
    cache_dir = Path.home() / ".agent-commander" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cache_dir / "localhost_oauth.pem"
    if cert_path.exists():
        return str(cert_path)

    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256())
        )
        pem = (
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
            + cert.public_bytes(serialization.Encoding.PEM)
        )
        cert_path.write_bytes(pem)
        return str(cert_path)
    except ImportError:
        # cryptography not installed — fall back to openssl subprocess
        import subprocess
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(cert_path), "-out", str(cert_path),
                "-days", "3650", "-subj", "/CN=localhost",
            ],
            check=True, capture_output=True,
        )
        return str(cert_path)


# ---------------------------------------------------------------------------
# Worksection OAuth2 background thread
# ---------------------------------------------------------------------------

class _WorksectionTokenThread(QThread):
    """Exchanges authorization code for access token (runs off UI thread)."""

    auth_success = Signal(dict)
    auth_failed = Signal(str)

    _WS_TOKEN_URL = "https://worksection.com/oauth2/token"

    def __init__(
        self, account: str, client_id: str, client_secret: str,
        code: str, redirect_uri: str,
    ) -> None:
        super().__init__()
        self._account = account
        self._client_id = client_id
        self._client_secret = client_secret
        self._code = code
        self._redirect_uri = redirect_uri

    def run(self) -> None:
        import base64, json, urllib.error, urllib.parse, urllib.request

        _BROWSER_UA = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

        def _try_exchange(url: str, extra_headers: dict, body: dict) -> dict:
            data = urllib.parse.urlencode(body).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            req.add_header("Accept", "application/json")
            req.add_header("User-Agent", _BROWSER_UA)
            req.add_header("Accept-Language", "en-US,en;q=0.9")
            req.add_header("Origin", f"https://{self._account}")
            req.add_header("Referer", f"https://{self._account}/")
            for k, v in extra_headers.items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))

        try:
            basic = base64.b64encode(
                f"{self._client_id}:{self._client_secret}".encode()
            ).decode()

            body_with_creds = {
                "grant_type": "authorization_code",
                "code": self._code,
                "redirect_uri": self._redirect_uri,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
            body_no_creds = {
                "grant_type": "authorization_code",
                "code": self._code,
                "redirect_uri": self._redirect_uri,
            }

            account_domain = self._account.strip().lstrip("https://").lstrip("http://").rstrip("/")
            account_token_url = f"https://{account_domain}/oauth2/token"

            token_resp = None
            last_err = None
            attempts = [
                (account_token_url, {"Authorization": f"Basic {basic}"}, body_no_creds),
                (account_token_url, {}, body_with_creds),
                (self._WS_TOKEN_URL, {"Authorization": f"Basic {basic}"}, body_no_creds),
                (self._WS_TOKEN_URL, {}, body_with_creds),
            ]
            for url, headers, body in attempts:
                try:
                    token_resp = _try_exchange(url, headers, body)
                    break
                except urllib.error.HTTPError as e:
                    last_err = f"HTTP {e.code} ({url}): {e.read().decode('utf-8', errors='replace')[:200]}"
                except Exception as e:
                    last_err = f"{url}: {e}"

            if token_resp is None:
                self.auth_failed.emit(f"Token exchange failed: {last_err}")
                return

            access_token = token_resp.get("access_token", "")
            refresh_token = token_resp.get("refresh_token", "")
            if not access_token:
                self.auth_failed.emit(f"No access_token in response: {token_resp}")
                return

            self.auth_success.emit({
                "account": self._account,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            })
        except Exception as exc:
            self.auth_failed.emit(str(exc))


# ---------------------------------------------------------------------------
# Worksection OAuth dialog
# ---------------------------------------------------------------------------

class _WorksectionOAuthDialog(QDialog):
    """OAuth2 connection dialog for Worksection — manual code paste flow."""

    _WS_AUTH_URL = "https://worksection.com/oauth2/authorize"
    _WS_SCOPES = "projects_read,projects_write,tasks_read,tasks_write,comments_read,comments_write,users_read"

    def __init__(
        self,
        provider_info: dict,
        existing: "ExtensionDef | None",
        on_save: "Callable[[str, dict], None]",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._provider_info = provider_info
        self._on_save = on_save
        self._token_thread: _WorksectionTokenThread | None = None
        self._entries: dict[str, QLineEdit] = {}

        self.setWindowTitle(f"Connect — {provider_info['name']}")
        self.setMinimumWidth(500)
        self.setStyleSheet(f"background-color: {theme.BG_PANEL};")

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── Header ──────────────────────────────────────────────────────
        header = QFrame()
        header.setStyleSheet(f"background-color: {theme.BG_INPUT};")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(20, 16, 20, 16)
        hl.setSpacing(8)
        badge = QLabel(provider_info["name"])
        badge.setStyleSheet(
            f"background-color: {provider_info['badge_color']}; color: white;"
            " border-radius: 4px; padding: 3px 12px; font-weight: bold; font-size: 14px;"
        )
        badge.setFixedHeight(28)
        hl.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(header)

        # ── Body ────────────────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 16, 20, 16)
        bl.setSpacing(10)

        def _section(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {theme.TEXT}; font-size: 12px; font-weight: bold; background: transparent;"
            )
            return lbl

        def _hint(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
            )
            return lbl

        def _field(placeholder: str, secret: bool = False, value: str = "") -> QLineEdit:
            e = QLineEdit()
            e.setPlaceholderText(placeholder)
            e.setFixedHeight(34)
            e.setStyleSheet(
                f"QLineEdit {{ background: {theme.BG_INPUT}; color: {theme.TEXT};"
                f" border: 1px solid {theme.BORDER}; border-radius: 6px;"
                f" padding: 4px 10px; font-size: 12px; }}"
                f"QLineEdit:focus {{ border-color: {theme.ACCENT}; }}"
            )
            if secret:
                e.setEchoMode(QLineEdit.EchoMode.Password)
            if value:
                e.setText(value)
            return e

        creds = existing.credentials if existing else {}

        # Step 1 — credentials
        bl.addWidget(_section("Шаг 1 — Данные OAuth-приложения"))
        bl.addWidget(_hint("Создай OAuth-приложение в Worksection: аватар → Настройки → API"))

        e_account = _field("ws.company.com", value=creds.get("account", ""))
        bl.addWidget(_section("Домен Worksection"))
        bl.addWidget(e_account)
        self._entries["account"] = e_account

        e_client_id = _field("Client ID", value=creds.get("client_id", ""))
        bl.addWidget(_section("Client ID"))
        bl.addWidget(e_client_id)
        self._entries["client_id"] = e_client_id

        e_client_secret = _field("Client Secret", secret=True, value=creds.get("client_secret", ""))
        bl.addWidget(_section("Client Secret"))
        bl.addWidget(e_client_secret)
        self._entries["client_secret"] = e_client_secret

        e_redirect = _field("https://localhost:19876/", value=creds.get("redirect_uri", "https://localhost:19876/"))
        bl.addWidget(_section("Redirect URI (укажи точно такой же в OAuth-приложении)"))
        bl.addWidget(e_redirect)
        self._entries["redirect_uri"] = e_redirect

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {theme.BORDER}; background: {theme.BORDER}; max-height: 1px;")
        bl.addWidget(sep)

        # Step 2 — open browser
        bl.addWidget(_section("Шаг 2 — Авторизация в браузере"))
        bl.addWidget(_hint(
            "Нажми кнопку — откроется браузер. После авторизации браузер попытается "
            "открыть redirect URI и упадёт с ошибкой. Это нормально. "
            "Скопируй полный URL из адресной строки браузера и вставь ниже."
        ))

        self._open_btn = QPushButton("Открыть браузер для авторизации")
        self._open_btn.setFixedHeight(36)
        self._open_btn.setStyleSheet(
            f"QPushButton {{ background-color: {provider_info['badge_color']}; color: white;"
            " border: none; border-radius: 6px; padding: 5px 16px;"
            " font-size: 13px; font-weight: bold; }}"
            "QPushButton:disabled {{ background-color: #374151; color: #9CA3AF; }}"
        )
        self._open_btn.clicked.connect(self._on_open_browser)
        bl.addWidget(self._open_btn)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {theme.BORDER}; background: {theme.BORDER}; max-height: 1px;")
        bl.addWidget(sep2)

        # Step 3 — paste URL
        bl.addWidget(_section("Шаг 3 — Вставь URL из адресной строки браузера"))
        bl.addWidget(_hint("После ошибки редиректа URL будет выглядеть как: https://localhost:19876/?code=XXXX&state=..."))
        self._url_entry = _field("https://localhost:19876/?code=...")
        bl.addWidget(self._url_entry)

        self._status_lbl = QLabel("")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        bl.addWidget(self._status_lbl)
        layout.addWidget(body)

        # ── Button bar ───────────────────────────────────────────────────
        btn_bar = QWidget()
        btn_bar.setStyleSheet(f"background: {theme.BG_INPUT};")
        bbl = QHBoxLayout(btn_bar)
        bbl.setContentsMargins(20, 12, 20, 12)
        bbl.setSpacing(8)
        bbl.addStretch()

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setFixedWidth(90)
        cancel_btn.clicked.connect(self.reject)
        bbl.addWidget(cancel_btn)

        self._connect_btn = QPushButton("Получить токен")
        self._connect_btn.setFixedWidth(130)
        self._connect_btn.setDefault(True)
        self._connect_btn.setStyleSheet(
            f"QPushButton {{ background-color: {theme.ACCENT}; color: white;"
            " border: none; border-radius: 6px; padding: 5px 12px;"
            " font-size: 12px; font-weight: bold; }}"
            "QPushButton:hover { background-color: #4AABFF; }"
            "QPushButton:disabled { background-color: #374151; color: #9CA3AF; }"
        )
        self._connect_btn.clicked.connect(self._on_get_token)
        bbl.addWidget(self._connect_btn)
        layout.addWidget(btn_bar)

    def _on_open_browser(self) -> None:
        import secrets, urllib.parse, webbrowser
        client_id = self._entries["client_id"].text().strip()
        redirect_uri = self._entries["redirect_uri"].text().strip()
        if not client_id:
            self._status_lbl.setText("Заполни Client ID.")
            return
        self._state = secrets.token_urlsafe(16)
        params = urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self._WS_SCOPES,
            "state": self._state,
        })
        full_url = f"{self._WS_AUTH_URL}?{params}"
        # Show the exact redirect_uri being sent so user can verify it matches Worksection settings
        self._status_lbl.setText(
            f"Отправляем redirect_uri: {redirect_uri}\n"
            f"Убедись что ТОЧНО такая же строка в настройках OAuth-приложения в Worksection."
        )
        webbrowser.open(full_url)

    def _on_get_token(self) -> None:
        import urllib.parse
        account = self._entries["account"].text().strip()
        client_id = self._entries["client_id"].text().strip()
        client_secret = self._entries["client_secret"].text().strip()
        redirect_uri = self._entries["redirect_uri"].text().strip()
        pasted_url = self._url_entry.text().strip()

        if not all([account, client_id, client_secret, redirect_uri, pasted_url]):
            self._status_lbl.setText("Заполни все поля и вставь URL из браузера.")
            return

        # Extract code from pasted URL
        try:
            parsed = urllib.parse.urlparse(pasted_url)
            params = urllib.parse.parse_qs(parsed.query)
            code = params.get("code", [""])[0]
            if not code:
                self._status_lbl.setText("Не найден code= в URL. Проверь что вставил правильный адрес.")
                return
        except Exception as exc:
            self._status_lbl.setText(f"Ошибка парсинга URL: {exc}")
            return

        self._connect_btn.setEnabled(False)
        self._connect_btn.setText("Получаю токен…")
        self._status_lbl.setText("Обмениваю код на токен…")

        self._token_thread = _WorksectionTokenThread(
            account=account,
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=redirect_uri,
        )
        self._token_thread.auth_success.connect(self._on_auth_success)
        self._token_thread.auth_failed.connect(self._on_auth_failed)
        self._token_thread.start()

    def _on_auth_success(self, creds: dict) -> None:
        self._on_save(self._provider_info["id"], creds)
        self.accept()

    def _on_auth_failed(self, error: str) -> None:
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText("Получить токен")
        self._status_lbl.setText(f"Ошибка: {error}")


# ---------------------------------------------------------------------------
# Google OAuth dialog (via gws CLI)
# ---------------------------------------------------------------------------

class _GoogleOAuthDialog(QDialog):
    """OAuth2 connection dialog for Google Workspace.

    Three independent steps shown as rows:
      1. gcloud  — install → login → ✓ account
      2. gws     — download → ✓ ready
      3. Connect — enabled only when both ready, runs gws auth setup --login
    """

    def __init__(
        self,
        provider_info: dict,
        existing: ExtensionDef | None,
        on_save: Callable[[str, dict], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._provider_info = provider_info
        self._on_save = on_save

        # State (updated as steps complete)
        self._gcloud_path: str | None = _find_gcloud()
        self._gcloud_email: str = _gcloud_account() if self._gcloud_path else ""
        self._gws_path: str | None = _find_gws()

        # Threads
        self._install_thread: _GCloudInstallThread | None = None
        self._login_thread: _GCloudLoginThread | None = None
        self._download_thread: _GWSDownloadThread | None = None
        self._setup_thread: _GWSSetupThread | None = None

        self.setWindowTitle(f"Connect — {provider_info['name']}")
        self.setMinimumWidth(480)
        self.setStyleSheet(f"background-color: {theme.BG_PANEL};")

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── Header ──────────────────────────────────────────────────────
        header = QFrame()
        header.setStyleSheet(f"background-color: {theme.BG_INPUT};")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(20, 14, 20, 14)
        hl.setSpacing(6)
        badge = QLabel(provider_info["name"])
        badge.setStyleSheet(
            f"background-color: {provider_info['badge_color']}; color: white;"
            " border-radius: 4px; padding: 3px 12px; font-weight: bold; font-size: 14px;"
        )
        badge.setFixedHeight(28)
        hl.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)
        srow = QWidget(); srow.setStyleSheet("background: transparent;")
        srl = QHBoxLayout(srow); srl.setContentsMargins(0, 0, 0, 0); srl.setSpacing(5)
        srl.addWidget(QLabel("Включает:", styleSheet=f"color:{theme.TEXT_MUTED};font-size:11px;background:transparent;"))
        for svc in provider_info.get("services", []):
            chip = QLabel(svc, styleSheet=f"background:{theme.BG_APP};color:{theme.TEXT};border-radius:3px;padding:1px 7px;font-size:10px;")
            srl.addWidget(chip)
        srl.addStretch()
        hl.addWidget(srow)
        layout.addWidget(header)

        # ── Body ────────────────────────────────────────────────────────
        body = QWidget(); body.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 20, 24, 16)
        bl.setSpacing(10)

        def _small_btn(label: str) -> QPushButton:
            b = QPushButton(label)
            b.setFixedHeight(28)
            b.setStyleSheet(
                f"QPushButton{{background:{theme.BG_INPUT};color:{theme.TEXT};"
                "border:1px solid #4B5563;border-radius:5px;padding:0 12px;font-size:11px;}}"
                "QPushButton:hover{border-color:#9CA3AF;}"
                "QPushButton:disabled{color:#6B7280;border-color:#374151;}"
            )
            return b

        def _tool_label(ok: bool, name: str, detail: str) -> QLabel:
            dot = f"<span style='color:{'#34D399' if ok else '#6B7280'};'>{'●' if ok else '○'}</span>"
            lbl = QLabel(f"{dot}  <b style='font-size:12px;'>{name}</b>"
                         f"  <span style='color:{theme.TEXT_MUTED};font-size:10px;'>{detail}</span>")
            lbl.setStyleSheet("background:transparent;")
            return lbl

        # ── Row 1: gcloud ───────────────────────────────────────────────
        gc_detail = self._gcloud_email if self._gcloud_email else ("установлен" if self._gcloud_path else "не установлен")
        self._gcloud_lbl = _tool_label(bool(self._gcloud_email), "gcloud", gc_detail)
        self._gcloud_btn = _small_btn(self._gcloud_btn_label())
        self._gcloud_btn.clicked.connect(self._on_gcloud_action)

        gc_row = QWidget(); gc_row.setStyleSheet("background:transparent;")
        gcl = QHBoxLayout(gc_row); gcl.setContentsMargins(0, 0, 0, 0); gcl.setSpacing(10)
        gcl.addWidget(self._gcloud_lbl, stretch=1)
        gcl.addWidget(self._gcloud_btn)
        bl.addWidget(gc_row)

        # ── Row 2: client_secrets.json ──────────────────────────────────
        self._client_config: dict | None = None
        self._secrets_lbl = _tool_label(False, "client_secrets.json", "не загружен")
        self._secrets_btn = _small_btn("Загрузить  ↑")
        self._secrets_btn.clicked.connect(self._on_load_client_secrets)

        secrets_row = QWidget(); secrets_row.setStyleSheet("background:transparent;")
        secl = QHBoxLayout(secrets_row); secl.setContentsMargins(0, 0, 0, 0); secl.setSpacing(10)
        secl.addWidget(self._secrets_lbl, stretch=1)
        secl.addWidget(self._secrets_btn)
        bl.addWidget(secrets_row)

        hint = QLabel(
            "<span style='color:#6B7280;font-size:10px;'>"
            "GCP Console → APIs &amp; Services → "
            "<a href='https://console.cloud.google.com/apis/credentials' "
            "style='color:#60A5FA;'>Credentials</a>"
            " → Create credentials → OAuth client ID → Desktop app → Download JSON"
            "</span>"
        )
        hint.setOpenExternalLinks(True)
        hint.setWordWrap(True)
        hint.setStyleSheet("background:transparent;")
        bl.addWidget(hint)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{theme.BORDER};background:{theme.BORDER};max-height:1px;")
        bl.addWidget(sep)

        # ── Connect button ────────────────────────────────────────────────
        self._connect_btn = QPushButton("Подключить Google →")
        self._connect_btn.setFixedHeight(44)
        self._connect_btn.setStyleSheet(
            f"QPushButton{{background-color:{provider_info['badge_color']};color:white;"
            "border:none;border-radius:10px;padding:5px 20px;font-size:14px;font-weight:bold;}}"
            "QPushButton:hover{background-color:#5A95F5;}"
            "QPushButton:disabled{background-color:#374151;color:#6B7280;}"
        )
        self._connect_btn.clicked.connect(self._on_connect)
        self._connect_btn.setEnabled(False)
        bl.addWidget(self._connect_btn)

        # ── Status label ─────────────────────────────────────────────────
        self._status_lbl = QLabel("")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._status_lbl.setStyleSheet(f"color:{theme.TEXT_MUTED};font-size:11px;background:transparent;")
        bl.addWidget(self._status_lbl)

        # ── Copyable URL (shown on demand) ───────────────────────────────
        self._url_lbl = QLabel("Ссылка для браузера:")
        self._url_lbl.setStyleSheet(f"color:{theme.TEXT_MUTED};font-size:10px;background:transparent;padding-top:2px;")
        self._url_lbl.setVisible(False)
        bl.addWidget(self._url_lbl)

        self._url_field = QLineEdit()
        self._url_field.setReadOnly(True)
        self._url_field.setFixedHeight(26)
        self._url_field.setStyleSheet(
            f"QLineEdit{{background:{theme.BG_APP};color:{theme.ACCENT};"
            f"border:1px solid {theme.BORDER};border-radius:5px;padding:2px 8px;font-size:10px;}}"
        )
        self._url_field.setVisible(False)
        bl.addWidget(self._url_field)

        open_btn_row = QWidget(); open_btn_row.setStyleSheet("background:transparent;")
        orl = QHBoxLayout(open_btn_row); orl.setContentsMargins(0, 2, 0, 0); orl.setSpacing(8)
        self._open_url_btn = QPushButton("Открыть в браузере  ↗")
        self._open_url_btn.setFixedHeight(24)
        self._open_url_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{theme.ACCENT};"
            f"border:1px solid {theme.ACCENT};border-radius:4px;padding:1px 10px;font-size:10px;}}"
            f"QPushButton:hover{{background:{theme.ACCENT};color:white;}}"
        )
        self._open_url_btn.clicked.connect(
            lambda: webbrowser.open(self._url_field.text()) if self._url_field.text() else None
        )
        self._open_url_btn.setVisible(False)
        orl.addWidget(self._open_url_btn); orl.addStretch()
        bl.addWidget(open_btn_row)
        self._open_btn_row = open_btn_row

        bl.addStretch()
        layout.addWidget(body, stretch=1)

        # ── Button bar ───────────────────────────────────────────────────
        btn_bar = QWidget()
        btn_bar.setStyleSheet(f"background:{theme.BG_INPUT};")
        bbl = QHBoxLayout(btn_bar)
        bbl.setContentsMargins(20, 12, 20, 12)
        bbl.addStretch()
        cancel_btn = QPushButton("Отмена")
        cancel_btn.setFixedWidth(90)
        cancel_btn.clicked.connect(self.reject)
        bbl.addWidget(cancel_btn)
        layout.addWidget(btn_bar)

    # ── Helpers ─────────────────────────────────────────────────────────

    def _gcloud_btn_label(self) -> str:
        if self._gcloud_email:
            return "Сменить аккаунт"
        if self._gcloud_path:
            return "Войти →"
        return "Установить"

    def _refresh_gcloud_ui(self) -> None:
        gc_detail = self._gcloud_email if self._gcloud_email else ("установлен" if self._gcloud_path else "не установлен")
        dot = f"<span style='color:{'#34D399' if self._gcloud_email else '#6B7280'};'>{'●' if self._gcloud_email else '○'}</span>"
        self._gcloud_lbl.setText(
            f"{dot}  <b style='font-size:12px;'>gcloud</b>"
            f"  <span style='color:{theme.TEXT_MUTED};font-size:10px;'>{gc_detail}</span>"
        )
        self._gcloud_btn.setText(self._gcloud_btn_label())
        self._gcloud_btn.setEnabled(True)
        self._connect_btn.setEnabled(True)

    def _refresh_gws_ui(self) -> None:
        gws_detail = f"v{_GWS_VERSION} готов" if self._gws_path else "не скачан"
        dot = f"<span style='color:{'#34D399' if self._gws_path else '#6B7280'};'>{'●' if self._gws_path else '○'}</span>"
        self._gws_lbl.setText(
            f"{dot}  <b style='font-size:12px;'>gws</b>"
            f"  <span style='color:{theme.TEXT_MUTED};font-size:10px;'>{gws_detail}</span>"
        )
        self._gws_btn.setText("✓ Скачан" if self._gws_path else "Скачать  ↓")
        self._gws_btn.setEnabled(not bool(self._gws_path))
        self._connect_btn.setEnabled(True)

    def _show_url(self, url: str) -> None:
        webbrowser.open(url)
        self._url_field.setText(url)
        self._url_lbl.setVisible(True)
        self._url_field.setVisible(True)
        self._open_url_btn.setVisible(True)
        self._open_btn_row.setVisible(True)

    def _hide_url(self) -> None:
        self._url_lbl.setVisible(False)
        self._url_field.setVisible(False)
        self._url_field.clear()
        self._open_url_btn.setVisible(False)
        self._open_btn_row.setVisible(False)

    def _set_status(self, text: str, color: str = "") -> None:
        self._status_lbl.setText(text)
        c = color or theme.TEXT_MUTED
        self._status_lbl.setStyleSheet(f"color:{c};font-size:11px;background:transparent;")

    # ── gcloud actions ──────────────────────────────────────────────────

    def _on_gcloud_action(self) -> None:
        self._gcloud_btn.setEnabled(False)
        self._hide_url()
        if not self._gcloud_path:
            # Need to install first
            self._gcloud_btn.setText("Устанавливаю…")
            self._install_thread = _GCloudInstallThread()
            self._install_thread.status.connect(self._set_status)
            self._install_thread.done.connect(self._on_gcloud_installed)
            self._install_thread.failed.connect(self._on_gcloud_failed)
            self._install_thread.start()
        elif self._gcloud_email:
            # Logged in — revoke and re-login as different account
            self._gcloud_email = ""
            import subprocess, os
            try:
                subprocess.run(
                    [self._gcloud_path, "auth", "revoke", "--all", "--quiet"],
                    capture_output=True, timeout=10,
                    **({} if os.name != "nt" else {"creationflags": subprocess.CREATE_NO_WINDOW}),
                )
            except Exception:
                pass
            self._refresh_gcloud_ui()
            self._on_gcloud_action()
        else:
            # Installed but not logged in
            self._gcloud_btn.setText("Вхожу…")
            self._login_thread = _GCloudLoginThread(self._gcloud_path)
            self._login_thread.status.connect(self._set_status)
            self._login_thread.open_url.connect(self._show_url)
            self._login_thread.done.connect(self._on_gcloud_logged_in)
            self._login_thread.failed.connect(self._on_gcloud_failed)
            self._login_thread.start()

    def _on_gcloud_installed(self, gcloud_path: str) -> None:
        self._gcloud_path = gcloud_path
        self._set_status("✓  gcloud установлен. Нажми Войти →", "#34D399")
        self._refresh_gcloud_ui()
        # Immediately start login
        self._on_gcloud_action()

    def _on_gcloud_logged_in(self, email: str) -> None:
        # If gcloud auth list returned empty (PATH issue), fall back to a known-logged-in marker
        if not email:
            email = "authenticated"
        self._gcloud_email = email
        display = email if email != "authenticated" else "✓ авторизован"
        self._set_status(f"✓  Вошёл как {display}", "#34D399")
        self._hide_url()
        self._refresh_gcloud_ui()

    def _on_gcloud_failed(self, error: str) -> None:
        self._refresh_gcloud_ui()
        self._set_status(f"Ошибка gcloud: {error}", theme.DANGER)

    # ── client_secrets.json ──────────────────────────────────────────────

    def _on_load_client_secrets(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбери client_secrets.json", "",
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            import json
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            # Accept both "installed" and "web" client types
            if "installed" not in data and "web" not in data:
                self._set_status("Неверный формат файла — нужен OAuth2 Desktop App client.", theme.DANGER)
                return
            self._client_config = data
            fname = _Path(path).name
            dot = f"<span style='color:#34D399;'>●</span>"
            self._secrets_lbl.setText(
                f"{dot}  <b style='font-size:12px;'>client_secrets.json</b>"
                f"  <span style='color:{theme.TEXT_MUTED};font-size:10px;'>{fname}</span>"
            )
            self._secrets_btn.setText("Сменить")
            self._connect_btn.setEnabled(True)
            self._set_status("✓  client_secrets.json загружен.", "#34D399")
        except Exception as exc:
            self._set_status(f"Ошибка чтения файла: {exc}", theme.DANGER)

    # ── gws actions ─────────────────────────────────────────────────────

    def _on_download_gws(self) -> None:
        self._gws_btn.setEnabled(False)
        self._gws_btn.setText("Скачиваю…")
        self._set_status(f"Скачиваю gws v{_GWS_VERSION}…")
        self._download_thread = _GWSDownloadThread()
        self._download_thread.progress.connect(self._set_status)
        self._download_thread.done.connect(self._on_gws_downloaded)
        self._download_thread.failed.connect(self._on_gws_dl_failed)
        self._download_thread.start()

    def _on_gws_downloaded(self, path: str) -> None:
        self._gws_path = path
        self._set_status("✓  gws скачан.", "#34D399")
        self._refresh_gws_ui()

    def _on_gws_dl_failed(self, error: str) -> None:
        self._refresh_gws_ui()
        self._set_status(f"Ошибка скачивания gws: {error}", theme.DANGER)

    # ── Connect (gws auth setup) ─────────────────────────────────────────

    def _on_connect(self) -> None:
        self._connect_btn.setEnabled(False)
        self._connect_btn.setText("Подключение…")
        self._hide_url()
        self._set_status("Запуск авторизации Google Workspace…")

        self._setup_thread = _GWSSetupThread(
            client_config=self._client_config,
            email=self._gcloud_email or "",
        )
        self._setup_thread.status.connect(self._set_status)
        self._setup_thread.open_url.connect(self._show_url)
        self._setup_thread.auth_success.connect(self._on_auth_success)
        self._setup_thread.auth_failed.connect(self._on_connect_failed)
        self._setup_thread.start()

    def _on_auth_success(self, creds: dict) -> None:
        creds["services"] = self._provider_info.get("services", [])
        self._on_save(self._provider_info["id"], creds)
        self.accept()

    def _on_connect_failed(self, error: str) -> None:
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText("Подключить Google →")
        self._set_status(f"Ошибка подключения:\n{error}", theme.DANGER)


# ---------------------------------------------------------------------------
# Simple connect dialog (Yandex / generic)
# ---------------------------------------------------------------------------

class _ConnectDialog(QDialog):
    def __init__(
        self,
        provider_info: dict,
        existing: ExtensionDef | None,
        on_save: Callable[[str, dict], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._provider_info = provider_info
        self._on_save = on_save
        self._entries: dict[str, QLineEdit] = {}

        self.setWindowTitle(f"Connect — {provider_info['name']}")
        self.setMinimumWidth(460)
        self.setStyleSheet(f"background-color: {theme.BG_PANEL};")

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── Header ──────────────────────────────────────────────────────
        header = QFrame()
        header.setStyleSheet(f"background-color: {theme.BG_INPUT};")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(20, 16, 20, 16)
        hl.setSpacing(10)

        badge = QLabel(provider_info["name"])
        badge.setStyleSheet(
            f"background-color: {provider_info['badge_color']}; color: white;"
            " border-radius: 4px; padding: 3px 12px;"
            " font-weight: bold; font-size: 14px;"
        )
        badge.setFixedHeight(28)
        hl.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)

        services_row = QWidget()
        services_row.setStyleSheet("background: transparent;")
        srl = QHBoxLayout(services_row)
        srl.setContentsMargins(0, 0, 0, 0)
        srl.setSpacing(6)
        inc_lbl = QLabel("Включает:")
        inc_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        srl.addWidget(inc_lbl)
        for svc in provider_info.get("services", []):
            chip = QLabel(svc)
            chip.setStyleSheet(
                f"background-color: {theme.BG_APP}; color: {theme.TEXT};"
                " border-radius: 4px; padding: 2px 8px; font-size: 11px;"
            )
            srl.addWidget(chip)
        srl.addStretch()
        hl.addWidget(services_row)
        layout.addWidget(header)

        # ── Body ────────────────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 16, 20, 16)
        bl.setSpacing(12)

        steps_title = QLabel("Как подключить:")
        steps_title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 12px; font-weight: bold; background: transparent;"
        )
        bl.addWidget(steps_title)

        for step in provider_info.get("steps", []):
            lbl = QLabel(step)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
            )
            bl.addWidget(lbl)

        token_url = provider_info.get("get_token_url", "")
        if token_url:
            get_token_btn = QPushButton("Get Token  ↗")
            get_token_btn.setFixedWidth(140)
            get_token_btn.setStyleSheet(
                f"QPushButton {{ background-color: {theme.ACCENT}; color: white;"
                " border: none; border-radius: 6px; padding: 5px 12px; font-size: 12px; }}"
                "QPushButton:hover { background-color: #4AABFF; }"
            )
            get_token_btn.clicked.connect(lambda: webbrowser.open(token_url))
            bl.addWidget(get_token_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {theme.BORDER}; background: {theme.BORDER}; max-height: 1px;")
        bl.addWidget(sep)

        creds = existing.credentials if existing else {}
        for field in provider_info["fields"]:
            field_lbl = QLabel(field["label"])
            field_lbl.setStyleSheet(
                f"color: {theme.TEXT}; font-size: 12px; font-weight: bold; background: transparent;"
            )
            bl.addWidget(field_lbl)
            entry = QLineEdit()
            entry.setPlaceholderText(field.get("placeholder", field["label"]))
            entry.setFixedHeight(34)
            entry.setStyleSheet(
                f"QLineEdit {{ background: {theme.BG_INPUT}; color: {theme.TEXT};"
                f" border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 4px 10px;"
                f" font-size: 12px; }}"
                f"QLineEdit:focus {{ border-color: {theme.ACCENT}; }}"
            )
            if not field["show"]:
                entry.setEchoMode(QLineEdit.EchoMode.Password)
            if field["key"] in creds:
                entry.setText(creds[field["key"]])
            bl.addWidget(entry)
            self._entries[field["key"]] = entry

        layout.addWidget(body)

        # ── Buttons ─────────────────────────────────────────────────────
        btn_bar = QWidget()
        btn_bar.setStyleSheet(f"background: {theme.BG_INPUT};")
        bbl = QHBoxLayout(btn_bar)
        bbl.setContentsMargins(20, 12, 20, 12)
        bbl.setSpacing(8)
        bbl.addStretch()

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setFixedWidth(90)
        cancel_btn.clicked.connect(self.reject)
        bbl.addWidget(cancel_btn)

        save_btn = QPushButton("Сохранить")
        save_btn.setFixedWidth(110)
        save_btn.setDefault(True)
        save_btn.setStyleSheet(
            f"QPushButton {{ background-color: {theme.ACCENT}; color: white;"
            " border: none; border-radius: 6px; padding: 5px 12px; font-size: 12px; font-weight: bold; }}"
            "QPushButton:hover { background-color: #4AABFF; }"
        )
        save_btn.clicked.connect(self._save)
        bbl.addWidget(save_btn)
        layout.addWidget(btn_bar)

    def _save(self) -> None:
        creds: dict = {key: entry.text().strip() for key, entry in self._entries.items()}
        creds["services"] = self._provider_info.get("services", [])
        self._on_save(self._provider_info["id"], creds)
        self.accept()


# ---------------------------------------------------------------------------
# Provider card
# ---------------------------------------------------------------------------

class _ProviderCard(QFrame):
    def __init__(
        self,
        provider_info: dict,
        extension: ExtensionDef | None,
        on_connect: Callable[[dict], None],
        on_disconnect: Callable[[str], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._info = provider_info
        self._ext = extension
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self.setFixedWidth(240)
        self.setStyleSheet(
            f"QFrame {{ background-color: {theme.BG_INPUT};"
            "  border: none; border-radius: 8px; }}"
        )
        self._build()

    def _build(self) -> None:
        for child in self.findChildren(QWidget):
            child.deleteLater()

        is_connected = self._ext is not None and self._ext.status == "connected"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        badge = QLabel(self._info["name"])
        badge.setStyleSheet(
            f"background-color: {self._info['badge_color']}; color: white;"
            " border-radius: 4px; padding: 2px 10px; font-weight: bold; font-size: 13px;"
        )
        badge.setFixedHeight(26)
        layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)

        chips_row = QWidget()
        chips_row.setStyleSheet("background: transparent;")
        crl = QHBoxLayout(chips_row)
        crl.setContentsMargins(0, 0, 0, 0)
        crl.setSpacing(4)
        for svc in self._info.get("services", []):
            chip = QLabel(svc)
            chip.setStyleSheet(
                f"background-color: {theme.BG_APP}; color: {theme.TEXT_MUTED};"
                " border-radius: 3px; padding: 1px 6px; font-size: 10px;"
            )
            crl.addWidget(chip)
        crl.addStretch()
        layout.addWidget(chips_row)

        status_color = theme.SUCCESS if is_connected else "#6B7280"
        status_text = "● Connected" if is_connected else "● Not connected"
        if is_connected and self._ext:
            email = self._ext.credentials.get("email", "")
            if email:
                status_text = f"● {email}"
        status_lbl = QLabel(status_text)
        status_lbl.setWordWrap(True)
        status_lbl.setStyleSheet(
            f"color: {status_color}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(status_lbl)

        if is_connected:
            btn = QPushButton("Disconnect")
            btn.setFixedWidth(110)
            btn.setStyleSheet(
                "QPushButton { background-color: #374151; color: white; border: none;"
                " border-radius: 5px; padding: 4px 10px; font-size: 12px; }"
                "QPushButton:hover { background-color: #4B5563; }"
            )
            btn.clicked.connect(lambda: self._on_disconnect(self._info["id"]))
        else:
            btn = QPushButton("Connect")
            btn.setFixedWidth(110)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {theme.ACCENT}; color: white; border: none;"
                " border-radius: 5px; padding: 4px 10px; font-size: 12px; }"
                "QPushButton:hover { background-color: #4AABFF; }"
            )
            btn.clicked.connect(lambda: self._on_connect(self._info))
        layout.addWidget(btn)

    def refresh(self, extension: ExtensionDef | None) -> None:
        self._ext = extension
        self._build()


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class ExtensionsPanel(QWidget):
    """Full-screen panel for managing external service integrations."""

    def __init__(self, extension_store: ExtensionStore, parent=None) -> None:
        super().__init__(parent)
        self._store = extension_store
        self._cards: dict[str, _ProviderCard] = {}
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setStyleSheet(f"background-color: {theme.BG_INPUT};")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(16, 12, 16, 12)

        title = QLabel("Extensions")
        title.setStyleSheet(
            f"color: {theme.TEXT}; font-weight: bold; font-size: 15px; background: transparent;"
        )
        hl.addWidget(title)

        sub = QLabel("Подключите внешние аккаунты — агент получит доступ к вашим сервисам")
        sub.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 12px; background: transparent;"
        )
        hl.addWidget(sub)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ background: {theme.BG_APP}; border: none; }}")

        self._cards_container = QWidget()
        self._cards_container.setStyleSheet(f"background: {theme.BG_APP};")
        self._cards_layout = QHBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(20, 20, 20, 20)
        self._cards_layout.setSpacing(16)
        self._cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll.setWidget(self._cards_container)
        root.addWidget(scroll, stretch=1)

    def refresh(self) -> None:
        extensions_by_id = {e.id: e for e in self._store.list_extensions()}

        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()

        for pinfo in _PROVIDERS:
            ext = extensions_by_id.get(pinfo["id"]) or extensions_by_id.get(
                "yandex_mail" if pinfo["id"] == "yandex" else ""
            )
            card = _ProviderCard(
                provider_info=pinfo,
                extension=ext,
                on_connect=self._on_connect,
                on_disconnect=self._on_disconnect,
            )
            self._cards_layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignTop)
            self._cards[pinfo["id"]] = card

        self._cards_layout.addStretch()

    def _on_connect(self, provider_info: dict) -> None:
        ext_id = provider_info["id"]
        existing = self._store.get_extension(ext_id)

        def _save(pid: str, creds: dict) -> None:
            now = _now()
            ext = ExtensionDef(
                id=pid,
                name=provider_info["name"],
                provider=provider_info["provider"],
                status="connected",
                credentials=creds,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            self._store.upsert_extension(ext)
            if pid in self._cards:
                self._cards[pid].refresh(ext)

        auth_type = provider_info.get("auth_type", "app_password")
        if auth_type in ("oauth2", "oauth2_gws"):
            dlg = _GoogleOAuthDialog(
                provider_info=provider_info,
                existing=existing,
                on_save=_save,
                parent=self,
            )
        elif auth_type == "worksection_oauth":
            dlg = _WorksectionOAuthDialog(
                provider_info=provider_info,
                existing=existing,
                on_save=_save,
                parent=self,
            )
        else:
            dlg = _ConnectDialog(
                provider_info=provider_info,
                existing=existing,
                on_save=_save,
                parent=self,
            )
        dlg.exec()

    def _on_disconnect(self, ext_id: str) -> None:
        ext = self._store.get_extension(ext_id)
        if ext is None:
            return
        ext.status = "disconnected"
        self._store.upsert_extension(ext)
        if ext_id in self._cards:
            self._cards[ext_id].refresh(ext)
