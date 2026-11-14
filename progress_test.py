#!/usr/bin/env python3
"""Create a SAFE preview with a moving Hanuman PNG and white progress line.

Inputs are read only. The original final_output.mp4 is never overwritten.
Output: progress_test.mp4
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VIDEO = BASE_DIR / "final_output.mp4"
HANUMAN = BASE_DIR / "assets" / "hanuman_flight.png"
OUTPUT = BASE_DIR / "progress_test.mp4"

WIDTH = 1080
HEIGHT = 1920
FPS = 30


def run(command):
    print("+", " ".join(map(str, command)))
    return subprocess.run(command, check=True, text=True, capture_output=True)


def probe(path):
    result = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=codec_type,width,height",
        "-of", "json", str(path)
    ])
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video_stream or not audio_stream:
        raise RuntimeError("Input video must contain both video and audio streams.")
    if (video_stream.get("width"), video_stream.get("height")) != (WIDTH, HEIGHT):
        raise RuntimeError("Expected original video resolution 1080x1920; refusing to alter it.")
    return float(data["format"]["duration"]), video_stream, audio_stream


def main():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit("FFmpeg/FFprobe is not installed.")
    if not VIDEO.is_file():
        sys.exit("Missing final_output.mp4 in repository root.")
    if not HANUMAN.is_file():
        sys.exit("Missing assets/hanuman_flight.png. Check the GitHub upload path.")
    if OUTPUT.exists():
        OUTPUT.unlink()  # only removes the previous TEST output

    duration, _, _ = probe(VIDEO)

    # Draw a thin white track near the bottom. Hanuman remains a static PNG;
    # only its horizontal position changes with video timestamp t.
    track_x = 90
    track_width = 900
    track_y = 1770
    avatar_width = 180
    avatar_y = 1675

    filters = (
        f"[1:v]scale={avatar_width}:-1,format=rgba[hanuman];"
        f"[0:v]drawbox=x={track_x}:y={track_y}:w={track_width}:h=3:"
        "color=white@0.90:t=fill[base];"
        f"[base][hanuman]overlay=x='{track_x}+({track_width}-overlay_w)*t/{duration:.6f}':"
        f"y={avatar_y}:eval=frame:shortest=1:format=auto[v]"
    )

    run([
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(VIDEO),
        "-loop", "1", "-framerate", str(FPS), "-i", str(HANUMAN),
        "-filter_complex", filters,
        "-map", "[v]", "-map", "0:a:0",
        "-t", f"{duration:.6f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(OUTPUT)
    ])

    out_duration, out_video, out_audio = probe(OUTPUT)
    if abs(out_duration - duration) > 0.15:
        raise RuntimeError(
            f"Duration changed unexpectedly: source={duration:.3f}s, output={out_duration:.3f}s"
        )
    if OUTPUT.stat().st_size < 50_000:
        raise RuntimeError("Test MP4 is unexpectedly small.")

    print("\nSUCCESS: progress_test.mp4 created")
    print(f"Original duration: {duration:.3f}s")
    print(f"Test duration:     {out_duration:.3f}s")
    print("Original audio stream is copied without re-encoding.")
    print("Original final_output.mp4 was not modified.")


if __name__ == "__main__":
    main()
