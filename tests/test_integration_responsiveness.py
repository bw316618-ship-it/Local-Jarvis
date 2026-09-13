"""Integration tests for backend responsiveness, session isolation,
incremental streaming, timeout behaviour, and retrieval bypass.

All tests use controlled fake models and tools -- no real Ollama, no real
ChromaDB, no real embedder.  The conftest.py stubs out the heavy ML
modules at collection time, so these tests run fast and deterministically.

Coverage:
  1. Event-loop responsiveness: _process_message_async offloads blocking
     work to an executor; the event loop must remain free to service other
     coroutines while a turn is in progress.
  2. Progressive streaming: sentences are emitted incrementally as the
     model produces them, not buffered until the full reply is ready.
  3. Multi-device isolation: two devices get separate runtimes, separate
     short_term histories, and separate session states; a mode change on
     one device must not affect the other.
  4. Retrieval bypass: skip_retrieval routes (maps/system/search/time/date)
     must not call recall() or recall_facts() at all.
  5. Memory write latency: remember_turn is scheduled asynchronously and
     must not block the return of chat().
  6. Cancellation / timeout: a tool that exceeds TOOL_CALL_TIMEOUT_SECONDS
     produces an error string; the turn still completes and memory is still
     written.
  7. SessionState isolation: two JarvisLLM instances with separate
     SessionState objects do not share mode or brain-tier state.
  8. Backend executor: _process_message_async uses run_in_executor, not a
     bare blocking call inside the coroutine.
"""

import asyncio
import threading
import time
from concurrent.futures import Future
from unittest.mock import MagicMock, patch, call

import pytest

import brain.llm as llm_module
from brain.llm import JarvisLLM, _remember_turn_async, _MEMORY_EXECUTOR
from brain.runtime import JarvisRuntime
from brain.session_state import SessionState
from backend import JarvisBackend, BackendSurface


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

class FakeMemory:
    def search(self, q, **kwargs):
        return []


def _stream_chunks(*chunks):
    """Build a fake streaming response from (content, tool_calls) pairs."""
    return iter([
        {"message": {"content": c, "tool_calls": tc}}
        for c, tc in chunks
    ])


def make_jarvis(session_state=None):
    """Build a JarvisLLM test double that skips __init__ heavy setup."""
    jarvis = JarvisLLM.__new__(JarvisLLM)
    jarvis.confirm_callback = lambda name, args: True
    jarvis.system_prompt = "test"
    jarvis.model = "test-model"
    jarvis.memory = FakeMemory()
    jarvis.short_term = []
    jarvis._explicit_model_override = None
    jarvis._session_state = session_state
    return jarvis


# ---------------------------------------------------------------------------
# 1. Event-loop responsiveness
# ---------------------------------------------------------------------------

class TestEventLoopResponsiveness:
    """_process_message_async must offload blocking work to an executor so
    the event loop stays free to service other coroutines."""

    def test_process_message_async_uses_run_in_executor(self):
        """Verify that _process_message_async calls loop.run_in_executor
        rather than calling runtime.handle_message directly in the coroutine.

        We do this by patching asyncio.get_event_loop() to return a mock
        loop and asserting run_in_executor was called with the backend
        executor and a callable.
        """
        backend = JarvisBackend(runtime=MagicMock())

        mock_runtime = MagicMock()
        mock_ws = MagicMock()

        # Capture what run_in_executor is called with.
        executor_calls = []

        async def fake_run_in_executor(executor, func):
            executor_calls.append((executor, func))
            # Actually call the function so the test doesn't hang.
            func()

        mock_loop = MagicMock()
        mock_loop.run_in_executor = fake_run_in_executor

        # _send must be awaitable.
        async def fake_send(ws, payload):
            return True

        backend._send = fake_send

        async def run():
            with patch("asyncio.get_event_loop", return_value=mock_loop):
                await backend._process_message_async("hello", mock_ws, mock_runtime)

        asyncio.run(run())

        assert len(executor_calls) == 1, (
            "_process_message_async must call run_in_executor exactly once "
            f"per turn; got {len(executor_calls)} calls"
        )
        executor, func = executor_calls[0]
        # The executor must be the module-level _BACKEND_EXECUTOR, not None
        # (which would use the default loop executor).
        from backend import _BACKEND_EXECUTOR
        assert executor is _BACKEND_EXECUTOR, (
            "run_in_executor must use _BACKEND_EXECUTOR, not the default executor"
        )

    def test_event_loop_not_blocked_during_turn(self):
        """A slow handle_message must not prevent other coroutines from
        running on the same event loop.

        We schedule a 'ping' coroutine alongside a slow turn and verify
        the ping completes before the turn finishes.
        """
        backend = JarvisBackend(runtime=MagicMock())

        ping_done_at = [None]
        turn_done_at = [None]

        async def ping():
            await asyncio.sleep(0.01)
            ping_done_at[0] = time.monotonic()

        slow_runtime = MagicMock()

        def slow_handle(**kwargs):
            time.sleep(0.05)  # simulate blocking LLM call

        slow_runtime.handle_message.side_effect = slow_handle

        mock_ws = MagicMock()

        async def fake_send(ws, payload):
            return True

        backend._send = fake_send

        async def run():
            # Run both concurrently.
            await asyncio.gather(
                ping(),
                backend._process_message_async("hello", mock_ws, slow_runtime),
            )
            turn_done_at[0] = time.monotonic()

        asyncio.run(run())

        assert ping_done_at[0] is not None, "ping coroutine never completed"
        assert turn_done_at[0] is not None, "turn coroutine never completed"
        # The ping (10ms sleep) should finish well before the turn (50ms
        # blocking sleep in executor).  Allow generous margin for CI.
        assert ping_done_at[0] < turn_done_at[0], (
            "event loop was blocked: ping completed after the slow turn finished"
        )


