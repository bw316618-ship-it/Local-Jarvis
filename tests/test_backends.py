"""
Tests for brain/backends.py -- the OpenAI-compatible backend (Atomic Chat,
llama-server, LM Studio, ...) behind JarvisLLM's client.

No real server is used: httpx.MockTransport stands in for it, so these run
without a GPU, a model, or a network.
"""

import json
import sys
from unittest.mock import MagicMock

import httpx
import pytest

from brain.backends import (
    BackendError,
    OpenAICompatClient,
    ThinkStripper,
    make_client,
    strip_think_blocks,
    to_openai_messages,
)


# --- helpers ------------------------------------------------------------

def _sse(*events) -> bytes:
    """Build a text/event-stream body. Strings are sent raw (e.g. [DONE])."""
    lines = []
    for e in events:
        data = e if isinstance(e, str) else json.dumps(e)
        lines.append(f"data: {data}\n\n")
    return "".join(lines).encode()


def _delta(**fields):
    return {"choices": [{"delta": fields}]}


def _client(handler, **kwargs):
    return OpenAICompatClient(
        base_url="http://srv/v1",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def _recording_handler(response_factory):
    """Returns (handler, seen) where seen collects every request's JSON body."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append({"url": str(request.url), "headers": request.headers, "body": body})
        return response_factory(request)

    return handler, seen


# --- <think> stripping --------------------------------------------------

def test_strip_think_blocks_removes_complete_blocks():
    assert strip_think_blocks("<think>plan it</think>\n\nHello.") == "Hello."


def test_strip_think_blocks_leaves_plain_text_alone():
    assert strip_think_blocks("Just an answer.") == "Just an answer."


def test_think_stripper_handles_tags_split_across_chunks():
    s = ThinkStripper()
    chunks = ["Hel", "lo <thi", "nk>secret thoughts</th", "ink>\n\nWorld"]
    visible = "".join(s.feed(c) for c in chunks) + s.flush()
    assert visible == "Hello World"


def test_think_stripper_drops_an_unclosed_think_block():
    s = ThinkStripper()
    visible = s.feed("Answer. <think>never finishes") + s.flush()
    assert visible == "Answer. "


def test_think_stripper_flushes_a_partial_tag_that_never_completed():
    s = ThinkStripper()
    visible = s.feed("a < b and <thi") + s.flush()
    assert visible == "a < b and <thi"


# --- message translation ------------------------------------------------

def test_tool_calls_get_ids_and_json_string_arguments():
    out = to_openai_messages(
        [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "get_time", "arguments": {"tz": "IST"}}}],
            },
        ]
    )
    call = out[1]["tool_calls"][0]
    assert call["type"] == "function"
    assert call["id"].startswith("call_")
    assert call["function"]["name"] == "get_time"
    assert json.loads(call["function"]["arguments"]) == {"tz": "IST"}


def test_tool_results_are_matched_to_call_ids_in_order():
    out = to_openai_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_x", "function": {"name": "a", "arguments": {}}},
                    {"function": {"name": "b", "arguments": {}}},
                ],
            },
            # Jarvis appends tool results with no id at all.
            {"role": "tool", "content": "result a"},
            {"role": "tool", "content": "result b"},
        ]
    )
    ids = [c["id"] for c in out[0]["tool_calls"]]
    assert out[1]["tool_call_id"] == ids[0] == "call_x"
    assert out[2]["tool_call_id"] == ids[1]
    assert out[1]["content"] == "result a"


def test_plain_messages_pass_through():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert to_openai_messages(msgs) == msgs


# --- non-streaming ------------------------------------------------------

def test_non_streaming_returns_ollama_shaped_message():
    handler, seen = _recording_handler(
        lambda r: httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "<think>x</think>\nNo plan needed."}}]},
        )
    )
    client = _client(handler)

    resp = client.chat(model="m", messages=[{"role": "user", "content": "hi"}])

    assert resp["message"]["content"] == "No plan needed."
    assert "tool_calls" not in resp["message"]
    assert seen[0]["url"] == "http://srv/v1/chat/completions"
    assert seen[0]["body"]["stream"] is False


def test_non_streaming_parses_tool_call_arguments_into_a_dict():
    handler, _ = _recording_handler(
        lambda r: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "get_weather", "arguments": '{"city": "Delhi"}'},
                                }
                            ],
                        }
                    }
                ]
            },
        )
    )
    resp = _client(handler).chat(model="m", messages=[])

    call = resp["message"]["tool_calls"][0]
    assert call["function"]["name"] == "get_weather"
    assert call["function"]["arguments"] == {"city": "Delhi"}


def test_options_are_mapped_and_num_ctx_is_dropped():
    handler, seen = _recording_handler(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    )
    _client(handler).chat(
        model="m",
        messages=[],
        options={"num_ctx": 8192, "temperature": 0.2, "top_p": 0.9, "num_predict": 64},
    )
    body = seen[0]["body"]
    assert body["temperature"] == 0.2
    assert body["top_p"] == 0.9
    assert body["max_tokens"] == 64
    assert "num_ctx" not in body
    assert "options" not in body


def test_tools_are_forwarded_only_when_given_and_api_key_is_sent():
    handler, seen = _recording_handler(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    )
    client = _client(handler, api_key="secret")
    schema = [{"type": "function", "function": {"name": "t", "description": "", "parameters": {}}}]

    client.chat(model="m", messages=[], tools=schema)
    client.chat(model="m", messages=[], tools=None)

    assert seen[0]["body"]["tools"] == schema
    assert "tools" not in seen[1]["body"]
    assert seen[0]["headers"]["authorization"] == "Bearer secret"


def test_unparseable_tool_arguments_never_become_an_empty_call():
    handler, _ = _recording_handler(
        lambda r: httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"tool_calls": [{"function": {"name": "t", "arguments": "{not json"}}]}}
                ]
            },
        )
    )
    args = _client(handler).chat(model="m", messages=[])["message"]["tool_calls"][0]["function"]["arguments"]
    # A key no tool accepts, so func(**args) fails loudly instead of running
    # with defaults the model never chose.
    assert args == {"_invalid_arguments": "{not json"}


# --- streaming ----------------------------------------------------------

def test_streaming_yields_content_deltas():
    handler, seen = _recording_handler(
        lambda r: httpx.Response(
            200,
            content=_sse(_delta(content="Good "), _delta(content="morning."), "[DONE]"),
        )
    )
    chunks = list(_client(handler).chat(model="m", messages=[], stream=True))

    assert [c["message"]["content"] for c in chunks] == ["Good ", "morning."]
    assert all("tool_calls" not in c["message"] for c in chunks)
    assert seen[0]["body"]["stream"] is True


def test_streaming_reassembles_fragmented_tool_calls():
    handler, _ = _recording_handler(
        lambda r: httpx.Response(
            200,
            content=_sse(
                _delta(content="Checking. "),
                _delta(tool_calls=[{"index": 0, "id": "call_a", "function": {"name": "get_weather", "arguments": ""}}]),
                _delta(tool_calls=[{"index": 0, "function": {"arguments": '{"city": "Del'}}]),
                _delta(tool_calls=[{"index": 0, "function": {"arguments": 'hi"}'}}]),
                _delta(tool_calls=[{"index": 1, "id": "call_b", "function": {"name": "get_time", "arguments": "{}"}}]),
                "[DONE]",
            ),
        )
    )
    chunks = list(_client(handler).chat(model="m", messages=[], stream=True))

    assert chunks[0]["message"]["content"] == "Checking. "
    calls = chunks[-1]["message"]["tool_calls"]
    assert [c["function"]["name"] for c in calls] == ["get_weather", "get_time"]
    assert calls[0]["function"]["arguments"] == {"city": "Delhi"}
    assert calls[1]["function"]["arguments"] == {}
    assert calls[0]["id"] == "call_a"


def test_streaming_never_emits_think_blocks_or_reasoning_content():
    handler, _ = _recording_handler(
        lambda r: httpx.Response(
            200,
            content=_sse(
                _delta(reasoning_content="hmm, let me think"),
                _delta(content="<think>plan"),
                _delta(content=" more</think>\n\nIt is 4 pm."),
                "[DONE]",
            ),
        )
    )
    chunks = list(_client(handler).chat(model="m", messages=[], stream=True))
    assert "".join(c["message"]["content"] for c in chunks) == "It is 4 pm."


def test_streaming_ignores_keepalive_comments_and_malformed_events():
    body = b": keep-alive\n\ndata: {oops\n\n" + _sse(_delta(content="fine"), "[DONE]")
    handler, _ = _recording_handler(lambda r: httpx.Response(200, content=body))
    chunks = list(_client(handler).chat(model="m", messages=[], stream=True))
    assert [c["message"]["content"] for c in chunks] == ["fine"]


# --- errors -------------------------------------------------------------

def test_unreachable_server_raises_a_clear_error_non_streaming():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(BackendError, match="http://srv/v1"):
        _client(handler).chat(model="m", messages=[])


def test_unreachable_server_raises_a_clear_error_streaming():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    stream = _client(handler).chat(model="m", messages=[], stream=True)
    with pytest.raises(BackendError, match="Is it running"):
        next(stream)


def test_http_errors_surface_status_and_body():
    handler, _ = _recording_handler(lambda r: httpx.Response(500, text="model not loaded"))
    with pytest.raises(BackendError, match="HTTP 500.*model not loaded"):
        _client(handler).chat(model="m", messages=[])

    stream = _client(handler).chat(model="m", messages=[], stream=True)
    with pytest.raises(BackendError, match="HTTP 500"):
        next(stream)


# --- model discovery ----------------------------------------------------

def test_list_models_and_is_available():
    handler, seen = _recording_handler(
        lambda r: httpx.Response(200, json={"data": [{"id": "qwen3-8b"}, {"id": "gemma-4"}]})
    )
    client = _client(handler)
    assert client.list_models() == ["qwen3-8b", "gemma-4"]
    assert client.is_available() is True
    assert seen[0]["url"] == "http://srv/v1/models"


def test_is_available_is_false_when_server_is_down():
    def handler(request):
        raise httpx.ConnectError("refused")

    assert _client(handler).is_available() is False


# --- factory / config ---------------------------------------------------

def test_make_client_defaults_to_ollama(monkeypatch):
    fake_cls = MagicMock()
    monkeypatch.setattr(sys.modules["ollama"], "Client", fake_cls, raising=False)

    client = make_client({})

    fake_cls.assert_called_once_with(host="http://localhost:11434")
    assert client is fake_cls.return_value


def test_make_client_honours_a_custom_ollama_host(monkeypatch):
    fake_cls = MagicMock()
    monkeypatch.setattr(sys.modules["ollama"], "Client", fake_cls, raising=False)

    make_client({"llm_backend": "ollama", "ollama_host": "http://gpu-box:11434"})

    fake_cls.assert_called_once_with(host="http://gpu-box:11434")


def test_make_client_builds_the_openai_backend_from_config():
    client = make_client(
        {
            "llm_backend": "OpenAI",
            "openai_base_url": "http://localhost:1337/v1/",
            "openai_api_key": "k",
            "llm_request_timeout_seconds": 30,
        }
    )
    assert isinstance(client, OpenAICompatClient)
    assert client.base_url == "http://localhost:1337/v1"


def test_make_client_rejects_unknown_backends():
    with pytest.raises(ValueError, match="llm_backend"):
        make_client({"llm_backend": "carrier-pigeon"})


def test_config_defaults_keep_ollama_as_the_backend():
    import config

    assert config.DEFAULTS["llm_backend"] == "ollama"
    assert config.DEFAULTS["openai_base_url"] == "http://localhost:1337/v1"


def test_jarvisllm_uses_the_configured_backend(monkeypatch):
    from brain.llm import JarvisLLM
    from config import CONFIG

    monkeypatch.setitem(CONFIG, "llm_backend", "openai")
    jarvis = JarvisLLM(model="some-model")
    assert isinstance(jarvis.client, OpenAICompatClient)


# --- end to end through JarvisLLM's own streaming code -------------------

def test_tool_call_round_trip_through_jarvisllm_stream_round():
    """The exact loop JarvisLLM.chat() runs: stream a tool call, append the
    assistant turn and an id-less tool result, stream again. The second
    request must carry matching ids and a JSON-string argument payload."""
    from brain.llm import JarvisLLM

    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                200,
                content=_sse(
                    _delta(tool_calls=[{"index": 0, "id": "call_7", "function": {"name": "get_time", "arguments": '{"tz": "IST"}'}}]),
                    "[DONE]",
                ),
            )
        return httpx.Response(200, content=_sse(_delta(content="It is 4 pm."), "[DONE]"))

    jarvis = JarvisLLM.__new__(JarvisLLM)
    jarvis.client = _client(handler)
    jarvis.model = "m"

    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "time?"}]
    tokens, sentences = [], []

    content, tool_calls = jarvis._stream_round(messages, [{"type": "function", "function": {"name": "get_time"}}])
    assert content == "" and tool_calls[0]["function"]["arguments"] == {"tz": "IST"}

    messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
    messages.append({"role": "tool", "content": "16:00"})

    content, tool_calls = jarvis._stream_round(
        messages, None, on_token=tokens.append, on_sentence=sentences.append
    )

    assert content == "It is 4 pm." and tool_calls is None
    assert sentences == ["It is 4 pm."]

    second = requests[1]["messages"]
    assert second[2]["tool_calls"][0]["id"] == "call_7"
    assert json.loads(second[2]["tool_calls"][0]["function"]["arguments"]) == {"tz": "IST"}
    assert second[3] == {"role": "tool", "tool_call_id": "call_7", "content": "16:00"}
    assert "tools" not in requests[1]


def test_make_plan_works_over_the_openai_backend():
    from brain.llm import JarvisLLM

    handler, _ = _recording_handler(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "<think>hm</think>No plan needed."}}]})
    )
    jarvis = JarvisLLM.__new__(JarvisLLM)
    jarvis.client = _client(handler)
    jarvis.model = "m"

    assert jarvis._make_plan("what time is it") == "No plan needed."
