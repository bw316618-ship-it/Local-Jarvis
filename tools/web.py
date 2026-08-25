"""
Web search for Jarvis -- the one tool that reaches outside the local
machine. Uses the `ddgs` package (DuckDuckGo search, no API key needed).

Read-only, so it isn't marked risky -- it can't change anything. Still,
the system prompt tells the model to only reach for this when a task
genuinely needs current/external info, since Jarvis is offline-first by
design and every other tool works without an internet connection.
"""

import time


def web_search(query: str) -> str:
    """Search the web and return a handful of result titles + snippets."""
    try:
        from ddgs import DDGS
    except ImportError as e:
        return (
            "Web search isn't available: the ddgs package is not installed. "
            "Run: pip install -r requirements.txt"
        )

    # ddgs wraps its own HTTP client rather than exposing a plain
    # requests.Response, so tools/net.py's request_with_retry (built
    # around requests) doesn't apply cleanly here. A small local retry
    # loop covers the same transient-failure case -- DDGS() is cheap to
    # re-enter -- without trying to force ddgs through the requests-shaped
    # helper. Anything that isn't a plain transient network hiccup (e.g.
    # a malformed query) will keep failing identically on every attempt
    # and just costs a couple of quick retries before surfacing.
    from config import CONFIG

    attempts = max(1, CONFIG.get("network_retry_attempts", 3))
    backoff_seconds = CONFIG.get("network_retry_backoff_seconds", 0.5)

    last_exc = None
    results = None
    for attempt in range(1, attempts + 1):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
            last_exc = None
            break
        except Exception as e:
            last_exc = e
            if attempt < attempts:
                time.sleep(backoff_seconds * attempt)

    if last_exc is not None:
        return f"Web search failed: {last_exc}"

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
