"""
Memory tools for Jarvis -- lets the model explicitly store a durable fact
("my manager is named Sarah", "I prefer dark mode") as a structured
memory entry, separate from the automatic per-turn conversation memory
in brain/llm.py. Read-only from the user's system perspective (it only
writes into Jarvis's own memory store), so it isn't registered as risky.
"""

from memory.conversation_memory import remember_fact

MEMORY_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "remember_fact",
            "description": (
                "Store a durable fact for future sessions -- use this when the "
                "user tells you something worth remembering long-term: a "
                "person in their life, a preference, a project detail, a "
                "decision. Don't use it for one-off trivia that doesn't need "
                "to persist."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "A short label for the kind of fact, e.g. 'person', 'preference', 'project'.",
                    },
                    "fact": {
                        "type": "string",
                        "description": "The fact itself, written as a short standalone statement.",
                    },
                },
                "required": ["category", "fact"],
            },
        },
    },
]

MEMORY_TOOL_FUNCTIONS = {
    "remember_fact": remember_fact,
}
