# Local-Jarvis

A local, offline-first AI assistant for Windows (also runs on macOS/Linux with reduced features), CLI-based, voice-capable, with retrieval-augmented generation over your own documents and broad control over your machine.

The goal isn't a chatbot with some tools bolted on. It's "find the PDF where I wrote about binary trees" and it just knows, not "open Explorer, search folders, open the file." Eventually the OS becomes the hardware layer and Jarvis becomes the interface.

> Status: all 8 original roadmap phases are complete, plus a graphical HUD phase and a first tier of new tools (battery, location, calendar, PDF viewer, datasheet search, media control, session control). See the Roadmap section for what's next.

![Jarvis Demo](assets/Jarvis.gif)
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
- [Optional setup for newer tools](#optional-setup-for-newer-tools)
- [Safety: confirmation gating](#safety-confirmation-gating)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Roadmap](#roadmap)

---

## Features

- Offline LLM via [Ollama](https://ollama.com), tool-calling loop with confirmation gating on anything state-changing
- Streaming responses, replies print and (optionally) speak sentence by sentence as they generate, not after the whole reply is ready
- Short-term and long-term memory: verbatim recent turns for pronoun-heavy follow-ups ("open it", "try that again"), plus semantic recall of past sessions and explicitly remembered facts (`remember_fact`)
- Plan-skip heuristic, only genuinely multi-step requests pay for an extra planning round-trip
- Local RAG over documents you ingest, plus whole-computer semantic file search (`search_files`), separate from the manual ingest store
- Voice in and out: wake word ("Hey Jarvis"), pause-detection recording, local TTS (Piper), background model warm-up, mid-session mute
- Vision: screen OCR (`read_screen_text`, `find_text_on_screen`) plus general image understanding via a local Moondream model
- Full desktop control: files (sandboxed and unrestricted), windows, mouse and keyboard, shell commands, git
- Graphical HUD: an optional browser-based reactor/"data storm" visualization with a live chat panel and browser-side confirmation prompts, in addition to the terminal
- Standalone daemon mode: run Jarvis as a background process reachable purely from a browser tab, independent of any terminal session, with its own launcher scripts
- Self-improvement: proactive suggestions (`/insights`) from patterns in its own audit log: repeated failures, repeated searches, folder growth
- Real-time diagnostics: `/status` for CPU, memory, disk, top processes, and battery level
- Location awareness, preferring OS-native location services on Windows and macOS, falling back to a local offline database rather than a live third-party API
- A local task and calendar store backed by a standard ICS file, so tasks can be added, listed, completed, or deleted, and the file itself can be opened in any calendar app
- PDF opening and datasheet search, so Jarvis can find and open a manufacturer PDF without you doing the browsing yourself
- Media playback control and now-playing lookups, OS-level, no music service account required
- A way to end the current session or mute spoken output by asking, not just by typing a slash command
- Runs completely offline, no data leaves your machine except where a specific tool's docstring says otherwise (see [Optional setup for newer tools](#optional-setup-for-newer-tools))

## Quick start

### Windows

Download this repo as a ZIP, extract it anywhere, and double-click `start_jarvis.bat` for the normal terminal chat experience, or `start_jarvis_daemon.bat` to run Jarvis headless with only the graphical HUD as the interface.

### macOS / Linux

```bash
./start_jarvis.sh
```

or, for headless daemon mode:

```bash
./start_jarvis_daemon.sh
```

If double-clicking a script in Finder opens a text editor instead of running it, the executable bit was likely stripped during extraction. Run `chmod +x start_jarvis.sh start_jarvis_daemon.sh` once.

All four launchers create a virtual environment and install dependencies on first run only (a marker file in `venv/` skips that step on every run after, and it is shared between the regular and daemon launchers). Make sure [Python 3.11](https://www.python.org/downloads/) and [Ollama](https://ollama.com) are installed first, the scripts will warn you if either is missing.

Once Ollama is installed, pull the default model:

```bash
ollama pull qwen3:4b
```

## Manual setup

If you would rather not use the launch scripts:

```bash
pip install -r requirements.txt
ollama pull qwen3:4b
python main.py
```

> Windows and pip freeze: if you ever regenerate `requirements.txt` yourself, write it as UTF-8. PowerShell's default `>` redirection encodes UTF-16LE, which breaks `pip install -r requirements.txt`. Use `pip freeze | Out-File -Encoding utf8 requirements.txt` instead.

Ingest documents into the manual knowledge base (optional, do this whenever you want, it is separate from the chat loop):

```bash
python ingest/ingest.py <folder>
```

## Talking to Jarvis

There are three ways to run Jarvis, depending on how you want to interact with it.

### Terminal chat

```bash
python main.py
```

The default CLI loop, full command set (`/voice`, `/wake`, `/log`, `/save`, and so on), confirmation prompts printed inline. Type `exit` or `quit` to end the session, or simply ask Jarvis to end the session or disconnect. `/help` any time for the full command list.

### Graphical HUD

From inside the terminal chat, run `/hud` to open a local browser tab with a live reactor/storm visualization, a chat panel, and browser-side confirmation prompts for risky tool calls, layered on top of the same `JarvisLLM` instance the terminal is driving. Run `/hud` again to close it.

### Standalone daemon (browser-only)

```bash
python jarvis_daemon.py
```

or use `start_jarvis_daemon.bat` / `start_jarvis_daemon.sh` to handle the virtual environment setup for you.

Runs Jarvis with no terminal input loop at all, just its own `JarvisLLM` plus the HUD bridge, so closing the terminal that launched it does not have to kill it (background or detach it at the OS level if you want it to outlive the terminal, see the docstring in `jarvis_daemon.py` for the exact `nohup`/`pythonw` commands per platform). Chat and tool confirmations happen entirely through the browser tab it opens.

Voice (`/voice`, `/wake`) and terminal-only commands (`/log`, `/save`, `/insights`, and so on) are not available here, those are `main.py` CLI features layered on top of `JarvisLLM`, not part of the core assistant itself.

## Configuration

Defaults live in `config.py`. To override any of them, copy `jarvis_config.example.json` to `jarvis_config.json` at the project root and set just the keys you want, everything else keeps its default. `jarvis_config.json` is gitignored, so personal tweaks never get committed. Unknown keys and malformed JSON are warned about and ignored, not crashed on.

| Key | Default | Used by |
|---|---|---|
| `model` | `qwen3:4b` | `brain/llm.py` |
| `num_ctx` | `8192` | `brain/llm.py`, raise if tool schemas get silently truncated |
| `max_tool_rounds` | `15` | `brain/llm.py` |
| `short_term_turns` | `6` | `brain/llm.py`, verbatim (user, jarvis) turn pairs kept per session |
| `whisper_model` | `base.en` | `voice/voice.py` |
| `voice_listen_seconds` | `6` | `voice/voice.py` (fixed-duration fallback) |
| `voice_silence_seconds` | `1.2` | `voice/voice.py`, pause length that ends VAD recording |
| `voice_max_wait_seconds` | `6` | `voice/voice.py`, give up if nobody speaks |
| `voice_max_recording_seconds` | `30` | `voice/voice.py`, hard cap regardless of pauses |
| `wake_word_threshold` | `0.5` | `voice/wake_word.py` |
| `command_timeout_seconds` | `30` | `tools/system.py`, `tools/git_tools.py` |
| `index_roots` | `null` (goes to Documents/Desktop/Downloads) | `tools/file_index.py` |
| `index_chunk_size` / `index_chunk_overlap` | `500` / `50` | `tools/file_index.py`, `ingest/ingest.py` |
| `index_max_file_mb` | `20` | `tools/file_index.py` |
| `piper_voice_model` | `voices/en_US-amy-medium.onnx` | `voice/voice.py` |
| `hud_http_port` / `hud_ws_port` | `8765` / `8766` | `ui/hud_server.py` |

## Model notes

Why `qwen3:4b`, not a larger model: Qwen3 is trained specifically for tool calling and has a meaningfully lower rate of dropped or incorrect tool calls than similarly sized general models, directly relevant here, since the whole tool-use loop depends on the model reliably deciding whether to call a tool, not just formatting the call correctly. `llama3.1:8b` still works (`"model": "llama3.1:8b"` in `jarvis_config.json`) if you would rather use the more battle-tested option.

VRAM-constrained setups: on cards around 6GB VRAM, 8B-class models split across CPU and GPU and get slow. `qwen3:4b` fits fully in VRAM on most such cards. If you are evaluating pulls, `qwen3:4b-instruct-2507-q4_K_M` is non-thinking by architecture (rather than relying on a `think=False` flag, which is not honored by every pull's chat template) and has improved tool-calling reliability over earlier `qwen3:4b` builds.

Piper voices are not bundled, download a `.onnx` and `.onnx.json` pair from the [Piper voices list](https://github.com/rhasspy/piper/blob/master/VOICES.md), place both in `voices/`, and point `piper_voice_model` at the `.onnx` file if it is not the default.

## Command reference

| Command | What it does |
|---|---|
| `/help` | Show the full command list |
| `/index` | (Re)index Documents/Desktop/Downloads for semantic file search |
| `/insights` | Check for proactive suggestions based on recent activity |
| `/status` | CPU, memory, disk, top processes, and battery level at a glance |
| `/memory [category]` | List facts Jarvis has explicitly remembered about you |
| `/hud` | Toggle the graphical HUD (opens/closes a local browser tab) |
| `/voice [N]` | Speak your message, stops automatically after a pause, or record for a fixed N seconds |
| `/wake` | Always-listening mode, say "Hey Jarvis" (Ctrl+C to stop) |
| `/speak on\|off` | Toggle whether Jarvis speaks replies aloud |
| `/save [path]` | Save this session's transcript to Markdown |
| `/log [n]` | Show the last n tool calls (default 20) |
| `/forget` | Permanently clear long-term conversation memory and remembered facts |
| `exit` / `quit` | End the session |

Jarvis can also end the session or mute itself when asked in plain language, without a slash command. See the mute and disconnect entries under "What Jarvis can do."

## What Jarvis can do

Everything else is just a normal message, Jarvis decides on its own whether a tool call is needed.

- Files: sandboxed read, write, and delete inside `workspace/` (always auto-approved reads and writes within the sandbox), or unrestricted read, write, delete, rename, move, and organize anywhere on the machine (writes confirmed)
- Semantic file search: `search_files`/`index_files` find files by what they are about across `.txt`, `.md`, `.py`, `.pdf`, `.docx`
- System: run shell commands, open apps, files, and URLs (confirmed), live diagnostics (`system_status`, `top_processes`, `get_battery_level`, all read-only)
- Desktop: mouse and keyboard control (confirmed), window list, focus, minimize, and close by title substring (list is read-only, the rest confirmed)
- Screen and vision: OCR the screen (`read_screen_text`, `find_text_on_screen`, read-only) or ask a local vision model what is actually on screen or in an image (`describe_image`, read-only); saving a screenshot to disk (`take_screenshot`) is confirmed, since it is a file write to an arbitrary path
- Git: structured `git_status`/`git_log`/`git_diff`/`git_branch_list` (free), `git_add`/`git_commit`/`git_checkout`/`git_push` (confirmed)
- Web: `web_search` for anything current or external (read-only)
- Memory: `remember_fact` for durable facts worth persisting across sessions (confirmed, since it is replayed into every future prompt as "known facts about the user")
- Location: `get_location`, preferring OS-native services on Windows and macOS, falling back to a local offline database elsewhere (read-only)
- Calendar: `add_task`, `list_tasks`, `complete_task` (all safe), `delete_task` (confirmed, since it is a permanent removal), backed by a local ICS file at `memory/jarvis_calendar.ics`
- Documents: `open_pdf` to open a local file or URL in the default viewer (confirmed, since it launches an external app), `find_datasheet` to search for a manufacturer PDF (read-only)
- Media: `control_media` for play, pause, skip, and volume (confirmed, since it drives an external app), `get_now_playing` to check the current track (read-only)
- Session control: `mute_jarvis`/`unmute_jarvis` to toggle spoken output (safe, instantly reversible), `end_session` to disconnect (confirmed, since it is not easily reversible once the loop exits)

## Optional setup for newer tools

A few of the newer tools need something installed or downloaded beyond `pip install -r requirements.txt`, either because the dependency is platform-specific or because a license prevents bundling it directly. Every one of these degrades gracefully with a clear message if the optional piece is missing, nothing else in Jarvis is affected.

- Location on Windows: install `winsdk` (`pip install winsdk`) for OS-native Windows Location Services. Without it, Jarvis falls back to the local database below.
- Location on macOS: install `pyobjc-framework-CoreLocation` for OS-native macOS Location Services. Without it, Jarvis falls back to the local database below.
- Location fallback (Linux, or Windows/macOS without the packages above): download a free `GeoLite2-City.mmdb` database from MaxMind and place it in `geoip/GeoLite2-City.mmdb`. Steps are in `tools/location.py`'s module docstring and in `geoip/README.md`. This lookup is entirely offline once the file is downloaded; the only network call in this path is a plain IP-echo request used to learn the machine's own public IP, no location data is sent anywhere.
- Now playing on Windows: install `winsdk` (`pip install winsdk`) for the WinRT media session API. Music control on Windows (play, pause, skip, volume) works without any extra install, it uses simulated media key presses.
- Music control and now-playing on Linux: install `playerctl` through your package manager (for example `sudo apt install playerctl`), not a Python package.
- Music control and now-playing on macOS: no extra install, this uses AppleScript against Music.app.

None of these packages are added to `requirements.txt` unconditionally, since `winsdk` and `pyobjc-framework-CoreLocation` only have wheels for their respective platforms and would break installation everywhere else.

## Safety: confirmation gating

Every tool that changes something on your machine, running commands, opening apps, clicking, typing, hotkeys, focusing/minimizing/closing windows, writing/deleting/renaming/moving/organizing files outside the sandbox, saving a screenshot to disk, remembering a fact for future sessions, deleting a calendar task, opening a PDF, controlling media playback, ending the session, and any git operation that mutates repo state, asks for your explicit confirmation first, whether you are in the terminal or the HUD. Reads (files, directory listings, web search, window listing, screen OCR text, location, now-playing, calendar listings) never ask, since they cannot change anything. See `tools/tools.py`'s `RISKY_TOOLS` set and `tests/test_tools_registry.py` for the exact split.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

The suite covers confirmation gating, the chat/planning/streaming flow, memory storage on every exit path, file-safety edge cases (including sandbox-escape attempts), incremental indexing, insight/pattern detection, config loading, the local calendar store, battery reporting, mute and end-session state, and the location tool's fallback ordering (tested against MaxMind's real public GeoLite2 test database, not a mock). Heavy runtime dependencies (Ollama, ChromaDB, sentence-transformers) are mocked, so it stays fast and does not need the full model stack installed.

## Project structure

```
Local-Jarvis/
├── start_jarvis.bat / start_jarvis.sh              # Terminal launchers (venv + deps on first run)
├── start_jarvis_daemon.bat / start_jarvis_daemon.sh # Daemon launchers, share the venv with the above
├── main.py                              # CLI entry point / chat loop
├── jarvis_daemon.py                     # Headless daemon: JarvisLLM + HUD only, no terminal loop
├── config.py                            # Central config defaults + jarvis_config.json loader
├── jarvis_config.example.json           # Copy to jarvis_config.json to override defaults
├── pytest.ini
├── geoip/
│   └── README.md            # Where to place a downloaded GeoLite2-City.mmdb
├── brain/
│   ├── llm.py              # Ollama wrapper, streaming tool-calling loop, short-term memory, plan-skip
│   └── session.py          # Shared confirm-callback + HUD/console plumbing used by main.py and jarvis_daemon.py
├── memory/
│   ├── shared.py           # Shared embedder + ChromaDB client singletons
│   ├── document_store.py   # Shared chunk/embed/index logic behind both RAG stores (manual + discovered)
│   ├── retriever.py        # Semantic search over manually-ingested docs
│   ├── conversation_memory.py  # Long-term turns + structured remembered facts
│   ├── audit_log.py        # Every tool call goes to memory/audit_log.jsonl
│   ├── insights.py         # Pattern detection over the audit log, feeds /insights
│   └── transcript.py       # Session export, feeds /save
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
│   ├── diagnostics.py        # CPU/memory/disk/process/battery stats, feeds /status
│   ├── memory_tools.py       # remember_fact wrapper (confirmed)
│   ├── web.py                 # Web search
│   ├── location.py            # OS-native location, falling back to a local offline database
│   ├── calendar_tool.py       # Local ICS-backed task store (add/list/complete/delete)
│   ├── pdf_viewer.py          # open_pdf, opens a local file or URL in the default viewer
│   ├── datasheet.py           # find_datasheet, targeted web search for manufacturer PDFs
│   ├── media.py               # control_media and get_now_playing, OS-level
│   └── session_control.py     # mute_jarvis/unmute_jarvis/end_session
├── voice/
│   ├── voice.py             # STT (faster-whisper) + TTS (Piper) + VAD recording, checks the mute flag
│   ├── wake_word.py         # "Hey Jarvis" detection (openWakeWord)
│   └── session_state.py     # Shared mute flag and end-session flag, the bridge between tools and the running loop
├── ui/
│   ├── splash.py            # Terminal boot animation
│   ├── thinking.py           # Inline "thinking" pulse while waiting on a reply
│   ├── hud_server.py         # HTTP + WebSocket bridge for the graphical HUD
│   └── hud/static/           # HUD frontend (reactor/storm visuals, chat panel)
├── tests/                  # pytest suite
├── workspace/              # File-tool sandbox (gitignored)
├── transcripts/             # /save exports (gitignored)
├── requirements.txt
└── requirements-dev.txt
```

## Roadmap

| Phase | Status | Covers |
|---|---|---|
| 1, Foundation | Done | Offline LLM, local RAG, CLI, file indexing |
| 2, File and system control | Done | Sandboxed and unrestricted file ops, app/command execution, semantic search, structured git tools |
| 3, Planning and reasoning | Done | Per-turn tool selection, plan-skip heuristic for multi-step requests |
| 4, Voice | Done | `/voice`, `/wake`, Piper TTS, background model warm-up |
| 5, Desktop automation and vision | Done | Mouse/keyboard, screen OCR, Moondream vision |
| 6, Long-term memory | Done | Cross-session recall, `/forget` |
| 7, Self-improvement | Done | `/insights` pattern detection |
| 8, Responsiveness | Done | Streaming, short-term memory, plan-skip |
| 9, Graphical surfaces | Done | `/hud`, `jarvis_daemon.py` standalone browser mode, daemon launcher scripts |
| 10, First new-tools tier | Done | Battery, location (OS-native with offline fallback), calendar, PDF opening, datasheet search, media control, now playing, mute and end-session |

Bigger directions still on the table: webcam capture and an X-ray-style vision effect built on the existing Moondream pipeline, a HUD widget system (text notes, open/close/reset, a home dashboard widget, an in-HUD PDF viewer, map control), a system tray application with always-listening mode decoupled from the CLI, a floating transparent desktop overlay, and local image generation through a diffusion backend such as Automatic1111 or ComfyUI. Smart home integration and 3D printing support are explicitly out of scope for this project.
