"""Tests for the durable task/step store (memory/task_store/store.py).

All tests use an isolated in-memory or tmp-path SQLite database -- never
the production memory/tasks.db.  The conftest.py stubs out heavy ML
modules at collection time, so these tests run fast.

Coverage:
  1. Task lifecycle: create → start → complete / fail / cancel.
  2. Step lifecycle: create → start → complete / fail / timeout / unknown.
  3. Stable IDs: task_id and step_id survive across store re-opens.
  4. Restart recovery: RUNNING tasks/steps are marked FAILED/UNKNOWN.
  5. Concurrent writes: multiple threads writing steps for the same task
     do not corrupt the database.
  6. Store failures are isolated: a bad write does not raise in chat().
  7. Integration with JarvisLLM: tool calls create step records; task
     state reflects the turn outcome.
"""

import json
import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from memory.task_store.store import (
    TaskStore,
    TaskState,
    StepState,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """An isolated TaskStore backed by a temporary SQLite file."""
    s = TaskStore(path=tmp_path / "tasks.db")
    yield s
    s.close()


@pytest.fixture
def store2(tmp_path):
    """A second TaskStore pointing at the same file (simulates re-open)."""
    db = tmp_path / "tasks2.db"
    s1 = TaskStore(path=db)
    yield s1, db
    s1.close()


# ---------------------------------------------------------------------------
# 1. Task lifecycle
# ---------------------------------------------------------------------------

class TestTaskLifecycle:

    def test_create_task_returns_stable_id(self, store):
        task_id = store.create_task("hello world", session_id="dev-1")
        assert task_id, "create_task must return a non-empty ID"
        task = store.get_task(task_id)
        assert task is not None
        assert task["task_id"] == task_id
        assert task["user_message"] == "hello world"
        assert task["session_id"] == "dev-1"
        assert task["state"] == TaskState.PENDING

    def test_start_task_transitions_to_running(self, store):
        task_id = store.create_task("test")
        store.start_task(task_id)
        task = store.get_task(task_id)
        assert task["state"] == TaskState.RUNNING

    def test_complete_task_stores_reply(self, store):
        task_id = store.create_task("test")
        store.start_task(task_id)
        store.complete_task(task_id, final_reply="The answer is 42.")
        task = store.get_task(task_id)
        assert task["state"] == TaskState.SUCCEEDED
        assert task["final_reply"] == "The answer is 42."

    def test_fail_task_stores_reason(self, store):
        task_id = store.create_task("test")
        store.start_task(task_id)
        store.fail_task(task_id, reason="LLM exploded")
        task = store.get_task(task_id)
        assert task["state"] == TaskState.FAILED
        assert "LLM exploded" in task["final_reply"]

    def test_cancel_task(self, store):
        task_id = store.create_task("test")
        store.cancel_task(task_id)
        task = store.get_task(task_id)
        assert task["state"] == TaskState.CANCELLED

    def test_get_task_returns_none_for_unknown_id(self, store):
        assert store.get_task("nonexistent-id") is None

    def test_list_tasks_by_session(self, store):
        store.create_task("msg1", session_id="dev-a")
        store.create_task("msg2", session_id="dev-a")
        store.create_task("msg3", session_id="dev-b")

        tasks_a = store.list_tasks(session_id="dev-a")
        assert len(tasks_a) == 2
        assert all(t["session_id"] == "dev-a" for t in tasks_a)

    def test_list_tasks_by_state(self, store):
        t1 = store.create_task("msg1")
        store.start_task(t1)
        store.complete_task(t1, "done")

        t2 = store.create_task("msg2")
        store.start_task(t2)
        store.fail_task(t2, "oops")

        succeeded = store.list_tasks(state=TaskState.SUCCEEDED)
        failed = store.list_tasks(state=TaskState.FAILED)

        assert len(succeeded) == 1
        assert succeeded[0]["task_id"] == t1
        assert len(failed) == 1
        assert failed[0]["task_id"] == t2


# ---------------------------------------------------------------------------
# 2. Step lifecycle
# ---------------------------------------------------------------------------

class TestStepLifecycle:

    def test_create_step_returns_stable_id(self, store):
        task_id = store.create_task("test")
        step_id = store.create_step(task_id, "get_time", {})
        assert step_id, "create_step must return a non-empty ID"
        step = store.get_step(step_id)
        assert step is not None
        assert step["step_id"] == step_id
        assert step["task_id"] == task_id
        assert step["tool_name"] == "get_time"
        assert step["state"] == StepState.PENDING

    def test_start_step_transitions_to_running(self, store):
        task_id = store.create_task("test")
        step_id = store.create_step(task_id, "get_time", {})
        store.start_step(step_id)
        step = store.get_step(step_id)
        assert step["state"] == StepState.RUNNING

    def test_complete_step_stores_result(self, store):
        task_id = store.create_task("test")
        step_id = store.create_step(task_id, "get_time", {})
        store.start_step(step_id)
        store.complete_step(step_id, result="12:00 PM", duration_ms=42)
        step = store.get_step(step_id)
        assert step["state"] == StepState.SUCCEEDED
        assert step["result"] == "12:00 PM"
        assert step["duration_ms"] == 42

    def test_fail_step_stores_error(self, store):
        task_id = store.create_task("test")
        step_id = store.create_step(task_id, "bad_tool", {})
        store.start_step(step_id)
        store.fail_step(step_id, result="Error: something broke", duration_ms=10)
        step = store.get_step(step_id)
        assert step["state"] == StepState.FAILED
        assert "something broke" in step["result"]

    def test_timeout_step_leaves_result_null(self, store):
        """A timed-out step must have state=TIMEOUT and result=None,
        indicating the outcome is unknown (the underlying op may still run)."""
        task_id = store.create_task("test")
        step_id = store.create_step(task_id, "slow_tool", {})
        store.start_step(step_id)
        store.timeout_step(step_id, duration_ms=30000)
        step = store.get_step(step_id)
        assert step["state"] == StepState.TIMEOUT
        assert step["result"] is None, (
            "Timed-out step result must be NULL -- outcome is unknown"
        )

    def test_mark_step_unknown(self, store):
        task_id = store.create_task("test")
        step_id = store.create_step(task_id, "some_tool", {})
        store.start_step(step_id)
        store.mark_step_unknown(step_id)
        step = store.get_step(step_id)
        assert step["state"] == StepState.UNKNOWN

    def test_list_steps_for_task(self, store):
        task_id = store.create_task("test")
        s1 = store.create_step(task_id, "tool_a", {"x": 1})
        s2 = store.create_step(task_id, "tool_b", {"y": 2})
        steps = store.list_steps(task_id)
        assert len(steps) == 2
        step_ids = {s["step_id"] for s in steps}
        assert s1 in step_ids
        assert s2 in step_ids

    def test_step_arguments_round_trip_as_json(self, store):
        task_id = store.create_task("test")
        args = {"path": "/tmp/file.txt", "count": 3, "flag": True}
        step_id = store.create_step(task_id, "write_file", args)
        step = store.get_step(step_id)
        assert step["arguments"] == args


# ---------------------------------------------------------------------------
# 3. Stable IDs across re-opens
# ---------------------------------------------------------------------------

class TestStableIds:

    def test_task_id_survives_store_reopen(self, store2):
        s1, db_path = store2
        task_id = s1.create_task("persistent task", session_id="dev-x")
        s1.start_task(task_id)
        s1.close()

        # Re-open the same database.
        s2 = TaskStore(path=db_path)
        try:
            task = s2.get_task(task_id)
            assert task is not None, "Task must survive store re-open"
            assert task["task_id"] == task_id
            assert task["state"] == TaskState.RUNNING
        finally:
            s2.close()

    def test_step_id_survives_store_reopen(self, store2):
        s1, db_path = store2
        task_id = s1.create_task("test")
        step_id = s1.create_step(task_id, "my_tool", {"a": 1})
        s1.close()

        s2 = TaskStore(path=db_path)
        try:
            step = s2.get_step(step_id)
            assert step is not None
            assert step["step_id"] == step_id
            assert step["tool_name"] == "my_tool"
        finally:
            s2.close()


# ---------------------------------------------------------------------------
# 4. Restart recovery
# ---------------------------------------------------------------------------

class TestRestartRecovery:

    def test_running_tasks_marked_failed_on_recovery(self, tmp_path):
        db = tmp_path / "recover.db"

        # Simulate a process that died with a RUNNING task.
        s1 = TaskStore(path=db)
        task_id = s1.create_task("interrupted task")
        s1.start_task(task_id)
        s1.close()

        # Re-open and recover.
        s2 = TaskStore(path=db)
        recovered = s2.recover_interrupted()
        task = s2.get_task(task_id)
        s2.close()

        assert task["state"] == TaskState.FAILED, (
            "A RUNNING task at restart must be marked FAILED"
        )

    def test_running_steps_marked_unknown_on_recovery(self, tmp_path):
        db = tmp_path / "recover.db"

        s1 = TaskStore(path=db)
        task_id = s1.create_task("test")
        step_id = s1.create_step(task_id, "slow_tool", {})
        s1.start_step(step_id)
        s1.close()

        s2 = TaskStore(path=db)
        recovered = s2.recover_interrupted()
        step = s2.get_step(step_id)
        s2.close()

        assert step["state"] == StepState.UNKNOWN, (
            "A RUNNING step at restart must be marked UNKNOWN "
            "(outcome is unknown -- do not blindly retry)"
        )
        assert any(r["step_id"] == step_id for r in recovered), (
            "recover_interrupted must return the recovered step in its result list"
        )

    def test_recovery_is_idempotent(self, tmp_path):
        """Calling recover_interrupted() twice must not change already-
        recovered states."""
        db = tmp_path / "recover.db"

        s = TaskStore(path=db)
        task_id = s.create_task("test")
        s.start_task(task_id)
        s.recover_interrupted()
        s.recover_interrupted()  # second call must be a no-op
        task = s.get_task(task_id)
        s.close()

        assert task["state"] == TaskState.FAILED

    def test_completed_tasks_not_affected_by_recovery(self, tmp_path):
        db = tmp_path / "recover.db"

        s = TaskStore(path=db)
        task_id = s.create_task("done task")
        s.start_task(task_id)
        s.complete_task(task_id, "all good")
        s.close()

        s2 = TaskStore(path=db)
        s2.recover_interrupted()
        task = s2.get_task(task_id)
        s2.close()

        assert task["state"] == TaskState.SUCCEEDED, (
            "recover_interrupted must not touch already-completed tasks"
        )


# ---------------------------------------------------------------------------
# 5. Concurrent writes
# ---------------------------------------------------------------------------

class TestConcurrentWrites:

    def test_concurrent_step_writes_do_not_corrupt(self, store):
        """Multiple threads writing steps for the same task must all
        succeed without corrupting the database."""
        task_id = store.create_task("concurrent test")
        errors = []
        step_ids = []
        lock = threading.Lock()

        def write_step(i):
            try:
                step_id = store.create_step(task_id, f"tool_{i}", {"i": i})
                store.start_step(step_id)
                time.sleep(0.001)
                store.complete_step(step_id, result=f"result_{i}", duration_ms=i)
                with lock:
                    step_ids.append(step_id)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=write_step, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Concurrent writes raised errors: {errors}"
        steps = store.list_steps(task_id)
        assert len(steps) == 10, (
            f"Expected 10 steps; got {len(steps)}"
        )
        assert all(s["state"] == StepState.SUCCEEDED for s in steps)


# ---------------------------------------------------------------------------
# 6. Store failure isolation
# ---------------------------------------------------------------------------

class TestStoreFailureIsolation:
    """A broken task store must not prevent chat() from returning a reply."""

    def test_chat_succeeds_when_store_raises(self, monkeypatch):
        """If the task store raises on every call, chat() must still
        return a reply -- store failures are non-fatal."""
        import brain.llm as llm_module
        from brain.llm import JarvisLLM

        class BrokenStore:
            def create_task(self, *a, **kw):
                raise RuntimeError("DB is broken")
            def start_task(self, *a, **kw):
                raise RuntimeError("DB is broken")
            def complete_task(self, *a, **kw):
                raise RuntimeError("DB is broken")
            def fail_task(self, *a, **kw):
                raise RuntimeError("DB is broken")
            def create_step(self, *a, **kw):
                raise RuntimeError("DB is broken")
            def start_step(self, *a, **kw):
                raise RuntimeError("DB is broken")
            def complete_step(self, *a, **kw):
                raise RuntimeError("DB is broken")
            def fail_step(self, *a, **kw):
                raise RuntimeError("DB is broken")
            def timeout_step(self, *a, **kw):
                raise RuntimeError("DB is broken")

        jarvis = JarvisLLM.__new__(JarvisLLM)
        jarvis.confirm_callback = lambda name, args: True
        jarvis.system_prompt = "test"
        jarvis.model = "test-model"
        jarvis.memory = MagicMock()
        jarvis.memory.search.return_value = []
        jarvis.short_term = []
        jarvis._explicit_model_override = None
        jarvis._session_state = None
        jarvis._task_store = BrokenStore()
        jarvis._current_task_id = None

        def fake_chat(model, messages, tools=None, stream=False, **kwargs):
            return iter([{"message": {"content": "Hello.", "tool_calls": None}}])

        fake_client = MagicMock()
        fake_client.chat.side_effect = fake_chat
        jarvis.client = fake_client

        monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
        monkeypatch.setattr(llm_module, "recall", lambda q, k=3, **kwargs: [])
        monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3, **kwargs: [])

        result = jarvis.chat("hi there")
        assert result == "Hello.", (
            f"chat() must return a reply even when the task store is broken; "
            f"got {result!r}"
        )


