"""
Voice I/O for Jarvis.

Speech-to-text runs locally via faster-whisper (a CTranslate2 port of
OpenAI's Whisper). Text-to-speech runs locally via pyttsx3, which drives
the OS's built-in voices (SAPI5 on Windows). Neither sends audio or
transcripts anywhere -- consistent with the rest of Jarvis running fully
offline.

Imports for the audio/ML libraries are deferred to inside the methods
rather than the top of this file. That way, if sounddevice, faster-whisper,
or pyttsx3 fail to install or load (e.g. no microphone, no speakers, a
headless machine), the rest of Jarvis still starts and works in text-only
mode -- only /voice and /speak fail, with a clear error explaining why.
"""

import os
import tempfile

DEFAULT_LISTEN_SECONDS = 6
SAMPLE_RATE = 16000


class JarvisVoice:
    def __init__(self, whisper_model: str = "base.en"):
        self._whisper_model_name = whisper_model
        self._stt_model = None
        self._tts_engine = None

    def _get_stt_model(self):
        if self._stt_model is None:
            try:
                from faster_whisper import WhisperModel
            except (ImportError, OSError) as e:
                raise RuntimeError(
                    "Speech-to-text isn't available: faster-whisper is not "
                    "installed or failed to load. Run: pip install -r requirements.txt"
                ) from e

            print("Loading speech recognition model (first use only)...")
            self._stt_model = WhisperModel(
                self._whisper_model_name, device="cpu", compute_type="int8"
            )
        return self._stt_model

    def _get_tts_engine(self):
        if self._tts_engine is None:
            try:
                import pyttsx3
            except (ImportError, OSError) as e:
                raise RuntimeError(
                    "Text-to-speech isn't available: pyttsx3 is not "
                    "installed or failed to load. Run: pip install -r requirements.txt"
                ) from e

            try:
                self._tts_engine = pyttsx3.init()
            except Exception as e:
                raise RuntimeError(
                    "Text-to-speech isn't available: the local speech engine "
                    "failed to start. On Windows this uses the built-in SAPI5 "
                    "voices and should work out of the box; check Windows "
                    "Settings > Speech if this persists."
                ) from e
        return self._tts_engine

    def listen(self, duration: int = DEFAULT_LISTEN_SECONDS) -> str:
        """Record `duration` seconds from the default microphone and
        return the transcribed text (empty string if nothing was said)."""
        try:
            import sounddevice as sd
            import soundfile as sf
        except (ImportError, OSError) as e:
            raise RuntimeError(
                "Voice input isn't available: sounddevice/soundfile couldn't "
                "load (missing package, or no audio device found). Run: "
                "pip install -r requirements.txt, and check a microphone is connected."
            ) from e

        try:
            recording = sd.rec(
                int(duration * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
            )
            sd.wait()
        except Exception as e:
            raise RuntimeError(
                "Could not record audio. Check that a microphone is "
                "connected and that the app has microphone permission."
            ) from e

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            sf.write(tmp_path, recording, SAMPLE_RATE)

            model = self._get_stt_model()
            segments, _ = model.transcribe(tmp_path)
            return " ".join(segment.text for segment in segments).strip()
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    def speak(self, text: str) -> None:
        """Speak `text` aloud through the default speaker."""
        if not text:
            return
        engine = self._get_tts_engine()
        engine.say(text)
        engine.runAndWait()
