from ollama import Client
from memory.retriever import JarvisMemory
from tools.tools import TOOL_SCHEMAS, TOOL_FUNCTIONS, RISKY_TOOLS

# Safety valve: caps how many tool-call round-trips happen for a single
# user message. Bumped up from the original 3 -- multi-step desktop tasks
# (e.g. "open the app, click here, type this") legitimately need more turns.
MAX_TOOL_ROUNDS = 6


def _default_confirm(name: str, arguments: dict) -> bool:
    """Fallback confirmation prompt, used if the caller doesn't supply one.

    Defaults to a plain input() prompt rather than auto-approving, since a
    risky tool with no confirmation path at all would silently defeat the
    whole point of RISKY_TOOLS.
    """
    print(f"\nJarvis wants to run '{name}' with arguments: {arguments}")
    answer = input("Allow this? [y/N] ").strip().lower()
    return answer == "y"


class JarvisLLM:
    def __init__(self, model="llama3.1:8b", confirm_callback=None):
        self.client = Client(host="http://localhost:11434")
        self.model = model
        self.memory = JarvisMemory()
        self.confirm_callback = confirm_callback or _default_confirm

        self.system_prompt = (
            "You are Jarvis, a local-first AI assistant with broad access to "
            "my laptop, running mostly offline.\n"
            "You answer questions using the provided context when it's relevant.\n"
            "You have tools to manage files, run system commands, control the "
            "mouse and keyboard, open applications, and search the web. Use "
            "them whenever they help complete the task -- don't just describe "
            "what you would do, actually do it by calling the right tool.\n"
            "Only use the web_search tool when the task genuinely needs current "
            "or external information; otherwise stay offline.\n"
            "Some tools require the user's explicit confirmation before they "
            "run. If one is declined, tell the user and suggest an alternative "
            "rather than trying to achieve the same thing a different way "
            "without asking.\n"
        )

    def _run_tool_call(self, tool_call) -> str:
        name = tool_call["function"]["name"]
        arguments = tool_call["function"].get("arguments") or {}

        func = TOOL_FUNCTIONS.get(name)
        if func is None:
            return f"Error: unknown tool '{name}'"

        if name in RISKY_TOOLS:
            approved = self.confirm_callback(name, arguments)
            if not approved:
                return (
                    f"The user declined to run '{name}'. Do not attempt this "
                    "exact action again or try to achieve the same outcome "
                    "another way without asking first."
                )

        try:
            return str(func(**arguments))
        except Exception as e:
            return f"Error running tool '{name}': {e}"

    def chat(self, user_message: str) -> str:
        context_chunks = self.memory.search(user_message)

        if context_chunks:
            context = "\n\n".join(context_chunks)
        else:
            context = "No relevant information was found in local memory."

        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": (
                    f"Context:\n{context}\n\n"
                    f"Question:\n{user_message}"
                ),
            },
        ]

        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.chat(
                model=self.model,
                messages=messages,
                tools=TOOL_SCHEMAS,
            )

            message = response["message"]
            tool_calls = message.get("tool_calls")

            if not tool_calls:
                return message["content"]

            # Record the assistant's tool-call request, run each tool it
            # asked for (with confirmation for risky ones), and feed the
            # results back for a follow-up turn.
            messages.append(message)

            for tool_call in tool_calls:
                result = self._run_tool_call(tool_call)
                messages.append({
                    "role": "tool",
                    "content": result,
                })

        # Hit the round limit -- ask for a final answer without more tools.
        final = self.client.chat(model=self.model, messages=messages)
        return final["message"]["content"]
