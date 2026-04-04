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
        Check if the text is a direct task command rather than
        a general LLM query.
        
        Returns:
            {"action": "add_task", "text": "buy milk"}
            {"action": "complete_task", "id": 2}
            {"action": "remove_task", "id": 3}
            {"action": "list_tasks"}
            {"action": "clear_done"}
            {"action": "weather"}
            {"action": "market"}
            None — not a command, send to LLM
        """
        text_lower = text.lower().strip()

        # Task commands
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

        if text_lower in ("list tasks", "show tasks", "my tasks", "what are my tasks"):
            return {"action": "list_tasks"}

        if text_lower in ("clear done", "clear completed", "remove completed tasks"):
            return {"action": "clear_done"}

        # Info commands
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
