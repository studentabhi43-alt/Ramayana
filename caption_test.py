
#!/usr/bin/env python3
"""
BADSAH Premium Hindi Caption Test V2

Text source: story_output.json
Timing source: individual scene MP3 files
Output: captions_test.mp4

Normal words: White
Active word: Golden + enlarged
Caption background: translucent white
Visible words: rolling 3-4 word window

Original files are never overwritten.
"""

import json
import re
import shutil
import subprocess
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

BASE = Path(__file__).resolve().parent

VIDEO = BASE / "final_output.mp4"
STORY = BASE / "story_output.json"
AUDIO_DIR = BASE / "audio_files"

OUTPUT = BASE / "captions_test.mp4"
WORK = BASE / "caption_test_temp"
ASS_FILE = WORK / "captions.ass"
REPORT = BASE / "caption_test_report.json"

WIDTH = 1080
HEIGHT = 1920

MODEL_NAME = "small"
LANGUAGE = "hi"

FONT_NAME = "Noto Sans Devanagari"
FONT_SIZE = 52

CAPTION_Y = 1535
ACTIVE_SCALE = 112
BOX_ALPHA = "55"


def run(command):
    print("+", " ".join(map(str, command)), flush=True)

    result = subprocess.run(
        command,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Command failed:\n" + result.stderr[-5000:]
        )

    return result


def duration(path):
    result = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ])

    return float(result.stdout.strip())


def normalize_word(word):
    word = unicodedata.normalize("NFKC", str(word))
    word = word.lower()
    word = re.sub(r"[^\w\u0900-\u097F]", "", word)
    return word.strip()


def script_words(dialogue):
    return re.findall(r"\S+", str(dialogue).strip())


def whisper_words(audio_path, model):
    print(f"\nTranscribing: {audio_path.name}")

    segments, info = model.transcribe(
        str(audio_path),
        language=LANGUAGE,
        word_timestamps=True,
        beam_size=5,
        vad_filter=False
    )

    detected = []

    for segment in segments:
        if not segment.words:
            continue

        for word in segment.words:
            if word.start is None or word.end is None:
                continue

            text = str(word.word).strip()

            if not normalize_word(text):
                continue

            detected.append({
                "text": text,
                "start": max(0.0, float(word.start)),
                "end": max(0.0, float(word.end))
            })

    return detected


def align_script_to_audio(dialogue, detected, audio_duration):
    """
    Keep exact spelling from the script.
    Whisper is used only to locate matching word timestamps.
    Unmatched word times are interpolated between matched anchors.
    """

    original = script_words(dialogue)

    if not original:
        raise RuntimeError("Empty scene dialogue.")

    script_norm = [normalize_word(w) for w in original]
    audio_norm = [normalize_word(w["text"]) for w in detected]

    matcher = SequenceMatcher(
        None,
        script_norm,
        audio_norm,
        autojunk=False
    )

    matched = {}

    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            script_index = block.a + offset
            audio_index = block.b + offset

            matched[script_index] = {
                "start": detected[audio_index]["start"],
                "end": detected[audio_index]["end"]
            }

    match_ratio = len(matched) / max(1, len(original))

    if match_ratio < 0.45:
        raise RuntimeError(
            f"Scene alignment too weak: {match_ratio:.0%}. "
            "Refusing to create unreliable captions."
        )

    anchors = [(-1, 0.0)]

    for index, timing in sorted(matched.items()):
        anchors.append((index, timing["start"]))

    anchors.append((len(original), audio_duration))

    timings = [None] * len(original)

    for index, timing in matched.items():
        timings[index] = timing

    for anchor_pos in range(len(anchors) - 1):
        left_index, left_time = anchors[anchor_pos]
        right_index, right_time = anchors[anchor_pos + 1]

        missing = list(range(left_index + 1, right_index))

        if not missing:
            continue

        weights = [
            max(1, len(normalize_word(original[i])))
            for i in missing
        ]

        total_weight = sum(weights)
        available = max(0.05, right_time - left_time)

        cursor = left_time

        for i, weight in zip(missing, weights):
            word_duration = available * weight / total_weight

            timings[i] = {
                "start": cursor,
                "end": cursor + word_duration
            }

            cursor += word_duration

    final = []

    for index, word in enumerate(original):
        timing = timings[index]

        start = max(0.0, min(audio_duration, timing["start"]))
        end = max(start + 0.04, min(audio_duration, timing["end"]))

        final.append({
            "text": word,
            "start": start,
            "end": end
        })

    return final, match_ratio


def ass_time(seconds):
    seconds = max(0.0, float(seconds))

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60

    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def safe_ass_text(text):
    text = str(text)
    text = text.replace("\\", "")
    text = text.replace("{", "(")
    text = text.replace("}", ")")
    return text


