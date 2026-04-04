# Smart Mirror Project Directives

## Architecture: Edge-Node (Client-Server)
- **Backend (PC):** Python with FastAPI. Handles all heavy lifting: Face Recognition, Mood Detection, wake word listening, STT/TTS processing, Groq API calls, and local MP3 playback management.
- **Frontend (Raspberry Pi 4):** Vanilla JS, HTML, CSS. Acts as a sensory relay. Captures video/audio and displays the UI. 
- **Communication:** Strict WebSocket protocol over the local network. No standard HTTP polling.

## Frontend UI: The Digital Mirror
- **Video Background:** The webcam feed must be captured via `navigator.mediaDevices.getUserMedia()` and mapped to a fullscreen, `z-index: -1`, `position: absolute` `<video>` element.
- **Mirror Effect:** The video element MUST have `transform: scaleX(-1)` applied in CSS to act like a real mirror.
- **Frame Extraction:** A hidden `<canvas>` must grab a frame from the video feed every 1000ms, convert it to a base64 JPEG, and send it to the backend via WebSocket.
- **Aesthetic:** High contrast. Pure white text and glowing neon accents (cyan/magenta/green) for UI widgets so they remain legible over the live camera feed.

## Technology Stack & Modules
1. **Wake Word:** `pvporcupine` (Picovoice) for local, lightweight "Hey Lumo" detection.
2. **Vision (Face/Mood):** `DeepFace` and `OpenCV`.
3. **LLM:** `groq` Python client.
4. **Music Playback:** Use `pygame.mixer` or `vlc` Python bindings to asynchronously play local MP3 files stored on the PC.
5. **Speech/Audio:** `SpeechRecognition` for STT. `pyttsx3` or `gTTS` for TTS. 

## Business Logic Rules
- **State Management:** The backend must maintain an active session state for recognized users (e.g., Jonathan) to keep their personalized tasks on screen.
- **Mood-to-Music Logic:** 1. Upon face recognition, initiate a 5-second scan window.
  2. Collect mood predictions from incoming frames.
  3. Calculate the dominant emotion (mode) at the end of the 5 seconds.
  4. Trigger a contextual TTS greeting and play a corresponding local MP3 file.
  5. Enforce a strict 3600-second (1 hour) cooldown lock on this specific user so the music doesn't constantly trigger or change.
- **Audio Concurrency:** The microphone/STT listener must be paused or muted while TTS or local MP3 music is playing to prevent audio feedback loops.