"""
Memory tools for Jarvis -- lets the model explicitly store a durable fact
("my manager is named Sarah", "I prefer dark mode") as a structured
memory entry, separate from the automatic per-turn conversation memory
in brain/llm.py.

Registered as risky: what gets stored here is replayed into *every*
future prompt as "known facts about the user...treat them as existing
knowledge" (see brain/llm.py's system prompt), not just used once. That
makes it a persistence mechanism, not a one-off action -- if a scraped
web page, an ingested document, or OCR'd screen text can talk the model
into calling this, the injected content survives across sessions rather
than affecting a single reply. Confirming before it writes gives the
user a chance to catch a bogus/injected fact before it becomes "known"
long-term, the same way any other durable, hard-to-undo action does.
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

# See module docstring -- storing a fact persists it into every future
# prompt, so it gets the same confirmation gate as any other durable,
# hard-to-undo action rather than being treated as a harmless local write.
MEMORY_RISKY_TOOLS = {"remember_fact"}
