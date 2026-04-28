"""
Smart Mirror — FastAPI Server
Main WebSocket hub bridging the Raspberry Pi frontend and all AI modules.
"""

import asyncio
import json
import io
import base64
import socket
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import (
    SERVER_HOST, SERVER_PORT, MUSIC_DIR, KNOWN_FACES_DIR,
)
from backend.modules.session_manager import SessionManager
from backend.modules.data_feeds import DataFeedManager
from backend.modules.face_engine import decode_frame, identify, detect_emotion
from backend.modules.voice_engine import VoiceEngine
from backend.modules.assistant import Assistant
from backend.modules.music_player import MusicPlayer

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-20s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("smart-mirror")

# ─── Module Instances ───────────────────────────────────────────────────────
session_mgr = SessionManager()
data_feeds = DataFeedManager()
voice_engine = VoiceEngine()
assistant = Assistant()
music_player = MusicPlayer()

# Track TTS/music playback state to gate microphone
audio_playing = False


# ─── Safe WebSocket Send ────────────────────────────────────────────────────

async def safe_send(ws: WebSocket, data: dict) -> bool:
    """Send JSON to WebSocket, silently handling closed connections."""
    try:
        await ws.send_json(data)
        return True
    except (RuntimeError, Exception):
        return False


# ─── TTS Helper ─────────────────────────────────────────────────────────────

async def generate_tts(text: str) -> str | None:
    """Generate TTS audio as base64 MP3 using gTTS, for playback on the Pi."""
    try:
        from gtts import gTTS
        loop = asyncio.get_event_loop()

        def _generate():
            tts = gTTS(text=text, lang="en", slow=False)
            buf = io.BytesIO()
            tts.write_to_fp(buf)
            buf.seek(0)
            return base64.b64encode(buf.read()).decode("utf-8")

        return await loop.run_in_executor(None, _generate)
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        return None


# ─── Lifespan ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    ip = get_local_ip()
    logger.info("=" * 60)
    logger.info(f"  🪞 Smart Mirror Backend Starting")
    logger.info(f"  📡 Open on Pi:  http://{ip}:{SERVER_PORT}")
    logger.info(f"  🔌 WebSocket:   ws://{ip}:{SERVER_PORT}/ws")
    logger.info("=" * 60)

    await data_feeds.start()
    yield
    await data_feeds.stop()
    logger.info("Smart Mirror Backend stopped.")


# ─── FastAPI App ────────────────────────────────────────────────────────────

app = FastAPI(title="Smart Mirror", lifespan=lifespan)

# Serve frontend files
app.mount("/css", StaticFiles(directory="frontend/css"), name="css")
app.mount("/js", StaticFiles(directory="frontend/js"), name="js")

# Serve music files for Pi playback
if MUSIC_DIR.exists():
    app.mount("/music", StaticFiles(directory=str(MUSIC_DIR)), name="music")


@app.get("/")
async def serve_index():
    """Serve the main mirror interface."""
    return FileResponse("frontend/index.html")


@app.get("/test-speech")
async def serve_speech_test():
    """Speech recognition test page."""
    return FileResponse("frontend/test-speech.html")


# ─── WebSocket Endpoint ────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    logger.info(f"Client connected: {ws.client}")

    # Send initial data immediately
    await send_feed_data(ws)

    # Background tasks for periodic data pushes
    feed_task = asyncio.create_task(periodic_data_sender(ws))

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")

            if msg_type == "frame":
                asyncio.create_task(handle_frame(ws, msg.get("data", "")))

            elif msg_type == "voice_command":
                asyncio.create_task(
                    handle_voice_command(ws, msg.get("text", ""))
                )

            elif msg_type == "voice_status_update":
                state = msg.get("data", {}).get("state")
                if state == "wake_word":
                    logger.info("🎤 Wake word detected (from browser)")

            elif msg_type == "audio_done":
                audio_playing = False
                logger.info("Audio playback finished on client — mic resumed")

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        feed_task.cancel()


# ─── Frame Processing (Face + Mood) ────────────────────────────────────────

