# POC: Open-source split-screen demo recorder with TTS narration

## Context
End goal is an all-open-source pipeline for recording product demos: a single MP4 with a browser pane on the left, a terminal pane on the right, and TTS narration synced to the visuals. We're inside a claudeman-managed devcontainer (Debian 12 aarch64, Python + Node already present), so environment setup goes through a **claudeman profile** rather than ad-hoc Dockerfile edits. The existing Piper TTS POC at `/workspace/app.py` is reference material — the working `voice.synthesize()` loop with `chunk.audio_int16_bytes` (and the `en_US-libritts_r-medium` model files) is reused, but the POC lives in its own subdirectory.

## Tool choices

| Concern | Choice | Why |
|---|---|---|
| Browser capture | **Playwright (Python)** with `record_video_dir` | Native WebM recording inside headless Chromium, deterministic, no Xvfb needed. Already covered by claudeman's `schlich/playwright` feature |
| Terminal capture | **VHS** (charmbracelet/vhs) | Declarative `.tape` files map to YAML steps; emits clean MP4 directly. Beats asciinema+agg (GIF only) and live screen-capture (fragile) |
| TTS | **Piper** (reuse pattern from `app.py`) | `voice.synthesize(text)` loop with `chunk.audio_int16_bytes` is already proven working |
| Composition | **FFmpeg** `hstack` + concat demuxer | Standard pattern; per-clip re-encode then stream-copy concat avoids drift |
| Environment | **claudeman profile** + minimal `postCreateCommand` for VHS | Profile owns features/domains/caches declaratively |

## File structure
```
~/.claudeman/profiles/
  demo-recorder.json          # NEW claudeman profile

/workspace/
  .devcontainer/devcontainer.json   # extend: postCreateCommand for VHS + pip installs
  demo-recorder/                    # NEW — POC lives here, isolated from app.py
    record_demo.py                  # single entrypoint
    requirements.txt                # piper-tts, playwright, pyyaml
    voices/                         # symlink/copy of model from /workspace/
      en_US-libritts_r-medium.onnx
      en_US-libritts_r-medium.onnx.json
    demos/example.yaml              # minimal 2-step smoke-test demo
  out/                              # MP4 output (workspace mount, visible on host)
```

## claudeman profile (`~/.claudeman/profiles/demo-recorder.json`)
Modeled on the existing `web` profile, plus ffmpeg + caches + the outbound hosts we need:
```json
{
  "name": "demo-recorder",
  "description": "Open-source product demo recorder: Playwright + Piper TTS + VHS + FFmpeg",
  "features": {
    "ghcr.io/devcontainers/features/python:1": { "version": "latest" },
    "ghcr.io/schlich/devcontainer-features/playwright:0": { "browsers": "chromium" },
    "ghcr.io/devcontainers-extra/features/ffmpeg-apt-get:1": {}
  },
  "extraDomains": [
    "pypi.org",
    "files.pythonhosted.org",
    "playwright.azureedge.net",
    "cdn.playwright.dev",
    "github.com",
    "objects.githubusercontent.com",
    "huggingface.co",
    "cdn-lfs.huggingface.co"
  ],
  "cacheEnv": {
    "PIP_CACHE_DIR": "pip",
    "PLAYWRIGHT_BROWSERS_PATH": "playwright"
  }
}
```
Run with: `claudeman run --profile=demo-recorder`. (Verify the exact ffmpeg feature ref via `claudeman feature search ffmpeg` before committing — the `devcontainers-extra` ref above is the most likely match.)

## Project `.devcontainer/devcontainer.json` additions
Profile handles features/domains/caches; the project still owns the one-off VHS binary install + Python deps.
```json
"postCreateCommand": "set -e; pip install -r demo-recorder/requirements.txt; sudo apt-get update && sudo apt-get install -y ttyd fonts-dejavu; curl -fsSL https://github.com/charmbracelet/vhs/releases/latest/download/vhs_Linux_arm64.tar.gz | sudo tar xz -C /usr/local/bin vhs"
```