def make_ass_header():
    return f"""[Script Info]
Title: BADSAH Premium Hindi Captions
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: BADSAH,{FONT_NAME},{FONT_SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&H{BOX_ALPHA}FFFFFF,-1,0,0,0,100,100,0,0,3,16,2,5,45,45,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass(all_words):
    lines = [make_ass_header()]

    for index, word in enumerate(all_words):

        start = word["start"]
        end = word["end"]

        if end <= start:
            continue

        # Previous word + active word + next two words
        first = max(0, index - 1)
        last = min(len(all_words), index + 3)

        visible = all_words[first:last]
        parts = []

        for visible_index, item in enumerate(visible):
            actual_index = first + visible_index
            text = safe_ass_text(item["text"])

            if actual_index == index:
                parts.append(
                    "{\\c&H0000BFFF&"
                    f"\\fscx{ACTIVE_SCALE}"
                    f"\\fscy{ACTIVE_SCALE}"
                    "\\bord3\\3c&H000000&}"
                    + text
                    + "{\\rBADSAH}"
                )
            else:
                parts.append(
                    "{\\c&H00FFFFFF&"
                    "\\fscx100\\fscy100"
                    "\\bord3\\3c&H000000&}"
                    + text
                    + "{\\rBADSAH}"
                )

        caption_text = " ".join(parts)

        event = (
            "Dialogue: 0,"
            + ass_time(start)
            + ","
            + ass_time(end)
            + ",BADSAH,,0,0,0,,"
            + "{\\an5\\move(600,"
            + str(CAPTION_Y)
            + ",540,"
            + str(CAPTION_Y)
            + ",0,130)}"
            + caption_text
            + "\n"
        )

        lines.append(event)

    ASS_FILE.write_text(
        "\n".join(lines),
        encoding="utf-8-sig"
    )


def main():

    print("=" * 55)
    print("BADSAH PREMIUM CAPTION TEST V2")
    print("=" * 55)

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"Missing required tool: {tool}")

    for path in (VIDEO, STORY):
        if not path.is_file():
            sys.exit(f"Missing required file: {path.name}")

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("Install faster-whisper before running this script.")

    story = json.loads(
        STORY.read_text(encoding="utf-8")
    )

    if not isinstance(story, list) or not story:
        raise RuntimeError(
            "story_output.json must contain a non-empty scene list."
        )

    WORK.mkdir(parents=True, exist_ok=True)

    if OUTPUT.exists():
        OUTPUT.unlink()

    video_duration = duration(VIDEO)

    print(f"Video duration: {video_duration:.3f}s")
    print(f"Total scenes: {len(story)}")

    print("\nLoading Hindi speech model...")

    model = WhisperModel(
        MODEL_NAME,
        device="cpu",
        compute_type="int8"
    )

    all_words = []
    scene_reports = []
    timeline = 0.0

    for index, scene in enumerate(story, start=1):

        scene_id = str(
            scene.get("scene_id")
            or scene.get("scene_number")
            or index
        )

        dialogue = str(scene.get("dialogue", "")).strip()

        audio_path = AUDIO_DIR / f"scene_{scene_id}.mp3"

        if not dialogue:
            raise RuntimeError(
                f"Scene {scene_id} has empty dialogue."
            )

        if not audio_path.is_file():
            raise FileNotFoundError(
                f"Missing scene audio: {audio_path}"
            )

        audio_duration = duration(audio_path)

        detected = whisper_words(audio_path, model)

        if not detected:
            raise RuntimeError(
                f"No speech detected in scene {scene_id}."
            )

        aligned, match_ratio = align_script_to_audio(
            dialogue,
            detected,
            audio_duration
        )

        for word in aligned:
            all_words.append({
                "text": word["text"],
                "start": timeline + word["start"],
                "end": timeline + word["end"]
            })

        scene_reports.append({
            "scene_id": scene_id,
            "audio_duration": round(audio_duration, 3),
            "script_words": len(aligned),
            "whisper_words": len(detected),
            "matched_ratio": round(match_ratio, 3)
        })

        print(
            f"Scene {scene_id}: "
            f"{len(aligned)} script words, "
            f"match {match_ratio:.0%}, "
            f"{audio_duration:.2f}s"
        )

        timeline += audio_duration

    drift = abs(timeline - video_duration)

    if drift > 1.0:
        raise RuntimeError(
            f"Audio/video duration mismatch: "
            f"scene audio={timeline:.2f}s, "
            f"video={video_duration:.2f}s. "
            "Refusing to create drifting captions."
        )

    build_ass(all_words)

    ass_path = str(ASS_FILE.resolve())
    ass_path = ass_path.replace("\\", "/")
    ass_path = ass_path.replace(":", r"\:")
    ass_path = ass_path.replace("'", r"\'")

    subtitle_filter = f"subtitles='{ass_path}'"

    print("\nRendering premium caption preview...")

    run([
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(VIDEO),
        "-vf", subtitle_filter,
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-t", f"{video_duration:.6f}",
        str(OUTPUT)
    ])

    output_duration = duration(OUTPUT)

    if abs(output_duration - video_duration) > 0.20:
        raise RuntimeError("Output duration validation failed.")

    report = {
        "status": "success",
        "output": OUTPUT.name,
        "source": VIDEO.name,
        "language": LANGUAGE,
        "text_source": STORY.name,
        "timing_source": "individual scene MP3 files",
        "alignment": "Whisper timestamps matched to original script",
        "normal_word_color": "white",
        "active_word_color": "gold",
        "active_word_scale_percent": ACTIVE_SCALE,
        "visible_word_window": "up to 4 words",
        "word_count": len(all_words),
        "source_duration": round(video_duration, 3),
        "scene_audio_total": round(timeline, 3),
        "output_duration": round(output_duration, 3),
        "scene_alignment": scene_reports,
        "original_video_modified": False,
        "original_audio_modified": False
    }

    REPORT.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("\n" + "=" * 55)
    print("CAPTION PREVIEW SUCCESS")
    print("=" * 55)
    print(f"Output: {OUTPUT.name}")
    print(f"Words: {len(all_words)}")
    print(f"Duration: {output_duration:.2f}s")
    print("Normal text: WHITE")
    print("Active word: GOLD + enlarged")
    print("Caption box: translucent white")
    print("Original files: unchanged")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("\nCAPTION TEST FAILED")
        print(error)
        raise