# ---------------------------------------------------------------------------
# 7. Integration with JarvisLLM tool calls
# ---------------------------------------------------------------------------

class TestLLMTaskStoreIntegration:
    """Tool calls must create step records; task state must reflect outcome."""

    def test_tool_call_creates_step_record(self, tmp_path, monkeypatch):
        import brain.llm as llm_module
        from brain.llm import JarvisLLM
        from tools.tools import TOOL_FUNCTIONS

        store = TaskStore(path=tmp_path / "tasks.db")

        jarvis = JarvisLLM.__new__(JarvisLLM)
        jarvis.confirm_callback = lambda name, args: True
        jarvis.system_prompt = "test"
        jarvis.model = "test-model"
        jarvis.memory = MagicMock()
        jarvis.memory.search.return_value = []
        jarvis.short_term = []
        jarvis._explicit_model_override = None
        jarvis._session_state = None
        jarvis._task_store = store
        jarvis._current_task_id = None

        monkeypatch.setitem(TOOL_FUNCTIONS, "test_tool_xyz", lambda: "tool result")

        call_count = [0]

        def fake_chat(model, messages, tools=None, stream=False, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return iter([{
                    "message": {
                        "content": "",
                        "tool_calls": [{"function": {"name": "test_tool_xyz", "arguments": {}}}],
                    }
                }])
            return iter([{"message": {"content": "Done.", "tool_calls": None}}])

        fake_client = MagicMock()
        fake_client.chat.side_effect = fake_chat
        jarvis.client = fake_client

        monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
        monkeypatch.setattr(llm_module, "recall", lambda q, k=3, **kwargs: [])
        monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3, **kwargs: [])

        result = jarvis.chat("run test_tool_xyz", on_step=lambda m: None)

        assert result == "Done."

        # There must be exactly one task in the store.
        tasks = store.list_tasks()
        assert len(tasks) == 1
        task = tasks[0]
        assert task["state"] == TaskState.SUCCEEDED
        assert task["final_reply"] == "Done."

        # There must be exactly one step for the tool call.
        steps = store.list_steps(task["task_id"])
        assert len(steps) == 1
        step = steps[0]
        assert step["tool_name"] == "test_tool_xyz"
        assert step["state"] == StepState.SUCCEEDED
        assert step["result"] == "tool result"

        store.close()

    def test_failed_turn_marks_task_failed(self, tmp_path, monkeypatch):
        import brain.llm as llm_module
        from brain.llm import JarvisLLM

        store = TaskStore(path=tmp_path / "tasks.db")

        jarvis = JarvisLLM.__new__(JarvisLLM)
        jarvis.confirm_callback = lambda name, args: True
        jarvis.system_prompt = "test"
        jarvis.model = "test-model"
        jarvis.memory = MagicMock()
        jarvis.memory.search.return_value = []
        jarvis.short_term = []
        jarvis._explicit_model_override = None
        jarvis._session_state = None
        jarvis._task_store = store
        jarvis._current_task_id = None

        def fake_chat(model, messages, tools=None, stream=False, **kwargs):
            raise RuntimeError("Ollama is down")

        fake_client = MagicMock()
        fake_client.chat.side_effect = fake_chat
        jarvis.client = fake_client

        monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
        monkeypatch.setattr(llm_module, "recall", lambda q, k=3, **kwargs: [])
        monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3, **kwargs: [])

        with pytest.raises(RuntimeError, match="Ollama is down"):
            jarvis.chat("what time is it")

        tasks = store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["state"] == TaskState.FAILED, (
            "A turn that raises must mark the task FAILED"
        )

        store.close()

    def test_timed_out_tool_creates_timeout_step(self, tmp_path, monkeypatch):
        import brain.llm as llm_module
        from brain.llm import JarvisLLM
        from concurrent.futures import TimeoutError as FutureTimeoutError
        from tools.tools import TOOL_FUNCTIONS

        store = TaskStore(path=tmp_path / "tasks.db")

        jarvis = JarvisLLM.__new__(JarvisLLM)
        jarvis.confirm_callback = lambda name, args: True
        jarvis.system_prompt = "test"
        jarvis.model = "test-model"
        jarvis.memory = MagicMock()
        jarvis.memory.search.return_value = []
        jarvis.short_term = []
        jarvis._explicit_model_override = None
        jarvis._session_state = None
        jarvis._task_store = store
        jarvis._current_task_id = None

        monkeypatch.setitem(TOOL_FUNCTIONS, "timeout_tool_xyz", lambda: "never")

        mock_future = MagicMock()
        mock_future.result.side_effect = FutureTimeoutError()
        mock_executor = MagicMock()
        mock_executor.submit.return_value = mock_future
        monkeypatch.setattr(llm_module, "_TOOL_EXECUTOR", mock_executor)

        call_count = [0]

        def fake_chat(model, messages, tools=None, stream=False, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return iter([{
                    "message": {
                        "content": "",
                        "tool_calls": [{"function": {"name": "timeout_tool_xyz", "arguments": {}}}],
                    }
                }])
            return iter([{"message": {"content": "Handled.", "tool_calls": None}}])

        fake_client = MagicMock()
        fake_client.chat.side_effect = fake_chat
        jarvis.client = fake_client

        monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
        monkeypatch.setattr(llm_module, "recall", lambda q, k=3, **kwargs: [])
        monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3, **kwargs: [])

        jarvis.chat("run timeout_tool_xyz", on_step=lambda m: None)

        tasks = store.list_tasks()
        assert len(tasks) == 1
        steps = store.list_steps(tasks[0]["task_id"])
        assert len(steps) == 1
        assert steps[0]["state"] == StepState.TIMEOUT, (
            "A timed-out tool call must create a TIMEOUT step, not FAILED"
        )
        assert steps[0]["result"] is None, (
            "TIMEOUT step result must be NULL -- outcome is unknown"
        )

        store.close()
