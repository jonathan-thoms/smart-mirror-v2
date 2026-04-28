"""
Smart Mirror — AI Assistant (Groq LLM)
Chat interface with Lumo persona, handles commands and conversation.
"""

import re
import logging
from groq import Groq
from backend.config import GROQ_API_KEY, GROQ_MODEL, SYSTEM_PROMPT, ASSISTANT_NAME

logger = logging.getLogger(__name__)


class Assistant:
    """
    Groq-powered LLM assistant with:
      - Lumo persona
      - Per-user conversation history
      - Task/command extraction
    """

    def __init__(self):
        self.client = None
        self.conversations: dict[str, list[dict]] = {}
        self.enabled = False

        if not GROQ_API_KEY:
            logger.warning("GROQ_API_KEY not set — assistant disabled")
            return

        try:
            self.client = Groq(api_key=GROQ_API_KEY)
            self.enabled = True
            logger.info("Groq assistant initialised")
        except Exception as e:
            logger.error(f"Groq init failed: {e}")

    def _get_history(self, user: str) -> list[dict]:
        key = user.lower()
        if key not in self.conversations:
            self.conversations[key] = [
                {"role": "system", "content": SYSTEM_PROMPT}
            ]
        return self.conversations[key]

    def parse_command(self, text: str) -> dict | None:
        """
        Check if the text is a direct command rather than
        a general LLM query.
        
        Returns:
            {"action": "add_task", "text": "buy milk"}
            {"action": "complete_task", "id": 2}
            {"action": "remove_task", "id": 3}
            {"action": "list_tasks"}
            {"action": "clear_done"}
            {"action": "weather"}
            {"action": "market"}
            {"action": "pause_music"}
            {"action": "resume_music"}
            {"action": "stop_music"}
            {"action": "play_music"}
            {"action": "next_track"}
            {"action": "now_playing"}
            {"action": "volume_up"}
            {"action": "volume_down"}
            {"action": "set_volume", "level": 50}
            {"action": "time"}
            {"action": "date"}
            {"action": "scan_mood"}
            {"action": "greet_me"}
            {"action": "who_am_i"}
            {"action": "hide_widget", "widget": "weather"}
            {"action": "show_widget", "widget": "weather"}
            {"action": "clear_screen"}
            {"action": "show_all"}
            {"action": "sleep_display"}
            {"action": "wake_display"}
            {"action": "clear_chat"}
            {"action": "help"}
            None — not a command, send to LLM
        """
        text_lower = text.lower().strip()

        # ── Task commands ───────────────────────────────────────────────
        add_match = re.match(
            r"(?:add|create|new)\s+(?:a\s+)?task\s+(.+)", text_lower
        )
        if add_match:
            return {"action": "add_task", "text": add_match.group(1).strip()}

        complete_match = re.match(
            r"(?:complete|finish|done|check)\s+task\s+(\d+)", text_lower
        )
        if complete_match:
            return {"action": "complete_task", "id": int(complete_match.group(1))}

        remove_match = re.match(
            r"(?:remove|delete)\s+task\s+(\d+)", text_lower
        )
        if remove_match:
            return {"action": "remove_task", "id": int(remove_match.group(1))}

        if text_lower in ("list tasks", "show tasks", "my tasks",
                          "what are my tasks", "show my tasks"):
            return {"action": "list_tasks"}

        if text_lower in ("clear done", "clear completed",
                          "remove completed tasks", "remove done tasks"):
            return {"action": "clear_done"}

        # ── Music commands ──────────────────────────────────────────────
        if re.match(r"(?:pause|pause music|pause the music)$", text_lower):
            return {"action": "pause_music"}

        if re.match(r"(?:resume|resume music|unpause|continue music|"
                    r"continue playing)$", text_lower):
            return {"action": "resume_music"}

        if re.match(r"(?:stop music|stop playing|stop the music|"
                    r"turn off music|mute music)$", text_lower):
            return {"action": "stop_music"}

        if re.match(r"(?:play music|play some music|play a song|"
                    r"play something|start music)$", text_lower):
            return {"action": "play_music"}

        if re.match(r"(?:next song|next track|skip|skip song|"
                    r"play next|skip track)$", text_lower):
            return {"action": "next_track"}

        if re.match(r"(?:what'?s? playing|current song|what song|"
                    r"what song is this|now playing|which song)$", text_lower):
            return {"action": "now_playing"}

        if re.match(r"(?:volume up|louder|turn it up|raise volume|"
                    r"increase volume|turn up)$", text_lower):
            return {"action": "volume_up"}

        if re.match(r"(?:volume down|quieter|turn it down|lower volume|"
                    r"decrease volume|softer|turn down)$", text_lower):
            return {"action": "volume_down"}

        vol_match = re.match(
            r"(?:set\s+)?volume\s+(?:to\s+)?(\d+)", text_lower
        )
        if vol_match:
            level = min(100, max(0, int(vol_match.group(1))))
            return {"action": "set_volume", "level": level}

        # ── Time & Date ─────────────────────────────────────────────────
        if any(p in text_lower for p in (
            "what time", "tell me the time", "current time",
            "time is it", "time right now"
        )):
            return {"action": "time"}

        if any(p in text_lower for p in (
            "what's the date", "what is the date", "what day",
            "today's date", "current date", "date today",
            "what date is it"
        )):
            return {"action": "date"}

        # ── Mood & Greeting ─────────────────────────────────────────────
        if any(p in text_lower for p in (
            "scan my mood", "how am i feeling", "rescan mood",
            "check my mood", "read my mood", "detect my mood",
            "what's my mood", "how do i look"
        )):
            return {"action": "scan_mood"}

        if any(p in text_lower for p in (
            "greet me", "say hello", "say hi",
            "give me a greeting", "hello lumo"
        )):
            return {"action": "greet_me"}

        # ── Identity ────────────────────────────────────────────────────
        if any(p in text_lower for p in (
            "who am i", "what's my name", "what is my name",
            "do you know me", "do you recognize me",
            "who do you see"
        )):
            return {"action": "who_am_i"}

        # ── Widget Visibility ───────────────────────────────────────────
        hide_match = re.match(
            r"hide\s+(?:the\s+)?(weather|market|stock|tasks|task list)",
            text_lower
        )
        if hide_match:
            widget = hide_match.group(1)
            if widget in ("stock",):
                widget = "market"
            if widget in ("task list",):
                widget = "tasks"
            return {"action": "hide_widget", "widget": widget}

        show_match = re.match(
            r"show\s+(?:the\s+)?(weather|market|stock|tasks|task list)",
            text_lower
        )
        if show_match:
            widget = show_match.group(1)
            if widget in ("stock",):
                widget = "market"
            if widget in ("task list",):
                widget = "tasks"
            return {"action": "show_widget", "widget": widget}

        if text_lower in ("clear screen", "hide everything",
                          "clean display", "hide all"):
            return {"action": "clear_screen"}

        if text_lower in ("show all", "show everything",
                          "restore display", "restore all"):
            return {"action": "show_all"}

        # ── Display Sleep / Wake ────────────────────────────────────────
        if any(p in text_lower for p in (
            "go to sleep", "sleep", "dim display", "dim screen",
            "turn off screen", "good night", "screen off",
            "lights off"
        )):
            return {"action": "sleep_display"}

        if any(p in text_lower for p in (
            "wake up", "turn on", "turn on screen", "good morning",
            "lights on", "screen on", "undim", "bright"
        )):
            return {"action": "wake_display"}

        # ── Chat Management ─────────────────────────────────────────────
        if any(p in text_lower for p in (
            "forget our conversation", "clear chat", "reset conversation",
            "clear conversation", "forget everything",
            "start fresh", "new conversation"
        )):
            return {"action": "clear_chat"}

        # ── Help ────────────────────────────────────────────────────────
        if text_lower in ("help", "what can you do", "list commands",
                          "show commands", "what do you do",
                          "what are your commands"):
            return {"action": "help"}

        # ── Info commands (keep broad matches last) ─────────────────────
        if any(w in text_lower for w in ("weather", "temperature", "forecast")):
            return {"action": "weather"}

        if any(w in text_lower for w in ("market", "nifty", "stock", "index")):
            return {"action": "market"}

        return None

    def chat(self, user: str, message: str) -> str:
        """Send a message to the Groq LLM and get a response."""
        if not self.enabled:
            return "I'm sorry, the assistant is not available right now."

        history = self._get_history(user)
        history.append({"role": "user", "content": message})

        # Keep history manageable (last 20 messages + system prompt)
        if len(history) > 21:
            history[:] = [history[0]] + history[-20:]

        try:
            response = self.client.chat.completions.create(
                model=GROQ_MODEL,
                messages=history,
                temperature=0.7,
                max_tokens=256,
            )
            reply = response.choices[0].message.content.strip()
            history.append({"role": "assistant", "content": reply})
            logger.info(f"Assistant reply to {user}: {reply[:80]}...")
            return reply

        except Exception as e:
            logger.error(f"Groq API error: {e}")
            return "I'm having trouble connecting. Please try again in a moment."

    def clear_history(self, user: str):
        key = user.lower()
        if key in self.conversations:
            self.conversations[key] = [
                {"role": "system", "content": SYSTEM_PROMPT}
            ]
