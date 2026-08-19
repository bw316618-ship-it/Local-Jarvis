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

    def _listen_fixed_duration(self, duration: int) -> str:
        try:
            import sounddevice as sd
        except (ImportError, OSError) as e:
            raise RuntimeError(
                "Voice input isn't available: sounddevice couldn't load."
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
            raise RuntimeError("Could not record audio.") from e

        return self._transcribe(recording)

    def _listen_until_silence(self) -> str:
        try:
            import numpy as np
            import sounddevice as sd
        except (ImportError, OSError) as e:
            raise RuntimeError("Voice input isn't available.") from e

        try:
            vad = self._get_vad()
        except (ImportError, OSError) as e:
            raise RuntimeError("Voice input isn't available: VAD couldn't load.") from e

        frame_seconds = VAD_FRAME_SIZE / SAMPLE_RATE
        silence_frames_to_stop = max(1, int(CONFIG["voice_silence_seconds"] / frame_seconds))
        max_wait_frames = max(1, int(CONFIG["voice_max_wait_seconds"] / frame_seconds))
        max_recording_frames = max(1, int(CONFIG["voice_max_recording_seconds"] / frame_seconds))

        recorded_chunks = []
        started_speaking = False
        silence_run = 0
        waited_frames = 0
        recorded_frames = 0

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=VAD_FRAME_SIZE,
            ) as stream:
                while True:
                    chunk, _ = stream.read(VAD_FRAME_SIZE)
                    chunk = chunk.flatten()
                    is_speech = vad.predict(chunk) >= VAD_SPEECH_THRESHOLD

                    if not started_speaking:
                        if is_speech:
                            started_speaking = True
                            recorded_chunks.append(chunk)
                            recorded_frames += 1
                        else:
                            waited_frames += 1
                            if waited_frames >= max_wait_frames:
                                return ""
                        continue

                    recorded_chunks.append(chunk)
                    recorded_frames += 1
                    silence_run = 0 if is_speech else silence_run + 1

                    if silence_run >= silence_frames_to_stop:
                        break
                    if recorded_frames >= max_recording_frames:
                        break
        except Exception as e:
            raise RuntimeError("Could not record audio.") from e

        if not recorded_chunks:
            return ""

        import numpy as np
        recording = np.concatenate(recorded_chunks).astype(np.float32) / 32768.0
        return self._transcribe(recording)

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
