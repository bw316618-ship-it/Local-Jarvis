from ollama import Client
from memory.retriever import JarvisMemory

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
        )

    def chat(self, user_message: str) -> str:
        context_chunks = self.memory.search(user_message)

        if context_chunks:
            context = "\n\n".join(context_chunks)
        else:
            context = "No relevant information was found in local memory."

        response = self.client.chat(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": self.system_prompt
                },
                {
                    "role": "user",
                    "content": (
                        f"Context:\n{context}\n\n"
                        f"Question:\n{user_message}"
                    ),
                },
            ],
        )

        return response["message"]["content"]