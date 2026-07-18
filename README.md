# Local-Jarvis

A local, offline AI assistant built in Python — CLI-based, with retrieval-augmented generation (RAG) over your own documents.

## Features

- Offline LLM via [Ollama](https://ollama.com) (`llama3.1:8b`)
- Local retrieval-augmented generation (RAG)
- Semantic document search
- ChromaDB vector database for local, persistent storage
- Document ingestion for building your knowledge base
- Runs completely offline — no data leaves your machine

## Quick start (Windows)

Download this repo as a ZIP, extract it anywhere, and double-click **`start_jarvis.bat`**.

On the first run it will create a virtual environment and install dependencies automatically -- this can take a few minutes. Every run after that starts instantly. Make sure [Python 3.11](https://www.python.org/downloads/) and [Ollama](https://ollama.com) are installed first (the script will tell you if either is missing).

## Requirements

- Python 3.11
- [Ollama](https://ollama.com) installed and running locally

## Setup

If you're not using `start_jarvis.bat` (e.g. on macOS/Linux, or if you prefer running things manually), set up by hand:

Install dependencies:

```bash
pip install -r requirements.txt
```

> **Windows users:** if you ever regenerate `requirements.txt` yourself (e.g. via `pip freeze`), make sure to write it as UTF-8. PowerShell's default redirection (`>`) encodes as UTF-16LE, which breaks `pip install -r requirements.txt`. Use `pip freeze | Out-File -Encoding utf8 requirements.txt` instead.

Download the model:

```bash
ollama pull llama3.1:8b
```

## Usage

Ingest documents into your local knowledge base (do this manually even if you're using `start_jarvis.bat`, which only launches the chat loop):

```bash
python ingest/ingest.py
```

Run the assistant:

```bash
python main.py
```

Type `exit` or `quit` to end the session, or `/help` any time to see the full command list.

### Configuration

Defaults (model name, tool-call round limit, voice/wake-word settings, which folders get indexed, chunk sizes) live in `config.py`. To change any of them without editing code, copy `jarvis_config.example.json` to `jarvis_config.json` at the project root and set just the keys you want -- everything else keeps its default. `jarvis_config.json` is gitignored, so personal tweaks (a different Ollama model, custom indexed folders) don't get committed. Unknown keys and malformed JSON are warned about and ignored rather than crashing the app.

### Audit log

Every tool call -- what ran, when, the arguments, and whether it needed (and got) your confirmation -- is recorded to `memory/audit_log.jsonl`. Run `/log` to see the last 20 calls, or `/log 50` for more.

### Saving a conversation

`/save` writes the current session to a Markdown file under `transcripts/` (or `/save path/to/file.md` for a custom location). This is just an export for your own records, not memory Jarvis reads back -- see the next section for that.

### Long-term memory

Jarvis remembers past conversations across sessions -- not by pasting the whole history into every prompt (the local model's context window is too small for that), but by semantically recalling the few most relevant past turns for whatever you're currently asking. Ask something like *"continue the authentication system"* and Jarvis checks whether an earlier session already covered what was decided.

- Every turn (your message + Jarvis's reply) is automatically stored after each response -- no command needed.
- Stored in a separate ChromaDB collection (`jarvis_conversations`) from the manual RAG store and the file index, so the three don't collide.
- `/forget` permanently clears all stored conversation memory (asks for confirmation first -- this can't be undone).

Worth knowing: every turn gets stored, including trivial ones ("what time is it?"), rather than trying to judge what's "important" -- semantic search naturally deprioritizes irrelevant entries at retrieval time, so this is mostly harmless, but it does mean the store grows indefinitely with no pruning yet. If that becomes noisy over long-term use, periodic summarization/pruning would be the natural next refinement.

### Voice

- `/voice` — record 6 seconds from your microphone and send it as your message (`/voice 10` records for 10 seconds instead)
- `/wake` — always-listening mode: say "Hey Jarvis" and it'll prompt "Yes?" then record your command, same as `/voice` but hands-free. Press Ctrl+C to stop and return to typed input.
- `/speak on` / `/speak off` — toggle whether Jarvis speaks its replies aloud (off by default)

Speech-to-text runs via faster-whisper, text-to-speech via your OS's built-in voices (SAPI5 on Windows), and the wake word via openWakeWord -- all fully local. The first time you use `/voice` or `/wake`, faster-whisper downloads a small model (~150 MB) and caches it; the wake-word model ships bundled in the package itself, no download needed.

### Screen reading

Jarvis can capture and read the screen via OCR (`rapidocr-onnxruntime`, no external OCR program like Tesseract required):

- `read_screen_text` — see everything currently visible on screen as text
- `find_text_on_screen` — locate a specific label (e.g. "Save", "Submit") and get its coordinates, meant to be paired with `mouse_click`
- `take_screenshot` — save a PNG of the current screen

All three are read-only, so none require confirmation. Worth knowing: this reads *text*, not layout or images -- Jarvis can find a button by its label but doesn't have general visual understanding of icons or graphics (that would need a vision-capable model, which isn't part of this setup).

### Full system access

Jarvis can now run shell commands, launch apps/files/URLs, control the mouse and keyboard, read/write/delete files anywhere on the machine, and search the web when a task needs current information.

**Every action that changes something on your machine asks for your confirmation first** -- Jarvis will show you exactly what it wants to run and wait for a yes/no. This covers: running commands, opening applications, clicking, typing, hotkeys, and writing or deleting files outside its own `workspace/` sandbox. Reads (files, directory listings, web search) run without asking, since they can't change anything.

### Semantic file search

Find files by what they're *about*, not just their name -- e.g. "find the PDF where I wrote about binary trees" -- across `.txt`, `.md`, `.py`, `.pdf`, and `.docx` files.

- `/index` — (re)index your Documents, Desktop, and Downloads folders. Only new or changed files are processed each time, so it's cheap to run again later.
- Once indexed, just ask normally -- e.g. "find my notes about the Flask project" -- and Jarvis calls `search_files` automatically.

This is separate from the manual `ingest/ingest.py` knowledge base: that one is for documents you deliberately curate, this one is for finding *anything* on disk without ingesting it by hand first. Note there's no background file-watcher yet -- re-run `/index` when you want it to notice new or changed files.

### Git integration

Structured git tools instead of guessing the right flags through the generic command runner: `git_status`, `git_log`, `git_diff`, and `git_branch_list` run freely (read-only); `git_add`, `git_commit`, `git_checkout`, and `git_push` all ask for confirmation first, since git mistakes are often more annoying to undo than a file operation.

### Planning

For anything that looks like it needs more than one step (e.g. "create a Flask API, run it, test it, fix errors, commit"), Jarvis first sketches a short plan and shows it to you before touching any tools, then works through it step by step -- adjusting if a step's result changes what's needed, rather than following the plan blindly. Simple questions skip this and go straight to an answer. Each step gets printed live as it works.

## Vision

The goal isn't a chatbot with some tools bolted on -- it's treating the whole computer as something you talk to. Not "open Explorer, search folders, open Chrome, copy files" but "find the PDF where I wrote about binary trees" and it just knows. Eventually the OS becomes the hardware layer and Jarvis becomes the interface.

## Roadmap

**Phase 1 — Foundation** ✅ *done*
Offline LLM, local RAG, CLI, file indexing.

**Phase 2 — File & system control** ✅ *done*
File manipulation (sandboxed and unrestricted), opening apps, running terminal commands, semantic file search, and structured git tools (status/log/diff/branch free, add/commit/checkout/push confirmed).

**Phase 3 — Planning & reasoning** ✅ *done*
Tool selection (the model picks which tool to call per turn) plus an explicit planning step for multi-step tasks: a short plan is generated and shown before execution, then followed step by step with room to adapt if something unexpected happens. The round limit for a single request went from 6 to 15 to give multi-step tasks room to actually finish.

**Phase 4 — Voice** ✅ *done*
Speech input (`/voice`), offline recognition (faster-whisper), text-to-speech (`/speak on`), and now always-listening wake word (`/wake`, "Hey Jarvis" via openWakeWord).

**Phase 5 — Desktop automation** ✅ *done*
Mouse and keyboard control, plus screen reading via OCR (`read_screen_text`, `find_text_on_screen`, `take_screenshot`) so Jarvis can find and click things by their visible label. Reads text only, not general visual/layout understanding -- that would need a vision-capable model, which isn't part of this setup.

**Phase 6 — Long-term memory** ✅ *done*
Every conversation turn is automatically stored and semantically recalled in future sessions, so Jarvis can pick up context from earlier work ("continue the authentication system") without you re-explaining it. `/forget` clears it all if needed. Not covered: explicit user-preference modeling or habit tracking as a distinct concept -- everything is stored uniformly as conversation turns, and habit *learning* specifically (noticing patterns and proactively acting on them) is Phase 7's job.

**Phase 7 — Self-improvement** — *not started*
Proactive suggestions ("you search this folder daily, should I index it permanently?", "this script has failed three times, want a fix?"). This is the one phase left -- and the only one that couldn't have started before now, since it depends on Phase 6's memory to notice patterns at all.

## Project structure

```
Local-Jarvis/
├── start_jarvis.bat     # Windows double-click launcher
├── main.py              # CLI entry point / chat loop
├── config.py             # Central config defaults + jarvis_config.json loader
├── jarvis_config.example.json # Template -- copy to jarvis_config.json to override defaults
├── brain/
│   └── llm.py            # Ollama LLM wrapper + tool-calling loop + confirmation gating + audit logging
├── memory/
│   ├── retriever.py       # ChromaDB-backed semantic search over manually-ingested docs
│   ├── conversation_memory.py # Long-term memory: stores + recalls past conversation turns
│   ├── audit_log.py        # Records every tool call to memory/audit_log.jsonl
│   └── transcript.py       # Session transcript tracking + /save export
├── ingest/
│   └── ingest.py          # Manual document ingestion into the 'jarvis_memory' collection
├── tools/
│   ├── tools.py            # Central tool registry (schemas, functions, risky-tool set)
│   ├── file_manager.py     # Sandboxed file read/write/delete tools (workspace/ only)
│   ├── full_access_files.py # Unrestricted file read/write/delete (confirmed for writes/deletes)
│   ├── file_index.py        # Whole-computer semantic file search + incremental indexer
│   ├── git_tools.py          # Structured git tools (status/log/diff/branch free, rest confirmed)
│   ├── system.py            # Shell commands + app launching (confirmed)
│   ├── desktop_control.py   # Mouse/keyboard control (confirmed)
│   ├── screen.py             # Screenshots + OCR (read-only, not confirmed)
│   └── web.py                # Web search (read-only, not confirmed)
├── voice/
│   ├── voice.py            # Local speech-to-text (faster-whisper) + text-to-speech (pyttsx3)
│   └── wake_word.py         # "Hey Jarvis" wake-word detection (openWakeWord)
├── workspace/            # Sandbox folder file tools operate in (gitignored)
├── transcripts/          # Saved /save exports (gitignored)
└── requirements.txt
```
