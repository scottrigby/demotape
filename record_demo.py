#!/usr/bin/env python3
"""Record a split-screen product demo (browser + terminal + TTS narration) to MP4.

Reads a YAML demo spec, generates per-step assets (Piper narration WAV,
Playwright browser WebM, VHS terminal MP4), composites each step side-by-side
with FFmpeg's hstack, and concatenates the per-step clips into a single MP4.
"""

import argparse
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import yaml
from piper.voice import PiperVoice
from playwright.sync_api import sync_playwright

PADDING_MS = 250
FPS = 30


def synth(voice: PiperVoice, text: str, speaker_id: int, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(voice.config.sample_rate)
        for chunk in voice.synthesize(text):
            wav_file.writeframes(chunk.audio_int16_bytes)


def wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as f:
        return int(f.getnframes() * 1000 / f.getframerate())


def record_browser(action: dict, total_ms: int, video_dir: Path,
                   pane_w: int, pane_h: int) -> Path:
    video_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": pane_w, "height": pane_h},
            record_video_dir=str(video_dir),
            record_video_size={"width": pane_w, "height": pane_h},
        )
        page = ctx.new_page()
        try:
            if "goto" in action:
                page.goto(action["goto"], wait_until="domcontentloaded", timeout=20000)
            elif "click" in action:
                page.click(action["click"], timeout=5000)
        except Exception as e:
            print(f"  ! browser action failed (continuing): {e}", file=sys.stderr)
        page.wait_for_timeout(total_ms)
        ctx.close()
        browser.close()
    webms = sorted(video_dir.glob("*.webm"))
    if not webms:
        raise RuntimeError(f"Playwright produced no webm in {video_dir}")
    return webms[0]


def vhs_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def compile_tape(actions: list, total_ms: int, output_mp4: Path,
                 pane_w: int, pane_h: int) -> str:
    lines = [
        f"Output {output_mp4}",
        f"Set Width {pane_w}",
        f"Set Height {pane_h}",
        "Set FontSize 28",
        "Set TypingSpeed 50ms",
        'Set Theme "Dracula"',
        "Set Padding 30",
    ]
    used_ms = 0
    for action in actions:
        if "type" in action:
            lines.append(f'Type "{vhs_escape(action["type"])}"')
            used_ms += len(action["type"]) * 50
        if action.get("enter"):
            lines.append("Enter")
            used_ms += 100
        if "sleep_ms" in action:
            lines.append(f'Sleep {int(action["sleep_ms"])}ms')
            used_ms += int(action["sleep_ms"])
    remaining = total_ms - used_ms
    if remaining > 0:
        lines.append(f"Sleep {remaining}ms")
    return "\n".join(lines) + "\n"


def record_terminal(actions: list, total_ms: int, work_dir: Path,
                    pane_w: int, pane_h: int, idx: int) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    tape_path = work_dir / f"{idx}.tape"
    out_path = (work_dir / f"{idx}.mp4").resolve()
    tape_path.write_text(compile_tape(actions, total_ms, out_path, pane_w, pane_h))
    subprocess.run(["vhs", str(tape_path)], check=True)
    return out_path


def composite_step(browser_webm: Path, terminal_mp4: Path, audio_wav: Path,
                   output_mp4: Path, pane_w: int, pane_h: int) -> None:
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    filter_complex = (
        f"[0:v]scale={pane_w}:{pane_h}:force_original_aspect_ratio=decrease,"
        f"pad={pane_w}:{pane_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}[L];"
        f"[1:v]scale={pane_w}:{pane_h}:force_original_aspect_ratio=decrease,"
        f"pad={pane_w}:{pane_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}[R];"
        f"[L][R]hstack=inputs=2[v];"
        f"[2:a]apad[a]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(browser_webm),
        "-i", str(terminal_mp4),
        "-i", str(audio_wav),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        str(output_mp4),
    ]
    subprocess.run(cmd, check=True)


def concat_clips(clip_paths: list, out_path: Path, work_dir: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = work_dir / "concat.txt"
    list_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in clip_paths) + "\n"
    )
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file), "-c", "copy", str(out_path),
    ], check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("yaml_path", help="Path to demo YAML spec")
    parser.add_argument("--out", default="/workspace/out/demo.mp4")
    parser.add_argument("--work", default="/workspace/work")
    parser.add_argument(
        "--voice-model",
        default="/workspace/voices/en_US-libritts_r-medium.onnx",
    )
    parser.add_argument("--keep-work", action="store_true",
                        help="Don't wipe the work dir at start")
    args = parser.parse_args()

    spec = yaml.safe_load(Path(args.yaml_path).read_text())
    res = spec.get("resolution", {"w": 1920, "h": 1080})
    pane_w, pane_h = res["w"] // 2, res["h"]
    speaker_id = spec.get("voice", 0)

    work = Path(args.work)
    if work.exists() and not args.keep_work:
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    print(f"Loading Piper voice from {args.voice_model}...")
    voice = PiperVoice.load(args.voice_model)
    print(f"  sample_rate={voice.config.sample_rate}, speaker_id={speaker_id}")

    clip_paths = []
    for i, step in enumerate(spec["steps"]):
        sid = step.get("id", f"step{i}")
        narration = step["narration"]
        print(f"\n=== [{i}] {sid}: {narration[:60]}... ===")

        audio_path = work / "audio" / f"{i}.wav"
        synth(voice, narration, speaker_id, audio_path)
        narration_ms = wav_duration_ms(audio_path)
        total_ms = narration_ms + PADDING_MS
        print(f"  narration={narration_ms}ms total={total_ms}ms")

        browser_action = step.get("browser") or {"goto": "about:blank"}
        b_webm = record_browser(browser_action, total_ms,
                                work / "browser" / f"{i}", pane_w, pane_h)
        print(f"  browser → {b_webm.name}")

        t_mp4 = record_terminal(step.get("terminal", []) or [],
                                total_ms, work / "term", pane_w, pane_h, i)
        print(f"  terminal → {t_mp4.name}")

        clip_path = work / "clips" / f"{i}.mp4"
        composite_step(b_webm, t_mp4, audio_path, clip_path, pane_w, pane_h)
        clip_paths.append(clip_path)
        print(f"  composite → {clip_path.name}")

    out_path = Path(args.out)
    print(f"\n=== Concatenating {len(clip_paths)} clips → {out_path} ===")
    concat_clips(clip_paths, out_path, work)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_name,width,height",
         "-of", "default=nw=1", str(out_path)],
        capture_output=True, text=True,
    )
    print(probe.stdout)
    print(f"✅ {out_path}")


if __name__ == "__main__":
    main()
