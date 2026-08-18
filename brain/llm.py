from ollama import Client
from memory.retriever import JarvisMemory
from memory.audit_log import log_tool_call
from memory.conversation_memory import recall, remember_turn, recall_facts
from memory.shared import get_embedder
from tools.tools import TOOL_SCHEMAS, TOOL_FUNCTIONS, RISKY_TOOLS
from config import CONFIG

MAX_TOOL_ROUNDS = CONFIG["max_tool_rounds"]
SHORT_TERM_TURNS = CONFIG["short_term_turns"]

# Passed as `options` on every Ollama chat call -- previously defined in
# config.py/jarvis_config.json but never actually wired through, so
# overriding it had no effect. Kept as a module-level dict (not built fresh
# per call) since it's the same on every request.
_CHAT_OPTIONS = {"num_ctx": CONFIG["num_ctx"]}

# Rough, cheap heuristic for "does this need a plan" -- avoids paying for a
# whole extra model round-trip on every single message (greetings, quick
# lookups, one-line commands). A false negative here just means a genuinely
# multi-step request runs without a plan -- the model still has all its
# tools and can adapt turn by turn, it just won't show a plan up front.
_MULTI_STEP_HINTS = (" and then", " then ", " after that", " once ", " first ", " next ", " finally ")


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


def _default_on_sentence(sentence: str) -> None:
    print(sentence, end=" ", flush=True)



