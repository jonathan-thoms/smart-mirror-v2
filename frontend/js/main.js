/* ═══════════════════════════════════════════════════════════════════════════
   Smart Mirror — Main Frontend Controller
   WebSocket client, camera capture, audio streaming, and UI updates.
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
    "use strict";

    // ── Configuration ──────────────────────────────────────────────────────
    const WS_URL = `ws://${window.location.host}/ws`;
    const FRAME_INTERVAL = 1000;       // ms between frame sends
    const FRAME_QUALITY = 0.6;         // JPEG quality (0-1)
    const RECONNECT_DELAY = 3000;      // ms before reconnect attempt
    const GREETING_DISPLAY_TIME = 8000; // ms to show greeting overlay
    const ASSISTANT_DISPLAY_TIME = 10000;

    // ── State ──────────────────────────────────────────────────────────────
    let ws = null;
    let frameTimer = null;
    let audioContext = null;
    let audioProcessorNode = null;
    let isAudioStreaming = false;
    let isTTSPlaying = false;
    let currentAudio = null;

    // ── DOM Elements ───────────────────────────────────────────────────────
    const $ = (id) => document.getElementById(id);
    const video         = $("camera-feed");
    const canvas        = $("frame-canvas");
    const ctx           = canvas.getContext("2d");

    // Clock
    const clockTime     = $("clock-time");
    const clockSeconds  = $("clock-seconds");
    const clockDate     = $("clock-date");

    // Weather
    const weatherTemp   = $("weather-temp-value");
    const weatherDesc   = $("weather-desc");
    const weatherHumidity = $("weather-humidity");
    const weatherWind   = $("weather-wind");

    // Market
    const marketPrice   = $("market-price");
    const marketChange  = $("market-change");
    const marketChangeVal = $("market-change-value");
    const marketChangePct = $("market-change-pct");
    const marketLow     = $("market-low");
    const marketHigh    = $("market-high");

    // User
    const widgetUser    = $("widget-user");
    const userName      = $("user-name");
    const userGreeting  = $("user-greeting");
    const taskList      = $("task-list");

    // Greeting overlay
    const greetingOverlay = $("greeting-overlay");
    const greetingEmoji = $("greeting-emoji");
    const greetingText  = $("greeting-text");
    const greetingMood  = $("greeting-mood");

    // Voice
    const widgetVoice   = $("widget-voice");
    const voiceStatus   = $("voice-status");
    const voiceTranscript = $("voice-transcript");

    // Assistant
    const widgetAssistant = $("widget-assistant");
    const assistantText = $("assistant-text");

    // Status
    const connBadge     = $("connection-status");
    const connText      = $("conn-text");
    const moodScanner   = $("mood-scanner");


    // ═══════════════════════════════════════════════════════════════════════
    //  1. CLOCK
    // ═══════════════════════════════════════════════════════════════════════

    function updateClock() {
        const now = new Date();
        const h = now.getHours().toString().padStart(2, "0");
        const m = now.getMinutes().toString().padStart(2, "0");
        const s = now.getSeconds().toString().padStart(2, "0");

        clockTime.textContent = `${h}:${m}`;
        clockSeconds.textContent = s;

        const options = { weekday: "long", month: "long", day: "numeric", year: "numeric" };
        clockDate.textContent = now.toLocaleDateString("en-IN", options);
    }

    setInterval(updateClock, 1000);
    updateClock();


    // ═══════════════════════════════════════════════════════════════════════
    //  2. CAMERA INITIALISATION
    // ═══════════════════════════════════════════════════════════════════════

    async function initCamera() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    width:  { ideal: 640 },
                    height: { ideal: 480 },
                    facingMode: "user",
                },
                audio: false,  // Audio handled separately
            });
            video.srcObject = stream;
            console.log("📷 Camera initialised");
        } catch (err) {
            console.error("⛔ Camera access denied:", err);
        }
    }


    // ═══════════════════════════════════════════════════════════════════════
    //  3. FRAME CAPTURE & SEND
    // ═══════════════════════════════════════════════════════════════════════

    function startFrameCapture() {
        if (frameTimer) clearInterval(frameTimer);

        frameTimer = setInterval(() => {
            if (!ws || ws.readyState !== WebSocket.OPEN) return;
            if (video.readyState < 2) return; // Not enough data yet

            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            ctx.drawImage(video, 0, 0);

            const b64 = canvas.toDataURL("image/jpeg", FRAME_QUALITY);
            ws.send(JSON.stringify({
                type: "frame",
                data: b64,
            }));
        }, FRAME_INTERVAL);
    }

    function stopFrameCapture() {
        if (frameTimer) {
            clearInterval(frameTimer);
            frameTimer = null;
        }
    }


    // ═══════════════════════════════════════════════════════════════════════
    //  4. AUDIO CAPTURE (for wake word / STT)
    // ═══════════════════════════════════════════════════════════════════════

    async function initAudioCapture() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    sampleRate: 16000,
                    echoCancellation: true,
                    noiseSuppression: true,
                }
            });

            audioContext = new AudioContext({ sampleRate: 16000 });
            const source = audioContext.createMediaStreamSource(stream);

            await audioContext.audioWorklet.addModule("/js/audio-processor.js");
            audioProcessorNode = new AudioWorkletNode(audioContext, "audio-capture");

            audioProcessorNode.port.onmessage = (e) => {
                if (!ws || ws.readyState !== WebSocket.OPEN) return;
                if (isTTSPlaying) return; // Mute mic during TTS/music

                const float32 = e.data;
                // Convert Float32 → Int16 PCM
                const int16 = new Int16Array(float32.length);
                for (let i = 0; i < float32.length; i++) {
                    const sample = Math.max(-1, Math.min(1, float32[i]));
                    int16[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
                }

                // Encode as base64
                const b64 = arrayBufferToBase64(int16.buffer);
                ws.send(JSON.stringify({
                    type: "audio_chunk",
                    data: b64,
                }));
            };

            source.connect(audioProcessorNode);
            // Do NOT connect to destination (no playback of raw mic)
            isAudioStreaming = true;
            console.log("🎙 Audio capture initialised (16kHz PCM)");

        } catch (err) {
            console.warn("⚠ Audio capture not available:", err.message);
        }
    }

    function arrayBufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        let binary = "";
        for (let i = 0; i < bytes.length; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return btoa(binary);
    }


    // ═══════════════════════════════════════════════════════════════════════
    //  5. WEBSOCKET CONNECTION
    // ═══════════════════════════════════════════════════════════════════════

    function connectWebSocket() {
        setConnectionState("connecting");

        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            console.log("🔌 WebSocket connected");
            setConnectionState("connected");
            startFrameCapture();
        };

        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                routeMessage(msg);
            } catch (err) {
                console.error("Message parse error:", err);
            }
        };

        ws.onclose = () => {
            console.warn("🔌 WebSocket disconnected");
            setConnectionState("disconnected");
            stopFrameCapture();
            setTimeout(connectWebSocket, RECONNECT_DELAY);
        };

        ws.onerror = (err) => {
            console.error("WebSocket error:", err);
            ws.close();
        };
    }

    function setConnectionState(state) {
        connBadge.className = `connection-badge ${state}`;
        const labels = {
            connecting:   "Connecting...",
            connected:    "Connected",
            disconnected: "Disconnected",
        };
        connText.textContent = labels[state] || state;
    }


    // ═══════════════════════════════════════════════════════════════════════
    //  6. MESSAGE ROUTER
    // ═══════════════════════════════════════════════════════════════════════

    function routeMessage(msg) {
        switch (msg.type) {
            case "weather":           updateWeather(msg.data);          break;
            case "market":            updateMarket(msg.data);           break;
            case "face_result":       updateFace(msg.data);             break;
            case "mood_result":       updateMoodResult(msg.data);       break;
            case "mood_status":       updateMoodStatus(msg.data);       break;
            case "greeting":          showGreeting(msg.data);           break;
            case "tasks":             updateTasks(msg.data);            break;
            case "tts_audio":         playTTSAudio(msg.data);           break;
            case "play_music":        playMusic(msg.data);              break;
            case "assistant_response": showAssistantResponse(msg.data); break;
            case "voice_status":      updateVoiceStatus(msg.data);      break;
            default:
                console.log("Unknown message type:", msg.type);
        }
    }


    // ═══════════════════════════════════════════════════════════════════════
    //  7. UI UPDATERS
    // ═══════════════════════════════════════════════════════════════════════

    // ── Weather ────────────────────────────────────────────────────────────
    function updateWeather(data) {
        if (!data) return;
        weatherTemp.textContent = data.temp;
        weatherDesc.textContent = data.description;
        weatherHumidity.innerHTML = `<span class="detail-icon">💧</span><span>${data.humidity}%</span>`;
        weatherWind.innerHTML = `<span class="detail-icon">💨</span><span>${data.wind_speed} km/h</span>`;
    }

    // ── Market ─────────────────────────────────────────────────────────────
    function updateMarket(data) {
        if (!data) return;
        marketPrice.textContent = formatNumber(data.price);

        const direction = data.change >= 0 ? "positive" : "negative";
        const arrow = data.change >= 0 ? "▲" : "▼";
        marketChange.className = `market-change ${direction}`;
        marketChangeVal.textContent = `${arrow} ${Math.abs(data.change).toFixed(2)}`;
        marketChangePct.textContent = `(${data.change_pct >= 0 ? "+" : ""}${data.change_pct.toFixed(2)}%)`;

        marketLow.textContent = `L: ${formatNumber(data.day_low)}`;
        marketHigh.textContent = `H: ${formatNumber(data.day_high)}`;
    }

    function formatNumber(num) {
        if (!num || num === 0) return "--";
        return num.toLocaleString("en-IN", {
            maximumFractionDigits: 2,
            minimumFractionDigits: 2,
        });
    }

    // ── Face Recognition ───────────────────────────────────────────────────
    function updateFace(data) {
        if (!data || !data.name) return;

        widgetUser.classList.remove("hidden");
        userName.textContent = data.name.toUpperCase();
    }

    // ── Mood Status (during scan) ──────────────────────────────────────────
    function updateMoodStatus(data) {
        if (data.scanning) {
            moodScanner.classList.remove("hidden");
        } else {
            moodScanner.classList.add("hidden");
        }
    }

    // ── Mood Result (scan complete) ────────────────────────────────────────
    function updateMoodResult(data) {
        moodScanner.classList.add("hidden");
    }

    // ── Greeting Overlay ───────────────────────────────────────────────────
    const moodEmojis = {
        happy:    "😊",
        sad:      "😢",
        angry:    "😤",
        surprise: "😲",
        fear:     "😨",
        neutral:  "😌",
        disgust:  "🤢",
    };

    function showGreeting(data) {
        if (!data) return;

        greetingEmoji.textContent = moodEmojis[data.mood] || "👋";
        greetingText.textContent = data.text;
        greetingMood.textContent = data.mood || "";
        greetingOverlay.classList.remove("hidden");

        // Auto-hide after timeout
        setTimeout(() => {
            greetingOverlay.classList.add("hidden");
        }, GREETING_DISPLAY_TIME);
    }

    // ── Tasks ──────────────────────────────────────────────────────────────
    function updateTasks(data) {
        if (!data) return;

        widgetUser.classList.remove("hidden");
        if (data.user) {
            userName.textContent = data.user.toUpperCase();
        }

        const items = data.items || [];
        if (items.length === 0) {
            taskList.innerHTML = `<div class="task-empty">No tasks yet — say "Add task ..."</div>`;
            return;
        }

        taskList.innerHTML = items.map((t, idx) => `
            <div class="task-item ${t.done ? "done" : ""}" style="animation-delay: ${idx * 0.05}s">
                <span class="task-id">#${t.id}</span>
                <div class="task-check">${t.done ? "✓" : ""}</div>
                <span class="task-text">${escapeHtml(t.text)}</span>
            </div>
        `).join("");
    }

    // ── TTS Audio Playback ─────────────────────────────────────────────────
    function playTTSAudio(b64Data) {
        if (!b64Data) return;

        isTTSPlaying = true;
        setVoiceState("speaking");

        // Decode base64 → Blob → Object URL
        const audioBytes = atob(b64Data);
        const audioArray = new Uint8Array(audioBytes.length);
        for (let i = 0; i < audioBytes.length; i++) {
            audioArray[i] = audioBytes.charCodeAt(i);
        }
        const blob = new Blob([audioArray], { type: "audio/mp3" });
        const url = URL.createObjectURL(blob);

        // Stop any currently playing audio
        if (currentAudio) {
            currentAudio.pause();
            currentAudio = null;
        }

        currentAudio = new Audio(url);
        currentAudio.onended = () => {
            isTTSPlaying = false;
            setVoiceState("idle");
            URL.revokeObjectURL(url);
            currentAudio = null;
        };
        currentAudio.onerror = () => {
            isTTSPlaying = false;
            setVoiceState("idle");
            URL.revokeObjectURL(url);
            currentAudio = null;
        };
        currentAudio.play().catch(err => {
            console.warn("TTS playback failed:", err);
            isTTSPlaying = false;
            setVoiceState("idle");
        });
    }

    // ── Music Playback ─────────────────────────────────────────────────────
    function playMusic(data) {
        if (!data || !data.url) return;

        // Music is served as static files from the backend
        const musicUrl = `${window.location.origin}${data.url}`;
        const audio = new Audio(musicUrl);
        audio.volume = 0.4; // Background music volume
        audio.onended = () => {
            isTTSPlaying = false;
        };
        audio.play().catch(err => {
            console.warn("Music playback failed:", err);
        });
    }

    // ── Assistant Response ─────────────────────────────────────────────────
    function showAssistantResponse(data) {
        if (!data || !data.text) return;

        assistantText.textContent = data.text;
        widgetAssistant.classList.remove("hidden");

        setTimeout(() => {
            widgetAssistant.classList.add("hidden");
        }, ASSISTANT_DISPLAY_TIME);
    }

    // ── Voice Status ───────────────────────────────────────────────────────
    function updateVoiceStatus(data) {
        if (!data) return;
        setVoiceState(data.state);
        if (data.text !== undefined) {
            voiceTranscript.textContent = data.text;
        }
    }

    function setVoiceState(state) {
        // Remove all voice state classes
        widgetVoice.classList.remove(
            "voice-listening", "voice-processing", "voice-speaking"
        );

        switch (state) {
            case "listening":
                widgetVoice.classList.add("voice-listening");
                voiceStatus.textContent = "Listening...";
                break;
            case "processing":
                widgetVoice.classList.add("voice-processing");
                voiceStatus.textContent = "Processing...";
                break;
            case "speaking":
                widgetVoice.classList.add("voice-speaking");
                voiceStatus.textContent = "Speaking...";
                break;
            default:
                voiceStatus.textContent = 'Say "Hey Lumo"';
                voiceTranscript.textContent = "";
        }
    }


    // ═══════════════════════════════════════════════════════════════════════
    //  8. UTILITIES
    // ═══════════════════════════════════════════════════════════════════════

    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }


    // ═══════════════════════════════════════════════════════════════════════
    //  9. INITIALISATION
    // ═══════════════════════════════════════════════════════════════════════

    async function init() {
        console.log("🪞 Smart Mirror UI initialising...");

        // Start camera
        await initCamera();

        // Start audio capture (for wake-word detection)
        await initAudioCapture();

        // Connect to backend
        connectWebSocket();

        console.log("🪞 Smart Mirror UI ready!");
    }

    // Launch when DOM is ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

})();
