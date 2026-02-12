import os
import sqlite3
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class TaskRecord:
    id: int
    title: str
    folder: str
    goal: str
    dod: str
    status: str
    priority: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ProjectRecord:
    id: int
    name: str
    folder: str
    description: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class EventRecord:
    id: int
    pane_id: str
    task_id: int
    agent: str
    event_type: str
    payload_json: str
    created_at: str


class OrchestratorStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    folder TEXT NOT NULL DEFAULT '',
                    goal TEXT NOT NULL DEFAULT '',
                    dod TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'todo',
                    priority INTEGER NOT NULL DEFAULT 2,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    pane_id TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    run_id INTEGER NOT NULL DEFAULT 0,
                    summary_md TEXT NOT NULL DEFAULT '',
                    next_step TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pane_id TEXT NOT NULL,
                    task_id INTEGER NOT NULL DEFAULT 0,
                    agent TEXT NOT NULL DEFAULT '',
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_created_at
                ON events(created_at);

                CREATE INDEX IF NOT EXISTS idx_events_pane_id_id
                ON events(pane_id, id);

                CREATE INDEX IF NOT EXISTS idx_events_task_id_id
                ON events(task_id, id);

                CREATE TABLE IF NOT EXISTS policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL DEFAULT 0,
                    pane_id TEXT NOT NULL DEFAULT '',
                    auto_continue INTEGER NOT NULL DEFAULT 0,
                    auto_resume INTEGER NOT NULL DEFAULT 0,
                    fallback_chain_json TEXT NOT NULL DEFAULT '[]',
                    limits_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS pane_bindings (
                    pane_id TEXT PRIMARY KEY,
                    task_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    folder TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pane_project_bindings (
                    pane_id TEXT PRIMARY KEY,
                    project_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                );
                """
            )

    def list_tasks(self) -> list[TaskRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, folder, goal, dod, status, priority, created_at, updated_at
                FROM tasks
                ORDER BY
                    CASE status
                        WHEN 'in_progress' THEN 0
                        WHEN 'paused' THEN 1
                        WHEN 'todo' THEN 2
                        WHEN 'blocked' THEN 3
                        WHEN 'done' THEN 4
                        ELSE 5
                    END,
                    priority ASC,
                    updated_at DESC,
                    id DESC
                """
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_task(self, task_id: int) -> Optional[TaskRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, folder, goal, dod, status, priority, created_at, updated_at
                FROM tasks
                WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
        return self._row_to_task(row) if row else None

    def create_task(
        self,
        title: str,
        folder: str = "",
        goal: str = "",
        dod: str = "",
        status: str = "todo",
        priority: int = 2,
    ) -> TaskRecord:
        now = utc_now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO tasks (title, folder, goal, dod, status, priority, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (title.strip(), folder.strip(), goal.strip(), dod.strip(), status, priority, now, now),
            )
            task_id = int(cur.lastrowid)
        task = self.get_task(task_id)
        if not task:
            raise RuntimeError("Failed to create task")
        return task

    def update_task_status(self, task_id: int, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now_iso(), task_id),
            )

    def delete_task(self, task_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cur.rowcount > 0

    def set_pane_binding(self, pane_id: str, task_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pane_project_bindings WHERE pane_id = ?", (pane_id,))
            conn.execute(
                """
                INSERT INTO pane_bindings (pane_id, task_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(pane_id) DO UPDATE SET
                    task_id = excluded.task_id,
                    updated_at = excluded.updated_at
                """,
                (pane_id, task_id, utc_now_iso()),
            )

    def clear_pane_binding(self, pane_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pane_bindings WHERE pane_id = ?", (pane_id,))

    def list_pane_bindings(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT pane_id, task_id FROM pane_bindings ORDER BY pane_id"
            ).fetchall()
        return {str(row["pane_id"]): int(row["task_id"]) for row in rows}

    def _row_to_task(self, row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            id=int(row["id"]),
            title=str(row["title"]),
            folder=str(row["folder"]),
            goal=str(row["goal"]),
            dod=str(row["dod"]),
            status=str(row["status"]),
            priority=int(row["priority"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    # ── Project CRUD ──────────────────────────────────────────────────────

    def list_projects(self) -> list[ProjectRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, folder, description, status, created_at, updated_at
                FROM projects
                ORDER BY
                    CASE status
                        WHEN 'active' THEN 0
                        WHEN 'paused' THEN 1
                        WHEN 'archived' THEN 2
                        ELSE 3
                    END,
                    updated_at DESC,
                    id DESC
                """
            ).fetchall()
        return [self._row_to_project(row) for row in rows]

    def get_project(self, project_id: int) -> Optional[ProjectRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, folder, description, status, created_at, updated_at
                FROM projects WHERE id = ?
                """,
                (project_id,),
            ).fetchone()
        return self._row_to_project(row) if row else None

    def create_project(
        self,
        name: str,
        folder: str,
        description: str = "",
        status: str = "active",
    ) -> ProjectRecord:
        now = utc_now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO projects (name, folder, description, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name.strip(), folder.strip(), description.strip(), status, now, now),
            )
            project_id = int(cur.lastrowid)
        project = self.get_project(project_id)
        if not project:
            raise RuntimeError("Failed to create project")
        return project

    def update_project_status(self, project_id: int, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now_iso(), project_id),
            )

    def delete_project(self, project_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        return cur.rowcount > 0

    def set_pane_project_binding(self, pane_id: str, project_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pane_bindings WHERE pane_id = ?", (pane_id,))
            conn.execute(
                """
                INSERT INTO pane_project_bindings (pane_id, project_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(pane_id) DO UPDATE SET
                    project_id = excluded.project_id,
                    updated_at = excluded.updated_at
                """,
                (pane_id, project_id, utc_now_iso()),
            )

    def clear_pane_project_binding(self, pane_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM pane_project_bindings WHERE pane_id = ?", (pane_id,)
            )

    def list_pane_project_bindings(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT pane_id, project_id FROM pane_project_bindings ORDER BY pane_id"
            ).fetchall()
        return {str(row["pane_id"]): int(row["project_id"]) for row in rows}

    # Event log (foundation for chat-like UI transcript)
    def append_event(
        self,
        pane_id: str,
        event_type: str,
        payload: object = None,
        task_id: int = 0,
        agent: str = "",
    ) -> int:
        payload_json = self._encode_payload(payload)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO events (pane_id, task_id, agent, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pane_id, int(task_id), agent, event_type, payload_json, utc_now_iso()),
            )
            return int(cur.lastrowid)

    def list_events(
        self,
        limit: int = 200,
        pane_id: Optional[str] = None,
        task_id: Optional[int] = None,
        event_types: Optional[list[str]] = None,
        after_id: Optional[int] = None,
    ) -> list[EventRecord]:
        safe_limit = max(1, min(int(limit), 2000))
        query = (
            "SELECT id, pane_id, task_id, agent, event_type, payload_json, created_at "
            "FROM events"
        )
        clauses: list[str] = []
        args: list[object] = []

        if pane_id is not None:
            clauses.append("pane_id = ?")
            args.append(pane_id)
        if task_id is not None:
            clauses.append("task_id = ?")
            args.append(int(task_id))
        if after_id is not None:
            clauses.append("id > ?")
            args.append(int(after_id))
        if event_types:
            placeholders = ", ".join("?" for _ in event_types)
            clauses.append(f"event_type IN ({placeholders})")
            args.extend(event_types)

        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id ASC LIMIT ?"
        args.append(safe_limit)

        with self._connect() as conn:
            rows = conn.execute(query, tuple(args)).fetchall()
        return [self._row_to_event(row) for row in rows]

    def list_events_since(
        self,
        event_id: int,
        limit: int = 200,
        pane_id: Optional[str] = None,
        task_id: Optional[int] = None,
        event_types: Optional[list[str]] = None,
    ) -> list[EventRecord]:
        return self.list_events(
            limit=limit,
            pane_id=pane_id,
            task_id=task_id,
            event_types=event_types,
            after_id=event_id,
        )

    def _encode_payload(self, payload: object) -> str:
        if payload is None:
            payload = {}
        try:
            return json.dumps(payload, ensure_ascii=False)
        except Exception:
            return json.dumps({"value": str(payload)}, ensure_ascii=False)

    def _row_to_event(self, row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            id=int(row["id"]),
            pane_id=str(row["pane_id"]),
            task_id=int(row["task_id"]),
            agent=str(row["agent"]),
            event_type=str(row["event_type"]),
            payload_json=str(row["payload_json"]),
            created_at=str(row["created_at"]),
        )

    def _row_to_project(self, row: sqlite3.Row) -> ProjectRecord:
        return ProjectRecord(
            id=int(row["id"]),
            name=str(row["name"]),
            folder=str(row["folder"]),
            description=str(row["description"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
