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
    const MUSIC_DISPLAY_TIME = 15000;   // ms to show music notification

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

    // Music notification
    const musicNotif    = $("music-notification");
    const musicLabel    = $("music-label");
    const musicTrack    = $("music-track");
    let musicNotifTimer = null;

    // Status
    const connBadge     = $("connection-status");
    const connText      = $("conn-text");
    const moodScanner   = $("mood-scanner");

    // Speech debug
    const speechDebug   = $("speech-debug");
    const speechDbgText = $("speech-debug-text");

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
    //  4. VOICE RECOGNITION (Web Speech API — wake word + STT)
    // ═══════════════════════════════════════════════════════════════════════

    const WAKE_PHRASE = "hey lumo";
    let recognition = null;
    let isWakeWordActive = false;  // true = listening for a command after wake word

    // All the ways Chrome might hear "Hey Lumo"
    const WAKE_VARIANTS = [
        "hey lumo", "a lumo", "hey limo", "hey luma", "hey loumo",
        "hello lumo", "hey lumoo", "hey lomo", "he lumo", "hey loomo",
        "hey luma", "heylumo", "hey llamo", "hey lobo"
    ];

    function matchesWakeWord(text) {
        const lower = text.toLowerCase();
        return WAKE_VARIANTS.some(v => lower.includes(v));
    }

    function updateDebugBar(text, isWake = false) {
        if (speechDbgText) speechDbgText.textContent = text;
        if (speechDebug) {
            if (isWake) {
                speechDebug.classList.add("wake-detected");
            } else {
                speechDebug.classList.remove("wake-detected");
            }
        }
    }

    function initVoiceRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            console.warn("⚠ Web Speech API not available in this browser");
            updateDebugBar("Web Speech API not available");
            return;
        }

        recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = "en-US";
        recognition.maxAlternatives = 1;

        recognition.onresult = (event) => {
            if (isTTSPlaying) return; // Ignore during playback

            // Scan ALL results (not just latest) for better detection
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const result = event.results[i];
                const transcript = result[0].transcript.trim();
                const lower = transcript.toLowerCase();

                // Always update the debug bar with what's being heard
                updateDebugBar(transcript);

                if (!isWakeWordActive) {
                    // ── Scanning for wake word (check even interim) ────
                    if (matchesWakeWord(lower)) {
                        isWakeWordActive = true;
                        console.log(`🎤 Wake word detected! (heard: "${transcript}")`);
                        updateDebugBar(`✅ WAKE WORD: "${transcript}"`, true);
                        setVoiceState("listening");

                        if (ws && ws.readyState === WebSocket.OPEN) {
                            ws.send(JSON.stringify({
                                type: "voice_status_update",
                                data: { state: "wake_word" }
                            }));
                        }

                        // Reset recognition to capture fresh command
                        recognition.stop();
                        return; // Stop processing once wake word found
                    }
                } else {
                    // ── Capturing command after wake word ─────────────
                    if (result.isFinal) {
                        const command = transcript;
                        // Filter out the wake word from the command
                        let cleaned = command;
                        for (const v of WAKE_VARIANTS) {
                            cleaned = cleaned.replace(new RegExp(v, "gi"), "");
                        }
                        cleaned = cleaned.trim();

                        if (cleaned.length > 2) {
                            console.log(`🎤 Command: "${cleaned}"`);
                            updateDebugBar(`📤 Command: "${cleaned}"`);
                            isWakeWordActive = false;
                            setVoiceState("processing");

                            if (ws && ws.readyState === WebSocket.OPEN) {
                                ws.send(JSON.stringify({
                                    type: "voice_command",
                                    text: cleaned,
                                }));
                            }
                        }
                    } else {
                        // Show interim transcript in orb and debug bar
                        voiceTranscript.textContent = transcript;
                        updateDebugBar(`🎤 Hearing: "${transcript}"`, true);
                    }
                }
            }
        };

        recognition.onend = () => {
            // Auto-restart — Chrome stops recognition periodically
            const delay = isWakeWordActive ? 50 : 200;
            setTimeout(() => {
                try {
                    recognition.start();
                    updateDebugBar(isWakeWordActive ? "Listening for command..." : "Say 'Hey Lumo'...");
                } catch(e) { /* already started */ }
            }, delay);
        };

        recognition.onerror = (event) => {
            if (event.error === "no-speech") {
                updateDebugBar("(silence) Say 'Hey Lumo'...");
                return;
            }
            if (event.error === "aborted") return;

            console.warn("🎤 Speech recognition error:", event.error);
            updateDebugBar(`Error: ${event.error}`);

            if (isWakeWordActive && event.error === "network") {
                isWakeWordActive = false;
                setVoiceState("idle");
            }
        };

        // Start listening
        try {
            recognition.start();
            isAudioStreaming = true;
            updateDebugBar("Say 'Hey Lumo'...");
            console.log("🎤 Voice recognition started (Web Speech API)");
        } catch (e) {
            console.warn("⚠ Could not start speech recognition:", e.message);
            updateDebugBar("Failed to start: " + e.message);
        }
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
            case "music_notification": showMusicNotification(msg.data); break;
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
            notifyAudioDone();
        };
        currentAudio.onerror = () => {
            isTTSPlaying = false;
            setVoiceState("idle");
            URL.revokeObjectURL(url);
            currentAudio = null;
            notifyAudioDone();
        };
        currentAudio.play().catch(err => {
            console.warn("TTS playback failed:", err);
            isTTSPlaying = false;
            setVoiceState("idle");
            notifyAudioDone();
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
            notifyAudioDone();
        };
        audio.play().catch(err => {
            console.warn("Music playback failed:", err);
        });
    }

    // ── Music Notification ("Now Playing" bar) ─────────────────────────────
    function showMusicNotification(data) {
        if (!data) return;

        musicLabel.textContent = data.has_track ? "NOW PLAYING" : "SUGGESTED";
        musicTrack.textContent = data.has_track
            ? data.track_name || data.label
            : `${data.label} ♪`;

        musicNotif.classList.remove("hidden");

        // Clear previous timer
        if (musicNotifTimer) clearTimeout(musicNotifTimer);
        musicNotifTimer = setTimeout(() => {
            musicNotif.classList.add("hidden");
            musicNotifTimer = null;
        }, MUSIC_DISPLAY_TIME);
    }

    // ── Notify backend audio finished (un-gates the mic) ──────────────────
    function notifyAudioDone() {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "audio_done" }));
        }
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

        // Start voice recognition (Web Speech API — wake word + STT)
        initVoiceRecognition();

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
