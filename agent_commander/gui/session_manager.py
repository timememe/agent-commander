"""Session management — pure Python, no tkinter."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from agent_commander.gui.chat_panel import ChatMessage
from agent_commander.session.gui_store import GUIStore, LoopState, ScheduleDef, SessionMeta, StoredMessage


@dataclass
class SessionState:
    """Session state for one chat."""

    session_id: str
    title: str
    agent: str = "codex"
    workdir: str = ""
    messages: list[ChatMessage] = field(default_factory=list)
    streaming: bool = False
    request_started_at: float | None = None
    created_at: str = ""
    active_skill_ids: list[str] = field(default_factory=list)
    active_extension_ids: list[str] = field(default_factory=list)
    mode: str = "manual"           # "manual" | "loop" | "schedule"
    project_id: str | None = None
    loop_state: LoopState | None = None
    schedule_def: ScheduleDef | None = None
    schedule_prompt: str = ""      # prompt text that runs on schedule


class SessionManager:
    """Manages session creation, persistence, and auto-titling without GUI."""

    def __init__(self, store: GUIStore | None, default_agent: str) -> None:
        self._store = store
        self._default_agent = default_agent
        self.sessions: dict[str, SessionState] = {}
        self.active_session_id: str = ""
        self.session_counter: int = 0

    def create(
        self,
        session_id: str | None = None,
        agent: str | None = None,
        make_active: bool = True,
        mode: str = "manual",
        project_id: str | None = None,
    ) -> SessionState:
        """Create a new session, write to store, and optionally make it active."""
        self.session_counter += 1
        sid = session_id or f"chat_{self.session_counter:03d}"
        title = f"Chat {self.session_counter}"
        now = datetime.now().isoformat(timespec="seconds")
        session = SessionState(session_id=sid, title=title, created_at=now, mode=mode, project_id=project_id)
        session.agent = (agent or self._default_agent).strip().lower()
        if mode == "loop":
            session.loop_state = LoopState()
        self.sessions[sid] = session
        if make_active:
            self.active_session_id = sid

        store = self._store
        if store is not None:
            store.upsert_meta(SessionMeta(
                session_id=sid,
                title=title,
                agent=session.agent,
                workdir=session.workdir,
                created_at=now,
                updated_at=now,
                message_count=0,
                mode=mode,
                project_id=project_id,
            ))
            store.ensure_agent_cache(sid, session.agent, session.workdir)

        return session

    def load_persisted(self) -> str | None:
        """Load sessions from store. Returns active_session_id if any, else None."""
        store = self._store
        if store is None:
            return None
        metas = store.list_sessions()
        if not metas:
            return None

        max_counter = 0
        for meta in metas:
            msgs = store.load_messages(meta.session_id)
            session = SessionState(
                session_id=meta.session_id,
                title=meta.title,
                agent=meta.agent,
                workdir=meta.workdir,
                created_at=meta.created_at,
                messages=[ChatMessage(role=m.role, text=m.text) for m in msgs],
                active_skill_ids=list(meta.active_skill_ids),
                active_extension_ids=list(meta.active_extension_ids),
                mode=meta.mode,
                project_id=meta.project_id,
            )
            if session.mode == "loop":
                session.loop_state = LoopState()
            self.sessions[meta.session_id] = session
            try:
                num = int(meta.session_id.rsplit("_", 1)[-1])
                max_counter = max(max_counter, num)
            except (ValueError, IndexError):
                pass

        self.session_counter = max(self.session_counter, max_counter)
        self.active_session_id = metas[0].session_id
        return self.active_session_id

    def persist_message(self, session_id: str, role: str, text: str) -> None:
        """Append one message to JSONL and refresh session meta in index."""
        store = self._store
        if store is None:
            return
        ts = datetime.now().isoformat(timespec="seconds")
        store.append_message(session_id, StoredMessage(role=role, text=text, ts=ts))
        session = self.sessions.get(session_id)
        if session is not None:
            store.upsert_meta(SessionMeta(
                session_id=session_id,
                title=session.title,
                agent=session.agent,
                workdir=session.workdir or "",
                created_at=session.created_at,
                updated_at=ts,
                message_count=len(session.messages),
                active_skill_ids=list(session.active_skill_ids),
                active_extension_ids=list(session.active_extension_ids),
                mode=session.mode,
                project_id=session.project_id,
            ))

    def delete_session(self, session_id: str) -> None:
        """Remove session from memory and persistent store."""
        self.sessions.pop(session_id, None)
        if self._store is not None:
            self._store.delete_session(session_id)

    def maybe_auto_title(self, session: SessionState, first_user_text: str) -> bool:
        """Derive title from first user message. Returns True if title changed."""
        if not re.match(r"^Chat \d+$", session.title):
            return False  # Already has a custom title (e.g. restored from disk).
        cleaned = first_user_text.strip().replace("\n", " ")
        new_title = cleaned[:40] + ("…" if len(cleaned) > 40 else "")
        if not new_title:
            return False
        session.title = new_title
        store = self._store
        if store is not None:
            ts = datetime.now().isoformat(timespec="seconds")
            store.upsert_meta(SessionMeta(
                session_id=session.session_id,
                title=new_title,
                agent=session.agent,
                workdir=session.workdir or "",
                created_at=session.created_at,
                updated_at=ts,
                message_count=len(session.messages),
                active_skill_ids=list(session.active_skill_ids),
                active_extension_ids=list(session.active_extension_ids),
                mode=session.mode,
                project_id=session.project_id,
            ))
        return True
