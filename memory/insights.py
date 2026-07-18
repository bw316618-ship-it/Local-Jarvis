"""
Self-improvement / proactive suggestions for Jarvis -- Phase 7.

Looks for patterns in the audit log (memory/audit_log.jsonl) and in
tracked folder sizes to surface things you might not have noticed
yourself: a command that keeps failing, a search you keep repeating, a
folder that's ballooned in size. This is the first cut at "self-
improvement": noticing patterns using the audit trail Phase 6-era
logging already built, not autonomous action -- Jarvis surfaces
suggestions, it doesn't act on them without being asked.

Suggestions are computed on demand (`/insights`) and once automatically
at startup, rather than via a continuous background watcher -- Jarvis
has no persistent background process (that's what system-tray mode would
add, and it's a bigger, separate undertaking -- see the README). So
"proactive" here means "checked at natural touchpoints", not
"continuously monitored".

Known limitation: pattern matching on repeated actions is exact-match on
the tool + arguments, not semantic -- searching for "flask project" and
"the flask project setup" won't be recognized as the same repeated
interest. Catching near-duplicate phrasing would need embedding-based
clustering; left as a natural next refinement if exact-match doesn't
catch enough in practice.
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memory.audit_log import LOG_PATH
from config import CONFIG

BASE_DIR = Path(__file__).resolve().parent.parent
SIZE_SNAPSHOT_PATH = BASE_DIR / "memory" / "folder_size_snapshot.json"

REPEAT_THRESHOLD = 3            # same successful action N+ times -> worth mentioning
FAILURE_THRESHOLD = 3           # same action failing N+ times -> worth mentioning
LOOKBACK_DAYS = 14              # only consider recent activity
SIZE_GROWTH_THRESHOLD_MB = 500  # only flag growth above this

# Tools where "you keep doing this" is a meaningful suggestion. Deliberately
# excludes cheap/trivial tools (calculate, get_current_time, list_directory,
# read_file, screen_size, ...) where repetition is normal and not interesting.
REPEAT_WORTHY_TOOLS = {"search_files", "open_application", "run_command", "web_search", "git_status", "git_log"}

# Verified against the actual failure strings tools in this codebase return
# (see tools/*.py, brain/llm.py) rather than guessed generically.
FAILURE_MARKERS = ("error", "could not", "failed", "does not exist", "timed out", "not installed", "invalid", "refus")


def _load_recent_entries() -> list:
    if not LOG_PATH.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    entries = []
    try:
        for line in LOG_PATH.read_text(encoding="utf-8").strip().splitlines():
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts >= cutoff:
                    entries.append(entry)
            except Exception:
                continue
    except Exception:
        return []
    return entries


def _signature(entry: dict) -> str:
    """A dedup key for 'the same action' -- tool name + its exact arguments."""
    tool = entry.get("tool", "")
    args = entry.get("arguments") or {}
    return f"{tool}::{json.dumps(args, sort_keys=True)}"


def _looks_like_failure(entry: dict) -> bool:
    preview = (entry.get("result_preview") or "").lower()
    if not preview:
        return False
    return any(marker in preview for marker in FAILURE_MARKERS)


def _find_repeated_failures(failed_entries: list) -> list:
    groups = defaultdict(list)
    for e in failed_entries:
        groups[_signature(e)].append(e)

    suggestions = []
    for group in groups.values():
        if len(group) >= FAILURE_THRESHOLD:
            tool = group[0].get("tool")
            args = group[0].get("arguments") or {}
            suggestions.append(
                f"`{tool}({args})` has failed {len(group)} times in the last "
                f"{LOOKBACK_DAYS} days. Want help figuring out why?"
            )
    return suggestions


def _find_repeated_actions(successful_entries: list) -> list:
    relevant = [e for e in successful_entries if e.get("tool") in REPEAT_WORTHY_TOOLS]
    groups = defaultdict(list)
    for e in relevant:
        groups[_signature(e)].append(e)

    suggestions = []
    for group in groups.values():
        if len(group) >= REPEAT_THRESHOLD:
            tool = group[0].get("tool")
            args = group[0].get("arguments") or {}
            suggestions.append(
                f"You've called `{tool}({args})` {len(group)} times in the last "
                f"{LOOKBACK_DAYS} days. Want this remembered as something to check "
                f"automatically?"
            )
    return suggestions


def _tracked_folders() -> list:
    return CONFIG["index_roots"] or [
        str(Path.home() / "Documents"),
        str(Path.home() / "Desktop"),
        str(Path.home() / "Downloads"),
    ]


def _folder_size_mb(path: Path) -> float:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    continue
    except Exception:
        pass
    return total / (1024 * 1024)


def _check_folder_growth() -> list:
    """Compare tracked folder sizes against the last snapshot, then update it."""
    snapshot = {}
    if SIZE_SNAPSHOT_PATH.exists():
        try:
            snapshot = json.loads(SIZE_SNAPSHOT_PATH.read_text())
        except Exception:
            snapshot = {}

    suggestions = []
    new_snapshot = dict(snapshot)

    for folder in _tracked_folders():
        path = Path(folder).expanduser()
        if not path.exists():
            continue

        size_mb = _folder_size_mb(path)
        new_snapshot[folder] = size_mb

        previous = snapshot.get(folder)
        if previous is not None:
            growth = size_mb - previous
            if growth >= SIZE_GROWTH_THRESHOLD_MB:
                suggestions.append(
                    f"{path.name} has grown by {growth:.0f} MB since it was last "
                    f"checked (now {size_mb / 1024:.1f} GB)."
                )

    try:
        SIZE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SIZE_SNAPSHOT_PATH.write_text(json.dumps(new_snapshot))
    except Exception:
        pass

    return suggestions


def get_suggestions(include_folder_check: bool = True) -> list:
    """Return a list of proactive suggestion strings (empty if nothing stands out)."""
    entries = _load_recent_entries()
    failures = [e for e in entries if _looks_like_failure(e)]
    successes = [e for e in entries if not _looks_like_failure(e)]

    suggestions = []
    suggestions.extend(_find_repeated_failures(failures))
    suggestions.extend(_find_repeated_actions(successes))
    if include_folder_check:
        suggestions.extend(_check_folder_growth())

    return suggestions
