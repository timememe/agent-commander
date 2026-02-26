"""Persistent GUI session store — two-tier cache architecture.

Directory layout::

    ~/.agent-commander/cache/
      main/                     # main cache: GUI session history
          index.json            # session metadata list (ordered by updated_at desc)
          {session_id}.jsonl    # messages for each session (append-only)
      agents/                   # agent cache: per-session data
          {session_id}/
              meta.json         # agent_type, workdir, created_at
              context.md        # workspace context (reserved – injected on session start)
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_CACHE_ROOT = Path.home() / ".agent-commander" / "cache"
_MAIN_DIR = "main"
_AGENTS_DIR = "agents"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class LoopState:
    """Runtime state for a loop-mode session."""

    iteration: int = 0
    checklist: list[dict] = field(default_factory=list)  # [{"text": str, "done": bool}]
    status: str = "idle"  # "idle" | "running" | "paused" | "done"
    stop_detected: bool = False


@dataclass
class ScheduleDef:
    """Schedule definition for a schedule-mode session."""

    cron_expr: str = ""   # stored as cron expression
    display: str = ""     # human-readable, e.g. "Every Monday at 09:00"
    job_id: str = ""      # reference to CronJob.id
    enabled: bool = True
    last_run_at: str = ""
    next_run_at: str = ""


@dataclass
class SessionMeta:
    """Lightweight metadata entry stored in index.json."""

    session_id: str
    title: str
    agent: str
    workdir: str
    created_at: str
    updated_at: str
    message_count: int = 0
    active_skill_ids: list[str] = field(default_factory=list)
    active_extension_ids: list[str] = field(default_factory=list)
    mode: str = "manual"           # "manual" | "loop" | "schedule"
    project_id: str | None = None


@dataclass
class StoredMessage:
    """One message line in a JSONL file."""

    role: str   # "user" | "assistant" | "system"
    text: str
    ts: str = ""


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class GUIStore:
    """Two-tier persistent cache: main (sessions) + agent (per-session).

    Thread safety: append_message uses file append which is atomic on all
    major OS-es for writes < PIPE_BUF. upsert_meta serialises through a
    full read-modify-write, so callers must avoid concurrent upserts for
    the same session (the GUI runs single-threaded, so this is fine).
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or _CACHE_ROOT
        self._main = self._root / _MAIN_DIR
        self._agents = self._root / _AGENTS_DIR
        self._main.mkdir(parents=True, exist_ok=True)
        self._agents.mkdir(parents=True, exist_ok=True)
        self._index_path = self._main / "index.json"

    # ------------------------------------------------------------------ #
    # Main cache — sessions                                                #
    # ------------------------------------------------------------------ #

    def list_sessions(self) -> list[SessionMeta]:
        """Return all session metadata sorted by updated_at descending."""
        result: list[SessionMeta] = []
        for d in self._read_index():
            try:
                result.append(SessionMeta(
                    session_id=d.get("session_id", ""),
                    title=d.get("title", ""),
                    agent=d.get("agent", ""),
                    workdir=d.get("workdir", ""),
                    created_at=d.get("created_at", ""),
                    updated_at=d.get("updated_at", ""),
                    message_count=d.get("message_count", 0),
                    active_skill_ids=d.get("active_skill_ids", []),
                    active_extension_ids=d.get("active_extension_ids", []),
                    mode=d.get("mode", "manual"),
                    project_id=d.get("project_id", None),
                ))
            except Exception:
                pass
        return result

    def load_messages(self, session_id: str) -> list[StoredMessage]:
        """Load all messages for a session from its JSONL file."""
        path = self._messages_path(session_id)
        if not path.exists():
            return []
        msgs: list[StoredMessage] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                msgs.append(StoredMessage(
                    role=d.get("role", ""),
                    text=d.get("text", ""),
                    ts=d.get("ts", ""),
                ))
            except Exception:
                pass
        return msgs

    def upsert_meta(self, meta: SessionMeta) -> None:
        """Insert or update a session entry in index.json.

        Preserves created_at from the existing entry if the new meta has
        an empty created_at (safe partial-update pattern).
        """
        index = self._read_index()
        for i, entry in enumerate(index):
            if entry.get("session_id") == meta.session_id:
                if not meta.created_at:
                    meta.created_at = entry.get("created_at", _now())
                index[i] = asdict(meta)
                break
        else:
            if not meta.created_at:
                meta.created_at = _now()
            index.append(asdict(meta))
        index.sort(key=lambda d: d.get("updated_at", ""), reverse=True)
        self._write_index(index)

    def append_message(self, session_id: str, msg: StoredMessage) -> None:
        """Append one message line to the JSONL file (never rewrites)."""
        path = self._messages_path(session_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(msg), ensure_ascii=False) + "\n")

    def delete_session(self, session_id: str) -> None:
        """Remove a session from the index, delete its JSONL file and agent cache dir."""
        index = [e for e in self._read_index() if e.get("session_id") != session_id]
        self._write_index(index)
        p = self._messages_path(session_id)
        if p.exists():
            p.unlink()
        agent_dir = self._agents / session_id
        if agent_dir.exists():
            shutil.rmtree(agent_dir, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # Agent cache — per session                                            #
    # ------------------------------------------------------------------ #

    def ensure_agent_cache(self, session_id: str, agent: str, workdir: str) -> Path:
        """Create the agent cache directory and seed meta.json + context.md."""
        cache_dir = self._agents / session_id
        cache_dir.mkdir(parents=True, exist_ok=True)

        meta_path = cache_dir / "meta.json"
        if not meta_path.exists():
            meta_path.write_text(
                json.dumps(
                    {
                        "session_id": session_id,
                        "agent": agent,
                        "workdir": workdir,
                        "created_at": _now(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        # Reserve context.md for future workspace-context injection.
        ctx = cache_dir / "context.md"
        if not ctx.exists():
            ctx.write_text("", encoding="utf-8")

        return cache_dir

    def get_agent_cache_dir(self, session_id: str) -> Path:
        """Return the agent cache directory path (may not exist yet)."""
        return self._agents / session_id

    def get_context_path(self, session_id: str) -> Path:
        """Return path to the workspace context file for this session."""
        return self._agents / session_id / "context.md"

    # ------------------------------------------------------------------ #
    # Private helpers                                                       #
    # ------------------------------------------------------------------ #

    def _messages_path(self, session_id: str) -> Path:
        return self._main / f"{session_id}.jsonl"

    def _read_index(self) -> list[dict[str, Any]]:
        if not self._index_path.exists():
            return []
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _write_index(self, data: list[dict[str, Any]]) -> None:
        self._index_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
