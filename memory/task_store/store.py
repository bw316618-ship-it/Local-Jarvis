"""Durable task and step store backed by SQLite.

Design goals
------------
* Stable IDs: every task and every tool-call step gets a UUID that
  survives process restarts.
* Explicit state machine: tasks and steps move through well-defined
  states (pending → running → succeeded | failed | timeout | unknown).
  No implicit "it must have worked because we got here" reasoning.
* Outcome-unknown handling: when a tool call times out the step is
  marked TIMEOUT (not FAILED) so callers know the underlying operation
  may still complete later.  Retrying a TIMEOUT step without checking
  idempotency is the caller's responsibility.
* Checkpoints: the step result (tool output string) is stored so that
  a restart can replay the conversation history from the DB rather than
  re-running non-idempotent tool calls.
* Attempts: each step records how many times it has been attempted so
  callers can detect runaway retries.
* Transactional consistency: task-state and step-state changes are
  committed in the same SQLite transaction where practical.
* No dependency on ChromaDB or the audit log -- this is execution truth,
  not a search index or a human-readable preview.

Schema
------
tasks(
    task_id TEXT PRIMARY KEY,
    session_id TEXT,          -- device_id or session identifier
    user_message TEXT,
    state TEXT,               -- TaskState value
    created_at TEXT,          -- ISO-8601 UTC
    updated_at TEXT,
    final_reply TEXT          -- set when task reaches a terminal state
)

steps(
    step_id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(task_id),
    tool_name TEXT,
    arguments TEXT,           -- JSON
    state TEXT,               -- StepState value
    attempt INTEGER DEFAULT 1,
    result TEXT,              -- tool output (may be NULL while running)
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER
)

Thread safety
-------------
SQLite in WAL mode supports concurrent readers and one writer.  We use a
module-level threading.Lock to serialise writes from multiple threads
(the tool executor threads) without relying on SQLite's own locking,
which is process-level and does not protect against concurrent writes
from threads in the same process sharing the same connection.

The store is a singleton per DB path (see get_default_store()).  Tests
can construct TaskStore(path=tmp_path/...) to get an isolated instance.
"""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = BASE_DIR / "memory" / "tasks.db"


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"       # timed out -- outcome unknown
    UNKNOWN = "unknown"       # process died mid-step -- outcome unknown


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id     TEXT PRIMARY KEY,
    session_id  TEXT,
    user_message TEXT,
    state       TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    final_reply TEXT
);