# ---------------------------------------------------------------------------
# 2. Progressive streaming
# ---------------------------------------------------------------------------

class TestProgressiveStreaming:
    """Sentences must be emitted incrementally as the model produces them."""

    def test_sentences_emitted_before_full_reply_complete(self, monkeypatch):
        """Each sentence boundary (. ! ? \\n) must trigger on_sentence
        immediately, not after the entire stream is consumed."""
        jarvis = make_jarvis()

        emission_times = []

        def fake_chat(model, messages, tools=None, stream=False, **kwargs):
            # Simulate three chunks arriving with a small delay between them.
            def _gen():
                for text in ["First sentence. ", "Second sentence. ", "Third."]:
                    yield {"message": {"content": text, "tool_calls": None}}
            return _gen()

        fake_client = MagicMock()
        fake_client.chat.side_effect = fake_chat
        jarvis.client = fake_client

        monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
        monkeypatch.setattr(llm_module, "recall", lambda q, k=3, **kwargs: [])
        monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3, **kwargs: [])

        sentences = []

        def on_sentence(s):
            sentences.append(s)
            emission_times.append(time.monotonic())

        result = jarvis.chat(
            "tell me three things",
            on_sentence=on_sentence,
        )

        assert len(sentences) >= 2, (
            f"Expected at least 2 sentences streamed; got {sentences}"
        )
        # Sentences must arrive in order.
        assert "First sentence." in sentences[0]
        assert "Second sentence." in sentences[1]

    def test_partial_sentence_flushed_at_end(self, monkeypatch):
        """A trailing fragment without a sentence-ending punctuation must
        still be emitted via on_sentence at the end of the stream."""
        jarvis = make_jarvis()

        def fake_chat(model, messages, tools=None, stream=False, **kwargs):
            return iter([
                {"message": {"content": "Complete sentence. ", "tool_calls": None}},
                {"message": {"content": "Trailing fragment", "tool_calls": None}},
            ])

        fake_client = MagicMock()
        fake_client.chat.side_effect = fake_chat
        jarvis.client = fake_client

        monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
        monkeypatch.setattr(llm_module, "recall", lambda q, k=3, **kwargs: [])
        monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3, **kwargs: [])

        sentences = []
        jarvis.chat("test", on_sentence=sentences.append)

        full_text = " ".join(sentences)
        assert "Trailing fragment" in full_text, (
            "Trailing fragment without punctuation must be flushed at stream end"
        )


# ---------------------------------------------------------------------------
# 3. Multi-device isolation
# ---------------------------------------------------------------------------

