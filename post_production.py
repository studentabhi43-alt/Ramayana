
"""VEDIC GURU BADSAH — FINAL POST PRODUCTION
Combines caption_test.py V7 and progress_test.py.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parent
ASSETS = BASE / "assets"
WORK = BASE / "post_production_temp"

SOURCE = BASE / "final_output.mp4"
OUTPUT = BASE / "badsah_final.mp4"
LOGO = ASSETS / "logo.png"
HANUMAN = ASSETS / "hanuman_flight.png"
REPORT = BASE / "post_production_report.json"

WIDTH = 1080
HEIGHT = 1920
FPS = 30

# Exact progress-test settings
HANUMAN_WIDTH = 234
LANE_X = 90
LANE_WIDTH = 900
AVATAR_Y = 1685
LINE_HEIGHT = 3

# Three times the previous 260 px logo width
LOGO_WIDTH = 780
LOGO_TOP = 35


def run(command):
    print("+", " ".join(map(str, command)), flush=True)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr[-5000:]
        )
    return result


def probe(path):
    result = run([
        "ffprobe", "-v", "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height",
        "-of", "json", str(path)
    ])

    data = json.loads(result.stdout)
    streams = data.get("streams", [])

    video = next(
        (s for s in streams if s.get("codec_type") == "video"),
        None
    )
    audio = next(
        (s for s in streams if s.get("codec_type") == "audio"),
        None
    )

    if video is None or audio is None:
        raise RuntimeError("Video and audio streams are required.")

    if (
        int(video.get("width", 0)) != WIDTH
        or int(video.get("height", 0)) != HEIGHT
    ):
        raise RuntimeError("Expected 1080x1920 video.")

    return float(data["format"]["duration"])


def create_captions():
    """Run the exact V7 caption test implementation."""

    sys.path.insert(0, str(BASE))

    import caption_test

    caption_test.VIDEO = SOURCE
    caption_test.STORY = BASE / "story_output.json"
    caption_test.AUDIO = BASE / "audio_files"
    caption_test.OUTPUT = WORK / "captioned_video.mp4"
    caption_test.REPORT = WORK / "caption_report.json"

    # Preserve all original V7 design constants and rendering logic.
    caption_test.main()

    output = WORK / "captioned_video.mp4"

    if not output.exists() or output.stat().st_size < 50000:
        raise RuntimeError("V7 caption video was not generated.")

    return output


def create_final_video(captioned_video, original_duration):
    logo = Image.open(LOGO).convert("RGBA")
    logo_width = min(LOGO_WIDTH, WIDTH - 40)
    logo_height = round(logo.height * logo_width / logo.width)

    if logo_height + LOGO_TOP >= HEIGHT:
        raise RuntimeError("Logo dimensions are invalid.")

    logo.close()

    avatar_height = round(HANUMAN_WIDTH * 724 / 2172)
    line_y = AVATAR_Y + avatar_height // 2
    travel = LANE_WIDTH - HANUMAN_WIDTH

    progress = f"min(1,max(0,t/{original_duration:.9f}))"
    avatar_x = f"{LANE_X}+{travel}*({progress})"

    # Hanuman artwork, original test geometry and white trail
    filters = (
        f"[1:v]scale={HANUMAN_WIDTH}:-1,format=rgba[hanuman];"

        f"color=c=white@0.82:s={travel}x{LINE_HEIGHT}:"
        f"r={FPS}:d={original_duration:.9f},"
        "format=rgba,"
        f"scale=w='max(1,{travel}*"
        f"min(1,max(0,t/{original_duration:.9f})))':"
        f"h={LINE_HEIGHT}:eval=frame[trail];"

        f"[0:v][trail]overlay="
        f"x={LANE_X}:y={line_y}:eval=frame[base];"

        "[2:v]scale=780:-1,format=rgba[logo];"

        "[base][hanuman]overlay="
        f"x='{avatar_x}':y={AVATAR_Y}:"
        "eval=frame:eof_action=repeat[withhanuman];"

        "[withhanuman][logo]overlay="
        "x=(W-w)/2:y=35:"
        "eof_action=repeat[v]"
    )

    run([
        "ffmpeg", "-hide_banner", "-y",

        "-i", str(captioned_video),

        "-loop", "1",
        "-framerate", str(FPS),
        "-i", str(HANUMAN),

        "-loop", "1",
        "-framerate", str(FPS),
        "-i", str(LOGO),

        "-filter_complex", filters,

        "-map", "[v]",
        "-map", "0:a:0",

        "-t", f"{original_duration:.6f}",

        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "19",
        "-pix_fmt", "yuv420p",

        # Copy the captioned video's audio without another encode.
        "-c:a", "copy",

        "-movflags", "+faststart",
        str(OUTPUT)
    ])


def main():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} is not installed.")

    required = [
        SOURCE,
        BASE / "story_output.json",
        LOGO,
        HANUMAN,
        BASE / "caption_test.py"
    ]

    for path in required:
        if not path.is_file():
            raise FileNotFoundError(f"Required file missing: {path}")

    WORK.mkdir(parents=True, exist_ok=True)

    original_duration = probe(SOURCE)

    print("\nSTEP 1: GENERATING V7 CAPTIONS")
    captioned = create_captions()

    print("\nSTEP 2: APPLYING TESTED HANUMAN PROGRESS")
    print("\nSTEP 3: APPLYING LARGE CHANNEL LOGO")

    create_final_video(captioned, original_duration)

    final_duration = probe(OUTPUT)

    if abs(final_duration - original_duration) > 0.2:
        raise RuntimeError("Final video duration does not match source.")

    if OUTPUT.stat().st_size < 500000:
        raise RuntimeError("Final MP4 is unexpectedly small.")

    report = {
        "status": "success",
        "output": OUTPUT.name,
        "duration_seconds": round(final_duration, 3),
        "resolution": "1080x1920",
        "caption_design": "Original caption_test.py V7",
        "caption_grouping": "Maximum 5 words",
        "caption_active_word": "Gold",
        "caption_other_words": "White",
        "caption_background": "Maroon and gold rounded bubble",
        "caption_timing": "Whisper word timestamps with interpolation for unmatched words",
        "caption_animation": "Original V7 fade and scale",
        "hanuman_asset": "assets/hanuman_flight.png",
        "hanuman_width": HANUMAN_WIDTH,
        "hanuman_position": "Original progress_test.py geometry",
        "hanuman_movement": "Left to right",
        "progress_trail": "Thin white trail behind Hanuman only",
        "logo_asset": "assets/logo.png",
        "logo_width": LOGO_WIDTH,
        "logo_position": "Top center",
        "narrator_portrait": False,
        "original_video_preserved": True,
        "audio": "Copied from captioned video without another encode"
    }

    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("\nFINAL PRODUCTION SUCCESS")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
