
"""BADSAH post-production.
Keeps final_output.mp4 untouched.
Requires FFmpeg, FFprobe and Pillow.

Optional assets:
  assets/narrator.png
  assets/hanuman_flying.png

Note: Word highlighting uses estimated timing, not true forced alignment.
The narrator is currently a static portrait, not lip-synced animation.
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
INTRO_SECONDS = 3.0
OUTRO_SECONDS = 4.0


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
    # The source video begins with the 3-second logo intro; narration starts after it.
    cursor = INTRO_SECONDS

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

    data = json.loads(STORY.read_text(encoding="utf-8"))

    scenes = data.get("scenes") if isinstance(data, dict) else data

    if not isinstance(scenes, list) or not scenes:
        raise ValueError("No scenes found in story_output.json")

    WORK.mkdir(exist_ok=True)
    ASSETS.mkdir(exist_ok=True)

    scene_durations = []

    for index, scene in enumerate(scenes, 1):
        scene_id = str(scene.get("scene_id", index))

        audio = BASE / "audio_files" / f"scene_{scene_id}.mp3"

        if not audio.exists():
            raise FileNotFoundError(f"Missing audio: {audio}")

        scene_durations.append(duration(audio))

    original_duration = duration(SOURCE)
    narration_duration = sum(scene_durations)
    expected_narration_duration = original_duration - INTRO_SECONDS

    if expected_narration_duration <= 0:
        raise RuntimeError(
            "Original video is shorter than the configured logo intro. "
            "Check INTRO_SECONDS and final_output.mp4."
        )

    if abs(narration_duration - expected_narration_duration) > 1.0:
        raise RuntimeError(
            f"Scene audio total ({narration_duration:.2f}s) "
            f"differs from video narration section "
            f"({expected_narration_duration:.2f}s; total video "
            f"{original_duration:.2f}s including {INTRO_SECONDS:.2f}s logo intro). "
            "Refusing to risk caption drift."
        )

    build_ass(scenes, scene_durations)

    intro_image = WORK / "intro.png"
    outro_image = WORK / "outro.png"

    make_book_card(
        intro_image,
        "आज का विशेष प्रसंग",
        "एक नई शास्त्रीय यात्रा"
    )

    make_book_card(
        outro_image,
        "आपका उत्तर क्या है?",
        "अपना जवाब कमेंट में लिखें",
        closing=True
    )

    intro_video = WORK / "intro.mp4"
    outro_video = WORK / "outro.mp4"

    for image, output, seconds in [
        (intro_image, intro_video, INTRO_SECONDS),
        (outro_image, outro_video, OUTRO_SECONDS)
    ]:
        run([
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(image),
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t", str(seconds),
            "-r", str(FPS),
            "-vf", f"scale={W}:{H},format=yuv420p",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "22",
            "-c:a", "aac",
            "-shortest",
            str(output)
        ])

    captioned = WORK / "captioned_original.mp4"

    ass_path = (
        ASS.as_posix()
        .replace("\\", "/")
        .replace(":", "\\:")
    )

    subtitle_filter = f"subtitles='{ass_path}'"

    narrator = ASSETS / "narrator.png"
    hanuman = ASSETS / "hanuman_flying.png"

    inputs = [
        "ffmpeg", "-y",
        "-i", str(SOURCE)
    ]

    filters = [
        f"[0:v]{subtitle_filter}[base]"
    ]

    last = "base"

    if narrator.exists():
        inputs += [
            "-loop", "1",
            "-i", str(narrator)
        ]

        filters.append(
            "[1:v]scale=220:-1,format=rgba[narr]"
        )

        filters.append(
            f"[{last}][narr]overlay=W-w-35:100:"
            "shortest=1[v1]"
        )

        last = "v1"

    if hanuman.exists():
        inputs += [
            "-loop", "1",
            "-i", str(hanuman)
        ]

        index = 2 if narrator.exists() else 1

        filters.append(
            f"[{index}:v]scale=105:75,format=rgba[han]"
        )

        filters.append(
            f"[{last}]drawbox=x=70:y=1790:w=940:h=5:"
            "color=0x8B6A32@0.9:t=fill[track]"
        )

        filters.append(
            f"[track][han]overlay="
            f"x='70+(940-105)*t/{original_duration:.6f}':"
            "y=1705:shortest=1[v2]"
        )

        last = "v2"

    else:
        filters.append(
            f"[{last}]drawbox=x=70:y=1790:w=940:h=5:"
            "color=0x8B6A32@0.9:t=fill[v2]"
        )

        last = "v2"

    inputs += [
        "-filter_complex",
        ";".join(filters),
        "-map", f"[{last}]",
        "-map", "0:a:0",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(captioned)
    ]

    run(inputs)

    concat_file = WORK / "concat.txt"

    concat_file.write_text(
        "\n".join(
            f"file '{path.resolve()}'"
            for path in (intro_video, captioned, outro_video)
        ),
        encoding="utf-8"
    )

    run([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(OUTPUT)
    ])

    final_duration = duration(OUTPUT)

    if final_duration < (
        original_duration + INTRO_SECONDS + OUTRO_SECONDS - 0.5
    ):
        raise RuntimeError(
            "Output duration check failed. "
            "Original episode may not have been preserved."
        )

    report = {
        "output": OUTPUT.name,
        "original_duration_seconds": round(original_duration, 3),
        "final_duration_seconds": round(final_duration, 3),
        "intro_seconds": INTRO_SECONDS,
        "outro_seconds": OUTRO_SECONDS,
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