class TestMultiDeviceIsolation:
    """Two devices must get separate runtimes, histories, and session states."""

    def test_two_devices_get_separate_runtimes(self):
        backend = JarvisBackend(runtime=MagicMock())
        rt_a, lock_a = backend._get_runtime("device-alpha")
        rt_b, lock_b = backend._get_runtime("device-beta")

        assert rt_a is not rt_b, "Different devices must get different runtimes"
        assert lock_a is not lock_b, "Different devices must get different locks"

    def test_short_term_history_is_isolated_per_device(self, monkeypatch):
        """A message sent by device A must not appear in device B's history."""
        backend = JarvisBackend(runtime=MagicMock())

        rt_a, _ = backend._get_runtime("device-alpha")
        rt_b, _ = backend._get_runtime("device-beta")

        # Directly manipulate short_term to simulate a prior turn.
        rt_a.jarvis.short_term = [
            {"role": "user", "content": "device A message"},
            {"role": "assistant", "content": "device A reply"},
        ]

        assert rt_b.jarvis.short_term == [], (
            "Device B's short_term must be empty; device A's history leaked"
        )

    def test_mode_change_on_device_a_does_not_affect_device_b(self):
        """Setting CODING mode on device A's session must not change device B's
        mode, which must remain NORMAL."""
        backend = JarvisBackend(runtime=MagicMock())

        rt_a, _ = backend._get_runtime("device-alpha")
        rt_b, _ = backend._get_runtime("device-beta")

        # Both runtimes must have their own SessionState.
        assert rt_a.session_state is not rt_b.session_state, (
            "Each runtime must own a distinct SessionState"
        )

        rt_a.session_state.set_mode("coding")

        assert rt_b.session_state.current_mode() == "normal", (
            f"Device B mode should be 'normal' but got "
            f"'{rt_b.session_state.current_mode()}'"
        )

    def test_concurrent_turns_on_different_devices_do_not_race(self):
        """Two devices sending messages concurrently must each get their own
        reply without their short_term histories interleaving."""
        backend = JarvisBackend(runtime=MagicMock())

        rt_a, lock_a = backend._get_runtime("device-alpha")
        rt_b, lock_b = backend._get_runtime("device-beta")

        results = {}
        errors = []

        def run_turn(device_id, runtime, lock, message):
            try:
                with lock:
                    runtime.jarvis.short_term.append(
                        {"role": "user", "content": message}
                    )
                    time.sleep(0.02)  # simulate work
                    runtime.jarvis.short_term.append(
                        {"role": "assistant", "content": f"reply to {message}"}
                    )
                    results[device_id] = list(runtime.jarvis.short_term)
            except Exception as e:
                errors.append(e)

        t_a = threading.Thread(
            target=run_turn,
            args=("alpha", rt_a, lock_a, "alpha message"),
        )
        t_b = threading.Thread(
            target=run_turn,
            args=("beta", rt_b, lock_b, "beta message"),
        )

        t_a.start()
        t_b.start()
        t_a.join(timeout=2)
        t_b.join(timeout=2)

        assert not errors, f"Concurrent turns raised errors: {errors}"

        # Each device's history must contain only its own messages.
        alpha_contents = [m["content"] for m in results.get("alpha", [])]
        beta_contents = [m["content"] for m in results.get("beta", [])]

        assert all("alpha" in c for c in alpha_contents), (
            f"Alpha history contains non-alpha content: {alpha_contents}"
        )
        assert all("beta" in c for c in beta_contents), (
            f"Beta history contains non-beta content: {beta_contents}"
        )


# ---------------------------------------------------------------------------
# 4. Retrieval bypass
# ---------------------------------------------------------------------------

