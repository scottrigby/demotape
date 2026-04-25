import gradio as gr
from piper.voice import PiperVoice
import threading
import sys
import os
import json
import time
import wave

# Configuration
MODEL_PATH = "en_US-libritts_r-medium.onnx"
JSON_PATH = "en_US-libritts_r-medium.onnx.json"

# 1. PRE-FLIGHT CHECKS
if not os.path.exists(MODEL_PATH) or not os.path.exists(JSON_PATH):
    print(f"ERROR: Missing {MODEL_PATH} or {JSON_PATH}")
    sys.exit(1)

# 2. LOAD TTS ENGINE
print("Loading TTS engine...")
try:
    voice = PiperVoice.load(MODEL_PATH)
    print("✅ Engine loaded successfully!")
except Exception as e:
    print(f"❌ Failed to load Piper: {e}")
    sys.exit(1)

# 3. ROBUST SPEECH FUNCTION
def speak(text):
    if not text or not text.strip():
        return None
    
    timestamp = int(time.time())
    filename = f"/app/output_{timestamp}.wav"
    
    try:
        print(f"Synthesizing: {text[:20]}...")
        with wave.open(filename, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(voice.config.sample_rate)
            for chunk in voice.synthesize(text):
                wav_file.writeframes(chunk.audio_int16_bytes)
        
        file_size = os.path.getsize(filename)
        if file_size > 44:
            print(f"✅ Success: {file_size} bytes saved to {filename}")
            return filename
        else:
            print("❌ Error: Generated file is empty.")
            return None
            
    except Exception as e:
        print(f"❌ Synthesis error: {e}")
        return None

# 4. TERMINAL INTERACTION
def terminal_listener():
    print("--- TERMINAL READY: Type here and press Enter ---")
    while True:
        line = sys.stdin.readline()
        if line and line.strip():
            speak(line)

threading.Thread(target=terminal_listener, daemon=True).start()

# 5. GRADIO UI
with gr.Blocks(title="2026 Hybrid TTS Demo") as demo:
    gr.Markdown("# 🎙️ Linux TTS Demo (Podman-Mac Optimized)")
    with gr.Row():
        with gr.Column():
            input_text = gr.Textbox(label="Input", placeholder="Type here...")
            btn = gr.Button("Generate Audio", variant="primary")
        with gr.Column():
            audio_out = gr.Audio(label="Audio Result", autoplay=True)
    
    btn.click(fn=speak, inputs=input_text, outputs=audio_out)
    input_text.submit(fn=speak, inputs=input_text, outputs=audio_out)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)

