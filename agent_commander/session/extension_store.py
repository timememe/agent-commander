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
        gws_bin = ext.credentials.get("gws_bin", "")
        gws_config_dir = ext.credentials.get("gws_config_dir", "")
        services_list = ext.credentials.get("services", ["Gmail", "Drive", "Calendar", "Sheets", "Docs"])
        services_str = ", ".join(services_list) if services_list else "Gmail, Drive, Calendar, Sheets, Docs"

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

        gws_section = ""
        if gws_bin and gws_config_dir:
            gws_env = (
                f'env = {{\n'
                f'    **os.environ,\n'
                f'    "GOOGLE_WORKSPACE_CLI_CONFIG_DIR": r"{gws_config_dir}",\n'
                f'    "GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND": "file",\n'
                f'}}\n'
                f'# Example: list Drive files\n'
                f'result = subprocess.run([r"{gws_bin}", "drive", "files", "list"],\n'
                f'    env=env, capture_output=True, text=True)\n'
                f'# Example: list Gmail inbox\n'
                f'result = subprocess.run([r"{gws_bin}", "gmail", "messages", "list"],\n'
                f'    env=env, capture_output=True, text=True)'
            )
            gws_section = (
                f"\n\n**Alternative — use gws CLI directly** (no Python Google packages needed):\n"
                f"```python\n"
                f"import os, subprocess\n"
                f"{gws_env}\n"
                f"```"
            )

        return (
            f"### Google Workspace — {email}\n\n"
            f"**Active services:** {services_str}\n"
            f"**Account:** {email}\n\n"
            f"Use the built-in agent tools for ALL Google Workspace operations — "
            f"do NOT write Python code or install packages manually:\n\n"
            f"**Google Drive:**\n"
            f"- `gdrive_list_files` — list files/folders (params: folder_id, query, page_size)\n"
            f"- `gdrive_get_file_info` — get metadata for a file (params: file_id)\n"
            f"- `gdrive_create_folder` — create a folder (params: name, parent_id)\n"
            f"- `gdrive_delete_file` — delete a file or folder (params: file_id)\n\n"
            f"**Google Docs:**\n"
            f"- `gdocs_create` — create a new document (params: title, content)\n"
            f"- `gdocs_get` — read document content (params: document_id)\n"
            f"- `gdocs_append` — append text to document (params: document_id, text)\n\n"
            f"**Google Sheets:**\n"
            f"- `gsheets_create` — create a new spreadsheet (params: title)\n"
            f"- `gsheets_read` — read a range (params: spreadsheet_id, range)\n"
            f"- `gsheets_write` — write 2D data to a range (params: spreadsheet_id, range, values)\n"
            f"- `gsheets_append` — append rows (params: spreadsheet_id, range, values)\n\n"
            f"Always use these tools — never use `run_command` with gws/gcloud for data operations."
            f"{gws_section}"
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

    if provider == "worksection_user":
        account = ext.credentials.get("account", "").strip().rstrip("/")
        access_token = ext.credentials.get("access_token", "")
        account_url = f"https://{account}" if account and not account.startswith("http") else account or "https://worksection.com"
        return (
            f"### Worksection (User OAuth) — {account_url}\n\n"
            f"**Account:** {account}\n"
            f"**Access token:** {access_token}\n\n"
            f"Use this for Worksection user-level operations via agent tools:\n"
            f"```\n"
            f"ws_get_projects, ws_get_tasks, ws_get_task,\n"
            f"ws_create_task, ws_update_task, ws_add_comment\n"
            f"```\n"
            f"Pass `\"connection\": \"user\"` (or omit — default is user)."
        )

    if provider == "worksection_admin":
        account = ext.credentials.get("account", "").strip().rstrip("/")
        admin_email = ext.credentials.get("email", "")
        account_url = f"https://{account}" if account and not account.startswith("http") else account or "https://worksection.com"
        return (
            f"### Worksection (Admin API) — {account_url}\n\n"
            f"**Account:** {account}\n"
            f"**Admin email:** {admin_email}\n\n"
            f"Use this for full admin access via agent tools:\n"
            f"```\n"
            f"ws_get_projects, ws_get_tasks, ws_get_task,\n"
            f"ws_create_task, ws_update_task, ws_add_comment,\n"
            f"ws_get_users, ws_get_time\n"
            f"```\n"
            f"Pass `\"connection\": \"admin\"` to force admin auth."
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
        # Try gws-based refresh first (no Google packages needed)
        gws_bin = ext.credentials.get("gws_bin", "")
        gws_config_dir = ext.credentials.get("gws_config_dir", "")
        if gws_bin and gws_config_dir and Path(gws_bin).is_file():
            try:
                import os, subprocess
                env = {
                    **os.environ,
                    "GOOGLE_WORKSPACE_CLI_CONFIG_DIR": gws_config_dir,
                    "GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND": "file",
                }
                # gws refreshes the token automatically when making API calls;
                # calling auth status will trigger a silent refresh if needed
                subprocess.run(
                    [gws_bin, "auth", "status"],
                    env=env, capture_output=True, timeout=10,
                )
            except Exception:
                pass
            return ext

        # Fall back to Python Google libs
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