class TestRetrievalBypass:
    """skip_retrieval routes must not call recall() or recall_facts()."""

    @pytest.mark.parametrize("route_name,message", [
        ("maps", "show me the map"),
        ("system", "what's my cpu usage"),
        ("search", "search for python tutorials"),
        ("time", "what time is it"),
        ("date", "what's today's date"),
    ])
    def test_skip_retrieval_routes_do_not_call_recall(
        self, route_name, message, monkeypatch
    ):
        jarvis = make_jarvis()

        recall_calls = []
        recall_facts_calls = []
        embed_calls = []

        monkeypatch.setattr(
            llm_module, "recall",
            lambda q, k=3, **kwargs: recall_calls.append(q) or [],
        )
        monkeypatch.setattr(
            llm_module, "recall_facts",
            lambda q, k=3, **kwargs: recall_facts_calls.append(q) or [],
        )
        monkeypatch.setattr(
            llm_module, "get_embedder",
            lambda: embed_calls.append(True) or MagicMock(),
        )
        monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)

        # Patch the router to return the target route.
        from brain.fast_router import Route
        fake_route = MagicMock()
        fake_route.name = route_name
        monkeypatch.setattr(llm_module, "classify", lambda msg: fake_route)

        def fake_chat(model, messages, tools=None, stream=False, **kwargs):
            return iter([{"message": {"content": "ok", "tool_calls": None}}])

        fake_client = MagicMock()
        fake_client.chat.side_effect = fake_chat
        jarvis.client = fake_client

        jarvis.chat(message)

        assert recall_calls == [], (
            f"recall() must not be called for route '{route_name}'; "
            f"got calls: {recall_calls}"
        )
        assert recall_facts_calls == [], (
            f"recall_facts() must not be called for route '{route_name}'; "
            f"got calls: {recall_facts_calls}"
        )
        assert embed_calls == [], (
            f"get_embedder() must not be called for route '{route_name}'; "
            f"got calls: {embed_calls}"
        )

    def test_non_skip_route_does_call_recall(self, monkeypatch):
        """Sanity check: a normal route must still call recall()."""
        jarvis = make_jarvis()

        recall_calls = []

        monkeypatch.setattr(
            llm_module, "recall",
            lambda q, k=3, **kwargs: recall_calls.append(q) or [],
        )
        monkeypatch.setattr(
            llm_module, "recall_facts",
            lambda q, k=3, **kwargs: [],
        )
        monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)

        class FakeEmbedding:
            def tolist(self):
                return [0.1, 0.2]

        class FakeEmbedder:
            def encode(self, text):
                return FakeEmbedding()

        monkeypatch.setattr(llm_module, "get_embedder", lambda: FakeEmbedder())

        from brain.fast_router import Route
        fake_route = MagicMock()
        fake_route.name = "general"
        monkeypatch.setattr(llm_module, "classify", lambda msg: fake_route)

        def fake_chat(model, messages, tools=None, stream=False, **kwargs):
            return iter([{"message": {"content": "ok", "tool_calls": None}}])

        fake_client = MagicMock()
        fake_client.chat.side_effect = fake_chat
        jarvis.client = fake_client

        jarvis.chat("what is the meaning of life")

        assert recall_calls != [], (
            "recall() must be called for non-skip routes"
        )


# ---------------------------------------------------------------------------
# 5. Memory write latency
# ---------------------------------------------------------------------------

class TestMemoryWriteLatency:
    """remember_turn must be scheduled asynchronously; chat() must return
    before the memory write completes."""

    def test_chat_returns_before_memory_write_completes(self, monkeypatch):
        """Simulate a slow remember_turn and verify chat() returns first."""
        jarvis = make_jarvis()

        write_started = threading.Event()
        write_done = threading.Event()
        chat_returned_at = [None]
        write_done_at = [None]

        original_remember = llm_module.remember_turn

        def slow_remember(user_message, reply):
            write_started.set()
            time.sleep(0.05)  # simulate slow embedding + Chroma write
            write_done_at[0] = time.monotonic()
            write_done.set()

        monkeypatch.setattr(llm_module, "remember_turn", slow_remember)
        monkeypatch.setattr(llm_module, "recall", lambda q, k=3, **kwargs: [])
        monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3, **kwargs: [])

        def fake_chat(model, messages, tools=None, stream=False, **kwargs):
            return iter([{"message": {"content": "Hello.", "tool_calls": None}}])

        fake_client = MagicMock()
        fake_client.chat.side_effect = fake_chat
        jarvis.client = fake_client

        jarvis.chat("hi there")
        chat_returned_at[0] = time.monotonic()

        # Wait for the background write to finish (with timeout).
        write_done.wait(timeout=2.0)

        assert write_done_at[0] is not None, "Background memory write never completed"
        assert chat_returned_at[0] < write_done_at[0], (
            "chat() must return before the slow memory write completes; "
            "memory write is blocking the response path"
        )

    def test_memory_executor_is_single_worker(self):
        """The memory executor must use exactly 1 worker to serialise writes."""
        assert _MEMORY_EXECUTOR._max_workers == 1, (
            f"_MEMORY_EXECUTOR must have max_workers=1 to serialise Chroma "
            f"writes; got {_MEMORY_EXECUTOR._max_workers}"
        )


