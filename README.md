# Local-Jarvis

A local, offline-first AI assistant for Windows (also runs on macOS/Linux with reduced features) — CLI-based, voice-capable, with retrieval-augmented generation over your own documents and broad control over your machine.

The goal isn't a chatbot with some tools bolted on. It's "find the PDF where I wrote about binary trees" and it just knows — not "open Explorer, search folders, open the file." Eventually the OS becomes the hardware layer and Jarvis becomes the interface.

> **Status:** all 8 roadmap phases below are complete. Currently in active tuning — see [Model notes](#model-notes) for the current model/latency work.

---

## Table of contents

- [Features](#features)
- [Quick start](#quick-start)
- [Manual setup](#manual-setup)
- [Talking to Jarvis](#talking-to-jarvis)
  - [Terminal chat](#terminal-chat)
  - [Graphical HUD](#graphical-hud)
  - [Standalone daemon (browser-only)](#standalone-daemon-browser-only)
- [Configuration](#configuration)
- [Model notes](#model-notes)
- [Command reference](#command-reference)
- [What Jarvis can do](#what-jarvis-can-do)
- [Safety: confirmation gating](#safety-confirmation-gating)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Roadmap](#roadmap)

---

## Features

- **Offline LLM** via [Ollama](https://ollama.com), tool-calling loop with confirmation gating on anything state-changing
- **Streaming responses** — replies print and (optionally) speak sentence-by-sentence as they generate, not after the whole reply is ready
- **Short-term + long-term memory** — verbatim recent turns for pronoun-heavy follow-ups ("open it", "try that again"), plus semantic recall of past sessions and explicitly remembered facts (`remember_fact`)
- **Plan-skip heuristic** — only genuinely multi-step requests pay for an extra planning round-trip
- **Local RAG** over documents you ingest, plus whole-computer semantic file search (`search_files`) — separate from the manual ingest store
- **Voice in/out** — wake word ("Hey Jarvis"), pause-detection recording, local TTS (Piper), background model warm-up
- **Vision** — screen OCR (`read_screen_text`, `find_text_on_screen`) plus general image understanding via a local Moondream model
- **Full desktop control** — files (sandboxed *and* unrestricted), windows, mouse/keyboard, shell commands, git
- **Graphical HUD** — an optional browser-based reactor/"data storm" visualization with a live chat panel and browser-side confirmation prompts, in addition to the terminal
- **Standalone daemon mode** — run Jarvis as a background process reachable purely from a browser tab, independent of any terminal session
- **Self-improvement** — proactive suggestions (`/insights`) from patterns in its own audit log: repeated failures, repeated searches, folder growth
- **Real-time diagnostics** — `/status` for CPU/memory/disk/top processes
- Runs completely offline — no data leaves your machine

## Quick start

### Windows

Download this repo as a ZIP, extract it anywhere, and double-click **`start_jarvis.bat`**.

### macOS / Linux

```bash
./start_jarvis.sh
```

If double-clicking it in Finder opens a text editor instead of running it, the executable bit was likely stripped during extraction — run `chmod +x start_jarvis.sh` once.

Both launchers create a virtual environment and install dependencies on first run only (a marker file in `venv/` skips that step on every run after). Make sure **[Python 3.11](https://www.python.org/downloads/)** and **[Ollama](https://ollama.com)** are installed first — the scripts will warn you if either is missing.

Once Ollama is installed, pull the default model:

```bash
ollama pull qwen3:4b
```

## Manual setup

If you'd rather not use the launch scripts:

```bash
pip install -r requirements.txt
ollama pull qwen3:4b
python main.py
```

> **Windows + `pip freeze`:** if you ever regenerate `requirements.txt` yourself, write it as UTF-8 — PowerShell's default `>` redirection encodes UTF-16LE, which breaks `pip install -r requirements.txt`. Use `pip freeze | Out-File -Encoding utf8 requirements.txt` instead.

Ingest documents into the manual knowledge base (optional, do this whenever you want — it's separate from the chat loop):

```bash
python ingest/ingest.py <folder>
```

## Talking to Jarvis

There are three ways to run Jarvis, depending on how you want to interact with it.

### Terminal chat

```bash
python main.py
```

The default CLI loop — full command set (`/voice`, `/wake`, `/log`, `/save`, etc.), confirmation prompts printed inline. Type `exit` or `quit` to end the session, `/help` any time for the full command list.

### Graphical HUD

From inside the terminal chat, run `/hud` to open a local browser tab with a live reactor/storm visualization, a chat panel, and browser-side confirmation prompts for risky tool calls — layered on top of the same `JarvisLLM` instance the terminal is driving. Run `/hud` again to close it.

### Standalone daemon (browser-only)

```bash
python jarvis_daemon.py
```

Runs Jarvis with **no terminal input loop at all** — just its own `JarvisLLM` plus the HUD bridge, so closing the terminal that launched it doesn't have to kill it (background/detach it at the OS level if you want it to outlive the terminal — see the docstring in `jarvis_daemon.py` for the exact `nohup`/`pythonw` incantations per platform). Chat and tool confirmations happen entirely through the browser tab it opens.

Voice (`/voice`, `/wake`) and terminal-only commands (`/log`, `/save`, `/insights`, etc.) are **not** available here — those are `main.py` CLI features layered on top of `JarvisLLM`, not part of the core assistant itself.

## Configuration

Defaults live in `config.py`. To override any of them, copy `jarvis_config.example.json` to `jarvis_config.json` at the project root and set just the keys you want — everything else keeps its default. `jarvis_config.json` is gitignored, so personal tweaks never get committed. Unknown keys and malformed JSON are warned about and ignored, not crashed on.

| Key | Default | Used by |
|---|---|---|
| `model` | `qwen3:4b` | `brain/llm.py` |
| `num_ctx` | `8192` | `brain/llm.py` — raise if tool schemas get silently truncated |
| `max_tool_rounds` | `15` | `brain/llm.py` |
| `short_term_turns` | `6` | `brain/llm.py` — verbatim (user, jarvis) turn pairs kept per session |
| `whisper_model` | `base.en` | `voice/voice.py` |
| `voice_listen_seconds` | `6` | `voice/voice.py` (fixed-duration fallback) |
| `voice_silence_seconds` | `1.2` | `voice/voice.py` — pause length that ends VAD recording |
| `voice_max_wait_seconds` | `6` | `voice/voice.py` — give up if nobody speaks |
| `voice_max_recording_seconds` | `30` | `voice/voice.py` — hard cap regardless of pauses |
| `wake_word_threshold` | `0.5` | `voice/wake_word.py` |
| `command_timeout_seconds` | `30` | `tools/system.py`, `tools/git_tools.py` |
| `index_roots` | `null` (→ Documents/Desktop/Downloads) | `tools/file_index.py` |
| `index_chunk_size` / `index_chunk_overlap` | `500` / `50` | `tools/file_index.py`, `ingest/ingest.py` |
| `index_max_file_mb` | `20` | `tools/file_index.py` |
| `piper_voice_model` | `voices/en_US-amy-medium.onnx` | `voice/voice.py` |
| `hud_http_port` / `hud_ws_port` | `8765` / `8766` | `ui/hud_server.py` |

## Model notes

**Why `qwen3:4b`, not a larger model:** Qwen3 is trained specifically for tool calling and has a meaningfully lower rate of dropped/incorrect tool calls than similarly-sized general models — directly relevant here, since the whole tool-use loop depends on the model reliably deciding *whether* to call a tool, not just formatting the call correctly. `llama3.1:8b` still works (`"model": "llama3.1:8b"` in `jarvis_config.json`) if you'd rather use the more battle-tested option.

**VRAM-constrained setups:** on cards around 6GB VRAM, 8B-class models split across CPU/GPU and get slow. `qwen3:4b` fits fully in VRAM on most such cards; if you're evaluating pulls, `qwen3:4b-instruct-2507-q4_K_M` is non-thinking by architecture (rather than relying on a `think=False` flag, which isn't honored by every pull's chat template) and has improved tool-calling reliability over earlier `qwen3:4b` builds.

**Piper voices** aren't bundled — download a `.onnx` + `.onnx.json` pair from the [Piper voices list](https://github.com/rhasspy/piper/blob/master/VOICES.md), place both in `voices/`, and point `piper_voice_model` at the `.onnx` file if it's not the default.

## Command reference

| Command | What it does |
|---|---|
| `/help` | Show the full command list |
| `/index` | (Re)index Documents/Desktop/Downloads for semantic file search |
| `/insights` | Check for proactive suggestions based on recent activity |
| `/status` | CPU, memory, disk, and top processes at a glance |
| `/memory [category]` | List facts Jarvis has explicitly remembered about you |
| `/hud` | Toggle the graphical HUD (opens/closes a local browser tab) |
| `/voice [N]` | Speak your message — stops automatically after a pause, or record for a fixed N seconds |
| `/wake` | Always-listening mode — say "Hey Jarvis" (Ctrl+C to stop) |
| `/speak on\|off` | Toggle whether Jarvis speaks replies aloud |
| `/save [path]` | Save this session's transcript to Markdown |
| `/log [n]` | Show the last n tool calls (default 20) |
| `/forget` | Permanently clear long-term conversation memory and remembered facts |
| `exit` / `quit` | End the session |

## What Jarvis can do

Everything else is just a normal message — Jarvis decides on its own whether a tool call is needed.

- **Files** — sandboxed read/write/delete inside `workspace/` (always auto-approved reads/writes within the sandbox), or unrestricted read/write/delete/rename/move/organize anywhere on the machine (writes confirmed)
- **Semantic file search** — `search_files`/`index_files` find files by what they're *about* across `.txt`, `.md`, `.py`, `.pdf`, `.docx`
- **System** — run shell commands, open apps/files/URLs (confirmed), live diagnostics (`system_status`, `top_processes`, read-only)
- **Desktop** — mouse/keyboard control (confirmed), window list/focus/minimize/close by title substring (list is read-only, the rest confirmed)
- **Screen & vision** — OCR the screen (`read_screen_text`, `find_text_on_screen`, read-only) or ask a local vision model what's actually on screen or in an image (`describe_image`, read-only); saving a screenshot to disk (`take_screenshot`) is confirmed, since it's a file write to an arbitrary path
- **Git** — structured `git_status`/`git_log`/`git_diff`/`git_branch_list` (free), `git_add`/`git_commit`/`git_checkout`/`git_push` (confirmed)
- **Web** — `web_search` for anything current or external (read-only)
- **Memory** — `remember_fact` for durable facts worth persisting across sessions (confirmed, since it's replayed into every future prompt as "known facts about the user")

## Safety: confirmation gating

Every tool that changes something on your machine — running commands, opening apps, clicking, typing, hotkeys, focusing/minimizing/closing windows, writing/deleting/renaming/moving/organizing files outside the sandbox, saving a screenshot to disk, remembering a fact for future sessions, and any git operation that mutates repo state — asks for your explicit confirmation first, whether you're in the terminal or the HUD. Reads (files, directory listings, web search, window listing, screen OCR text) never ask, since they can't change anything. See `tools/tools.py`'s `RISKY_TOOLS` set and `tests/test_tools_registry.py` for the exact split.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

The suite covers confirmation gating, the chat/planning/streaming flow, memory storage on every exit path, file-safety edge cases (including sandbox-escape attempts), incremental indexing, insight/pattern detection, and config loading. Heavy runtime dependencies (Ollama, ChromaDB, sentence-transformers) are mocked, so it stays fast and doesn't need the full model stack installed.

## Project structure

```
Local-Jarvis/
├── start_jarvis.bat / start_jarvis.sh   # Launchers (venv + deps on first run)
├── main.py                              # CLI entry point / chat loop
├── jarvis_daemon.py                     # Headless daemon: JarvisLLM + HUD only, no terminal loop
├── config.py                            # Central config defaults + jarvis_config.json loader
├── jarvis_config.example.json           # Copy to jarvis_config.json to override defaults
├── pytest.ini
├── brain/
│   ├── llm.py              # Ollama wrapper, streaming tool-calling loop, short-term memory, plan-skip
│   └── session.py          # Shared confirm-callback + HUD/console plumbing used by main.py and jarvis_daemon.py
├── memory/
│   ├── shared.py           # Shared embedder + ChromaDB client singletons
│   ├── document_store.py   # Shared chunk/embed/index logic behind both RAG stores (manual + discovered)
│   ├── retriever.py        # Semantic search over manually-ingested docs
│   ├── conversation_memory.py  # Long-term turns + structured remembered facts
│   ├── audit_log.py        # Every tool call -> memory/audit_log.jsonl
│   ├── insights.py         # Pattern detection over the audit log -> /insights
│   └── transcript.py       # Session export -> /save
├── ingest/
│   └── ingest.py           # Manual document ingestion
├── tools/
│   ├── tools.py             # Central registry: schemas, functions, risky-tool set
│   ├── file_manager.py      # Sandboxed file ops (workspace/ only)
│   ├── full_access_files.py # Unrestricted file ops (writes confirmed)
│   ├── file_index.py        # Whole-computer semantic file search
│   ├── git_tools.py         # Structured git tools
│   ├── system.py            # Shell commands + app launching (confirmed)
│   ├── desktop_control.py   # Mouse/keyboard (confirmed)
│   ├── window_control.py    # Window list/focus/minimize/close (Windows/macOS only)
│   ├── screen.py             # Screenshots (confirmed) + OCR (read-only)
│   ├── vision.py             # Image/screen understanding via local Moondream
│   ├── diagnostics.py        # CPU/memory/disk/process stats -> /status
│   ├── memory_tools.py       # remember_fact wrapper (confirmed)
│   └── web.py                 # Web search
├── voice/
│   ├── voice.py             # STT (faster-whisper) + TTS (Piper) + VAD recording
│   └── wake_word.py         # "Hey Jarvis" detection (openWakeWord)
├── ui/
│   ├── splash.py            # Terminal boot animation
│   ├── thinking.py           # Inline "thinking" pulse while waiting on a reply
│   ├── hud_server.py         # HTTP + WebSocket bridge for the graphical HUD
│   └── hud/static/           # HUD frontend (reactor/storm visuals, chat panel)
├── tests/                  # pytest suite
├── workspace/              # File-tool sandbox (gitignored)
├── transcripts/            # /save exports (gitignored)
├── requirements.txt
└── requirements-dev.txt
```

## Roadmap

| Phase | Status | Covers |
|---|---|---|
| 1 — Foundation | ✅ | Offline LLM, local RAG, CLI, file indexing |
| 2 — File & system control | ✅ | Sandboxed + unrestricted file ops, app/command execution, semantic search, structured git tools |
| 3 — Planning & reasoning | ✅ | Per-turn tool selection, plan-skip heuristic for multi-step requests |
| 4 — Voice | ✅ | `/voice`, `/wake`, Piper TTS, background model warm-up |
| 5 — Desktop automation & vision | ✅ | Mouse/keyboard, screen OCR, Moondream vision |
| 6 — Long-term memory | ✅ | Cross-session recall, `/forget` |
| 7 — Self-improvement | ✅ | `/insights` pattern detection |
| 8 — Responsiveness | ✅ | Streaming, short-term memory, plan-skip |
| 9 — Graphical surfaces *(unreleased phase)* | ✅ (code present, undocumented until now) | `/hud`, `jarvis_daemon.py` standalone browser mode |

Bigger directions still on the table: system-tray / persistent background mode by default, two-tier model routing (a `/think-hard` command routing occasional hard-reasoning tasks to a larger local model), and more autonomous agent behavior.
