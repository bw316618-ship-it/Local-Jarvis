"""
Wake-word detection for Jarvis ("Hey Jarvis"), via openWakeWord.

Runs a blocking microphone listen loop: small audio chunks are fed to a
lightweight local ONNX model that scores how "hey jarvis"-like each chunk
sounds. When the score crosses a threshold, the caller (main.py) switches
into recording the actual command via JarvisVoice.listen(), the same as
the manual /voice command does.

The "hey jarvis" model ships bundled inside the openwakeword package
itself -- no separate download step, unlike faster-whisper's model.
Everything here runs fully locally.
"""

CHUNK_SAMPLES = 1280  # 80ms at 16kHz -- what openWakeWord expects per call
SAMPLE_RATE = 16000
DEFAULT_THRESHOLD = 0.5
WAKEWORD_KEY = "hey_jarvis_v0.1"


def listen_for_wake_word(threshold: float = DEFAULT_THRESHOLD, on_listening=None) -> bool:
    """Block until "hey jarvis" is detected, then return True.

    Raises KeyboardInterrupt naturally on Ctrl+C (not caught here) so the
    caller can use that to exit wake-word mode cleanly.
    `on_listening`, if given, is called once right before the mic stream
    opens, so the caller can print a status message at the right moment.
    """
    try:
        import numpy as np
        import sounddevice as sd
        from openwakeword.model import Model
        import openwakeword
    except (ImportError, OSError) as e:
        raise RuntimeError(
            "Wake-word detection isn't available: openwakeword/sounddevice "
            "couldn't load. Run: pip install -r requirements.txt"
        ) from e

    model = Model(wakeword_model_paths=[openwakeword.models["hey_jarvis"]["model_path"]])

    if on_listening:
        on_listening()

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=CHUNK_SAMPLES) as stream:
            while True:
                audio_chunk, _ = stream.read(CHUNK_SAMPLES)
                scores = model.predict(audio_chunk.flatten())
                if scores.get(WAKEWORD_KEY, 0.0) >= threshold:
                    return True
    except KeyboardInterrupt:
        raise
    except Exception as e:
        raise RuntimeError(f"Wake-word listening failed: {e}") from e
