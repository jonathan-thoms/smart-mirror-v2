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

            elif msg_type == "audio_chunk":
                asyncio.create_task(handle_audio(ws, msg.get("data", "")))

            elif msg_type == "voice_command":
                asyncio.create_task(
                    handle_voice_command(ws, msg.get("text", ""))
                )

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

        await ws.send_json({"type": "face_result", "data": face_result})

        # Send user's tasks
        tasks = session_mgr.get_tasks(user_name)
        await ws.send_json({
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
            await ws.send_json({
                "type": "mood_status",
                "data": {"emotion": emotion, "scanning": True}
            })

            if result:
                # Scan complete — dominant mood determined
                dominant = result["dominant_emotion"]
                await ws.send_json({
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
    await ws.send_json({
        "type": "greeting",
        "data": {"text": greeting_text, "user": user, "mood": mood}
    })

    # Generate and stream TTS audio
    audio_playing = True
    tts_b64 = await generate_tts(greeting_text)
    if tts_b64:
        await ws.send_json({
            "type": "tts_audio",
            "data": tts_b64
        })

    # Select and send mood music
    track = music_player.get_track_for_mood(mood)
    if track:
        await ws.send_json({
            "type": "play_music",
            "data": track
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
        await ws.send_json({
            "type": "voice_status",
            "data": {"state": "listening", "text": "Listening..."}
        })

    elif event == "partial":
        await ws.send_json({
            "type": "voice_status",
            "data": {"state": "listening", "text": result["text"]}
        })

    elif event == "command":
        command_text = result["text"]
        logger.info(f"🎤 Command: {command_text}")

        await ws.send_json({
            "type": "voice_status",
            "data": {"state": "processing", "text": command_text}
        })

        await handle_voice_command(ws, command_text)

    elif event == "timeout":
        await ws.send_json({
            "type": "voice_status",
            "data": {"state": "idle", "text": ""}
        })


async def handle_voice_command(ws: WebSocket, text: str):
    """Route a voice command to the appropriate handler."""
    global audio_playing

    # Get active user (or default to "user")
    active_session = session_mgr.get_active_session()
    user = active_session.name if active_session else "user"

    # Check if it's a direct command (task, weather, market)
    command = assistant.parse_command(text)

    if command:
        action = command["action"]

        if action == "add_task":
            tasks = session_mgr.add_task(user, command["text"])
            await ws.send_json({
                "type": "tasks",
                "data": {"user": user, "items": tasks}
            })
            reply = f"Got it! I've added '{command['text']}' to your tasks."

        elif action == "complete_task":
            tasks = session_mgr.complete_task(user, command["id"])
            await ws.send_json({
                "type": "tasks",
                "data": {"user": user, "items": tasks}
            })
            reply = f"Task {command['id']} marked as done."

        elif action == "remove_task":
            tasks = session_mgr.remove_task(user, command["id"])
            await ws.send_json({
                "type": "tasks",
                "data": {"user": user, "items": tasks}
            })
            reply = f"Task {command['id']} removed."

        elif action == "list_tasks":
            tasks = session_mgr.get_tasks(user)
            await ws.send_json({
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
            await ws.send_json({
                "type": "tasks",
                "data": {"user": user, "items": tasks}
            })
            reply = "Cleared all completed tasks."

        elif action == "weather":
            if data_feeds.latest_weather:
                w = data_feeds.latest_weather
                reply = (
                    f"It's currently {w['temp']}°C in {w['city']} "
                    f"with {w['description']}. "
                    f"Humidity is {w['humidity']}%."
                )
                await ws.send_json({
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
                await ws.send_json({
                    "type": "market",
                    "data": data_feeds.latest_market
                })
            else:
                reply = "Market data is not available right now."
        else:
            reply = "I didn't understand that command."

    else:
        # Send to Groq LLM for general conversation
        await ws.send_json({
            "type": "voice_status",
            "data": {"state": "processing", "text": "Thinking..."}
        })
        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(
            None, assistant.chat, user, text
        )

    # Send assistant response
    await ws.send_json({
        "type": "assistant_response",
        "data": {"text": reply, "user": user}
    })

    # Stream TTS of the response to the Pi
    audio_playing = True
    tts_b64 = await generate_tts(reply)
    if tts_b64:
        await ws.send_json({
            "type": "tts_audio",
            "data": tts_b64
        })

    await ws.send_json({
        "type": "voice_status",
        "data": {"state": "idle", "text": ""}
    })


# ─── Periodic Data Sender ──────────────────────────────────────────────────

async def send_feed_data(ws: WebSocket):
    """Send current weather and market data."""
    if data_feeds.latest_weather:
        await ws.send_json({
            "type": "weather",
            "data": data_feeds.latest_weather
        })
    if data_feeds.latest_market:
        await ws.send_json({
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
                await ws.send_json({
                    "type": "market",
                    "data": data_feeds.latest_market
                })

            # Weather data every 5 minutes (10 * 30s)
            if counter % 10 == 0 and data_feeds.latest_weather:
                await ws.send_json({
                    "type": "weather",
                    "data": data_feeds.latest_weather
                })
    except asyncio.CancelledError:
        pass


# ─── Audio playback completion handler ──────────────────────────────────────

@app.websocket("/ws/audio-done")
async def audio_done_handler(ws: WebSocket):
    """Pi notifies when TTS/music finishes so we can resume mic listening."""
    global audio_playing
    await ws.accept()
    try:
        while True:
            await ws.receive_text()
            audio_playing = False
            logger.info("Audio playback completed on Pi — mic resumed")
    except WebSocketDisconnect:
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
