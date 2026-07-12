from ollama import Client
from memory.retriever import JarvisMemory
from tools.tools import TOOL_SCHEMAS, TOOL_FUNCTIONS

# Safety valve: caps how many tool-call round-trips happen for a single
# user message, in case the model gets stuck calling tools repeatedly.
MAX_TOOL_ROUNDS = 3


class JarvisLLM:
    def __init__(self, model="llama3.1:8b"):
        self.client = Client(host="http://localhost:11434")
        self.model = model
        self.memory = JarvisMemory()

        self.system_prompt = (
            "You are Jarvis, a local AI assistant running fully on my laptop.\n"
            "You answer questions using the provided context.\n"
            "If the answer is not in the context, say you do not know.\n"
            "You do not use the internet unless explicitly instructed.\n"
            "You have access to tools -- use them when they would make your "
            "answer more accurate (e.g. arithmetic, the current time) or when "
            "asked to read, write, delete, or list files. File tools only see "
            "a sandboxed 'workspace' folder, not the whole computer. Only call "
            "a tool when it's actually needed.\n"
        )

    def _run_tool_call(self, tool_call) -> str:
        name = tool_call["function"]["name"]
        arguments = tool_call["function"].get("arguments") or {}

        func = TOOL_FUNCTIONS.get(name)
        if func is None:
            return f"Error: unknown tool '{name}'"

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
            # asked for, and feed the results back for a follow-up turn.
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
