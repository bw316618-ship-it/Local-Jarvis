"""Voice I/O for Jarvis."""

import os
import queue
import threading
from pathlib import Path

from config import CONFIG
from voice import session_state

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

BASE_DIR = Path(__file__).resolve().parent.parent
VOICES_DIR = BASE_DIR / "voices"
DEFAULT_LISTEN_SECONDS = CONFIG["voice_listen_seconds"]
SAMPLE_RATE = 16000
VAD_FRAME_SIZE = 480
VAD_SPEECH_THRESHOLD = 0.5


class JarvisVoice:
    def __init__(self, whisper_model: str = None, piper_voice_model: str = None):
        self._whisper_model_name = whisper_model or CONFIG["whisper_model"]
        self._piper_model_name = piper_voice_model or CONFIG["piper_voice_model"]
        self._stt_model = None
        self._tts_voice = None
        self._vad = None
        self._speech_queue = queue.Queue()
        self._speech_thread = None

    def _ensure_speech_worker(self):
        if self._speech_thread is None or not self._speech_thread.is_alive():
            self._speech_thread = threading.Thread(target=self._speech_worker, daemon=True)
            self._speech_thread.start()

    def _speech_worker(self):
        while True:
            text = self._speech_queue.get()
            try:
                if text is None:
                    return
                self.speak(text)
            except Exception:
                pass
            finally:
                self._speech_queue.task_done()

    def speak_async(self, text: str) -> None:
        if not text or session_state.is_muted():
            return
        self._ensure_speech_worker()
        self._speech_queue.put(text)

    def warm_up(self) -> None:
        try:
            self._get_tts_voice()
        except Exception:
            pass
        try:
            self._get_stt_model()
        except Exception:
            pass

    def _get_stt_model(self):
        if self._stt_model is None:
            try:
                from faster_whisper import WhisperModel
            except (ImportError, OSError) as e:
                raise RuntimeError(
                    "Speech-to-text isn't available: faster-whisper is not installed "
                    "or failed to load. Run: pip install -r requirements.txt"
                ) from e
            print("Loading speech recognition model (first use only)...")
            self._stt_model = WhisperModel(
                self._whisper_model_name, device="cpu", compute_type="int8"
            )
        return self._stt_model

    def _get_tts_voice(self):
        if self._tts_voice is None:
            try:
                from piper import PiperVoice
            except ImportError as e:
                raise RuntimeError(
                    "Text-to-speech isn't available: the piper-tts package "
                    "is not installed. Run: pip install -r requirements.txt"
                ) from e

            model_path = (BASE_DIR / self._piper_model_name).resolve()
            if not model_path.exists():
                raise RuntimeError(
                    f"Text-to-speech isn't available: voice model '{model_path}' not found."
                )

            try:
                print("Loading text-to-speech voice (first use only)...")
                self._tts_voice = PiperVoice.load(str(model_path))
            except Exception as e:
                raise RuntimeError(
                    f"Text-to-speech isn't available: could not load Piper voice model '{model_path}': {e}"
                ) from e
        return self._tts_voice

    def _get_vad(self):
        if self._vad is None:
            from openwakeword import VAD
            self._vad = VAD()
        return self._vad

    def _transcribe(self, recording) -> str:
        """Transcribe a float32 mono NumPy array directly with Whisper."""
        model = self._get_stt_model()
        segments, _ = model.transcribe(recording)
        return " ".join(segment.text for segment in segments).strip()


    def listen(self, duration: int = None) -> str:
        if duration:
            return self._listen_fixed_duration(duration)
        return self._listen_until_silence()

    def speak(self, text: str) -> None:
        if not text or session_state.is_muted():
            return

        voice = self._get_tts_voice()

        try:
            import sounddevice as sd
            import numpy as np
        except (ImportError, OSError) as e:
            raise RuntimeError("Text-to-speech isn't available.") from e

        try:
            chunks = [
                np.frombuffer(audio_chunk.audio_int16_bytes, dtype=np.int16)
                for audio_chunk in voice.synthesize(text)
            ]
        except Exception as e:
            raise RuntimeError(f"Piper failed to synthesize speech: {e}") from e

        if not chunks:
            return

        audio = np.concatenate(chunks)
        try:
            sd.play(audio, samplerate=voice.config.sample_rate)
            sd.wait()
        except Exception as e:
            raise RuntimeError(f"Could not play synthesized audio: {e}") from e
