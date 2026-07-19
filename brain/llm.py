from ollama import Client
from memory.retriever import JarvisMemory
from memory.audit_log import log_tool_call
from memory.conversation_memory import recall, remember_turn, recall_facts
from tools.tools import TOOL_SCHEMAS, TOOL_FUNCTIONS, RISKY_TOOLS
from config import CONFIG

# Safety valve: caps how many tool-call round-trips happen for a single
# user message. Raised from 6 -- genuinely multi-step tasks (create a
# project, run it, fix errors, commit) need more turns than a quick
# lookup does. Configurable via jarvis_config.json ("max_tool_rounds").
MAX_TOOL_ROUNDS = CONFIG["max_tool_rounds"]


def _default_confirm(name: str, arguments: dict) -> bool:
    """Fallback confirmation prompt, used if the caller doesn't supply one.

    Defaults to a plain input() prompt rather than auto-approving, since a
    risky tool with no confirmation path at all would silently defeat the
    whole point of RISKY_TOOLS.
    """
    print(f"\nJarvis wants to run '{name}' with arguments: {arguments}")
    answer = input("Allow this? [y/N] ").strip().lower()
    return answer == "y"


def _default_on_step(message: str) -> None:
    """Fallback progress reporter, used if the caller doesn't supply one."""
    print(message)


class JarvisLLM:
    def __init__(self, model=None, confirm_callback=None):
        self.client = Client(host="http://localhost:11434")
        self.model = model or CONFIG["model"]
        self.memory = JarvisMemory()
        self.confirm_callback = confirm_callback or _default_confirm

        self.system_prompt = (
            "You are Jarvis, a local-first AI assistant with broad access to "
            "my laptop, running mostly offline.\n"
            "You answer questions using the provided context when it's relevant.\n"
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
            "git repos, read text visible on screen, and semantically search "
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
        """Ask the model, with tools disabled, whether this request needs
        more than one step -- and if so, sketch a short plan.

        This runs as a separate, tool-free call rather than folding planning
        into the main loop, so the model can't short-circuit straight to a
        tool call before thinking about the shape of the whole task. Simple
        requests get "No plan needed" and skip straight past this.
        """
        planning_messages = [
            {
                "role": "system",
                "content": (
                    "You are planning, not executing. Do not call any tools here."
                ),
            },
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

    def chat(self, user_message: str, on_step=None) -> str:
        emit = on_step or _default_on_step

        context_chunks = self.memory.search(user_message)
        if context_chunks:
            context = "\n\n".join(context_chunks)
        else:
            context = "No relevant information was found in local memory."

        past_turns = recall(user_message)
        if past_turns:
            past_context = "\n\n".join(past_turns)
        else:
            past_context = "No relevant past conversation found."

        known_facts = recall_facts(user_message)
        if known_facts:
            facts_context = "\n".join(known_facts)
        else:
            facts_context = "No relevant remembered facts found."

        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": (
                    f"Context:\n{context}\n\n"
                    f"Relevant past conversation (from earlier sessions):\n{past_context}\n\n"
                    f"Known facts about the user/their projects:\n{facts_context}\n\n"
                    f"Question:\n{user_message}"
                ),
            },
        ]

        plan_text = self._make_plan(user_message)
        has_plan = bool(plan_text) and "no plan needed" not in plan_text.lower()

        if has_plan:
            emit(f"Plan:\n{plan_text}")
            messages.append({"role": "assistant", "content": f"My plan:\n{plan_text}"})
            messages.append({"role": "user", "content": "Now carry out the plan, one tool call at a time."})

        reply = None

        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.chat(
                model=self.model,
                messages=messages,
                tools=TOOL_SCHEMAS,
            )

            message = response["message"]
            tool_calls = message.get("tool_calls")

            if not tool_calls:
                reply = message["content"]
                break

            # Record the assistant's tool-call request, run each tool it
            # asked for (with confirmation for risky ones), and feed the
            # results back for a follow-up turn.
            messages.append(message)

            for tool_call in tool_calls:
                name = tool_call["function"]["name"]
                args = tool_call["function"].get("arguments") or {}
                emit(f"Step: {name}({args})")

                result = self._run_tool_call(tool_call)
                messages.append({
                    "role": "tool",
                    "content": result,
                })

        if reply is None:
            # Hit the round limit -- ask for a final answer without more tools.
            final = self.client.chat(model=self.model, messages=messages)
            reply = final["message"]["content"]

        remember_turn(user_message, reply)
        return reply