CREATE TABLE IF NOT EXISTS steps (
    step_id     TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL REFERENCES tasks(task_id),
    tool_name   TEXT NOT NULL,
    arguments   TEXT NOT NULL DEFAULT '{}',
    state       TEXT NOT NULL DEFAULT 'pending',
    attempt     INTEGER NOT NULL DEFAULT 1,
    result      TEXT,
    started_at  TEXT,
    finished_at TEXT,
    duration_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_steps_task_id ON steps(task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_session  ON tasks(session_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    """SQLite-backed store for tasks and their tool-call steps.

    Parameters
    ----------
    path:
        Path to the SQLite database file.  Created (including parent
        directories) if it does not exist.
    """

    def __init__(self, path: Path = DEFAULT_DB_PATH):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = self._open()

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self._path),
            check_same_thread=False,
            isolation_level=None,  # autocommit; we manage transactions manually
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA)
        return conn

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    def create_task(
        self,
        user_message: str,
        session_id: str = "",
        task_id: str = None,
    ) -> str:
        """Create a new task in PENDING state.  Returns the task_id."""
        task_id = task_id or str(uuid.uuid4())
        now = _now()
        with self._lock:
            self._conn.execute(
                "BEGIN",
            )
            try:
                self._conn.execute(
                    """
                    INSERT INTO tasks
                        (task_id, session_id, user_message, state, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (task_id, session_id or "", user_message, TaskState.PENDING, now, now),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return task_id

    def start_task(self, task_id: str) -> None:
        """Transition task from PENDING to RUNNING."""
        self._update_task_state(task_id, TaskState.RUNNING)

    def complete_task(self, task_id: str, final_reply: str) -> None:
        """Transition task to SUCCEEDED and store the final reply."""
        now = _now()
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    """
                    UPDATE tasks
                    SET state = ?, final_reply = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (TaskState.SUCCEEDED, final_reply, now, task_id),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def fail_task(self, task_id: str, reason: str = "") -> None:
        """Transition task to FAILED."""
        now = _now()
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    """
                    UPDATE tasks
                    SET state = ?, final_reply = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (TaskState.FAILED, reason, now, task_id),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def cancel_task(self, task_id: str) -> None:
        """Transition task to CANCELLED."""
        self._update_task_state(task_id, TaskState.CANCELLED)

    def _update_task_state(self, task_id: str, state: TaskState) -> None:
        now = _now()
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    "UPDATE tasks SET state = ?, updated_at = ? WHERE task_id = ?",
                    (state, now, task_id),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def get_task(self, task_id: str) -> Optional[dict]:
        """Return the task row as a dict, or None if not found."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT task_id, session_id, user_message, state, "
                "created_at, updated_at, final_reply FROM tasks WHERE task_id = ?",
                (task_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "task_id": row[0],
            "session_id": row[1],
            "user_message": row[2],
            "state": row[3],
            "created_at": row[4],
            "updated_at": row[5],
            "final_reply": row[6],
        }

    def list_tasks(
        self,
        session_id: str = None,
        state: TaskState = None,
        limit: int = 50,
    ) -> list:
        """Return tasks, optionally filtered by session_id and/or state."""
        query = (
            "SELECT task_id, session_id, user_message, state, "
            "created_at, updated_at, final_reply FROM tasks"
        )
        params = []
        conditions = []
        if session_id is not None:
            conditions.append("session_id = ?")
            params.append(session_id)
        if state is not None:
            conditions.append("state = ?")
            params.append(state)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            cur = self._conn.execute(query, params)
            rows = cur.fetchall()

        return [
            {
                "task_id": r[0],
                "session_id": r[1],
                "user_message": r[2],
                "state": r[3],
                "created_at": r[4],
                "updated_at": r[5],
                "final_reply": r[6],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Step lifecycle
    # ------------------------------------------------------------------

    def create_step(
        self,
        task_id: str,
        tool_name: str,
        arguments: dict,
        step_id: str = None,
    ) -> str:
        """Create a new step in PENDING state.  Returns the step_id."""
        step_id = step_id or str(uuid.uuid4())
        now = _now()
        args_json = json.dumps(arguments, default=str)
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    """
                    INSERT INTO steps
                        (step_id, task_id, tool_name, arguments, state, attempt, started_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    """,
                    (step_id, task_id, tool_name, args_json, StepState.PENDING, now),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return step_id

    def start_step(self, step_id: str) -> None:
        """Transition step to RUNNING."""
        now = _now()
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    "UPDATE steps SET state = ?, started_at = ? WHERE step_id = ?",
                    (StepState.RUNNING, now, step_id),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def complete_step(
        self,
        step_id: str,
        result: str,
        duration_ms: int = None,
    ) -> None:
        """Transition step to SUCCEEDED and store the result."""
        now = _now()
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    """
                    UPDATE steps
                    SET state = ?, result = ?, finished_at = ?, duration_ms = ?
                    WHERE step_id = ?
                    """,
                    (StepState.SUCCEEDED, result, now, duration_ms, step_id),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def fail_step(
        self,
        step_id: str,
        result: str,
        duration_ms: int = None,
    ) -> None:
        """Transition step to FAILED and store the error string."""
        now = _now()
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    """
                    UPDATE steps
                    SET state = ?, result = ?, finished_at = ?, duration_ms = ?
                    WHERE step_id = ?
                    """,
                    (StepState.FAILED, result, now, duration_ms, step_id),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def timeout_step(
        self,
        step_id: str,
        duration_ms: int = None,
    ) -> None:
        """Transition step to TIMEOUT.

        The underlying operation may still be running in the thread pool.
        The result is left NULL to make it clear the outcome is unknown.
        Callers must not blindly retry non-idempotent operations.
        """
        now = _now()
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    """
                    UPDATE steps
                    SET state = ?, finished_at = ?, duration_ms = ?
                    WHERE step_id = ?
                    """,
                    (StepState.TIMEOUT, now, duration_ms, step_id),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def mark_step_unknown(self, step_id: str) -> None:
        """Mark a step UNKNOWN -- used on restart when a step was RUNNING
        at the time the process died and its outcome cannot be determined."""
        now = _now()
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    "UPDATE steps SET state = ?, finished_at = ? WHERE step_id = ?",
                    (StepState.UNKNOWN, now, step_id),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def get_step(self, step_id: str) -> Optional[dict]:
        """Return the step row as a dict, or None if not found."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT step_id, task_id, tool_name, arguments, state, "
                "attempt, result, started_at, finished_at, duration_ms "
                "FROM steps WHERE step_id = ?",
                (step_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "step_id": row[0],
            "task_id": row[1],
            "tool_name": row[2],
            "arguments": json.loads(row[3]),
            "state": row[4],
            "attempt": row[5],
            "result": row[6],
            "started_at": row[7],
            "finished_at": row[8],
            "duration_ms": row[9],
        }

    def list_steps(self, task_id: str) -> list:
        """Return all steps for a task, ordered by started_at."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT step_id, task_id, tool_name, arguments, state, "
                "attempt, result, started_at, finished_at, duration_ms "
                "FROM steps WHERE task_id = ? ORDER BY started_at ASC",
                (task_id,),
            )
            rows = cur.fetchall()
        return [
            {
                "step_id": r[0],
                "task_id": r[1],
                "tool_name": r[2],
                "arguments": json.loads(r[3]),
                "state": r[4],
                "attempt": r[5],
                "result": r[6],
                "started_at": r[7],
                "finished_at": r[8],
                "duration_ms": r[9],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Restart recovery
    # ------------------------------------------------------------------

    def recover_interrupted(self) -> list:
        """On startup, find tasks/steps that were RUNNING when the process
        died and mark them with appropriate unknown/failed states.

        Returns a list of (task_id, step_id) pairs that were recovered so
        callers can log or surface them.

        This must be called once at startup before any new tasks are
        created.  It is idempotent: calling it again on an already-
        recovered store is a no-op.
        """
        recovered = []
        now = _now()

        with self._lock:
            self._conn.execute("BEGIN")
            try:
                # Steps that were RUNNING when the process died -- their
                # outcome is unknown.  Mark them UNKNOWN rather than FAILED
                # so callers know not to blindly retry non-idempotent ops.
                cur = self._conn.execute(
                    "SELECT step_id, task_id FROM steps WHERE state = ?",
                    (StepState.RUNNING,),
                )
                running_steps = cur.fetchall()

                for step_id, task_id in running_steps:
                    self._conn.execute(
                        "UPDATE steps SET state = ?, finished_at = ? WHERE step_id = ?",
                        (StepState.UNKNOWN, now, step_id),
                    )
                    recovered.append({"task_id": task_id, "step_id": step_id})

                # Tasks that were RUNNING when the process died -- mark
                # them FAILED since we cannot resume them.
                self._conn.execute(
                    "UPDATE tasks SET state = ?, updated_at = ? WHERE state = ?",
                    (TaskState.FAILED, now, TaskState.RUNNING),
                )

                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        return recovered

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_store: Optional[TaskStore] = None
_store_lock = threading.Lock()


def get_default_store() -> TaskStore:
    """Return the process-wide default TaskStore, creating it on first call.

    Tests should construct TaskStore(path=...) directly to get an isolated
    instance rather than using this singleton.
    """
    global _default_store
    if _default_store is None:
        with _store_lock:
            if _default_store is None:
                _default_store = TaskStore(DEFAULT_DB_PATH)
    return _default_store
