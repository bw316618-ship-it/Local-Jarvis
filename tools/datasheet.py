"""
Datasheet search for Jarvis.

A thin, targeted wrapper around tools/web.py's web_search: appends
"datasheet filetype:pdf" to the query and prioritizes results that
actually end in .pdf, so the model doesn't have to guess search-term
phrasing every time someone asks "find the datasheet for X". Read-only
(it only searches, it doesn't open anything) -- pair it with
tools/pdf_viewer.py's open_pdf to actually view a result.

Uses the same ddgs backend as web_search rather than any distributor-
specific API, so no API keys are required.

Retries transient failures the same way tools/web.py's web_search does
and for the same reason: ddgs wraps its own HTTP client rather than
exposing a plain requests.Response, so tools/net.py's request_with_retry
(built around requests) doesn't apply cleanly here. This tool used to
have no retry at all -- a single dropped connection failed the whole
search immediately, unlike every other network-touching tool -- which
is the gap this closes.
"""

import time


def find_datasheet(part_or_product: str) -> str:
    """Search the web for an official PDF datasheet for a part or product."""
    query = (part_or_product or "").strip()
    if not query:
        return "A part number or product name is required."

    try:
        from ddgs import DDGS
    except ImportError:
        return (
            "Datasheet search isn't available: the ddgs package is not installed. "
            "Run: pip install -r requirements.txt"
        )

    search_query = f"{query} datasheet filetype:pdf"

    from config import CONFIG

    attempts = max(1, CONFIG.get("network_retry_attempts", 3))
    backoff_seconds = CONFIG.get("network_retry_backoff_seconds", 0.5)

    last_exc = None
    results = None
    for attempt in range(1, attempts + 1):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(search_query, max_results=8))
            last_exc = None
            break
        except Exception as e:
            last_exc = e
            if attempt < attempts:
                time.sleep(backoff_seconds * attempt)

    if last_exc is not None:
        return f"Datasheet search failed: {last_exc}"

    if not results:
        return f"No datasheet results found for '{query}'."

    pdf_results = [r for r in results if r.get("href", "").lower().endswith(".pdf")]
    shown = pdf_results if pdf_results else results

    lines = []
    for r in shown:
        title = r.get("title", "").strip()
        url = r.get("href", "").strip()
        lines.append(f"- {title} ({url})")

    header = "PDF datasheet results:" if pdf_results else "No direct PDF links found -- closest results:"
    return header + "\n" + "\n".join(lines) + "\n\nUse open_pdf with one of these URLs to view it."


DATASHEET_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "find_datasheet",
            "description": (
                "Search the web for an official manufacturer PDF datasheet for a "
                "part number or product name. Returns a list of candidate links -- "
                "use open_pdf on the best match to actually view it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "part_or_product": {
                        "type": "string",
                        "description": "The part number or product name to find a datasheet for.",
                    },
                },
                "required": ["part_or_product"],
            },
        },
    },
]

DATASHEET_TOOL_FUNCTIONS = {"find_datasheet": find_datasheet}

# Read-only -- only searches the web, never opens or changes anything.
DATASHEET_RISKY_TOOLS = set()
