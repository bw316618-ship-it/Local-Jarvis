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

Type `exit` or `quit` to end the session.

### Voice

- `/voice` — record 6 seconds from your microphone and send it as your message (`/voice 10` records for 10 seconds instead)
- `/speak on` / `/speak off` — toggle whether Jarvis speaks its replies aloud (off by default)

Both run fully locally: speech-to-text via faster-whisper, text-to-speech via your OS's built-in voices (SAPI5 on Windows). The first time you use `/voice`, it downloads a small Whisper model (~150 MB) and caches it -- expect a short delay only on that first use.

### Full system access

Jarvis can now run shell commands, launch apps/files/URLs, control the mouse and keyboard, read/write/delete files anywhere on the machine, and search the web when a task needs current information.

**Every action that changes something on your machine asks for your confirmation first** -- Jarvis will show you exactly what it wants to run and wait for a yes/no. This covers: running commands, opening applications, clicking, typing, hotkeys, and writing or deleting files outside its own `workspace/` sandbox. Reads (files, directory listings, web search) run without asking, since they can't change anything.

## Roadmap

Original planned capabilities -- all shipped:

1. ~~**Tool calling**~~ — done. Jarvis can invoke functions (calculator, current time, directory listing) instead of just chatting.
2. ~~**File management**~~ — done. Sandboxed read/write/delete tools scoped to a `workspace/` folder.
3. ~~**Voice assistant**~~ — done. `/voice` for speech input, `/speak on` for spoken replies.
4. ~~**Desktop automation**~~ — done. Shell commands, app launching, mouse/keyboard control, unrestricted file access, and web search -- all gated by confirmation for anything risky.

## Project structure

```
Local-Jarvis/
├── start_jarvis.bat     # Windows double-click launcher
├── main.py              # CLI entry point / chat loop
├── brain/
│   └── llm.py            # Ollama LLM wrapper + tool-calling loop + confirmation gating
├── memory/
│   └── retriever.py       # ChromaDB-backed semantic search
├── ingest/
│   └── ingest.py          # Document ingestion into the vector store
├── tools/
│   ├── tools.py            # Central tool registry (schemas, functions, risky-tool set)
│   ├── file_manager.py     # Sandboxed file read/write/delete tools (workspace/ only)
│   ├── full_access_files.py # Unrestricted file read/write/delete (confirmed for writes/deletes)
│   ├── system.py            # Shell commands + app launching (confirmed)
│   ├── desktop_control.py   # Mouse/keyboard control (confirmed)
│   └── web.py                # Web search (read-only, not confirmed)
├── voice/
│   └── voice.py            # Local speech-to-text (faster-whisper) + text-to-speech (pyttsx3)
├── workspace/            # Sandbox folder file tools operate in (gitignored)
└── requirements.txt
```
