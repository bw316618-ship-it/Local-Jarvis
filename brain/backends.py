"""
LLM backends for Jarvis.

JarvisLLM talks to its model through ``client.chat(model, messages, tools,
stream, options)`` and reads Ollama-shaped results (``chunk["message"]
["content"]``, ``message["tool_calls"][i]["function"]["name" | "arguments"]``).

This module keeps that contract and lets the thing behind it vary:

  * "ollama"  -- the stock ``ollama.Client`` (default; behaviour unchanged).
  * "openai"  -- any OpenAI-compatible server: Atomic Chat
                 (http://localhost:1337/v1), llama.cpp's ``llama-server``,
                 LM Studio, vLLM, ...  ``OpenAICompatClient`` translates in
                 both directions so nothing above this layer has to know.

Things the translation has to get right, because Jarvis is a voice
assistant with a tool loop:

  * Tool-call arguments are a *dict* on the Ollama side and a *JSON string*
    on the OpenAI side; OpenAI also wants call ids, and ``tool`` messages
    must reference them.  Jarvis appends ``{"role": "tool", "content": ...}``
    with no id, so ids are assigned here and matched back up in order.
  * Streamed tool calls arrive as fragments (name first, arguments in
    pieces, keyed by index) and are reassembled before Jarvis sees them.
  * Reasoning models (Qwen3) may emit ``<think>...</think>`` inline in the
    content.  Jarvis speaks content sentence by sentence, so those blocks
    are removed here, including when a tag is split across stream chunks.
  * ``num_ctx`` has no per-request equivalent on OpenAI-style servers: the
    context window is fixed when the model is loaded.  It is ignored here,
    not faked.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Iterator, Optional

import httpx

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

# Ollama option name -> OpenAI request field.  Anything not listed (notably
# num_ctx) is dropped on purpose; see the module docstring.
_OPTION_MAP = {
    "temperature": "temperature",
    "top_p": "top_p",
    "num_predict": "max_tokens",
    "seed": "seed",
    "stop": "stop",
}


class BackendError(RuntimeError):
    """The LLM server was unreachable or returned an error."""


# ---------------------------------------------------------------------------
# <think> stripping
# ---------------------------------------------------------------------------

def strip_think_blocks(text: str) -> str:
    """Remove complete ``<think>...</think>`` blocks from a finished string."""
    return _THINK_BLOCK_RE.sub("", text or "").strip()


def _partial_suffix_len(buf: str, tag: str) -> int:
    """Length of the longest proper prefix of ``tag`` that ``buf`` ends with.

    That tail might be the start of a tag split across two stream chunks,
    so it must be held back rather than emitted or discarded.
    """
    for k in range(min(len(tag) - 1, len(buf)), 0, -1):
        if buf.endswith(tag[:k]):
            return k
    return 0


class ThinkStripper:
    """Incrementally drop ``<think>...</think>`` from streamed text."""

    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False
        self._trim_leading = False

    def feed(self, text: str) -> str:
        self._buf += text
        out: list[str] = []

        while True:
            if self._in_think:
                i = self._buf.find(_THINK_CLOSE)
                if i == -1:
                    keep = _partial_suffix_len(self._buf, _THINK_CLOSE)
                    self._buf = self._buf[len(self._buf) - keep:] if keep else ""
                    break
                self._buf = self._buf[i + len(_THINK_CLOSE):]
                self._in_think = False
                # Models put blank lines between the thought and the answer.
                self._trim_leading = True
                continue

            i = self._buf.find(_THINK_OPEN)
            if i == -1:
                keep = _partial_suffix_len(self._buf, _THINK_OPEN)
                emit = self._buf[: len(self._buf) - keep] if keep else self._buf
                self._buf = self._buf[len(emit):]
                out.append(emit)
                break

            out.append(self._buf[:i])
            self._buf = self._buf[i + len(_THINK_OPEN):]
            self._in_think = True

        result = "".join(out)
        if self._trim_leading and result:
            result = result.lstrip()
            if result:
                self._trim_leading = False
        return result

    def flush(self) -> str:
        """End of stream: release a held-back partial tag that never completed."""
        leftover = "" if self._in_think else self._buf
        self._buf = ""
        return leftover


# ---------------------------------------------------------------------------
# Message / tool-call translation
# ---------------------------------------------------------------------------

def _new_call_id() -> str:
    return "call_" + uuid.uuid4().hex[:12]


def _args_to_json(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments or {}, ensure_ascii=False)


def _json_to_args(raw: Any) -> dict:
    """Parse a tool call's arguments into a dict.

    Unparseable arguments must never silently become ``{}``: a tool whose
    parameters are all optional would then run with defaults the model never
    chose.  Instead the raw text is passed under a key no tool accepts, so
    the call fails loudly (TypeError -> "Error running tool ..." handed back
    to the model, or a visibly odd confirmation prompt for risky tools).
    """
    if isinstance(raw, dict):
        return raw
    if raw is None or raw == "":
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {"_invalid_arguments": str(raw)}
    return parsed if isinstance(parsed, dict) else {"_invalid_arguments": str(raw)}


def to_openai_messages(messages: list) -> list:
    """Convert Jarvis/Ollama-style messages to OpenAI chat messages."""
    out: list[dict] = []
    pending_ids: list[str] = []

    for m in messages:
        role = m.get("role")

        if role == "assistant" and m.get("tool_calls"):
            pending_ids = []
            calls = []
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                call_id = tc.get("id") or _new_call_id()
                pending_ids.append(call_id)
                calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": fn.get("name", ""),
                            "arguments": _args_to_json(fn.get("arguments")),
                        },
                    }
                )
            out.append(
                {
                    "role": "assistant",
                    "content": m.get("content") or "",
                    "tool_calls": calls,
                }
            )

        elif role == "tool":
            call_id = m.get("tool_call_id") or (
                pending_ids.pop(0) if pending_ids else _new_call_id()
            )
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": str(m.get("content", "")),
                }
            )

        else:
            out.append({"role": role, "content": m.get("content") or ""})

    return out


def _from_openai_tool_calls(calls: Optional[list]) -> Optional[list]:
    if not calls:
        return None
    return [
        {
            "id": c.get("id") or _new_call_id(),
            "function": {
                "name": c.get("function", {}).get("name", ""),
                "arguments": _json_to_args(c.get("function", {}).get("arguments")),
            },
        }
        for c in calls
    ]


# ---------------------------------------------------------------------------
# OpenAI-compatible client
# ---------------------------------------------------------------------------

class OpenAICompatClient:
    """Drop-in for ``ollama.Client`` as far as JarvisLLM uses it."""

    def __init__(
        self,
        base_url: str = "http://localhost:1337/v1",
        api_key: str = "not-needed",
        timeout: float = 120.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout, connect=5.0),
            transport=transport,
        )

    # -- public API ---------------------------------------------------------

    def chat(
        self,
        model: str,
        messages: list,
        tools: Optional[list] = None,
        stream: bool = False,
        options: Optional[dict] = None,
        **_ignored: Any,
    ):
        payload: dict[str, Any] = {
            "model": model,
            "messages": to_openai_messages(messages),
            "stream": bool(stream),
        }
        if tools:
            payload["tools"] = tools
        for src, dst in _OPTION_MAP.items():
            if options and options.get(src) is not None:
                payload[dst] = options[src]

        if stream:
            return self._stream(payload)
        return self._complete(payload)

    def list_models(self) -> list[str]:
        """Model ids the server reports (GET /models)."""
        try:
            resp = self._http.get(f"{self.base_url}/models")
        except httpx.HTTPError as exc:
            raise self._unreachable(exc) from exc
        self._raise_for_status(resp)
        return [m.get("id", "") for m in resp.json().get("data", []) if m.get("id")]

    def is_available(self) -> bool:
        try:
            self.list_models()
            return True
        except BackendError:
            return False

    # -- internals ----------------------------------------------------------

    def _unreachable(self, exc: Exception) -> BackendError:
        return BackendError(
            f"Could not reach the LLM server at {self.base_url} ({exc}). "
            "Is it running with a model loaded?"
        )

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            body = resp.text[:300]
            raise BackendError(f"LLM server returned HTTP {resp.status_code}: {body}")

    def _complete(self, payload: dict) -> dict:
        try:
            resp = self._http.post(f"{self.base_url}/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise self._unreachable(exc) from exc
        self._raise_for_status(resp)

        try:
            msg = resp.json()["choices"][0]["message"]
        except (KeyError, IndexError, ValueError) as exc:
            raise BackendError(f"Unexpected response from LLM server: {resp.text[:300]}") from exc

        message: dict[str, Any] = {
            "role": "assistant",
            "content": strip_think_blocks(msg.get("content") or ""),
        }
        tool_calls = _from_openai_tool_calls(msg.get("tool_calls"))
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {"message": message}

    def _stream(self, payload: dict) -> Iterator[dict]:
        stripper = ThinkStripper()
        fragments: dict[int, dict] = {}

        try:
            with self._http.stream(
                "POST", f"{self.base_url}/chat/completions", json=payload
            ) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    self._raise_for_status(resp)

                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except ValueError:
                        continue

                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}

                    # Reasoning servers may send thoughts in a separate
                    # field (reasoning_content); it is never spoken.
                    text = delta.get("content") or ""
                    if text:
                        visible = stripper.feed(text)
                        if visible:
                            yield {"message": {"role": "assistant", "content": visible}}

                    for tc in delta.get("tool_calls") or []:
                        slot = fragments.setdefault(
                            tc.get("index", 0),
                            {"id": None, "name": "", "arguments": ""},
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
        except httpx.HTTPError as exc:
            raise self._unreachable(exc) from exc

        tail = stripper.flush()
        if tail:
            yield {"message": {"role": "assistant", "content": tail}}

        if fragments:
            calls = [
                {
                    "id": f["id"],
                    "function": {"name": f["name"], "arguments": f["arguments"]},
                }
                for _, f in sorted(fragments.items())
            ]
            yield {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": _from_openai_tool_calls(calls),
                }
            }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_client(config: Optional[dict] = None):
    """Build the chat client selected by CONFIG["llm_backend"]."""
    if config is None:
        from config import CONFIG as config  # local import: avoids a cycle

    backend = str(config.get("llm_backend", "ollama")).strip().lower()

    if backend == "openai":
        return OpenAICompatClient(
            base_url=config.get("openai_base_url", "http://localhost:1337/v1"),
            api_key=config.get("openai_api_key", "not-needed"),
            timeout=float(config.get("llm_request_timeout_seconds", 120)),
        )

    if backend != "ollama":
        raise ValueError(
            f"Unknown llm_backend {backend!r} in jarvis_config.json; "
            "use \"ollama\" or \"openai\"."
        )

    from ollama import Client

    return Client(host=config.get("ollama_host", "http://localhost:11434"))
