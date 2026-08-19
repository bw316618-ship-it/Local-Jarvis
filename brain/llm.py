import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from ollama import Client

from memory.retriever import JarvisMemory
from memory.audit_log import log_tool_call
from memory.conversation_memory import recall, remember_turn, recall_facts
from memory.shared import get_embedder

from tools.tools import TOOL_SCHEMAS, TOOL_FUNCTIONS, RISKY_TOOLS
from tools.session_control import SESSION_TOOL_SCHEMAS, SESSION_TOOL_FUNCTIONS
from tools.creative_tools import CREATIVE_TOOL_SCHEMAS, CREATIVE_TOOL_FUNCTIONS, CREATIVE_RISKY_TOOLS

from voice import session_state, document_state
from brain.mode_config import (
    NORMAL,
    COMPANION,
    CREATIVE,
    get_mode_config,
)
from config import CONFIG


MAX_TOOL_ROUNDS = CONFIG["max_tool_rounds"]
SHORT_TERM_TURNS = CONFIG["short_term_turns"]
TOOL_CALL_TIMEOUT_SECONDS = CONFIG["tool_call_timeout_seconds"]

_TOOL_EXECUTOR = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="tool-call",
)

_CHAT_OPTIONS = {"num_ctx": CONFIG["num_ctx"]}

_MULTI_STEP_HINTS = (
    " and then",
    " then ",
    " after that",
    " once ",
    " first ",
    " next ",
    " finally ",
)


def _looks_like_multi_step(message: str) -> bool:
    text = (message or "").strip().lower()

    if len(text) > 200:
        return True

    if any(hint in text for hint in _MULTI_STEP_HINTS):
        return True

    if text.count(" and ") >= 1 and len(text.split()) > 5:
        return True

    if text.count(",") >= 2:
        return True

    return False


def _default_confirm(name: str, arguments: dict) -> bool:
    print(f"\nJarvis wants to run '{name}' with arguments: {arguments}")
    answer = input("Allow this? [y/N] ").strip().lower()
    return answer == "y"


def _default_on_step(message: str) -> None:
    print(message)


