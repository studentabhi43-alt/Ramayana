
#!/usr/bin/env python3
"""BADSAH progress-overlay preview.

- Reads final_output.mp4; never overwrites it.
- Uses the Hanuman transparent PNG as a moving overlay.
- Draws a thin white trail ONLY behind Hanuman (no line ahead).
- Scales Hanuman to 234 px wide (30% larger than the previous 180 px).
- Automatically adapts movement to the input video's measured duration.
- Copies the original audio stream without re-encoding.

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

EXPECTED_WIDTH = 1080
EXPECTED_HEIGHT = 1920
FPS = 30
AVATAR_WIDTH = 234  # 180 px + 30%


def run(command):
    print("+", " ".join(map(str, command)), flush=True)
    return subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True
    )


def probe(path):
    result = run([
        "ffprobe", "-v", "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height",
        "-of", "json", str(path),
    ])

    data = json.loads(result.stdout)
    streams = data.get("streams", [])

    video_stream = next(
        (s for s in streams if s.get("codec_type") == "video"),
        None
    )

    audio_stream = next(
        (s for s in streams if s.get("codec_type") == "audio"),
        None
    )

    if video_stream is None or audio_stream is None:
        raise RuntimeError(
            "Input must contain both video and audio streams."
        )

    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))

    if (width, height) != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
        raise RuntimeError(
            f"Expected {EXPECTED_WIDTH}x{EXPECTED_HEIGHT}; "
            f"found {width}x{height}. "
            "Refusing to resize or crop the source."
        )

    duration = float(data["format"]["duration"])

    if duration <= 0:
        raise RuntimeError(
            "Could not read a valid video duration."
        )

    return duration


def main():

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit(
            "ERROR: FFmpeg and FFprobe must be installed."
        )

    if not VIDEO.is_file():
        sys.exit(
            "ERROR: final_output.mp4 is missing from the repository root."
        )

    if not HANUMAN.is_file():
        sys.exit(
            "ERROR: assets/hanuman_flight.png is missing. "
            "Check the exact filename."
        )

    duration = probe(VIDEO)

    if OUTPUT.exists():
        OUTPUT.unlink()  # Only previous preview is removed

    # Progress design
    lane_x = 90
    lane_width = 900

    # Hanuman PNG size: 30% larger
    avatar_height = round(AVATAR_WIDTH * 724 / 2172)

    avatar_y = 1685
    line_y = avatar_y + avatar_height // 2
    line_height = 3

    travel = lane_width - AVATAR_WIDTH

    # Automatically calculate progress from actual video duration
    progress = f"min(1,max(0,t/{duration:.9f}))"

    # Hanuman moves from left to right
    avatar_x = f"{lane_x}+{travel}*({progress})"

    # White line grows only behind Hanuman
    filter_complex = (
        f"[1:v]scale={AVATAR_WIDTH}:-1,format=rgba[hanuman];"

        f"color=c=white@0.82:s={travel}x{line_height}:"
        f"r={FPS}:d={duration:.9f},"
        "format=rgba,"

        f"scale=w='max(1,{travel}*"
        f"min(1,max(0,t/{duration:.9f})))':"
        f"h={line_height}:eval=frame[trail];"

        f"[0:v][trail]overlay="
        f"x={lane_x}:y={line_y}:eval=frame[base];"

        f"[base][hanuman]overlay="
        f"x='{avatar_x}':y={avatar_y}:"
        "eval=frame:eof_action=repeat:"
        "format=auto[v]"
    )

    run([
        "ffmpeg", "-hide_banner", "-y",

        "-i", str(VIDEO),

        "-loop", "1",
        "-framerate", str(FPS),
        "-i", str(HANUMAN),

        "-filter_complex", filter_complex,

        "-map", "[v]",
        "-map", "0:a:0",

        "-t", f"{duration:.6f}",

        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",

        "-c:a", "copy",

        "-movflags", "+faststart",

        str(OUTPUT),
    ])

    output_duration = probe(OUTPUT)

    if abs(output_duration - duration) > 0.15:
        raise RuntimeError(
            f"Duration mismatch: "
            f"source={duration:.3f}s, "
            f"output={output_duration:.3f}s"
        )

    if OUTPUT.stat().st_size < 50_000:
        raise RuntimeError(
            "Preview MP4 is unexpectedly small."
        )

    print("\nSUCCESS: progress_test.mp4 created")
    print(f"Source duration: {duration:.3f}s")
    print(f"Preview duration: {output_duration:.3f}s")
    print(f"Hanuman PNG width: {AVATAR_WIDTH}px")
    print("White trail: behind Hanuman only; no line ahead")
    print("Original audio: copied without re-encoding")
    print("Original final_output.mp4: unchanged")


if __name__ == "__main__":
    main()
