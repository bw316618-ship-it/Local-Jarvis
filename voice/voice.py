"""
Voice I/O for Jarvis.

Speech-to-text runs locally via faster-whisper (a CTranslate2 port of
OpenAI's Whisper). Text-to-speech runs locally via Piper (a fast neural
TTS engine, ONNX-based) -- swapped in for the earlier pyttsx3 engine,
which drove the OS's built-in voices (SAPI5 on Windows) and sounded
noticeably more robotic/dated by comparison, on top of being platform-
dependent in what voices are even available. Piper ships its own voice
models instead, so quality and available voices are the same on every
platform. Neither sends audio or transcripts anywhere -- consistent with
the rest of Jarvis running fully offline.

Piper voice models aren't bundled (they're a model download, not a
Python package) -- download a voice's .onnx + .onnx.json pair from
https://github.com/rhasspy/piper/blob/master/VOICES.md and place both
files in a voices/ folder at the project root. Point CONFIG
["piper_voice_model"] (jarvis_config.json) at the .onnx file's path,
relative to the project root, if you want something other than the
default. The sample rate a voice plays back at is read straight from its
own config.json (via PiperVoice.config.sample_rate) rather than
hardcoded, so switching voice models never requires also updating a
separate playback-rate constant to match.

Recording is silence-based by default: listen() starts capturing once it
hears speech and stops automatically after a pause, via the Silero VAD
model bundled inside openwakeword (already a dependency for /wake, so
this adds no new install). No need to guess a duration for "talk
naturally" -- explicitly passing a duration still works too, for when
you know you'll need more time regardless of pauses.

Imports for the audio/ML libraries are deferred to inside the methods
rather than the top of this file. That way, if sounddevice, faster-whisper,
or piper fail to install or load (e.g. no microphone, no speakers, a
headless machine, no voice model downloaded yet), the rest of Jarvis
still starts and works in text-only mode -- only /voice and /speak fail,
with a clear error explaining why.
"""

import os
import queue
import tempfile
import threading
from pathlib import Path

from config import CONFIG

# Windows without Developer Mode (or without running as admin) can't create
# symlinks, so huggingface_hub's model cache falls back to copying files
# instead -- harmless (just slightly more disk space), but it prints a
# scary-looking warning on every first use if left unset. setdefault() so
# this doesn't override anything the user has explicitly configured.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

BASE_DIR = Path(__file__).resolve().parent.parent
VOICES_DIR = BASE_DIR / "voices"

DEFAULT_LISTEN_SECONDS = CONFIG["voice_listen_seconds"]
SAMPLE_RATE = 16000  # mic input rate for STT/VAD -- independent of Piper's output rate

VAD_FRAME_SIZE = 480  # 30ms @ 16kHz -- Silero VAD's recommended frame size
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
        """Queue `text` to be spoken without blocking the caller."""
        if not text:
            return
        self._ensure_speech_worker()
        self._speech_queue.put(text)

    def warm_up(self) -> None:
        """Pre-load the STT and TTS models in the background at startup."""
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
                    "Speech-to-text isn't available: faster-whisper is not "
                    "installed or failed to load. Run: pip install -r requirements.txt"
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
                    f"Text-to-speech isn't available: voice model "
                    f"'{model_path}' not found. Download a Piper voice "
                    "(.onnx + .onnx.json) from "
                    "https://github.com/rhasspy/piper/blob/master/VOICES.md, "
                    "place both files in the 'voices/' folder, and set "
                    "\"piper_voice_model\" in jarvis_config.json if the "
                    "filename differs from the default."
                )

            try:
                print("Loading text-to-speech voice (first use only)...")
                self._tts_voice = PiperVoice.load(str(model_path))
            except Exception as e:
                raise RuntimeError(
                    f"Text-to-speech isn't available: could not load Piper "
                    f"voice model '{model_path}': {e}"
                ) from e
        return self._tts_voice

    def _get_vad(self):
        if self._vad is None:
            from openwakeword import VAD
            self._vad = VAD()
        return self._vad

    def _transcribe(self, recording) -> str:
        """Write a float32 mono array to a temp wav and run it through Whisper."""
        tmp_path = None
        try:
            import soundfile as sf

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            sf.write(tmp_path, recording, SAMPLE_RATE)

            model = self._get_stt_model()
            segments, _ = model.transcribe(tmp_path)
            return " ".join(segment.text for segment in segments).strip()
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _listen_fixed_duration(self, duration: int) -> str:
        """Record exactly `duration` seconds, regardless of pauses."""
        try:
            import sounddevice as sd
        except (ImportError, OSError) as e:
            raise RuntimeError(
                "Voice input isn't available: sounddevice couldn't load "
                "(missing package, or no audio device found). Run: "
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

        return self._transcribe(recording)

    def _listen_until_silence(self) -> str:
        """Start recording once speech is heard, stop automatically after a pause."""
        try:
            import numpy as np
            import sounddevice as sd
        except (ImportError, OSError) as e:
            raise RuntimeError(
                "Voice input isn't available: sounddevice couldn't load "
                "(missing package, or no audio device found). Run: "
                "pip install -r requirements.txt, and check a microphone is connected."
            ) from e

        try:
            vad = self._get_vad()
        except (ImportError, OSError) as e:
            raise RuntimeError(
                "Voice input isn't available: openwakeword's VAD model "
                "couldn't load. Run: pip install -r requirements.txt"
            ) from e

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
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=VAD_FRAME_SIZE) as stream:
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
                                return ""  # nobody spoke -- give up quietly
                        continue

                    recorded_chunks.append(chunk)
                    recorded_frames += 1
                    silence_run = 0 if is_speech else silence_run + 1

                    if silence_run >= silence_frames_to_stop:
                        break
                    if recorded_frames >= max_recording_frames:
                        break
        except Exception as e:
            raise RuntimeError(
                "Could not record audio. Check that a microphone is "
                "connected and that the app has microphone permission."
            ) from e

        if not recorded_chunks:
            return ""

        import numpy as np
        recording = np.concatenate(recorded_chunks).astype(np.float32) / 32768.0
        return self._transcribe(recording)

    def listen(self, duration: int = None) -> str:
        """Record from the microphone and return the transcribed text.

        If `duration` is given, records for exactly that many seconds
        regardless of pauses (handy for '/voice 10' when you know you'll
        need more time). If omitted, recording starts when speech is
        detected and stops automatically after a pause -- no need to
        guess a duration for natural conversation.
        """
        if duration:
            return self._listen_fixed_duration(duration)
        return self._listen_until_silence()

    def speak(self, text: str) -> None:
        """Speak `text` aloud through the default speaker, via Piper."""
        if not text:
            return

        voice = self._get_tts_voice()

        try:
            import sounddevice as sd
            import numpy as np
        except (ImportError, OSError) as e:
            raise RuntimeError(
                "Text-to-speech isn't available: sounddevice couldn't load "
                "(missing package, or no audio device found). Run: "
                "pip install -r requirements.txt"
            ) from e

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