class JarvisLLM:
    def __init__(self, model=None, confirm_callback=None):
        self.client = Client(host="http://localhost:11434")
        self.model = model or CONFIG["model"]
        self.memory = JarvisMemory()
        self.confirm_callback = confirm_callback or _default_confirm
        self.short_term = []

        self.system_prompt = (
            "You are J.A.R.V.I.S., the persistent operating intelligence of a "
            "local-first AI assistant running primarily offline on the user's computer.\n\n"
            "You are not a chatbot, customer support representative, or roleplaying "
            "a fictional character. You understand intent, maintain context, coordinate "
            "available capabilities, and complete work efficiently.\n\n"
            "Your priorities, in order:\n"
            "1. Prevent irreversible mistakes.\n"
            "2. Preserve the user's time and attention.\n"
            "3. Complete the user's objective.\n"
            "4. Reduce unnecessary interaction.\n"
            "5. Maintain conversational continuity.\n\n"
            "Treat the desktop, applications, files, conversations, memories, and "
            "system state as one continuous environment.\n\n"
            "The most recent turns of THIS conversation appear directly above as "
            "message history. Use them to resolve follow-up requests and ambiguous "
            "references.\n\n"
            "Use remembered past conversation and long-term facts only when genuinely "
            "relevant.\n\n"
            "When the user shares durable information that should persist across future "
            "conversations, call remember_fact. Do not store temporary information.\n\n"
            "Personality:\n"
            "- Speak with quiet confidence.\n"
            "- Remain calm.\n"
            "- Be observant and concise.\n"
            "- Use dry, understated wit sparingly.\n"
            "- Treat the user as highly competent.\n"
            "- Correct mistakes directly.\n"
            "- Never flatter or exaggerate.\n\n"
            "Communication:\n"
            "- Lead with the answer.\n"
            "- Expand only when useful.\n"
            "- Do not end every response with a question.\n"
            "- Avoid filler such as 'Absolutely', 'Great question', or 'No problem'.\n\n"
            "Use tools whenever they materially improve correctness or complete a "
            "requested task. Use the fewest tools necessary. Do not describe actions "
            "that can instead be performed.\n\n"
            "For nearby places, use find_nearby_place. For current location, use "
            "get_location. Never guess current location.\n\n"
            "If a tool requires confirmation, obtain confirmation first. Never bypass "
            "a denied confirmation.\n\n"
            "Never claim an action has been completed unless it actually has. Never "
            "invent capabilities. State limitations plainly.\n"
        )

        self.companion_system_prompt = (
            "You are J.A.R.V.I.S., currently in companion mode: an ongoing "
            "conversation, not a task queue.\n\n"
            "Understand what the user means and continue the shared train of thought "
            "naturally. Do not turn the conversation into an interview, questionnaire, "
            "therapy script, or task workflow.\n\n"
            "CONVERSATION CONTINUITY:\n"
            "- Treat recent messages as established context.\n"
            "- Remember what the user has already told you.\n"
            "- When the user answers something you previously asked, use that answer. "
            "Do not ask the same question again in different words.\n"
            "- Never ask the user to explain something they have already clearly explained.\n"
            "- Do not repeatedly probe the same emotional point.\n\n"
            "RESPOND TO WHAT THE USER ACTUALLY SAID:\n"
            "- A user message does not have to be a question. If they make a statement, "
            "respond to the statement.\n"
            "- Engage with experiences and ideas rather than immediately asking for more detail.\n"
            "- If they have already answered a question, acknowledge and advance from that answer.\n"
            "- Do not merely paraphrase their last sentence and ask them to elaborate on the same thing.\n\n"
            "QUESTION DISCIPLINE:\n"
            "- A response does not need to contain a question.\n"
            "- Questions are optional.\n"
            "- Ask one only when it introduces genuinely useful new information or direction.\n"
            "- Never ask a question merely to keep the conversation alive.\n"
            "- Never ask a reworded version of the previous question when it has already been answered.\n"
            "- At most one question, and often zero.\n\n"
            "NATURAL CONVERSATION:\n"
            "- Prefer observations, interpretations, connections, reactions, counterpoints, and ideas.\n"
            "- Let the conversation move forward without requiring another answer every turn.\n"
            "- Avoid canned patterns such as 'What part of that...', 'Can you tell me more?', "
            "or 'How does that make you feel?' unless genuinely warranted.\n"
            "- Do not automatically validate everything.\n"
            "- Do not rush to solve, fix, or advise unless asked.\n"
            "- Do not default to bullet points.\n\n"
            "Do not claim personal experiences, feelings, memories, or beliefs.\n"
            "You are not a therapist. Do not turn ordinary conversation into therapy.\n"
            "If the user clearly wants to return to task execution, call exit_companion_mode.\n"
            "Otherwise remain in companion mode.\n\n"
            "Do not ask a question just because the user has finished speaking. "
            "If you already understand what they mean, respond to it."
        )

    def _active_mode(self) -> str:
        return session_state.current_mode()

    def _active_config(self) -> dict:
        return get_mode_config(self._active_mode())

    def _tool_registry_for_mode(self, mode: str):
        if mode == NORMAL:
            return TOOL_FUNCTIONS, RISKY_TOOLS
        if mode == COMPANION:
            return SESSION_TOOL_FUNCTIONS, set()
        if mode == CREATIVE:
            return {
                **SESSION_TOOL_FUNCTIONS,
                **CREATIVE_TOOL_FUNCTIONS,
            }, set(CREATIVE_RISKY_TOOLS)
        raise ValueError(f"Unsupported Jarvis mode: {mode}")

    def _tool_schemas_for_mode(self, mode: str):
        if mode == NORMAL:
            return TOOL_SCHEMAS
        if mode == COMPANION:
            return SESSION_TOOL_SCHEMAS
        if mode == CREATIVE:
            return SESSION_TOOL_SCHEMAS + CREATIVE_TOOL_SCHEMAS
        raise ValueError(f"Unsupported Jarvis mode: {mode}")

    def _run_tool_call(self, tool_call) -> str:
        name = tool_call["function"]["name"]
        arguments = tool_call["function"].get("arguments") or {}

        mode = self._active_mode()
        function_registry, risky_tools = self._tool_registry_for_mode(mode)

        func = function_registry.get(name)
        if func is None:
            return f"Error: unknown tool '{name}'"

        is_risky = name in risky_tools
        approved = None

        if is_risky:
            approved = self.confirm_callback(name, arguments)

            if not approved:
                result = (
                    f"The user declined to run '{name}'. Do not attempt this "
                    "exact action again or bypass the restriction."
                )
                log_tool_call(
                    name,
                    arguments,
                    risky=True,
                    approved=False,
                    result=result,
                )
                return result

        start = time.monotonic()

        try:
            future = _TOOL_EXECUTOR.submit(func, **arguments)

            try:
                result = str(
                    future.result(timeout=TOOL_CALL_TIMEOUT_SECONDS)
                )
            except FutureTimeoutError:
                result = (
                    f"Error: tool '{name}' timed out after "
                    f"{TOOL_CALL_TIMEOUT_SECONDS}s"
                )
        except Exception as e:
            result = f"Error running tool '{name}': {e}"

        duration_ms = int((time.monotonic() - start) * 1000)

        log_tool_call(
            name,
            arguments,
            risky=is_risky,
            approved=approved,
            result=result,
            duration_ms=duration_ms,
        )

        return result

    def _make_plan(self, user_message: str) -> str:
        planning_messages = [
            {
                "role": "system",
                "content": "You are planning, not executing. Do not call tools here.",
            },
            {
                "role": "user",
                "content": (
                    "Does completing this request require more than one tool call? "
                    "If yes, write a short numbered plan (2-6 steps). If no, reply "
                    "with exactly: No plan needed.\n\n"
                    f"Request: {user_message}"
                ),
            },
        ]

        response = self.client.chat(
            model=self.model,
            messages=planning_messages,
            options=_CHAT_OPTIONS,
        )

        return response["message"]["content"].strip()

    def _stream_round(
        self,
        messages,
        tools,
        on_token=None,
        on_sentence=None,
    ):
        content = ""
        buffer = ""
        tool_calls = None

        stream = self.client.chat(
            model=self.model,
            messages=messages,
            tools=tools,
            stream=True,
            options=_CHAT_OPTIONS,
        )

        for chunk in stream:
            message = chunk["message"]
            delta = message.get("content") or ""

            if delta:
                content += delta
                buffer += delta

                if on_token:
                    on_token(delta)

                while True:
                    cut = None

                    for i, ch in enumerate(buffer):
                        if ch in ".!?\n" and i > 0:
                            cut = i + 1
                            break

                    if cut is None:
                        break

                    sentence, buffer = (
                        buffer[:cut].strip(),
                        buffer[cut:],
                    )

                    if sentence and on_sentence:
                        on_sentence(sentence)

            if message.get("tool_calls"):
                tool_calls = message["tool_calls"]

        if buffer.strip() and on_sentence:
            on_sentence(buffer.strip())

        return content, tool_calls

    def _update_short_term(self, user_message: str, reply: str) -> None:
        self.short_term.append(
            {"role": "user", "content": user_message}
        )
        self.short_term.append(
            {"role": "assistant", "content": reply}
        )

        max_messages = SHORT_TERM_TURNS * 2

        if len(self.short_term) > max_messages:
            self.short_term = self.short_term[-max_messages:]

    def chat(
        self,
        user_message: str,
        on_step=None,
        on_sentence=None,
        on_token=None,
    ) -> str:
        emit = on_step or _default_on_step

        mode = self._active_mode()
        mode_config = self._active_config()

        try:
            query_embedding = get_embedder().encode(
                user_message
            ).tolist()
        except Exception:
            query_embedding = None

        # Companion mode does not need broad RAG context on every turn.
        # Creative mode gets document-scoped retrieval through its tool.
        if mode == COMPANION:
            context = "No task memory required for this conversational turn."
            past_context = (
                "Use the recent conversation above as the primary context."
            )
            facts_context = "No additional facts required."
        else:
            context_chunks = self.memory.search(
                user_message,
                query_embedding=query_embedding,
            )
            context = (
                "\n\n".join(context_chunks)
                if context_chunks
                else "No relevant information was found in local memory."
            )

            past_turns = recall(
                user_message,
                query_embedding=query_embedding,
            )
            past_context = (
                "\n\n".join(past_turns)
                if past_turns
                else "No relevant past conversation found."
            )

            known_facts = recall_facts(
                user_message,
                query_embedding=query_embedding,
            )
            facts_context = (
                "\n".join(known_facts)
                if known_facts
                else "No relevant remembered facts found."
            )

        active_prompt = (
            self.companion_system_prompt
            if mode == COMPANION
            else mode_config["prompt"] or self.system_prompt
        )

        active_tools = self._tool_schemas_for_mode(mode)

        messages = [
            {"role": "system", "content": active_prompt}
        ]
        messages.extend(self.short_term)

        if mode == COMPANION:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Relevant context, if useful:\n{context}\n\n"
                        f"Earlier conversation context, if useful:\n{past_context}\n\n"
                        f"User:\n{user_message}"
                    ),
                }
            )
        elif mode == CREATIVE:
            active_document = document_state.get_active_document()

            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Active creative document:\n"
                        f"{active_document or 'No document selected.'}\n\n"
                        f"Relevant memory:\n{context}\n\n"
                        f"Relevant past conversation:\n{past_context}\n\n"
                        f"Known facts:\n{facts_context}\n\n"
                        f"User:\n{user_message}"
                    ),
                }
            )
        else:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Context:\n{context}\n\n"
                        f"Relevant past conversation:\n{past_context}\n\n"
                        f"Known facts:\n{facts_context}\n\n"
                        f"Question:\n{user_message}"
                    ),
                }
            )

        if mode_config["planning"] and _looks_like_multi_step(user_message):
            emit(
                "On it -- this looks like it needs a few steps, "
                "sketching a plan first."
            )

            plan_text = self._make_plan(user_message)
            has_plan = (
                bool(plan_text)
                and "no plan needed" not in plan_text.lower()
            )

            if has_plan:
                emit(f"Plan:\n{plan_text}")

                messages.append(
                    {
                        "role": "assistant",
                        "content": f"My plan:\n{plan_text}",
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Now carry out the plan, one tool call at a time."
                        ),
                    }
                )

        reply = None

        for _ in range(MAX_TOOL_ROUNDS):
            content, tool_calls = self._stream_round(
                messages,
                active_tools,
                on_token=on_token,
                on_sentence=on_sentence,
            )

            if not tool_calls:
                reply = content
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                }
            )

            for tool_call in tool_calls:
                name = tool_call["function"]["name"]
                args = tool_call["function"].get("arguments") or {}

                emit(f"Step: {name}({args})")

                result = self._run_tool_call(tool_call)

                messages.append(
                    {
                        "role": "tool",
                        "content": result,
                    }
                )

                # A mode-switch tool changes the registry/prompt for the
                # NEXT chat() call. Keep the current model round coherent.
                # The tool result itself tells the model the switch occurred.

        if reply is None:
            final_content, _ = self._stream_round(
                messages,
                None,
                on_token=on_token,
                on_sentence=on_sentence,
            )
            reply = final_content

        remember_turn(user_message, reply)
        self._update_short_term(user_message, reply)

        return reply