## Demo schema (`demo-recorder/demos/example.yaml`)
```yaml
title: "deploy-demo"
resolution: { w: 1920, h: 1080 }     # each pane = 960x1080
voice: 0                             # Piper speaker_id (0–903)
steps:
  - id: open
    narration: "Let's open the dashboard."
    browser: { goto: "https://example.com" }
    terminal: []
  - id: deploy
    narration: "Now we run the deploy command."
    browser: { click: "text=Deploy" }
    terminal:
      - type: "kubectl get pods"
      - enter: true
      - sleep_ms: 1500
```
Per-step duration = `max(narration, visuals) + 250 ms`. Narration is the timing master; visuals stretch via `wait_for_timeout` (browser) and `Sleep` (VHS) to match.

## `record_demo.py` flow
```
load yaml; load PiperVoice once
for i, step in enumerate(steps):
    wav = synth(step.narration, speaker_id=voice)   → work/audio/{i}.wav
    dur_ms = wave_duration(wav)

    # Browser pane
    with sync_playwright() as p:
        ctx = chromium.launch().new_context(
            viewport=960x1080,
            record_video_dir=work/browser/{i},
            record_video_size=960x1080)
        page = ctx.new_page()
        run_action(page, step.browser)
        page.wait_for_timeout(dur_ms + 250)
        ctx.close()                                  # flushes webm

    # Terminal pane
    tape = compile_tape(step.terminal, dur_ms, size=960x1080)
    subprocess.run(["vhs", tape])                    → work/term/{i}.mp4

    # Per-step composite (re-encode for uniform timebase)
    ffmpeg -i browser.webm -i term.mp4 -i audio.wav \
      -filter_complex "[0:v]scale=960:1080,setsar=1[L];
                       [1:v]scale=960:1080,setsar=1[R];
                       [L][R]hstack=inputs=2,fps=30[v];
                       [2:a]apad[a]" \
      -map "[v]" -map "[a]" -shortest \
      -c:v libx264 -preset veryfast -crf 22 -pix_fmt yuv420p \
      -c:a aac work/clips/{i}.mp4

write concat.txt; ffmpeg -f concat -safe 0 -i concat.txt -c copy out/demo.mp4
```
The `synth()` helper is lifted from `app.py`'s working `speak()`: load `PiperVoice`, iterate `voice.synthesize(text)` writing `chunk.audio_int16_bytes` into a `wave.open()` file with `nchannels=1, sampwidth=2, framerate=voice.config.sample_rate`.

## Critical files
- `~/.claudeman/profiles/demo-recorder.json` (new profile)
- `/workspace/.devcontainer/devcontainer.json` (extend — add `postCreateCommand`)
- `/workspace/demo-recorder/record_demo.py` (new)
- `/workspace/demo-recorder/requirements.txt` (new)
- `/workspace/demo-recorder/demos/example.yaml` (new)
- `/workspace/app.py` (reference only — copy synth loop pattern)

## Riskiest part: visual/audio sync drift across step boundaries
Playwright WebMs aren't always exactly wall-clock duration (codec keyframes, browser warmup), and VHS adds startup frames. Concatenating misaligned clips drifts audio against video. **De-risk:**
1. Per-step clips are *re-encoded* (not `-c copy`) so all share identical timebase, fps, sample rate, pixel format
2. Pad each clip's audio to exact video duration with `apad` so A/V are equal length per clip
3. Concat demuxer runs only on uniform clips
4. Smoke-test with a 2-step YAML before scaling up

## Verification
1. Drop `demo-recorder.json` into the claudeman profiles directory
2. Restart the session: `claudeman run --profile=demo-recorder` (rebuilds the container with the new profile + runs `postCreateCommand`)
3. Inside the container: `python demo-recorder/record_demo.py demo-recorder/demos/example.yaml`
4. On Mac host: `open out/demo.mp4` — confirm split-screen layout, narration audible, terminal commands type visibly
5. Inside container: `ffprobe out/demo.mp4` — expect 1920x1080, h264+aac, single audio stream, duration ≈ sum of step durations
