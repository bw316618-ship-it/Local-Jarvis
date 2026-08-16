# Third-Party Licenses

Local-Jarvis uses third-party software, models, datasets, and services.
Each component remains subject to its own license and terms.

## Runtime and AI

### Ollama
- Purpose: Local LLM runtime
- Website: https://ollama.com/
- License: See Ollama's current license and terms
- Local-Jarvis does not distribute Ollama.

### Qwen3
- Purpose: Default local language model
- Model: `qwen3:4b`
- License: See the specific Qwen model license
- Local-Jarvis does not claim ownership of the Qwen model or its weights.

### Moondream
- Purpose: Local image/vision understanding
- License: See the specific Moondream model license
- Model files are not distributed with Local-Jarvis unless explicitly stated.

### Whisper
- Purpose: Local speech recognition
- License: MIT
- Repository: https://github.com/openai/whisper

## Voice

### Piper
- Purpose: Local text-to-speech
- License: See the Piper project and the specific voice model license
- Voice models may have licenses separate from the Piper software.
- Local-Jarvis does not claim ownership of third-party voice models.

## Location Data

### MaxMind GeoLite2
- Purpose: Offline IP-based geographic lookup fallback
- License/Terms: MaxMind GeoLite2 terms
- The GeoLite2 database is not bundled with Local-Jarvis.
- Users must obtain the database according to MaxMind's terms.

## Python Dependencies

Local-Jarvis also depends on third-party Python packages listed in:

`requirements.txt`

Each dependency remains subject to its respective license.

Users redistributing Local-Jarvis should review the licenses of all installed
dependencies and optional components.

## Important Notice

The MIT License applies to the Local-Jarvis source code authored by the
Local-Jarvis contributors. It does not replace or override the licenses of
third-party software, models, datasets, voices, or other external components.

Third-party components may have additional attribution, redistribution,
commercial-use, or usage requirements. Users are responsible for complying
with the applicable terms for those components.
