"""Persistent project store — groups of agent sessions with shared context."""

from __future__ import annotations

import json
import secrets
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_CACHE_ROOT = Path.home() / ".agent-commander" / "cache"
_PROJECTS_DIR = "projects"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _hex8() -> str:
    return secrets.token_hex(4)


@dataclass
class ProjectMeta:
    """Project metadata stored in project.json."""

    project_id: str
    name: str
    description: str = ""
    workdir: str = ""
    created_at: str = ""
    updated_at: str = ""
    agent_ids: list[str] = field(default_factory=list)


class ProjectStore:
    """Persistent store for projects.

    Directory layout::

        ~/.agent-commander/cache/projects/
            {project_id}/
                project.json
                architecture.md
                context_history.md
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or _CACHE_ROOT) / _PROJECTS_DIR
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # CRUD                                                                 #
    # ------------------------------------------------------------------ #

    def list_projects(self) -> list[ProjectMeta]:
        """Return all projects sorted by updated_at descending."""
        result: list[ProjectMeta] = []
        try:
            for d in self._root.iterdir():
                if not d.is_dir():
                    continue
                meta = self._read_meta(d.name)
                if meta is not None:
                    result.append(meta)
        except Exception:
            pass
        result.sort(key=lambda p: p.updated_at, reverse=True)
        return result

    def create_project(self, name: str, desc: str = "", workdir: str = "") -> ProjectMeta:
        """Create a new project directory and return its metadata."""
        project_id = _hex8()
        now = _now()
        meta = ProjectMeta(
            project_id=project_id,
            name=name,
            description=desc,
            workdir=workdir,
            created_at=now,
            updated_at=now,
        )
        d = self._root / project_id
        d.mkdir(parents=True, exist_ok=True)
        self._write_meta(meta)
        (d / "architecture.md").write_text("", encoding="utf-8")
        (d / "context_history.md").write_text("", encoding="utf-8")
        return meta

    def get_project(self, project_id: str) -> ProjectMeta | None:
        """Load project metadata by ID."""
        return self._read_meta(project_id)

    def update_project(self, meta: ProjectMeta) -> None:
        """Persist updated project metadata."""
        meta.updated_at = _now()
        d = self._root / meta.project_id
        d.mkdir(parents=True, exist_ok=True)
        self._write_meta(meta)

    def delete_project(self, project_id: str) -> None:
        """Remove project directory and all its files."""
        d = self._root / project_id
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # Architecture / History                                               #
    # ------------------------------------------------------------------ #

    def read_architecture(self, project_id: str) -> str:
        p = self._root / project_id / "architecture.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def write_architecture(self, project_id: str, content: str) -> None:
        d = self._root / project_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "architecture.md").write_text(content, encoding="utf-8")

    def read_context_history(self, project_id: str) -> str:
        p = self._root / project_id / "context_history.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def append_context_history(self, project_id: str, entry: str) -> None:
        p = self._root / project_id / "context_history.md"
        with p.open("a", encoding="utf-8") as f:
            f.write(f"\n---\n{entry}\n")

    # ------------------------------------------------------------------ #
    # Agent membership                                                     #
    # ------------------------------------------------------------------ #

    def add_agent(self, project_id: str, session_id: str) -> None:
        meta = self.get_project(project_id)
        if meta is not None and session_id not in meta.agent_ids:
            meta.agent_ids.append(session_id)
            self.update_project(meta)

    def remove_agent(self, project_id: str, session_id: str) -> None:
        meta = self.get_project(project_id)
        if meta is not None and session_id in meta.agent_ids:
            meta.agent_ids.remove(session_id)
            self.update_project(meta)

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _read_meta(self, project_id: str) -> ProjectMeta | None:
        meta_path = self._root / project_id / "project.json"
        if not meta_path.exists():
            return None
        try:
            data: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
            return ProjectMeta(
                project_id=data.get("project_id", project_id),
                name=data.get("name", ""),
                description=data.get("description", ""),
                workdir=data.get("workdir", ""),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                agent_ids=data.get("agent_ids", []),
            )
        except Exception:
            return None

    def _write_meta(self, meta: ProjectMeta) -> None:
        meta_path = self._root / meta.project_id / "project.json"
        meta_path.write_text(
            json.dumps(asdict(meta), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
