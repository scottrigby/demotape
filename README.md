# Open-source split-screen demo recorder

A small POC that records narrated product demos as a single MP4 — browser pane on the left, terminal pane on the right, TTS narration synced to the visuals. Built from open-source parts: Playwright (browser), VHS (terminal), Piper (TTS), FFmpeg (composition).

## Layout

```
claudeman-profile.json    Source of truth for the claudeman profile
record_demo.py            Entrypoint: YAML → MP4
setup.sh                  One-time install of bits the profile can't cover (VHS, ttyd, pip deps)
requirements.txt          Python deps
demos/example.yaml        30-second sample demo (Piper TTS story)
voices/                   Piper voice models (gitignored — see "Voice models" below)
out/                      Final MP4 lands here (gitignored)
work/                     Per-step intermediate artifacts (gitignored)
examples/piper-gradio/    Earlier Gradio TTS sandbox kept for reference
.claude/claudeman/profiles/demo-recorder.json  →  ../../../claudeman-profile.json
```

## Quick start

```bash
# Restart the session under the new profile (run on the host)
claudeman run --profile demo-recorder -- --continue

# Inside the container, one-time install
bash setup.sh

# Render the sample demo
python record_demo.py demos/example.yaml
# → out/demo.mp4
```

On the Mac host: `open out/demo.mp4`.

## Voice models

The Piper voice (`en_US-libritts_r-medium`) lives in `voices/` but is gitignored (~80 MB). Download from Hugging Face:

```bash
mkdir -p voices && cd voices
curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/libritts_r/medium/en_US-libritts_r-medium.onnx
curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/libritts_r/medium/en_US-libritts_r-medium.onnx.json
```

The model has 904 speakers; pick one with `voice: <0–903>` in your demo YAML.

## Demo YAML schema

Each step has `narration` (TTS), `browser` (one Playwright action), and `terminal` (a list of VHS actions). Narration drives the timing — visuals stretch to match. See `demos/example.yaml`.
