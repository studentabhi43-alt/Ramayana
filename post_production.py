#!/usr/bin/env python3
"""VEDIC GURU BADSAH post-production pipeline.

Keeps the existing tested designs unchanged and chains them in this order:
1. Hanuman progression bar (progress_test.py)
2. Premium word-synced captions (caption_test.py)
3. Small, safe-zone logo watermark (assets/logo.png)

No intro, no outro, and no extra title cards are added.
Input:  final_output.mp4
Output: badsah_final.mp4
"""

import json
import shutil
import subprocess
from pathlib import Path

import caption_test
import progress_test

BASE = Path(__file__).resolve().parent
ASSETS = BASE / "assets"
SOURCE = BASE / "final_output.mp4"
STORY = BASE / "story_output.json"
AUDIO = BASE / "audio_files"
HANUMAN = ASSETS / "hanuman_flight.png"
LOGO = ASSETS / "logo.png"
WORK = BASE / "post_production_temp"
PROGRESS_VIDEO = WORK / "01_hanuman_progress.mp4"
CAPTION_VIDEO = WORK / "02_captions.mp4"
CAPTION_REPORT = WORK / "caption_test_report_v7.json"
OUTPUT = BASE / "badsah_final.mp4"
REPORT = BASE / "post_production_report.json"

# 1080x1920 vertical video: restrained 13.4%-width watermark.
# Top-left of the central safe area, away from Shorts' right-side controls
# and the lower caption/description area.
LOGO_WIDTH = 145
LOGO_X = 76
LOGO_Y = 285
LOGO_OPACITY = 0.90


def run(command):
    result = subprocess.run(
        [str(part) for part in command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(str(part) for part in command)
            + "\n"
            + result.stderr[-5000:]
        )
    return result


def probe(path):
    result = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=codec_type,width,height",
        "-of", "json", path,
    ])
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None or audio is None:
        raise RuntimeError(f"{path.name} must contain video and audio streams.")
    width = int(video.get("width", 0))
    height = int(video.get("height", 0))
    if (width, height) != (1080, 1920):
        raise RuntimeError(
            f"{path.name}: expected 1080x1920, found {width}x{height}."
        )
    duration = float(data["format"]["duration"])
    if duration <= 0:
        raise RuntimeError(f"Invalid duration for {path.name}.")
    return duration


def main():
    for executable in ("ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            raise RuntimeError(f"{executable} is not installed.")

    required = (SOURCE, STORY, HANUMAN, LOGO)
    missing = [str(path.relative_to(BASE)) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Required project files missing: " + ", ".join(missing))
    if not AUDIO.is_dir():
        raise FileNotFoundError("audio_files/ folder is missing.")

    WORK.mkdir(parents=True, exist_ok=True)
    original_duration = probe(SOURCE)

    # STEP 1 — Run the exact saved Hanuman progression-bar test design.
    progress_test.VIDEO = SOURCE
    progress_test.HANUMAN = HANUMAN
    progress_test.OUTPUT = PROGRESS_VIDEO
    progress_test.main()
    if not PROGRESS_VIDEO.is_file() or PROGRESS_VIDEO.stat().st_size == 0:
        raise RuntimeError("Hanuman progression-bar stage did not create its video.")
    progress_duration = probe(PROGRESS_VIDEO)
    if abs(progress_duration - original_duration) > 0.15:
        raise RuntimeError("Hanuman stage changed the episode duration.")

    # STEP 2 — Run the exact saved V7 caption test design on the progress video.
    caption_test.VIDEO = PROGRESS_VIDEO
    caption_test.STORY = STORY
    caption_test.AUDIO = AUDIO
    caption_test.OUTPUT = CAPTION_VIDEO
    caption_test.REPORT = CAPTION_REPORT
    caption_test.main()
    if not CAPTION_VIDEO.is_file() or CAPTION_VIDEO.stat().st_size == 0:
        raise RuntimeError("Caption stage did not create its video.")
    caption_duration = probe(CAPTION_VIDEO)
    if abs(caption_duration - original_duration) > 0.35:
        raise RuntimeError("Caption stage changed the episode duration.")

    # STEP 3 — Add the logo as a subtle watermark; no intro/outro is generated.
    # The logo is 145px wide (13.4% of 1080px), preserving its original ratio.
    # x=76, y=285 keeps it inside a conservative vertical-video safe area.
    logo_filter = (
        f"[1:v]scale={LOGO_WIDTH}:-1,format=rgba,"
        f"colorchannelmixer=aa={LOGO_OPACITY}[logo];"
        f"[0:v][logo]overlay=x={LOGO_X}:y={LOGO_Y}:"
        "eof_action=repeat:shortest=1,format=yuv420p[v]"
    )

    OUTPUT.unlink(missing_ok=True)
    run([
        "ffmpeg", "-hide_banner", "-y",
        "-i", CAPTION_VIDEO,
        "-loop", "1", "-framerate", "30", "-i", LOGO,
        "-filter_complex", logo_filter,
        "-map", "[v]", "-map", "0:a:0",
        "-t", f"{original_duration:.6f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        OUTPUT,
    ])

    final_duration = probe(OUTPUT)
    if abs(final_duration - original_duration) > 0.35:
        raise RuntimeError(
            f"Final duration mismatch: source={original_duration:.3f}s, "
            f"final={final_duration:.3f}s"
        )
    if OUTPUT.stat().st_size < 50_000:
        raise RuntimeError("Final video is unexpectedly small.")

    caption_data = {}
    if CAPTION_REPORT.is_file():
        caption_data = json.loads(CAPTION_REPORT.read_text(encoding="utf-8"))

    report = {
        "status": "success",
        "output": OUTPUT.name,
        "resolution": "1080x1920",
        "original_duration_seconds": round(original_duration, 3),
        "final_duration_seconds": round(final_duration, 3),
        "intro": "Removed; no intro added",
        "outro": "None",
        "post_production_order": [
            "Hanuman progression bar from progress_test.py",
            "Premium V7 word-highlight captions from caption_test.py",
            "Logo watermark from assets/logo.png",
        ],
        "hanuman_asset": "assets/hanuman_flight.png",
        "logo": {
            "asset": "assets/logo.png",
            "width_px": LOGO_WIDTH,
            "position_px": {"x": LOGO_X, "y": LOGO_Y},
            "opacity": LOGO_OPACITY,
            "placement": "Top-left inside conservative vertical-video safe area",
        },
        "caption_style": caption_data.get("caption_style", "Saved caption_test.py design"),
        "caption_version": caption_data.get("version", "V7"),
        "original_video_preserved": True,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nSUCCESS: {OUTPUT}")


if __name__ == "__main__":
    main()
