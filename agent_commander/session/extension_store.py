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
        """Build context string for connected active extensions (no credentials)."""
        parts: list[str] = []
        for ext_id in active_ids:
            ext = self.get_extension(ext_id)
            if ext is None or ext.status != "connected":
                continue
            email = ext.credentials.get("email", "")
            if email:
                parts.append(
                    f"### {ext.name}\n\n"
                    f"You have access to {ext.name} for account {email}."
                )
            else:
                parts.append(f"### {ext.name}\n\nYou have access to {ext.name}.")
        return "\n\n".join(parts)

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
