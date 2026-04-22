"""
Smart Mirror — Voice Engine
Wake-word detection via Vosk keyword spotting + Speech-to-Text.
Replaces paid Porcupine with free, offline Vosk.
"""

import os
import json
import base64
import logging
from backend.config import VOSK_MODEL_PATH, WAKE_WORD, AUDIO_SAMPLE_RATE

logger = logging.getLogger(__name__)

# Vosk is optional — graceful fallback if model not downloaded
try:
    from vosk import Model, KaldiRecognizer
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False
    logger.warning("Vosk not installed. Voice pipeline disabled.")

# Buffer size: accumulate at least this many bytes before feeding Vosk.
# 16-bit mono @ 16kHz: 8000 bytes = 4000 samples = 250ms
MIN_VOSK_BYTES = 8000


class VoiceEngine:
    """
    Processes raw PCM audio chunks for:
      1. Wake-word detection ("Hey Lumo") via continuous transcription
      2. Command capture after wake-word is detected

    Audio arrives as base64-encoded 16-bit PCM @ 16 kHz mono,
    already downsampled by the frontend from the browser's native rate.
    """

    def __init__(self):
        self.model = None
        self.recognizer = None
        self.is_active = False          # Waiting for command after wake word
        self.silence_counter = 0
        self.MAX_SILENCE_CHUNKS = 15    # ~3.75s of silence at 250ms chunks
        self.enabled = False
        self._pcm_buffer = bytearray() # Accumulate PCM before feeding Vosk

        if not VOSK_AVAILABLE:
            logger.warning("Vosk not available -- voice engine disabled")
            return

        if not os.path.exists(VOSK_MODEL_PATH):
            logger.error(
                f"Vosk model not found at: {VOSK_MODEL_PATH}\n"
                f"Download from: https://alphacephei.com/vosk/models\n"
                f"Recommended: vosk-model-small-en-us-0.15"
            )
            return

        try:
            self.model = Model(VOSK_MODEL_PATH)
            self.recognizer = KaldiRecognizer(self.model, AUDIO_SAMPLE_RATE)
            self.recognizer.SetWords(False)
            self.enabled = True
            logger.info("Voice engine initialised (Vosk)")
        except Exception as e:
            logger.error(f"Vosk init failed: {e}")

    def process_chunk(self, b64_audio: str) -> dict | None:
        """
        Process a base64-encoded 16kHz Int16 PCM audio chunk.
        Buffers audio until we have enough for Vosk to process cleanly.

        Returns:
            None — no event
            {"event": "wake_word"} — wake word detected
            {"event": "command", "text": "..."} — full command captured
            {"event": "partial", "text": "..."} — partial transcription
            {"event": "timeout"} — silence timeout after wake word
        """
        if not self.enabled or not self.recognizer:
            return None

        try:
            pcm_bytes = base64.b64decode(b64_audio)
        except Exception:
            return None

        if len(pcm_bytes) < 2:
            return None

        # Accumulate into buffer
        self._pcm_buffer.extend(pcm_bytes)

        # Only feed Vosk when we have enough data (~250ms)
        if len(self._pcm_buffer) < MIN_VOSK_BYTES:
            return None

        # Extract chunk and clear buffer
        chunk = bytes(self._pcm_buffer)
        self._pcm_buffer.clear()

        # Feed to Vosk
        try:
            is_final = self.recognizer.AcceptWaveform(chunk)
        except Exception as e:
            logger.debug(f"Vosk error (non-critical): {e}")
            return None

        if is_final:
            result = json.loads(self.recognizer.Result())
            text = result.get("text", "").strip().lower()

            if not self.is_active:
                # Scanning for wake word
                if WAKE_WORD in text:
                    self.is_active = True
                    self.silence_counter = 0
                    logger.info(f"Wake word detected! (heard: '{text}')")
                    return {"event": "wake_word"}
                elif text:
                    logger.debug(f"Vosk heard: '{text}'")
            else:
                # Capturing command after wake word
                if text:
                    self.is_active = False
                    self.silence_counter = 0
                    logger.info(f"Voice command captured: {text}")
                    return {"event": "command", "text": text}
                else:
                    self.silence_counter += 1
                    if self.silence_counter > self.MAX_SILENCE_CHUNKS:
                        self.is_active = False
                        self.silence_counter = 0
                        return {"event": "timeout"}
        else:
            # Partial result
            try:
                partial = json.loads(self.recognizer.PartialResult())
                partial_text = partial.get("partial", "").strip().lower()

                if self.is_active and partial_text:
                    self.silence_counter = 0
                    return {"event": "partial", "text": partial_text}
            except Exception:
                pass

        return None

    def reset(self):
        """Reset the voice engine state."""
        self.is_active = False
        self.silence_counter = 0
        self._pcm_buffer.clear()

    @property
    def is_listening(self) -> bool:
        return self.is_active
