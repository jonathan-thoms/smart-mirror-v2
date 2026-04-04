"""
Smart Mirror — Session Manager
Per-user state: identity, mood scanning, cooldowns, and task persistence.
"""

import json
import time
import logging
from pathlib import Path
from collections import Counter
from backend.config import MOOD_COOLDOWN, EMOTION_SCAN_WINDOW, TASKS_FILE

logger = logging.getLogger(__name__)


class UserSession:
    """State for a single recognised user."""

    def __init__(self, name: str):
        self.name: str = name
        self.last_seen: float = time.time()
        self.mood_cooldown_until: float = 0.0
        self.mood_scan_start: float | None = None
        self.emotion_samples: list[str] = []
        self.current_mood: str | None = None

    # ── Cooldown ────────────────────────────────────────────────────────
    def is_cooldown_active(self) -> bool:
        return time.time() < self.mood_cooldown_until

    def activate_cooldown(self):
        self.mood_cooldown_until = time.time() + MOOD_COOLDOWN
        logger.info(f"Mood cooldown activated for {self.name} "
                     f"(until +{MOOD_COOLDOWN}s)")

    # ── Mood Scanning ───────────────────────────────────────────────────
    def start_scan(self):
        self.mood_scan_start = time.time()
        self.emotion_samples.clear()
        logger.info(f"Mood scan started for {self.name}")

    def is_scanning(self) -> bool:
        if self.mood_scan_start is None:
            return False
        elapsed = time.time() - self.mood_scan_start
        return elapsed < EMOTION_SCAN_WINDOW

    def add_emotion(self, emotion: str) -> dict | None:
        """Add an emotion sample. Returns aggregated result when window expires."""
        self.emotion_samples.append(emotion)

        elapsed = time.time() - (self.mood_scan_start or time.time())
        if elapsed >= EMOTION_SCAN_WINDOW and self.emotion_samples:
            dominant = Counter(self.emotion_samples).most_common(1)[0][0]
            self.current_mood = dominant
            self.mood_scan_start = None
            self.activate_cooldown()
            logger.info(f"Mood scan complete for {self.name}: {dominant} "
                         f"(from {len(self.emotion_samples)} samples)")
            samples = list(self.emotion_samples)
            self.emotion_samples.clear()
            return {
                "dominant_emotion": dominant,
                "samples": samples,
                "user": self.name,
            }
        return None


class SessionManager:
    """Manages all user sessions and task persistence."""

    def __init__(self):
        self.sessions: dict[str, UserSession] = {}
        self.active_user: str | None = None
        self._tasks: dict = self._load_tasks()

    # ── Session management ──────────────────────────────────────────────
    def get_or_create(self, name: str) -> UserSession:
        key = name.lower()
        if key not in self.sessions:
            self.sessions[key] = UserSession(key)
            logger.info(f"New session created for {key}")
        session = self.sessions[key]
        session.last_seen = time.time()
        self.active_user = key
        return session

    def get_active_session(self) -> UserSession | None:
        if self.active_user and self.active_user in self.sessions:
            return self.sessions[self.active_user]
        return None

    def is_cooldown_active(self, name: str) -> bool:
        key = name.lower()
        if key in self.sessions:
            return self.sessions[key].is_cooldown_active()
        return False

    def start_mood_scan(self, name: str):
        session = self.get_or_create(name)
        if not session.is_cooldown_active():
            session.start_scan()

    def get_scanning_user(self) -> str | None:
        """Return name of user currently being mood-scanned, if any."""
        for name, session in self.sessions.items():
            if session.is_scanning():
                return name
        return None

    def add_emotion_sample(self, name: str, emotion: str) -> dict | None:
        key = name.lower()
        if key in self.sessions:
            return self.sessions[key].add_emotion(emotion)
        return None

    # ── Task management (voice-driven) ──────────────────────────────────
    def _load_tasks(self) -> dict:
        try:
            if TASKS_FILE.exists():
                with open(TASKS_FILE, "r") as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load tasks: {e}")
        return {}

    def _save_tasks(self):
        TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TASKS_FILE, "w") as f:
            json.dump(self._tasks, f, indent=2)

    def get_tasks(self, user: str) -> list[dict]:
        key = user.lower()
        return self._tasks.get(key, {}).get("tasks", [])

    def add_task(self, user: str, text: str) -> list[dict]:
        key = user.lower()
        if key not in self._tasks:
            self._tasks[key] = {"tasks": []}

        tasks = self._tasks[key]["tasks"]
        new_id = max((t["id"] for t in tasks), default=0) + 1
        tasks.append({"id": new_id, "text": text, "done": False})
        self._save_tasks()
        logger.info(f"Task added for {key}: {text}")
        return tasks

    def complete_task(self, user: str, task_id: int) -> list[dict]:
        key = user.lower()
        tasks = self._tasks.get(key, {}).get("tasks", [])
        for t in tasks:
            if t["id"] == task_id:
                t["done"] = True
                self._save_tasks()
                logger.info(f"Task {task_id} completed for {key}")
                break
        return tasks

    def remove_task(self, user: str, task_id: int) -> list[dict]:
        key = user.lower()
        if key in self._tasks:
            self._tasks[key]["tasks"] = [
                t for t in self._tasks[key]["tasks"] if t["id"] != task_id
            ]
            self._save_tasks()
            logger.info(f"Task {task_id} removed for {key}")
        return self.get_tasks(user)

    def clear_done_tasks(self, user: str) -> list[dict]:
        key = user.lower()
        if key in self._tasks:
            self._tasks[key]["tasks"] = [
                t for t in self._tasks[key]["tasks"] if not t["done"]
            ]
            self._save_tasks()
        return self.get_tasks(user)