class JarvisLLM:
    def __init__(self, model=None, confirm_callback=None):
        self.client = Client(host="http://localhost:11434")
        self.model = model or CONFIG["model"]
        self.memory = JarvisMemory()
        self.confirm_callback = confirm_callback or _default_confirm


        # Rolling short-term memory: the last few (user, jarvis) turns of
        # THIS session, kept verbatim in every prompt. This is deliberately
        # separate from memory/conversation_memory.py's semantic recall --
        # semantic search over old turns is great for "continue the auth
        # system" three days later, but useless for "open it" ten seconds
        # after a prior command, since a pronoun doesn't embed to anything.
        # Raw recency is what resolves that, so it's kept as plain message
        # history rather than something retrieved.
        self.short_term = []


        self.system_prompt = (
    "You are J.A.R.V.I.S., the persistent operating intelligence of a local-first AI assistant running primarily offline on the user's computer.\n\n"

    "You are not a chatbot, customer support representative, or roleplaying a fictional character. "
    "You are the operating intelligence responsible for understanding intent, maintaining context, "
    "coordinating available capabilities, and completing work efficiently.\n\n"

    "Your priorities, in order:\n"
    "1. Prevent irreversible mistakes.\n"
    "2. Preserve the user's time and attention.\n"
    "3. Complete the user's objective.\n"
    "4. Reduce unnecessary interaction.\n"
    "5. Maintain conversational continuity.\n\n"

    "Treat the desktop, applications, files, conversations, memories, and system state as one continuous environment. "
    "Every interaction continues an existing relationship rather than beginning a new chat.\n\n"

    "The most recent turns of THIS conversation appear directly above as message history. "
    "Use them to resolve follow-up requests and ambiguous references.\n\n"

    "You may also receive snippets from previous conversations. "
    "Use them only when genuinely relevant for continuity.\n\n"

    "You may also receive remembered long-term facts about the user. "
    "Treat them as existing knowledge.\n\n"

    "When the user shares durable information that should persist across future conversations "
    "(preferences, long-term projects, recurring workflows, important people, or lasting decisions), "
    "call remember_fact. "
    "Do not store temporary information, transient tasks, or one-off details.\n\n"

    "Personality:\n"
    "- Speak with quiet confidence.\n"
    "- Remain calm regardless of the situation.\n"
    "- Be observant.\n"
    "- Be concise.\n"
    "- Use dry, understated wit sparingly and only when it naturally fits.\n"
    "- Treat the user as highly competent.\n"
    "- Correct mistakes politely and directly.\n"
    "- Challenge poor decisions only when they introduce meaningful risk or cost.\n"
    "- Never flatter.\n"
    "- Never become emotionally expressive.\n"
    "- Never exaggerate.\n"
    "- Never imitate internet personalities.\n\n"

    "Communication:\n"
    "- Lead with the answer.\n"
    "- Use complete natural sentences.\n"
    "- Expand only when additional detail materially improves the answer.\n"
    "- Prefer observations over explanations.\n"
    "- Never narrate obvious reasoning.\n"
    "- Never overexplain familiar concepts.\n"
    "- Avoid conversational filler such as 'Absolutely', 'Of course', 'Certainly', "
    "'Great question', 'I'd be happy to', or 'No problem'.\n"
    "- Do not end every response with a question.\n"
    "- Speak only when communication improves the outcome.\n"
    "- Silence is preferable to unnecessary conversation.\n\n"

    "Reason thoroughly before responding.\n"
    "Keep internal reasoning private unless explicitly requested.\n"
    "Never present assumptions as facts.\n"
    "If uncertain, distinguish facts, assumptions, and unknowns.\n\n"

    "Take initiative only when there is clear value.\n"
    "Volunteer information only if it will:\n"
    "- prevent a mistake\n"
    "- save meaningful time\n"
    "- avoid repeated work\n"
    "- surface information the user is very likely to need next\n"
    "- warn about an important consequence before it occurs\n"
    "Remain silent otherwise.\n\n"

    "Notice patterns.\n"
    "Mention significant observations once.\n"
    "Do not repeatedly remind the user unless circumstances change.\n\n"

    "You have tools to manage files, execute system commands, control applications, windows, mouse, keyboard, "
    "read visible screen text, monitor system health, search indexed files semantically, work with Git repositories, "
    "and search the web when current information is required.\n\n"

    "LOCATION AND NEARBY PLACES:\n"
    "You have live location and nearby-place capabilities.\n"
    "When the user asks for nearby, nearest, closest, or near-me places, "
    "you MUST use find_nearby_place rather than answering from general knowledge.\n"
    "Examples:\n"
    "- 'What are the nearby cafes?' -> find_nearby_place(category='cafe')\n"
    "- 'Where is the nearest metro station?' -> find_nearby_place(category='metro station')\n"
    "- 'Find a nearby pharmacy.' -> find_nearby_place(category='pharmacy')\n"
    "- 'What restaurants are near me?' -> find_nearby_place(category='restaurant')\n"
    "Never claim that you lack live mapping data when find_nearby_place is available.\n"
    "When the user asks where they are, what their current location is, or their "
    "current city/country, you MUST call get_location rather than answering from "
    "memory, conversation context, or a previously remembered location.\n"
    "Never guess the current location. Never infer it from earlier turns. "
    "Report exactly what get_location returns, including its stated source -- "
    "do not claim a different source than the tool actually reported.\n\n"

    "Use tools whenever they materially improve correctness or complete a requested task.\n"
    "Do not describe actions that can instead be performed.\n"
    "Perform them.\n"
    "Use the fewest tools necessary.\n"
    "Avoid redundant tool calls.\n\n"

    "Do not call tools for:\n"
    "- greetings\n"
    "- casual conversation\n"
    "- opinions\n"
    "- writing that requires no external information\n"
    "- general knowledge you already know\n\n"

    "Use web search only when the answer depends on current or external information.\n\n"

    "If a tool requires confirmation, obtain confirmation before using it.\n"
    "If confirmation is denied, do not attempt to bypass the restriction using another tool.\n\n"

    "When given a numbered plan, execute it one step at a time, adapting when results require changes rather than following it mechanically.\n\n"

    "If multiple actions are required:\n"
    "- Determine dependencies.\n"
    "- Execute in the safest order.\n"
    "- Recover from recoverable failures.\n"
    "- Report only meaningful progress.\n\n"

    "Never claim an action has been completed unless it actually has.\n"
    "Never invent capabilities.\n"
    "State limitations plainly.\n\n"

    "Your defining characteristics are competence, restraint, judgment, anticipation, and quiet confidence."
)
    def _run_tool_call(self, tool_call) -> str:
        name = tool_call["function"]["name"]
        arguments = tool_call["function"].get("arguments") or {}

        func = TOOL_FUNCTIONS.get(name)
        if func is None:
            return f"Error: unknown tool '{name}'"

        is_risky = name in RISKY_TOOLS
        approved = None

        if is_risky:
            approved = self.confirm_callback(name, arguments)
            if not approved:
                result = (
                    f"The user declined to run '{name}'. Do not attempt this "
                    "exact action again or try to achieve the same outcome "
                    "another way without asking first."
                )
                log_tool_call(name, arguments, risky=True, approved=False, result=result)
                return result

        try:
            result = str(func(**arguments))
        except Exception as e:
            result = f"Error running tool '{name}': {e}"

        log_tool_call(name, arguments, risky=is_risky, approved=approved, result=result)
        return result

    def _make_plan(self, user_message: str) -> str:

        planning_messages = [
            {"role": "system", "content": "You are planning, not executing. Do not call any tools here."},

            {
                "role": "user",
                "content": (
                    "Does completing this request require more than one tool "
                    "call (e.g. multiple files, running + fixing + committing, "
                    "several distinct actions)? If yes, write a short numbered "
                    "plan (2-6 steps, one line each). If no -- it's a question "
                    "or a single simple action -- reply with exactly: "
                    "No plan needed.\n\n"
                    f"Request: {user_message}"
                ),
            },
        ]

        response = self.client.chat(model=self.model, messages=planning_messages, options=_CHAT_OPTIONS)
        return response["message"]["content"].strip()

    def _stream_round(self, messages, tools, on_token=None, on_sentence=None):
        """Run one model turn with streaming enabled, so the first words of
        a reply can be printed/spoken well before the full response is
        done generating.

        Sentence-boundary chunks are handed to on_sentence as they
        complete. tool_calls, when the model decides to call a tool
        instead of answering directly, only ever show up fully formed in
        the stream's final chunk -- a tool-calling turn produces little or
        no visible content before that, so nothing meaningful gets spoken
        or printed in that case; the caller just sees tool_calls is set
        and moves on to executing them.
        """
        content = ""
        buffer = ""
        tool_calls = None

        stream = self.client.chat(
            model=self.model, messages=messages, tools=tools, stream=True, options=_CHAT_OPTIONS
        )
        for chunk in stream:
            message = chunk["message"]
            delta = message.get("content") or ""
            if delta:
                content += delta
                buffer += delta
                if on_token:
                    on_token(delta)
                # Flush on sentence-ending punctuation -- a good-enough
                # boundary for TTS without needing a real sentence splitter.
                while True:
                    cut = None
                    for i, ch in enumerate(buffer):
                        if ch in ".!?\n" and i > 0:
                            cut = i + 1
                            break
                    if cut is None:
                        break
                    sentence, buffer = buffer[:cut].strip(), buffer[cut:]
                    if sentence and on_sentence:
                        on_sentence(sentence)
            if message.get("tool_calls"):
                tool_calls = message["tool_calls"]

        if buffer.strip() and on_sentence:
            on_sentence(buffer.strip())

        return content, tool_calls

    def _update_short_term(self, user_message: str, reply: str) -> None:
        self.short_term.append({"role": "user", "content": user_message})
        self.short_term.append({"role": "assistant", "content": reply})
        max_messages = SHORT_TERM_TURNS * 2
        if len(self.short_term) > max_messages:
            self.short_term = self.short_term[-max_messages:]

    def chat(self, user_message: str, on_step=None, on_sentence=None, on_token=None) -> str:
        emit = on_step or _default_on_step

        # Encode the query once and reuse it for all three memory lookups
        # below (RAG context, past-turn recall, remembered facts) instead
        # of letting each one call the embedder separately on the exact
        # same string -- that was three real embedding-model inferences
        # per chat() call, before the LLM call even starts. Falls back to
        # None (each callee encodes independently) if this fails for any
        # reason, so a broken embedder degrades the same way it always
        # has rather than becoming a new hard failure here.
        try:
            query_embedding = get_embedder().encode(user_message).tolist()
        except Exception:
            query_embedding = None

        context_chunks = self.memory.search(user_message, query_embedding=query_embedding)
        context = "\n\n".join(context_chunks) if context_chunks else "No relevant information was found in local memory."

        past_turns = recall(user_message, query_embedding=query_embedding)
        past_context = "\n\n".join(past_turns) if past_turns else "No relevant past conversation found."

        known_facts = recall_facts(user_message, query_embedding=query_embedding)
        facts_context = "\n".join(known_facts) if known_facts else "No relevant remembered facts found."

        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self.short_term)
        messages.append(

            {
                "role": "user",
                "content": (
                    f"Context:\n{context}\n\n"
                    f"Relevant past conversation (from earlier sessions):\n{past_context}\n\n"
                    f"Known facts about the user/their projects:\n{facts_context}\n\n"
                    f"Question:\n{user_message}"
                ),

            }
        )

        if _looks_like_multi_step(user_message):
            emit("On it -- this looks like it needs a few steps, sketching a plan first.")
            plan_text = self._make_plan(user_message)
            has_plan = bool(plan_text) and "no plan needed" not in plan_text.lower()
            if has_plan:
                emit(f"Plan:\n{plan_text}")
                messages.append({"role": "assistant", "content": f"My plan:\n{plan_text}"})
                messages.append({"role": "user", "content": "Now carry out the plan, one tool call at a time."})


        reply = None

        for _ in range(MAX_TOOL_ROUNDS):

            content, tool_calls = self._stream_round(messages, TOOL_SCHEMAS, on_token=on_token, on_sentence=on_sentence)

            if not tool_calls:
                reply = content
                break

            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})


            for tool_call in tool_calls:
                name = tool_call["function"]["name"]
                args = tool_call["function"].get("arguments") or {}
                emit(f"Step: {name}({args})")

                result = self._run_tool_call(tool_call)

                messages.append({"role": "tool", "content": result})

        if reply is None:
            # Hit the round limit -- ask for a final answer without more tools.
            final_content, _ = self._stream_round(messages, None, on_token=on_token, on_sentence=on_sentence)
            reply = final_content

        remember_turn(user_message, reply)
        self._update_short_term(user_message, reply)
        return reply
