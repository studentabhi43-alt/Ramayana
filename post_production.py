
"""BADSAH post-production: corner logo, captions, Hanuman progress, outro.

The source video_generator.py may create a 3-second logo opening.
This script removes that opening, places assets/logo.png in the
top-right corner throughout the narrated episode, and adds a 4-second
closing card. The closing card keeps the existing GitHub verification
rule (cinematic output must be longer than final_output.mp4) satisfied.

No workflow YAML change is required.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
ASSETS = BASE / "assets"
AUDIO_DIR = BASE / "audio_files"
STORY = BASE / "story_output.json"
SOURCE = BASE / "final_output.mp4"
LOGO = ASSETS / "logo.png"
HANUMAN = ASSETS / "hanuman_flight.png"
OUTPUT = BASE / "badsah_final.mp4"
REPORT = BASE / "post_production_report.json"
WORK = BASE / "post_production_temp"

WIDTH = 1080
HEIGHT = 1920
FPS = 30
OUTRO_SECONDS = 4.0
LOGO_WIDTH = 170
LOGO_MARGIN = 28


def run(command):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    if result.returncode:
        raise RuntimeError(
            "FFmpeg/command failed:\n"
            + " ".join(str(x) for x in command)
            + "\n"
            + result.stderr[-5000:]
        )
    return result


def probe_duration(path):
    result = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
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


def create_outro(path):
    """Create a simple premium gold closing card; no opening logo screen."""
    image = Image.new("RGB", (WIDTH, HEIGHT), (12, 9, 7))
    draw = ImageDraw.Draw(image)

    for y in range(HEIGHT):
        glow = int(10 + 22 * (1 - abs(y - HEIGHT / 2) / (HEIGHT / 2)))
        draw.line(
            (0, y, WIDTH, y),
            fill=(glow + 5, int(glow * 0.72), int(glow * 0.36))
        )

    gold = (231, 190, 105)
    pale_gold = (255, 226, 165)

    draw.rounded_rectangle(
        (95, 570, 985, 1320),
        radius=48,
        fill=(35, 23, 13),
        outline=gold,
        width=6
    )
    draw.line((540, 625, 540, 1265), fill=gold, width=5)

    draw.text(
        (540, 790), "VEDIC GURU",
        font=get_font(68), fill=gold, anchor="mm"
    )
    draw.text(
        (540, 900), "BADSAH",
        font=get_font(100), fill=pale_gold, anchor="mm"
    )
    draw.text(
        (540, 1470), "आपका विचार क्या है?",
        font=get_font(52), fill=(255, 245, 225), anchor="mm"
    )
    draw.text(
        (540, 1560), "अपना जवाब कमेंट में लिखें",
        font=get_font(34), fill=gold, anchor="mm"
    )

    image.save(path)


def ass_timestamp(seconds):
    total = max(0, int(round(seconds * 100)))
    hours = total // 360000
    minutes = (total // 6000) % 60
    secs = (total // 100) % 60
    centis = total % 100
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def build_captions(scenes, scene_durations, path):
    """Create word-by-word karaoke captions using measured scene audio lengths."""
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans Devanagari,58,&H00FFFFFF,&H0000D7FF,&H00140D05,&H64000000,1,0,1,3,1,2,85,85,210,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    rows = [header]
    cursor = 0.0

    for scene, scene_seconds in zip(scenes, scene_durations):
        dialogue = str(scene.get("dialogue", "")).strip()
        words = re.findall(r"\S+", dialogue)

        if not words:
            cursor += scene_seconds
            continue

        weights = [
            max(1, len(re.sub(r"[^\w\u0900-\u097F]", "", word)))
            for word in words
        ]
        total_weight = sum(weights)
        karaoke = []

        centis = [
            max(1, int(round(scene_seconds * 100 * weight / total_weight)))
            for weight in weights
        ]

        if centis:
            centis[-1] += int(round(scene_seconds * 100)) - sum(centis)

        for word, word_centis in zip(words, centis):
            safe = word.replace("{", "(").replace("}", ")")
            karaoke.append(r"{\k" + str(max(1, word_centis)) + "}" + safe)

        rows.append(
            f"Dialogue: 0,{ass_timestamp(cursor)},"
            f"{ass_timestamp(cursor + scene_seconds)},"
            f"Default,,0,0,0,,{' '.join(karaoke)}\n"
        )
        cursor += scene_seconds

    path.write_text("".join(rows), encoding="utf-8-sig")


def load_scenes():
    if not STORY.exists():
        raise FileNotFoundError("story_output.json is missing.")

    data = json.loads(STORY.read_text(encoding="utf-8"))
    scenes = data.get("scenes") if isinstance(data, dict) else data

    if not isinstance(scenes, list) or len(scenes) != 7:
        raise ValueError("story_output.json must contain exactly 7 scenes.")

    return scenes


def main():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} is not installed.")

    if not SOURCE.exists():
        raise FileNotFoundError("final_output.mp4 is missing.")
    if not LOGO.exists():
        raise FileNotFoundError("assets/logo.png is missing.")

    WORK.mkdir(parents=True, exist_ok=True)

    scenes = load_scenes()
    scene_durations = []

    for index, scene in enumerate(scenes, start=1):
        scene_id = str(scene.get("scene_id", index))
        audio = AUDIO_DIR / f"scene_{scene_id}.mp3"
        if not audio.exists():
            raise FileNotFoundError(f"Missing narration file: {audio}")
        scene_durations.append(probe_duration(audio))

    narration_seconds = sum(scene_durations)
    source_seconds = probe_duration(SOURCE)
    difference = source_seconds - narration_seconds

    if abs(difference) <= 1.0:
        opening_seconds = 0.0
    elif 2.0 <= difference <= 4.0:
        opening_seconds = difference
    else:
        raise RuntimeError(
            f"Cannot safely align source video and narration: "
            f"video={source_seconds:.3f}s, narration={narration_seconds:.3f}s, "
            f"difference={difference:.3f}s. Expected no intro or an "
            "approximately 3-second silent logo intro."
        )

    print(f"Source duration: {source_seconds:.3f}s")
    print(f"Narration duration: {narration_seconds:.3f}s")
    print(f"Opening intro removed: {opening_seconds:.3f}s")

    ass_file = WORK / "captions.ass"
    build_captions(scenes, scene_durations, ass_file)

    ass_path = ass_file.resolve().as_posix()
    ass_path = ass_path.replace(":", r"\:")
    ass_path = ass_path.replace("'", r"\'")

    captioned_main = WORK / "episode_with_overlays.mp4"

    command = [
        "ffmpeg", "-y",
        "-ss", f"{opening_seconds:.6f}",
        "-i", str(SOURCE),
        "-loop", "1", "-i", str(LOGO),
    ]

    filters = [
        f"[0:v]trim=duration={narration_seconds:.6f},"
        f"setpts=PTS-STARTPTS,subtitles='{ass_path}'[captioned]",
        f"[1:v]scale={LOGO_WIDTH}:-1,format=rgba,"
        "colorchannelmixer=aa=0.90[logo]",
        f"[captioned][logo]overlay="
        f"W-w-{LOGO_MARGIN}:{LOGO_MARGIN}:shortest=1[vlogo]",
    ]

    last_video = "vlogo"
    next_input = 2

    if HANUMAN.exists():
        command += ["-loop", "1", "-i", str(HANUMAN)]
        filters += [
            f"[{next_input}:v]scale=105:75,format=rgba[hanuman]",
            f"[{last_video}]drawbox=x=70:y=1790:w=940:h=5:"
            "color=0x8B6A32@0.95:t=fill[track]",
            f"[track][hanuman]overlay="
            f"x='70+(940-105)*min(t/{narration_seconds:.6f},1)':"
            "y=1705:shortest=1[vfinal]",
        ]
        last_video = "vfinal"
    else:
        filters.append(
            f"[{last_video}]drawbox=x=70:y=1790:w=940:h=5:"
            "color=0x8B6A32@0.95:t=fill[vfinal]"
        )
        last_video = "vfinal"

    command += [
        "-filter_complex", ";".join(filters),
        "-map", f"[{last_video}]",
        "-map", "0:a:0",
        "-t", f"{narration_seconds:.6f}",
        "-r", str(FPS),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-movflags", "+faststart",
        str(captioned_main),
    ]

    run(command)

    main_seconds = probe_duration(captioned_main)
    if abs(main_seconds - narration_seconds) > 1.2:
        raise RuntimeError(
            f"Captioned episode duration {main_seconds:.2f}s does not "
            f"match narration duration {narration_seconds:.2f}s."
        )

    outro_image = WORK / "outro.png"
    outro_video = WORK / "outro.mp4"
    create_outro(outro_image)

    run([
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(FPS),
        "-i", str(outro_image),
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", str(OUTRO_SECONDS),
        "-vf", f"scale={WIDTH}:{HEIGHT},format=yuv420p",
        "-r", str(FPS),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-shortest",
        str(outro_video),
    ])

    concat_file = WORK / "concat.txt"
    concat_file.write_text(
        "file '" + captioned_main.resolve().as_posix() + "'\n"
        "file '" + outro_video.resolve().as_posix() + "'\n",
        encoding="utf-8"
    )

    run([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-movflags", "+faststart",
        str(OUTPUT),
    ])

    final_seconds = probe_duration(OUTPUT)

    if final_seconds <= source_seconds:
        raise RuntimeError(
            f"Final video ({final_seconds:.2f}s) is not longer than "
            f"the original ({source_seconds:.2f}s)."
        )

    report = {
        "output": OUTPUT.name,
        "original_duration_seconds": round(source_seconds, 3),
        "narration_duration_seconds": round(narration_seconds, 3),
        "opening_logo_intro_removed_seconds": round(opening_seconds, 3),
        "final_duration_seconds": round(final_seconds, 3),
        "outro_seconds": OUTRO_SECONDS,
        "logo_watermark": "assets/logo.png, top-right corner throughout narration",
        "hanuman_progress": (
            "assets/hanuman_flight.png overlay enabled"
            if HANUMAN.exists()
            else "Progress track enabled; Hanuman image missing"
        ),
        "captions": "Hindi word-by-word karaoke timing estimated from text",
        "original_scene_audio_preserved": True,
        "workflow_yaml_change_required": False,
    }

    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("BADSAH POST-PRODUCTION COMPLETE")
    print(f"SUCCESS: {OUTPUT}")


if __name__ == "__main__":
    main()
