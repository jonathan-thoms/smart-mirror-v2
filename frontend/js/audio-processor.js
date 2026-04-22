/* ═══════════════════════════════════════════════════════════════════════════
   Smart Mirror — Audio Capture Worklet Processor
   Buffers raw PCM audio and sends chunks to the main thread.
   ═══════════════════════════════════════════════════════════════════════════ */

class AudioCaptureProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this._bufferSize = 8192; // ~170ms at 48kHz, sends ~2730 samples at 16kHz
        this._buffer = new Float32Array(this._bufferSize);
        this._bytesWritten = 0;
    }

    process(inputs, outputs, parameters) {
        const input = inputs[0];
        if (!input || input.length === 0) return true;

        const channelData = input[0]; // Mono channel
        if (!channelData) return true;

        for (let i = 0; i < channelData.length; i++) {
            this._buffer[this._bytesWritten] = channelData[i];
            this._bytesWritten++;

            if (this._bytesWritten >= this._bufferSize) {
                // Send the filled buffer to the main thread
                this.port.postMessage(this._buffer.slice(0));
                this._bytesWritten = 0;
            }
        }

        return true; // Keep processor alive
    }
}

registerProcessor("audio-capture", AudioCaptureProcessor);