async def handle_frame(ws: WebSocket, b64_data: str):
    """Process a video frame for face recognition and mood detection."""
    loop = asyncio.get_event_loop()

    frame = await loop.run_in_executor(None, decode_frame, b64_data)
    if frame is None:
        return

    # ── Face Recognition ────────────────────────────────────────────────
    face_result = await loop.run_in_executor(None, identify, frame)

    if face_result:
        user_name = face_result["name"]
        session = session_mgr.get_or_create(user_name)

        await safe_send(ws, {"type": "face_result", "data": face_result})

        # Send user's tasks
        tasks = session_mgr.get_tasks(user_name)
        await safe_send(ws, {
            "type": "tasks",
            "data": {"user": user_name, "items": tasks}
        })

        # Start mood scan if cooldown not active
        if not session.is_cooldown_active() and not session.is_scanning():
            session_mgr.start_mood_scan(user_name)

    # ── Mood Detection (during scan window) ─────────────────────────────
    scanning_user = session_mgr.get_scanning_user()
    if scanning_user:
        emotion = await loop.run_in_executor(None, detect_emotion, frame)
        if emotion:
            result = session_mgr.add_emotion_sample(scanning_user, emotion)

            # Send live emotion data
            await safe_send(ws, {
                "type": "mood_status",
                "data": {"emotion": emotion, "scanning": True}
            })

            if result:
                # Scan complete — dominant mood determined
                dominant = result["dominant_emotion"]
                await safe_send(ws, {
                    "type": "mood_result",
                    "data": result
                })

                # Generate personalised greeting
                await send_mood_greeting(ws, scanning_user, dominant)


async def send_mood_greeting(ws: WebSocket, user: str, mood: str):
    """Send a TTS greeting and music recommendation based on mood."""
    global audio_playing

    # Build greeting text
    greetings = {
        "happy":    f"You look great today, {user}! Keep that smile going!",
        "sad":      f"Hey {user}, I hope this lifts your mood a little.",
        "angry":    f"Take a deep breath, {user}. Here's something to help you relax.",
        "surprise": f"Oh, something excited you, {user}? That's awesome!",
        "fear":     f"Don't worry, {user}. Everything is going to be alright.",
        "neutral":  f"Welcome, {user}. Ready to start your day?",
        "disgust":  f"Hmm, rough moment, {user}? Let me play something nice for you.",
    }
    greeting_text = greetings.get(mood, f"Hello, {user}!")

    # Send greeting text
    await safe_send(ws, {
        "type": "greeting",
        "data": {"text": greeting_text, "user": user, "mood": mood}
    })

    # Generate and stream TTS audio
    audio_playing = True
    tts_b64 = await generate_tts(greeting_text)
    if tts_b64:
        await safe_send(ws, {
            "type": "tts_audio",
            "data": tts_b64
        })

    # Select and send mood music (or show suggestion if no files)
    track = music_player.get_track_for_mood(mood)
    if track:
        await safe_send(ws, {
            "type": "play_music",
            "data": track
        })

    # Always send a music notification to the UI
    mood_labels = {
        "happy": "Upbeat Vibes", "sad": "Calm & Soothing",
        "angry": "Chill Beats", "surprise": "Feel-Good Mix",
        "fear": "Relaxing Ambient", "neutral": "Easy Listening",
        "disgust": "Comfort Tunes",
    }
    await safe_send(ws, {
        "type": "music_notification",
        "data": {
            "mood": mood,
            "label": mood_labels.get(mood, "Music"),
            "has_track": track is not None,
            "track_name": track["track"] if track else None,
        }
    })


# ─── Audio Processing (Wake Word + STT) ────────────────────────────────────