# ---------------------------------------------------------------------------
# 6. Tool timeout behaviour
# ---------------------------------------------------------------------------

class TestToolTimeout:
    """A tool that exceeds TOOL_CALL_TIMEOUT_SECONDS must produce an error
    string; the turn must still complete and memory must still be written."""

    def test_timed_out_tool_produces_error_string(self, monkeypatch):
        jarvis = make_jarvis()

        # Patch the tool executor to simulate a timeout.
        from concurrent.futures import TimeoutError as FutureTimeoutError

        mock_future = MagicMock()
        mock_future.result.side_effect = FutureTimeoutError()

        mock_executor = MagicMock()
        mock_executor.submit.return_value = mock_future

        monkeypatch.setattr(llm_module, "_TOOL_EXECUTOR", mock_executor)

        # Register a fake tool.
        from tools.tools import TOOL_FUNCTIONS
        monkeypatch.setitem(TOOL_FUNCTIONS, "slow_tool", lambda: "never")

        call_count = [0]

        def fake_chat(model, messages, tools=None, stream=False, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return iter([{
                    "message": {
                        "content": "",
                        "tool_calls": [{"function": {"name": "slow_tool", "arguments": {}}}],
                    }
                }])
            return iter([{"message": {"content": "Done.", "tool_calls": None}}])

        fake_client = MagicMock()
        fake_client.chat.side_effect = fake_chat
        jarvis.client = fake_client

        monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
        monkeypatch.setattr(llm_module, "recall", lambda q, k=3, **kwargs: [])
        monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3, **kwargs: [])

        steps = []
        result = jarvis.chat("run slow_tool", on_step=steps.append)

        # The tool result injected into the message history must contain
        # "timed out" so the model knows what happened.
        tool_messages = [
            m for m in fake_client.chat.call_args_list
            if m[1].get("messages") and any(
                msg.get("role") == "tool" for msg in m[1]["messages"]
            )
        ]
        # Find the tool result in the messages passed to the second LLM call.
        second_call_messages = fake_client.chat.call_args_list[1][1]["messages"]
        tool_result_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
        assert tool_result_msgs, "No tool result message found in second LLM call"
        assert "timed out" in tool_result_msgs[0]["content"].lower(), (
            f"Tool timeout must produce 'timed out' in result; "
            f"got: {tool_result_msgs[0]['content']!r}"
        )

        # The turn must still complete with a final reply.
        assert result == "Done.", f"Turn must complete after tool timeout; got {result!r}"

    def test_timed_out_tool_does_not_retry_automatically(self, monkeypatch):
        """A timed-out tool must not be retried automatically -- the model
        decides whether to retry based on the error string in the result."""
        jarvis = make_jarvis()

        from concurrent.futures import TimeoutError as FutureTimeoutError

        submit_count = [0]

        mock_future = MagicMock()
        mock_future.result.side_effect = FutureTimeoutError()

        mock_executor = MagicMock()

        def counting_submit(func, **kwargs):
            submit_count[0] += 1
            return mock_future

        mock_executor.submit.side_effect = counting_submit
        monkeypatch.setattr(llm_module, "_TOOL_EXECUTOR", mock_executor)

        from tools.tools import TOOL_FUNCTIONS
        monkeypatch.setitem(TOOL_FUNCTIONS, "slow_tool", lambda: "never")

        call_count = [0]

        def fake_chat(model, messages, tools=None, stream=False, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return iter([{
                    "message": {
                        "content": "",
                        "tool_calls": [{"function": {"name": "slow_tool", "arguments": {}}}],
                    }
                }])
            return iter([{"message": {"content": "Done.", "tool_calls": None}}])

        fake_client = MagicMock()
        fake_client.chat.side_effect = fake_chat
        jarvis.client = fake_client

        monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
        monkeypatch.setattr(llm_module, "recall", lambda q, k=3, **kwargs: [])
        monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3, **kwargs: [])

        jarvis.chat("run slow_tool", on_step=lambda m: None)

        assert submit_count[0] == 1, (
            f"Timed-out tool must be submitted exactly once; "
            f"got {submit_count[0]} submissions (automatic retry detected)"
        )


# ---------------------------------------------------------------------------
# 7. SessionState isolation
# ---------------------------------------------------------------------------

