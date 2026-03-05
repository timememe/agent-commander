"""Extension definition store — ~/.agent-commander/cache/extensions/."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

_CACHE_ROOT = Path.home() / ".agent-commander" / "cache"
_EXTENSIONS_DIR = "extensions"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _build_extension_section(ext: "ExtensionDef") -> str:
    """Build a rich context block for one extension, including credentials and usage templates."""
    email = ext.credentials.get("email", "")
    token = ext.credentials.get("token", "")
    provider = ext.provider

    if provider == "google":
        refresh_token = ext.credentials.get("refresh_token", "")
        client_id = ext.credentials.get("client_id", "")
        client_secret = ext.credentials.get("client_secret", "")
        if refresh_token:
            creds_init = (
                f'creds = Credentials(\n'
                f'    token="{token}",\n'
                f'    refresh_token="{refresh_token}",\n'
                f'    token_uri="https://oauth2.googleapis.com/token",\n'
                f'    client_id="{client_id}",\n'
                f'    client_secret="{client_secret}",\n'
                f')'
            )
        else:
            creds_init = f'creds = Credentials(token="{token}")'

        return (
            f"### Google — {email}\n\n"
            f"**Active services:** Gmail, Google Drive, Google Calendar\n"
            f"**Account:** {email}\n\n"
            f"Use this for all Google API calls"
            f" (install if needed: `pip install google-api-python-client google-auth`):\n"
            f"```python\n"
            f"from google.oauth2.credentials import Credentials\n"
            f"from google.auth.transport.requests import Request\n"
            f"from googleapiclient.discovery import build\n\n"
            f"{creds_init}\n"
            f"if creds.expired and creds.refresh_token:\n"
            f"    creds.refresh(Request())\n\n"
            f"# Send email via Gmail:\n"
            f"gmail = build('gmail', 'v1', credentials=creds)\n\n"
            f"# Create/list calendar events:\n"
            f"cal = build('calendar', 'v3', credentials=creds)\n\n"
            f"# Access Drive files:\n"
            f"drive = build('drive', 'v3', credentials=creds)\n"
            f"```"
        )

    if provider in ("yandex", "yandex_mail"):
        app_password = ext.credentials.get("token", "")
        return (
            f"### Яндекс — {email}\n\n"
            f"**Active services:** Яндекс Почта (IMAP/SMTP), Яндекс Диск (WebDAV)\n"
            f"**Account:** {email}\n"
            f"**App Password:** {app_password}\n\n"
            f"Use these credentials for all Yandex services:\n"
            f"```python\n"
            f"# Send email via SMTP:\n"
            f"import smtplib\n"
            f"from email.mime.text import MIMEText\n"
            f"from email.mime.multipart import MIMEMultipart\n\n"
            f"smtp = smtplib.SMTP_SSL('smtp.yandex.ru', 465)\n"
            f"smtp.login('{email}', '{app_password}')\n"
            f"msg = MIMEMultipart()\n"
            f"msg['From'] = '{email}'\n"
            f"msg['To'] = recipient\n"
            f"msg['Subject'] = subject\n"
            f"msg.attach(MIMEText(body, 'plain', 'utf-8'))\n"
            f"smtp.sendmail('{email}', [recipient], msg.as_string())\n"
            f"smtp.quit()\n\n"
            f"# Yandex Disk (WebDAV):\n"
            f"import requests\n"
            f"r = requests.request('PROPFIND', 'https://webdav.yandex.ru/',\n"
            f"    auth=('{email}', '{app_password}'))\n"
            f"```"
        )

    # Generic fallback
    services: list[str] = ext.credentials.get("services", [])
    services_str = ", ".join(services) if services else ext.name
    if email:
        return f"### {ext.name} — {email}\n\n**Active services:** {services_str}"
    return f"### {ext.name}\n\n**Active services:** {services_str}"


@dataclass
class ExtensionDef:
    """Metadata and credentials for one external integration."""

    id: str                 # "google", "yandex_mail", "custom_<hex>"
    name: str               # display name
    provider: str           # "google" | "yandex_mail" | "custom"
    status: str             # "connected" | "disconnected"
    credentials: dict       # {"email": ..., "token": ...} — plaintext
    created_at: str
    updated_at: str = ""


class ExtensionStore:
    """CRUD over ~/.agent-commander/cache/extensions/{id}/

    Directory layout::

        ~/.agent-commander/cache/
          extensions/
            {extension_id}/
              extension.json     # metadata + credentials
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or _CACHE_ROOT) / _EXTENSIONS_DIR
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Read                                                                  #
    # ------------------------------------------------------------------ #

    def list_extensions(self) -> list[ExtensionDef]:
        """Return all extensions sorted by created_at."""
        extensions: list[ExtensionDef] = []
        try:
            for d in self._root.iterdir():
                if not d.is_dir():
                    continue
                ext = self._load_meta(d)
                if ext is not None:
                    extensions.append(ext)
        except Exception:
            pass
        return sorted(extensions, key=lambda e: e.created_at)

    def get_extension(self, ext_id: str) -> ExtensionDef | None:
        return self._load_meta(self._root / ext_id)

    # ------------------------------------------------------------------ #
    # Write                                                                 #
    # ------------------------------------------------------------------ #

    def upsert_extension(self, ext: ExtensionDef) -> None:
        """Create or update an extension definition."""
        ext_dir = self._root / ext.id
        ext_dir.mkdir(parents=True, exist_ok=True)
        ext.updated_at = _now()
        if not ext.created_at:
            ext.created_at = ext.updated_at
        self._save_meta(ext_dir, ext)

    def delete_extension(self, ext_id: str) -> None:
        """Remove the extension directory entirely."""
        import shutil
        ext_dir = self._root / ext_id
        if ext_dir.is_dir():
            shutil.rmtree(ext_dir)

    def build_context(self, active_ids: list[str]) -> str:
        """Build context string with credentials and code templates for active extensions."""
        parts: list[str] = []
        for ext_id in active_ids:
            ext = self.get_extension(ext_id)
            if ext is None or ext.status != "connected":
                continue
            if ext.provider == "google":
                ext = self._maybe_refresh_google_token(ext)
            section = _build_extension_section(ext)
            if section:
                parts.append(section)
        if not parts:
            return ""
        header = (
            "The following external accounts are active for this session. "
            "Use ONLY these accounts — do not use other email addresses, "
            "calendars, or storage services.\n\n"
        )
        return header + "\n\n".join(parts)

    def _maybe_refresh_google_token(self, ext: "ExtensionDef") -> "ExtensionDef":
        """Refresh Google OAuth token if expired; saves updated credentials."""
        try:
            from datetime import datetime, timezone
            from google.oauth2.credentials import Credentials  # type: ignore
            from google.auth.transport.requests import Request  # type: ignore

            refresh_token = ext.credentials.get("refresh_token", "")
            if not refresh_token:
                return ext  # no refresh token → nothing to refresh

            expiry_str = ext.credentials.get("token_expiry", "")
            expiry = None
            if expiry_str:
                try:
                    expiry = datetime.fromisoformat(expiry_str)
                    if expiry.tzinfo is None:
                        expiry = expiry.replace(tzinfo=timezone.utc)
                except Exception:
                    pass

            creds = Credentials(
                token=ext.credentials.get("token", ""),
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=ext.credentials.get("client_id", ""),
                client_secret=ext.credentials.get("client_secret", ""),
                expiry=expiry,
            )

            if creds.expired or not creds.token:
                creds.refresh(Request())
                ext.credentials["token"] = creds.token or ""
                if creds.expiry:
                    ext.credentials["token_expiry"] = creds.expiry.isoformat()
                self.upsert_extension(ext)
        except Exception:
            pass
        return ext

    # ------------------------------------------------------------------ #
    # Private                                                               #
    # ------------------------------------------------------------------ #

    def _load_meta(self, ext_dir: Path) -> ExtensionDef | None:
        p = ext_dir / "extension.json"
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return ExtensionDef(
                id=d.get("id", ext_dir.name),
                name=d.get("name", ""),
                provider=d.get("provider", "custom"),
                status=d.get("status", "disconnected"),
                credentials=d.get("credentials", {}),
                created_at=d.get("created_at", ""),
                updated_at=d.get("updated_at", ""),
            )
        except Exception:
            return None

    def _save_meta(self, ext_dir: Path, ext: ExtensionDef) -> None:
        (ext_dir / "extension.json").write_text(
            json.dumps(asdict(ext), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
