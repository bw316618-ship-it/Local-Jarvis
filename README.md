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

## Roadmap

Planned capabilities, roughly in build order:

1. ~~**Tool calling**~~ — done. Jarvis can invoke functions (calculator, current time, directory listing) instead of just chatting.
2. ~~**File management**~~ — done. Sandboxed read/write/delete tools scoped to a `workspace/` folder.
3. **Voice assistant** — speech-to-text input and text-to-speech output
4. **Desktop automation** — control local apps and workflows

## Project structure

```
Local-Jarvis/
├── start_jarvis.bat     # Windows double-click launcher
├── main.py              # CLI entry point / chat loop
├── brain/
│   └── llm.py            # Ollama LLM wrapper + tool-calling loop
├── memory/
│   └── retriever.py       # ChromaDB-backed semantic search
├── ingest/
│   └── ingest.py          # Document ingestion into the vector store
├── tools/
│   ├── tools.py            # Tool registry (calculator, time, directory listing)
│   └── file_manager.py     # Sandboxed file read/write/delete tools
├── workspace/            # Sandbox folder file tools operate in (gitignored)
└── requirements.txt
```
