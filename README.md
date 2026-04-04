# 🪞 Smart Mirror — Lumo

AI-powered digital mirror with face recognition, mood detection, voice assistant, and live data feeds.

## Architecture

```
┌─────────────────────┐         WebSocket          ┌──────────────────────┐
│   Raspberry Pi 4    │◄──────────────────────────►│     PC (Backend)     │
│   (Thin Client)     │                             │    (FastAPI)         │
│                     │   Video frames (base64)  →  │                     │
│  • Webcam capture   │   Audio chunks (PCM)     →  │  • Face Recognition  │
│  • Mic capture      │                             │  • Mood Detection    │
│  • UI display       │   ← Weather/Market data     │  • Voice (Vosk STT)  │
│  • TTS playback     │   ← Face/mood results       │  • Groq LLM Chat     │
│  • Music playback   │   ← TTS audio (base64)      │  • gTTS generation   │
│                     │   ← Task updates             │  • Music serving     │
└─────────────────────┘                             └──────────────────────┘
```

## Setup

### 1. Prerequisites

- **Python 3.11+** on the PC
- **Raspberry Pi 4** with Chromium browser
- Both devices on the **same local network**
- **Webcam + Microphone + Speaker** connected to the Pi

### 2. PC Backend Setup

```bash
cd 1_smart-mirror

# Create virtual environment
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate   # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Download Vosk model (required for wake word)
# Download from: https://alphacephei.com/vosk/models
# Recommended: vosk-model-small-en-us-0.15 (~40MB)
# Extract to: backend/models/vosk-model-small-en-us-0.15/
```

### 3. Configure

Edit `.env` with your API keys (pre-filled if you followed setup):

```env
GROQ_API_KEY=your_key
OPENWEATHERMAP_API_KEY=your_key
```

### 4. Add Known Faces

Drop face photos into `backend/known_faces/`:
```
backend/known_faces/
├── jonathan.jpg
├── sarah.jpg
└── ...
```

### 5. Add Music (Optional)

Add MP3 files sorted by mood:
```
backend/music/
├── happy/
│   └── upbeat_song.mp3
├── sad/
│   └── calm_song.mp3
└── neutral/
    └── ambient.mp3
```

### 6. Run

```bash
python run.py
```

The server will display:
```
🪞 Smart Mirror Backend Starting
📡 Open on Pi:  http://192.168.x.x:8000
🔌 WebSocket:   ws://192.168.x.x:8000/ws
```

### 7. Open on Raspberry Pi

On the Pi's Chromium browser, navigate to the URL shown above. For kiosk mode:
```bash
chromium-browser --kiosk --noerrdialogs --disable-infobars http://192.168.x.x:8000
```

## Voice Commands

Say **"Hey Lumo"** followed by:

| Command | Example |
|---|---|
| Add task | "Add task buy groceries" |
| Complete task | "Complete task 1" |
| Remove task | "Remove task 2" |
| List tasks | "What are my tasks" |
| Weather | "What's the weather" |
| Market | "How's the market" |
| Chat | "Tell me a joke" |

## Project Structure

```
1_smart-mirror/
├── run.py                          # Entry point
├── requirements.txt
├── .env                            # API keys (DO NOT commit)
├── backend/
│   ├── server.py                   # FastAPI + WebSocket hub
│   ├── config.py                   # Central configuration
│   ├── modules/
│   │   ├── face_engine.py          # DeepFace recognition + emotion
│   │   ├── voice_engine.py         # Vosk wake word + STT
│   │   ├── assistant.py            # Groq LLM chat
│   │   ├── data_feeds.py           # Weather + NIFTY 50
│   │   ├── music_player.py         # Mood → MP3 mapping
│   │   └── session_manager.py      # User state + tasks
│   ├── known_faces/                # Face gallery (name.jpg)
│   ├── music/                      # MP3s by mood subfolder
│   ├── models/                     # Vosk model directory
│   └── data/
│       └── tasks.json              # Persisted task lists
└── frontend/
    ├── index.html                  # Mirror UI
    ├── css/
    │   └── mirror.css              # Dark theme + glassmorphism
    └── js/
        ├── main.js                 # WebSocket client + UI
        └── audio-processor.js      # AudioWorklet for mic capture
```
