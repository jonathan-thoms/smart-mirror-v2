"""
Smart Mirror — Central Configuration
Loads environment variables and defines all system constants.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ─── Load .env from project root ────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


# ─── API Keys ───────────────────────────────────────────────────────────────
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
OPENWEATHERMAP_API_KEY: str = os.getenv("OPENWEATHERMAP_API_KEY", "")


# ─── Weather ────────────────────────────────────────────────────────────────
WEATHER_CITY: str = os.getenv("WEATHER_CITY", "Kochi")
WEATHER_COUNTRY_CODE: str = os.getenv("WEATHER_COUNTRY_CODE", "IN")
WEATHER_POLL_INTERVAL: int = 300          # seconds  (5 minutes)


# ─── Market Data ────────────────────────────────────────────────────────────
NIFTY_SYMBOL: str = "^NSEI"               # Yahoo Finance ticker for NIFTY 50
MARKET_POLL_INTERVAL: int = 30             # seconds


# ─── Vision / AI ────────────────────────────────────────────────────────
KNOWN_FACES_DIR: Path = ROOT_DIR / "backend" / "known_faces"
FACE_MATCH_TOLERANCE: float = 0.6       # face_recognition distance threshold
EMOTION_SCAN_WINDOW: float = 5.0        # seconds of mood sampling
MOOD_COOLDOWN: int = 3600               # seconds (1 hour)


# ─── Voice / Audio ──────────────────────────────────────────────────────────
VOSK_MODEL_PATH: str = os.getenv(
    "VOSK_MODEL_PATH",
    str(ROOT_DIR / "backend" / "models" / "vosk-model-small-en-us-0.15"),
)
WAKE_WORD: str = "hey lumo"
AUDIO_SAMPLE_RATE: int = 16000             # Hz — Vosk expects 16 kHz mono


# ─── LLM ────────────────────────────────────────────────────────────────────
GROQ_MODEL: str = "llama-3.3-70b-versatile"
ASSISTANT_NAME: str = "Lumo"
SYSTEM_PROMPT: str = (
    f"You are {ASSISTANT_NAME}, a friendly and concise smart-mirror AI assistant. "
    "You help the user with tasks, reminders, weather updates, market info, and "
    "casual conversation. Keep responses brief (1-3 sentences) since they will "
    "be spoken aloud via text-to-speech. Be warm and helpful."
)


# ─── Music ──────────────────────────────────────────────────────────────────
MUSIC_DIR: Path = ROOT_DIR / "backend" / "music"
MOOD_MUSIC_MAP: dict = {
    "happy":    MUSIC_DIR / "happy",
    "sad":      MUSIC_DIR / "sad",
    "angry":    MUSIC_DIR / "angry",
    "surprise": MUSIC_DIR / "surprise",
    "fear":     MUSIC_DIR / "fear",
    "neutral":  MUSIC_DIR / "neutral",
    "disgust":  MUSIC_DIR / "disgust",
}


# ─── Persistence ────────────────────────────────────────────────────────────
TASKS_FILE: Path = ROOT_DIR / "backend" / "data" / "tasks.json"


# ─── Server ─────────────────────────────────────────────────────────────────
SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8000"))
