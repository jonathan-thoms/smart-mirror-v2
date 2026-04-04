"""
Smart Mirror — Music Player
Maps mood → MP3 file, serves playback URLs for the Pi frontend.
"""

import os
import random
import logging
from pathlib import Path
from backend.config import MUSIC_DIR, MOOD_MUSIC_MAP

logger = logging.getLogger(__name__)


class MusicPlayer:
    """
    Manages mood-based music selection.
    
    Music files are stored on the PC in:
        backend/music/<mood>/  (e.g., happy/, sad/, angry/)
    
    The backend serves these as static files at /music/<mood>/filename.mp3
    The frontend plays them via <audio> element.
    """

    def __init__(self):
        self._current_mood: str | None = None
        self._scan_library()

    def _scan_library(self):
        """Scan the music directory and log available tracks."""
        self.library: dict[str, list[str]] = {}

        for mood, mood_dir in MOOD_MUSIC_MAP.items():
            if mood_dir.exists():
                tracks = [
                    f.name for f in mood_dir.iterdir()
                    if f.suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a")
                ]
                if tracks:
                    self.library[mood] = tracks
                    logger.info(f"Music library: {mood} → {len(tracks)} tracks")

        if not self.library:
            logger.warning(
                f"No music files found. Add MP3s to: {MUSIC_DIR}/<mood>/"
            )

    def get_track_for_mood(self, mood: str) -> dict | None:
        """
        Select a random track for the given mood.
        
        Returns:
            {"url": "/music/happy/song.mp3", "mood": "happy", "track": "song.mp3"}
            or None if no tracks available for this mood.
        """
        mood_lower = mood.lower()

        # Try exact mood match
        if mood_lower in self.library:
            track = random.choice(self.library[mood_lower])
            return {
                "url": f"/music/{mood_lower}/{track}",
                "mood": mood_lower,
                "track": track,
            }

        # Fallback to neutral
        if "neutral" in self.library:
            track = random.choice(self.library["neutral"])
            return {
                "url": f"/music/neutral/{track}",
                "mood": "neutral",
                "track": track,
            }

        logger.warning(f"No music tracks for mood: {mood}")
        return None

    def refresh_library(self):
        """Re-scan the music directory (call if files are added at runtime)."""
        self._scan_library()
