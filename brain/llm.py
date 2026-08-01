from ollama import Client
from memory.retriever import JarvisMemory
from memory.audit_log import log_tool_call
from memory.conversation_memory import recall, remember_turn, recall_facts
from tools.tools import TOOL_SCHEMAS, TOOL_FUNCTIONS, RISKY_TOOLS
from config import CONFIG

MAX_TOOL_ROUNDS = CONFIG["max_tool_rounds"]
SHORT_TERM_TURNS = CONFIG["short_term_turns"]

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
            "You are Jarvis, a local-first AI assistant with broad access to "
            "my laptop, running mostly offline.\n"
            "You answer questions using the provided context when it's relevant.\n"

            "The most recent turns of THIS conversation appear directly above "
            "as message history -- use them to resolve vague or pronoun-heavy "
            "follow-ups ('open it', 'make that louder', 'try again') against "
            "whatever was just discussed or just ran.\n"

            "You may also be given snippets of relevant past conversation from "
            "earlier sessions -- use them for continuity (e.g. if asked to "
            "'continue the authentication system', check whether a past turn "
            "already covers what was decided or where things were left off), "
            "but don't assume every snippet is relevant just because it's "
            "present; ignore ones that don't actually help.\n"
            "You may also be given facts remembered from earlier sessions "
            "(people, preferences, project details) -- treat these as things "
            "you already know about the user. When the user tells you "
            "something durable worth remembering long-term -- a person in "
            "their life, a preference, a project detail, a decision -- call "
            "remember_fact to store it. Don't call it for one-off trivia that "
            "doesn't need to persist.\n"

            "You have tools to manage files (including renaming, moving, and "
            "organizing them into subfolders by type), run system commands, "
            "control the mouse and keyboard, list/focus/minimize/close "
            "windows by title, open applications, search the web, work with "
            "git repos, read text visible on screen, check system health "
            "(CPU/memory/disk/top processes), and semantically search "
            "files already indexed on this machine (search_files) -- use "
            "search_files, not just list_directory, when asked to find a file "
            "by what it's about rather than its exact name or location, and "
            "use find_text_on_screen before mouse_click when you need to "
            "click something by its visible label rather than a coordinate "
            "you already know.\n"

            "Only call a tool when it's genuinely needed to answer accurately "
            "or complete a requested action. Greetings, small talk, opinions, "
            "thanks, and general knowledge you already know get a plain reply "
            "with no tool call at all -- 'Hello', 'thanks', 'what's the "
            "capital of France' need nothing but an answer. Reach for "
            "web_search only when the task genuinely needs current or "
            "external information (e.g. today's news, a live score, "
            "something after your training data) -- never for a bare "
            "greeting or something you can already answer. When a tool "
            "really is needed, actually call it rather than describing what "
            "you would do.\n"

            "Keep replies concise and conversational, the way a sharp "
            "assistant speaking out loud would -- lead with the answer, skip "
            "preamble, expand only if the user actually needs the detail.\n"

            "Some tools require the user's explicit confirmation before they "
            "run. If one is declined, tell the user and suggest an alternative "
            "rather than trying to achieve the same thing a different way "
            "without asking.\n"
            "If you were given a numbered plan, follow it step by step, one "
            "tool call at a time, adjusting if a step's result changes what's "
            "needed -- the plan is a guide, not a script to follow blindly if "
            "something unexpected happens.\n"
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

        response = self.client.chat(model=self.model, messages=planning_messages)
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

        stream = self.client.chat(model=self.model, messages=messages, tools=tools, stream=True)
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

        context_chunks = self.memory.search(user_message)
        context = "\n\n".join(context_chunks) if context_chunks else "No relevant information was found in local memory."

        past_turns = recall(user_message)
        past_context = "\n\n".join(past_turns) if past_turns else "No relevant past conversation found."

        known_facts = recall_facts(user_message)
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

