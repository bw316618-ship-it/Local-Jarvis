"""
Web search for Jarvis -- the one tool that reaches outside the local
machine. Uses the `ddgs` package (DuckDuckGo search, no API key needed).

Read-only, so it isn't marked risky -- it can't change anything. Still,
the system prompt tells the model to only reach for this when a task
genuinely needs current/external info, since Jarvis is offline-first by
design and every other tool works without an internet connection.
"""


def web_search(query: str) -> str:
    """Search the web and return a handful of result titles + snippets."""
    try:
        from ddgs import DDGS
    except ImportError as e:
        return (
            "Web search isn't available: the ddgs package is not installed. "
            "Run: pip install -r requirements.txt"
        )

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
    except Exception as e:
        return f"Web search failed: {e}"

    if not results:
        return f"No results found for '{query}'."

    lines = []
    for r in results:
        title = r.get("title", "").strip()
        snippet = r.get("body", "").strip()
        url = r.get("href", "").strip()
        lines.append(f"- {title}: {snippet} ({url})")

    return "Search results:\n" + "\n".join(lines)


WEB_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the internet for current information that isn't "
                "available locally (news, prices, facts after the local "
                "model's training, anything you'd otherwise have to guess at)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                },
                "required": ["query"],
            },
        },
    },
]

WEB_TOOL_FUNCTIONS = {"web_search": web_search}
