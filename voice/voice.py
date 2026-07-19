"""
Voice I/O for Jarvis.

Speech-to-text runs locally via faster-whisper (a CTranslate2 port of
OpenAI's Whisper). Text-to-speech runs locally via pyttsx3, which drives
the OS's built-in voices (SAPI5 on Windows). Neither sends audio or
transcripts anywhere -- consistent with the rest of Jarvis running fully
offline.

Recording is silence-based by default: listen() starts capturing once it
hears speech and stops automatically after a pause, via the Silero VAD
model bundled inside openwakeword (already a dependency for /wake, so
this adds no new install). No need to guess a duration for "talk
naturally" -- explicitly passing a duration still works too, for when
you know you'll need more time regardless of pauses.

Imports for the audio/ML libraries are deferred to inside the methods
rather than the top of this file. That way, if sounddevice, faster-whisper,
or pyttsx3 fail to install or load (e.g. no microphone, no speakers, a
headless machine), the rest of Jarvis still starts and works in text-only
mode -- only /voice and /speak fail, with a clear error explaining why.
"""

import os
import tempfile

from config import CONFIG

# Windows without Developer Mode (or without running as admin) can't create
# symlinks, so huggingface_hub's model cache falls back to copying files
# instead -- harmless (just slightly more disk space), but it prints a
# scary-looking warning on every first use if left unset. setdefault() so
# this doesn't override anything the user has explicitly configured.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

DEFAULT_LISTEN_SECONDS = CONFIG["voice_listen_seconds"]
SAMPLE_RATE = 16000

VAD_FRAME_SIZE = 480  # 30ms @ 16kHz -- Silero VAD's recommended frame size
VAD_SPEECH_THRESHOLD = 0.5


class JarvisVoice:
    def __init__(self, whisper_model: str = None):
        self._whisper_model_name = whisper_model or CONFIG["whisper_model"]
        self._stt_model = None
        self._tts_engine = None
        self._vad = None

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
        """Speak `text` aloud through the default speaker."""
        if not text:
            return
        engine = self._get_tts_engine()
        engine.say(text)
        engine.runAndWait()
