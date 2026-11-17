
"""BADSAH post-production.
Keeps the original episode and places the channel logo
as a watermark in the top-right corner throughout.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
ASSETS = BASE / "assets"
STORY = BASE / "story_output.json"
SOURCE = BASE / "final_output.mp4"
OUTPUT = BASE / "badsah_final.mp4"
WORK = BASE / "post_production_temp"
REPORT = BASE / "post_production_report.json"
ASS = WORK / "captions.ass"

W, H, FPS = 1080, 1920, 30
LOGO_INTRO_SECONDS = 3.0
LOGO_WIDTH = 190
LOGO_CORNER = "top-right"


def run(cmd):
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    if result.returncode:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(map(str, cmd))
            + "\n"
            + result.stderr[-3500:]
        )
    return result


def duration(path):
    result = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        str(path)
    ])
    return float(result.stdout.strip())


def get_font(size):
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]

    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                pass

    return ImageFont.load_default()


def make_book_card(path, title, subtitle, closing=False):
    image = Image.new("RGB", (W, H), (15, 10, 7))
    draw = ImageDraw.Draw(image)

    for y in range(H):
        shade = int(
            14 + 24 * (1 - abs(y - H / 2) / (H / 2))
        )
        draw.line(
            (0, y, W, y),
            fill=(shade, int(shade * 0.68), int(shade * 0.32))
        )

    gold = (235, 190, 92)

    draw.rounded_rectangle(
        (125, 520, 955, 1370),
        radius=45,
        outline=gold,
        width=8,
        fill=(44, 27, 13)
    )

    draw.line(
        (540, 560, 540, 1330),
        fill=gold,
        width=5
    )

    if closing:
        draw.text(
            (540, 800),
            "VEDIC GURU BADSAH",
            font=get_font(50),
            fill=gold,
            anchor="mm"
        )
    else:
        draw.line(
            (170, 620, 510, 650),
            fill=(177, 139, 76),
            width=3
        )
        draw.line(
            (570, 650, 910, 620),
            fill=(177, 139, 76),
            width=3
        )

        draw.text(
            (540, 800),
            "VEDIC GURU",
            font=get_font(64),
            fill=gold,
            anchor="mm"
        )

        draw.text(
            (540, 900),
            "BADSAH",
            font=get_font(92),
            fill=(255, 225, 160),
            anchor="mm"
        )

    draw.text(
        (540, 1510),
        title,
        font=get_font(54),
        fill=(255, 244, 218),
        anchor="mm"
    )

    draw.text(
        (540, 1600),
        subtitle,
        font=get_font(30),
        fill=gold,
        anchor="mm"
    )

    image.save(path)


def ass_time(seconds):
    centiseconds = int(round(seconds * 100))

    hours = centiseconds // 360000
    minutes = (centiseconds // 6000) % 60
    secs = (centiseconds // 100) % 60
    remainder = centiseconds % 100

    return (
        f"{hours}:{minutes:02d}:"
        f"{secs:02d}.{remainder:02d}"
    )


def build_ass(scenes, audio_durations):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans Devanagari,54,&H00000000,&H00000000,&H00FFFFFF,&HCCFFFFFF,1,0,3,2,0,2,90,90,190,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    cursor = 0.0

    for scene, scene_duration in zip(scenes, audio_durations):
        dialogue = scene.get("dialogue", "").strip()
        words = re.findall(r"\S+", dialogue)

        if not words:
            cursor += scene_duration
            continue

        weights = [
            max(
                1,
                len(re.sub(r"[^\w\u0900-\u097F]", "", word))
            )
            for word in words
        ]

        parts = []

        for word, weight in zip(words, weights):
            centiseconds = max(
                1,
                round(scene_duration * 100 * weight / sum(weights))
            )

            safe_word = word.replace("{", "(").replace("}", ")")

            parts.append(
                r"{\k" + str(centiseconds) + "}" + safe_word
            )

        lines.append(
            f"Dialogue: 0,{ass_time(cursor)},"
            f"{ass_time(cursor + scene_duration)},"
            f"Default,,0,0,0,,"
            + " ".join(parts)
            + "\n"
        )

        cursor += scene_duration

    ASS.write_text(
        "".join(lines),
        encoding="utf-8-sig"
    )


def main():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} is not installed.")

    if not SOURCE.exists():
        raise FileNotFoundError(
            "final_output.mp4 not found. Run video_generator.py first."
        )

    if not STORY.exists():
        raise FileNotFoundError(
            "story_output.json not found."
        )

    WORK.mkdir(exist_ok=True)
    ASSETS.mkdir(exist_ok=True)

    data = json.loads(STORY.read_text(encoding="utf-8"))

    scenes = data.get("scenes") if isinstance(data, dict) else data

    if not isinstance(scenes, list) or not scenes:
        raise ValueError("No scenes found in story_output.json")

    scene_durations = []

    for index, scene in enumerate(scenes, 1):
        scene_id = str(scene.get("scene_id", index))

        audio = BASE / "audio_files" / f"scene_{scene_id}.mp3"

        if not audio.exists():
            raise FileNotFoundError(f"Missing audio: {audio}")

        scene_durations.append(duration(audio))

    original_duration = duration(SOURCE)
    narration_duration = sum(scene_durations)
    detected_intro_seconds = original_duration - narration_duration

    # Detect whether the source has a 3-second opening logo intro.
    if abs(detected_intro_seconds) <= 1.0:
        logo_intro_seconds = 0.0
    elif abs(detected_intro_seconds - LOGO_INTRO_SECONDS) <= 1.0:
        logo_intro_seconds = detected_intro_seconds
    else:
        raise RuntimeError(
            f"Scene audio total ({narration_duration:.2f}s) differs from "
            f"video duration ({original_duration:.2f}s) by "
            f"{detected_intro_seconds:.2f}s. Expected either no intro or "
            f"a {LOGO_INTRO_SECONDS:.1f}s logo intro. "
            "Refusing to risk caption drift."
        )

    build_ass(scenes, scene_durations)

    ass_path = (
        ASS.as_posix()
        .replace("\\", "/")
        .replace(":", "\\:")
    )

    subtitle_filter = f"subtitles='{ass_path}'"

    logo = ASSETS / "logo.png"
    narrator = ASSETS / "narrator.png"
    hanuman = ASSETS / "hanuman_flight.png"

    if not logo.exists():
        raise FileNotFoundError(
            "assets/logo.png is missing. Upload your channel logo there."
        )

    # Logo is a permanent top-right watermark.
    inputs = [
        "ffmpeg", "-y",
        "-i", str(SOURCE),
        "-loop", "1", "-i", str(logo),
    ]

    filters = [
        f"[0:v]trim=start={logo_intro_seconds},"
        f"setpts=PTS-STARTPTS,{subtitle_filter}[base]",

        f"[0:a]atrim=start={logo_intro_seconds},"
        "asetpts=PTS-STARTPTS[aout]",

        f"[1:v]scale={LOGO_WIDTH}:-1,"
        "format=rgba,colorchannelmixer=aa=0.88[logo]",

        "[base][logo]overlay=W-w-28:28:"
        "shortest=1[vlogo]",
    ]

    last = "vlogo"
    next_input = 2

    if narrator.exists():
        inputs += ["-loop", "1", "-i", str(narrator)]

        filters.append(
            f"[{next_input}:v]scale=220:-1,format=rgba[narr]"
        )

        filters.append(
            f"[{last}][narr]overlay=W-w-35:150:"
            "shortest=1[vnarr]"
        )

        last = "vnarr"
        next_input += 1

    if hanuman.exists():
        inputs += ["-loop", "1", "-i", str(hanuman)]

        filters.append(
            f"[{next_input}:v]scale=105:75,format=rgba[han]"
        )

        filters.append(
            f"[{last}]drawbox=x=70:y=1790:w=940:h=5:"
            "color=0x8B6A32@0.9:t=fill[track]"
        )

        narration_duration = max(
            1.0,
            original_duration - logo_intro_seconds
        )

        filters.append(
            f"[track][han]overlay="
            f"x='70+(940-105)*t/{narration_duration:.6f}':"
            "y=1705:shortest=1[vfinal]"
        )

        last = "vfinal"

    else:
        filters.append(
            f"[{last}]drawbox=x=70:y=1790:w=940:h=5:"
            "color=0x8B6A32@0.9:t=fill[vfinal]"
        )

        last = "vfinal"

    inputs += [
        "-filter_complex", ";".join(filters),
        "-map", f"[{last}]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-movflags", "+faststart",
        str(OUTPUT)
    ]

    run(inputs)

    final_duration = duration(OUTPUT)

    expected_final_duration = original_duration - logo_intro_seconds

    if abs(final_duration - expected_final_duration) > 1.0:
        raise RuntimeError(
            f"Final video duration ({final_duration:.2f}s) does not match "
            f"the episode duration after removing the "
            f"{logo_intro_seconds:.1f}s opening logo intro."
        )

    report = {
        "output": OUTPUT.name,
        "original_duration_seconds": round(original_duration, 3),
        "final_duration_seconds": round(final_duration, 3),
        "opening_logo_intro_removed_seconds": round(
            logo_intro_seconds, 3
        ),
        "logo_watermark": (
            "assets/logo.png, top-right corner throughout the episode"
        ),
        "original_episode_preserved": True,
        "word_highlighting": (
            "Estimated from text character weights; "
            "not exact forced alignment."
        ),
        "narrator_overlay": (
            "Static portrait; speaking animation not implemented."
        ),
        "hanuman_progress": (
            "Flying overlay enabled."
            if hanuman.exists()
            else "Golden track enabled; Hanuman asset missing."
        )
    }

    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nSUCCESS: {OUTPUT}")


if __name__ == "__main__":
    main()