async def handle_audio(ws: WebSocket, b64_audio: str):
    """Process an audio chunk for wake-word detection and STT."""
    global audio_playing

    # Don't process audio while TTS/music is playing (prevent feedback loops)
    if audio_playing:
        return

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, voice_engine.process_chunk, b64_audio
    )

    if result is None:
        return

    event = result.get("event")

    if event == "wake_word":
        logger.info("🎤 Wake word detected!")
        await safe_send(ws, {
            "type": "voice_status",
            "data": {"state": "listening", "text": "Listening..."}
        })

    elif event == "partial":
        await safe_send(ws, {
            "type": "voice_status",
            "data": {"state": "listening", "text": result["text"]}
        })

    elif event == "command":
        command_text = result["text"]
        logger.info(f"🎤 Command: {command_text}")

        await safe_send(ws, {
            "type": "voice_status",
            "data": {"state": "processing", "text": command_text}
        })

        await handle_voice_command(ws, command_text)

    elif event == "timeout":
        await safe_send(ws, {
            "type": "voice_status",
            "data": {"state": "idle", "text": ""}
        })


async def handle_voice_command(ws: WebSocket, text: str):
    """Route a voice command to the appropriate handler."""
    global audio_playing

    # Get active user (or default to "user")
    active_session = session_mgr.get_active_session()
    user = active_session.name if active_session else "user"

    # Check if it's a direct command (task, weather, market, etc.)
    command = assistant.parse_command(text)

    if command:
        action = command["action"]

        # ── Task Commands ───────────────────────────────────────────
        if action == "add_task":
            tasks = session_mgr.add_task(user, command["text"])
            await safe_send(ws, {
                "type": "tasks",
                "data": {"user": user, "items": tasks}
            })
            reply = f"Got it! I've added '{command['text']}' to your tasks."

        elif action == "complete_task":
            tasks = session_mgr.complete_task(user, command["id"])
            await safe_send(ws, {
                "type": "tasks",
                "data": {"user": user, "items": tasks}
            })
            reply = f"Task {command['id']} marked as done."

        elif action == "remove_task":
            tasks = session_mgr.remove_task(user, command["id"])
            await safe_send(ws, {
                "type": "tasks",
                "data": {"user": user, "items": tasks}
            })
            reply = f"Task {command['id']} removed."

        elif action == "list_tasks":
            tasks = session_mgr.get_tasks(user)
            await safe_send(ws, {
                "type": "tasks",
                "data": {"user": user, "items": tasks}
            })
            if tasks:
                task_list = ", ".join(
                    t["text"] for t in tasks if not t["done"]
                )
                reply = f"Your pending tasks are: {task_list}"
            else:
                reply = "You have no tasks right now."

        elif action == "clear_done":
            tasks = session_mgr.clear_done_tasks(user)
            await safe_send(ws, {
                "type": "tasks",
                "data": {"user": user, "items": tasks}
            })
            reply = "Cleared all completed tasks."

        # ── Info Commands ───────────────────────────────────────────
        elif action == "weather":
            if data_feeds.latest_weather:
                w = data_feeds.latest_weather
                reply = (
                    f"It's currently {w['temp']}°C in {w['city']} "
                    f"with {w['description']}. "
                    f"Humidity is {w['humidity']}%."
                )
                await safe_send(ws, {
                    "type": "weather",
                    "data": data_feeds.latest_weather
                })
            else:
                reply = "Weather data is not available right now."

        elif action == "market":
            if data_feeds.latest_market:
                m = data_feeds.latest_market
                direction = "up" if m["change"] >= 0 else "down"
                reply = (
                    f"NIFTY 50 is at {m['price']}, "
                    f"{direction} {abs(m['change_pct'])}% today."
                )
                await safe_send(ws, {
                    "type": "market",
                    "data": data_feeds.latest_market
                })
            else:
                reply = "Market data is not available right now."

        # ── Music Commands ──────────────────────────────────────────
        elif action == "pause_music":
            await safe_send(ws, {
                "type": "music_control",
                "data": {"action": "pause"}
            })
            reply = "Music paused."

        elif action == "resume_music":
            await safe_send(ws, {
                "type": "music_control",
                "data": {"action": "resume"}
            })
            reply = "Resuming music."

        elif action == "stop_music":
            await safe_send(ws, {
                "type": "music_control",
                "data": {"action": "stop"}
            })
            reply = "Music stopped."

        elif action == "play_music":
            # Pick a track based on last known mood or default to neutral
            last_mood = session_mgr.get_last_mood(user) or "neutral"
            track = music_player.get_track_for_mood(last_mood)
            if track:
                await safe_send(ws, {
                    "type": "play_music",
                    "data": track
                })
                await safe_send(ws, {
                    "type": "music_notification",
                    "data": {
                        "mood": last_mood,
                        "label": "Now Playing",
                        "has_track": True,
                        "track_name": track["track"],
                    }
                })
                reply = f"Playing some {last_mood} vibes for you."
            else:
                reply = "Sorry, I don't have any music tracks available right now."

        elif action == "next_track":
            last_mood = session_mgr.get_last_mood(user) or "neutral"
            track = music_player.get_track_for_mood(last_mood)
            if track:
                await safe_send(ws, {
                    "type": "music_control",
                    "data": {"action": "stop"}
                })
                await safe_send(ws, {
                    "type": "play_music",
                    "data": track
                })
                await safe_send(ws, {
                    "type": "music_notification",
                    "data": {
                        "mood": last_mood,
                        "label": "Now Playing",
                        "has_track": True,
                        "track_name": track["track"],
                    }
                })
                reply = "Skipping to the next track."
            else:
                reply = "No more tracks available."

        elif action == "now_playing":
            await safe_send(ws, {
                "type": "music_control",
                "data": {"action": "now_playing"}
            })
            reply = "Check the screen for what's currently playing."

        elif action == "volume_up":
            await safe_send(ws, {
                "type": "music_control",
                "data": {"action": "volume_up"}
            })
            reply = "Volume increased."

        elif action == "volume_down":
            await safe_send(ws, {
                "type": "music_control",
                "data": {"action": "volume_down"}
            })
            reply = "Volume decreased."

        elif action == "set_volume":
            level = command["level"]
            await safe_send(ws, {
                "type": "music_control",
                "data": {"action": "set_volume", "volume": level}
            })
            reply = f"Volume set to {level}%."

        # ── Time & Date ─────────────────────────────────────────────
        elif action == "time":
            from datetime import datetime
            now = datetime.now()
            time_str = now.strftime("%I:%M %p")
            reply = f"It's currently {time_str}."

        elif action == "date":
            from datetime import datetime
            now = datetime.now()
            date_str = now.strftime("%A, %B %d, %Y")
            reply = f"Today is {date_str}."

        # ── Mood & Greeting ─────────────────────────────────────────
        elif action == "scan_mood":
            if user != "user":
                session_mgr.force_mood_rescan(user)
                await safe_send(ws, {
                    "type": "force_mood_scan",
                    "data": {"user": user}
                })
                reply = "Starting a fresh mood scan. Hold still for a moment!"
            else:
                reply = "I need to recognize your face first before scanning your mood."

        elif action == "greet_me":
            last_mood = session_mgr.get_last_mood(user) or "neutral"
            await send_mood_greeting(ws, user, last_mood)
            reply = None  # Greeting handler already sends TTS

        # ── Identity ────────────────────────────────────────────────
        elif action == "who_am_i":
            if user != "user":
                reply = f"You are {user.title()}! I recognized you."
            else:
                reply = "I haven't been able to identify you yet. Make sure you're facing the camera."

        # ── Widget Visibility ───────────────────────────────────────
        elif action == "hide_widget":
            widget = command["widget"]
            await safe_send(ws, {
                "type": "widget_visibility",
                "data": {"widget": widget, "visible": False}
            })
            reply = f"{widget.title()} panel hidden."

        elif action == "show_widget":
            widget = command["widget"]
            await safe_send(ws, {
                "type": "widget_visibility",
                "data": {"widget": widget, "visible": True}
            })
            # Also push fresh data if applicable
            if widget == "weather" and data_feeds.latest_weather:
                await safe_send(ws, {
                    "type": "weather",
                    "data": data_feeds.latest_weather
                })
            elif widget == "market" and data_feeds.latest_market:
                await safe_send(ws, {
                    "type": "market",
                    "data": data_feeds.latest_market
                })
            elif widget == "tasks":
                tasks = session_mgr.get_tasks(user)
                await safe_send(ws, {
                    "type": "tasks",
                    "data": {"user": user, "items": tasks}
                })
            reply = f"{widget.title()} panel is now visible."

        elif action == "clear_screen":
            await safe_send(ws, {
                "type": "widget_visibility",
                "data": {"widget": "all", "visible": False}
            })
            reply = "Display cleared. Say 'show all' to restore."

        elif action == "show_all":
            await safe_send(ws, {
                "type": "widget_visibility",
                "data": {"widget": "all", "visible": True}
            })
            # Push all latest data
            await send_feed_data(ws)
            tasks = session_mgr.get_tasks(user)
            await safe_send(ws, {
                "type": "tasks",
                "data": {"user": user, "items": tasks}
            })
            reply = "All panels restored."

        # ── Display Sleep / Wake ────────────────────────────────────
        elif action == "sleep_display":
            await safe_send(ws, {
                "type": "display_mode",
                "data": {"mode": "sleep"}
            })
            reply = "Good night! The display is going to sleep."

        elif action == "wake_display":
            await safe_send(ws, {
                "type": "display_mode",
                "data": {"mode": "wake"}
            })
            reply = "Good morning! Display is back on."

        # ── Chat Management ─────────────────────────────────────────
        elif action == "clear_chat":
            assistant.clear_history(user)
            reply = "Conversation cleared. Let's start fresh!"

        # ── Help ────────────────────────────────────────────────────
        elif action == "help":
            reply = (
                "Here's what I can do! "
                "Tasks: add, complete, remove, or list tasks. "
                "Info: ask about weather, market, time, or date. "
                "Music: play, pause, resume, stop, skip, or change volume. "
                "Mood: scan your mood or ask for a greeting. "
                "Display: hide or show widgets, sleep, or wake the screen. "
                "Or just chat with me about anything!"
            )

        else:
            reply = "I didn't understand that command."

    else:
        # Send to Groq LLM for general conversation
        await safe_send(ws, {
            "type": "voice_status",
            "data": {"state": "processing", "text": "Thinking..."}
        })
        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(
            None, assistant.chat, user, text
        )

    # Send assistant response (skip if handler already sent TTS, e.g. greet_me)
    if reply is not None:
        await safe_send(ws, {
            "type": "assistant_response",
            "data": {"text": reply, "user": user}
        })

        # Stream TTS of the response to the Pi
        audio_playing = True
        tts_b64 = await generate_tts(reply)
        if tts_b64:
            await safe_send(ws, {
                "type": "tts_audio",
                "data": tts_b64
            })

    await safe_send(ws, {
        "type": "voice_status",
        "data": {"state": "idle", "text": ""}
    })


# ─── Periodic Data Sender ──────────────────────────────────────────────────

async def send_feed_data(ws: WebSocket):
    """Send current weather and market data."""
    if data_feeds.latest_weather:
        await safe_send(ws, {
            "type": "weather",
            "data": data_feeds.latest_weather
        })
    if data_feeds.latest_market:
        await safe_send(ws, {
            "type": "market",
            "data": data_feeds.latest_market
        })


async def periodic_data_sender(ws: WebSocket):
    """Background task: push weather every 5 min, market every 30 sec."""
    try:
        counter = 0
        while True:
            await asyncio.sleep(30)
            counter += 1

            # Market data every 30 seconds
            if data_feeds.latest_market:
                await safe_send(ws, {
                    "type": "market",
                    "data": data_feeds.latest_market
                })

            # Weather data every 5 minutes (10 * 30s)
            if counter % 10 == 0 and data_feeds.latest_weather:
                await safe_send(ws, {
                    "type": "weather",
                    "data": data_feeds.latest_weather
                })
    except asyncio.CancelledError:
        pass




# ─── Utilities ──────────────────────────────────────────────────────────────

def get_local_ip() -> str:
    """Get the machine's local network IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"