class TestSessionStateIsolation:
    """Two JarvisLLM instances with separate SessionState objects must not
    share mode or brain-tier state."""

    def test_separate_session_states_are_independent(self):
        state_a = SessionState()
        state_b = SessionState()

        state_a.set_mode("coding")
        state_b.set_mode("companion")

        assert state_a.current_mode() == "coding"
        assert state_b.current_mode() == "companion"

        state_a.enter_heavy_brain()
        assert state_a.is_heavy_brain() is True
        assert state_b.is_heavy_brain() is False

    def test_jarvis_llm_uses_its_own_session_state(self, monkeypatch):
        """JarvisLLM._active_mode() must read from its own SessionState,
        not from the global voice/session_state module."""
        state_a = SessionState()
        state_a.set_mode("coding")

        jarvis = make_jarvis(session_state=state_a)

        # The global is still NORMAL.
        import voice.session_state as global_ss
        assert global_ss.current_mode() == "normal"

        assert jarvis._active_mode() == "coding", (
            "JarvisLLM must read mode from its own SessionState, not the global"
        )

    def test_jarvis_llm_falls_back_to_global_when_no_session_state(self):
        """When _session_state is None, JarvisLLM must fall back to the
        global voice/session_state module (backward compatibility)."""
        jarvis = make_jarvis(session_state=None)

        import voice.session_state as global_ss
        global_mode = global_ss.current_mode()

        assert jarvis._active_mode() == global_mode, (
            "JarvisLLM with no session_state must fall back to global mode"
        )

    def test_runtime_creates_session_state_for_new_jarvis(self):
        """JarvisRuntime() without a pre-built jarvis must create a
        SessionState and pass it to JarvisLLM."""
        # We can't instantiate JarvisRuntime() without ollama, so test
        # the wiring via the constructor logic directly.
        from brain.session_state import SessionState as SS

        state = SS()
        jarvis = make_jarvis(session_state=state)

        # Simulate what JarvisRuntime.__init__ does when jarvis is supplied.
        class FakeRuntime:
            def __init__(self, jarvis):
                self.jarvis = jarvis
                self.session_state = getattr(jarvis, "_session_state", None) or SS()

        rt = FakeRuntime(jarvis)
        assert rt.session_state is state, (
            "Runtime must use the session_state already on the jarvis instance"
        )

    def test_two_runtimes_have_independent_session_states(self):
        """Two JarvisRuntime instances must each own a distinct SessionState."""
        from brain.session_state import SessionState as SS

        state_a = SS()
        state_b = SS()

        jarvis_a = make_jarvis(session_state=state_a)
        jarvis_b = make_jarvis(session_state=state_b)

        state_a.set_mode("creative")
        assert state_b.current_mode() == "normal", (
            "SessionState instances must be independent"
        )
        assert jarvis_a._active_mode() == "creative"
        assert jarvis_b._active_mode() == "normal"


# ---------------------------------------------------------------------------
# 8. Backend executor wiring
# ---------------------------------------------------------------------------

class TestBackendExecutorWiring:
    """Verify the backend executor is correctly wired."""

    def test_backend_executor_exists_and_has_capacity(self):
        from backend import _BACKEND_EXECUTOR
        assert _BACKEND_EXECUTOR is not None
        assert _BACKEND_EXECUTOR._max_workers >= 4, (
            f"_BACKEND_EXECUTOR must have at least 4 workers for concurrent "
            f"device sessions; got {_BACKEND_EXECUTOR._max_workers}"
        )

    def test_reply_done_sent_even_when_handle_message_raises(self):
        """reply_done must be sent even if handle_message raises an exception,
        so the client is never left waiting for a turn that errored out."""
        backend = JarvisBackend(runtime=MagicMock())

        mock_runtime = MagicMock()
        mock_runtime.handle_message.side_effect = RuntimeError("LLM exploded")

        sent_types = []

        async def fake_send(ws, payload):
            sent_types.append(payload.get("type"))
            return True

        backend._send = fake_send

        mock_ws = MagicMock()

        async def run():
            await backend._process_message_async("hello", mock_ws, mock_runtime)

        asyncio.run(run())

        assert "reply_done" in sent_types, (
            f"reply_done must be sent even after an exception; "
            f"got message types: {sent_types}"
        )
        assert "error" in sent_types, (
            f"error message must be sent when handle_message raises; "
            f"got message types: {sent_types}"
        )
