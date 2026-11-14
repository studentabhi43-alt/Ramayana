
#!/usr/bin/env python3
"""
BADSAH Hindi Word-by-Word Caption Test

Input : final_output.mp4
Output: captions_test.mp4

- Original video/audio are never overwritten.
- Hindi transcription with word timestamps.
- Current spoken word turns GOLD.
- Other words remain BLACK.
- White caption background.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

SOURCE = BASE / "final_output.mp4"
OUTPUT = BASE / "captions_test.mp4"
WORK = BASE / "caption_test_temp"

ASS_FILE = WORK / "captions.ass"
REPORT = BASE / "caption_test_report.json"

WIDTH = 1080
HEIGHT = 1920

MODEL_NAME = "small"
LANGUAGE = "hi"

# Caption appearance
FONT_NAME = "Noto Sans Devanagari"
FONT_SIZE = 58
MAX_WORDS_PER_LINE = 5

# Caption position: leaves room for Hanuman progress bar.
BOTTOM_MARGIN = 330


def run(command):
    print("+", " ".join(map(str, command)))

    result = subprocess.run(
        command,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + result.stderr[-5000:]
        )

    return result


def get_duration(path):
    result = run([
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ])

    return float(result.stdout.strip())


def ass_time(seconds):
    seconds = max(0.0, float(seconds))

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60

    return (
        f"{hours}:"
        f"{minutes:02d}:"
        f"{secs:05.2f}"
    )


def clean_ass_text(text):
    """
    Escape special ASS characters.
    """

    text = str(text or "")

    text = text.replace("\\", "")
    text = text.replace("{", "")
    text = text.replace("}", "")
    text = text.replace("\n", " ")

    return text.strip()


def make_ass_header():
    return f"""[Script Info]
Title: BADSAH Hindi Word Captions
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
PlayResX: {WIDTH}
PlayResY: {HEIGHT}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: BADSAH,{FONT_NAME},{FONT_SIZE},&H0000BFFF,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,2,65,65,{BOTTOM_MARGIN},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def group_words(words):
    """
    Divide transcript into short caption lines.
    Punctuation can end a line early.
    """

    groups = []
    current = []

    for word in words:
        text = clean_ass_text(word["text"])

        if not text:
            continue

        current.append({
            "text": text,
            "start": float(word["start"]),
            "end": float(word["end"])
        })

        punctuation_end = text.endswith(
            ("।", "?", "!", ".", "…")
        )

        if (
            len(current) >= MAX_WORDS_PER_LINE
            or punctuation_end
        ):
            groups.append(current)
            current = []

    if current:
        groups.append(current)

    return groups


def make_dialogue(group):
    """
    ASS karaoke:
    Black = upcoming words.
    Gold = currently spoken word.
    """

    parts = []

    for word in group:
        duration = max(
            0.05,
            word["end"] - word["start"]
        )

        centiseconds = max(
            1,
            round(duration * 100)
        )

        text = clean_ass_text(word["text"])

        parts.append(
            f"{{\\k{centiseconds}}}{text}"
        )

    return " ".join(parts)


def create_ass(words):
    groups = group_words(words)

    if not groups:
        raise RuntimeError(
            "No usable Hindi words were detected."
        )

    lines = [make_ass_header()]

    for group in groups:
        start = group[0]["start"]
        end = group[-1]["end"]

        # Avoid zero-duration subtitles.
        if end <= start:
            end = start + 0.2

        dialogue = make_dialogue(group)

        lines.append(
            "Dialogue: 0,"
            + ass_time(start)
            + ","
            + ass_time(end)
            + ",BADSAH,,0,0,0,,"
            + dialogue
        )

    ASS_FILE.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8-sig"
    )

    return len(groups)


def main():

    print("=" * 55)
    print("BADSAH WORD-BY-WORD HINDI CAPTION TEST")
    print("=" * 55)

    if not SOURCE.is_file():
        sys.exit(
            "ERROR: final_output.mp4 not found in repository root."
        )

    for program in ("ffmpeg", "ffprobe"):
        if not shutil.which(program):
            sys.exit(
                f"ERROR: {program} is not installed."
            )

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit(
            "ERROR: faster-whisper is missing. "
            "Install it before running this script."
        )

    WORK.mkdir(
        parents=True,
        exist_ok=True
    )

    if OUTPUT.exists():
        OUTPUT.unlink()

    source_duration = get_duration(SOURCE)

    print(f"\nSource duration: {source_duration:.2f} seconds")
    print(f"Loading Whisper model: {MODEL_NAME}")

    model = WhisperModel(
        MODEL_NAME,
        device="cpu",
        compute_type="int8"
    )

    print("\nTranscribing Hindi audio...")
    print("Word timestamps are enabled.")

    segments, info = model.transcribe(
        str(SOURCE),
        language=LANGUAGE,
        word_timestamps=True,
        beam_size=5,
        vad_filter=False
    )

    all_words = []

    for segment in segments:

        if not segment.words:
            continue

        for word in segment.words:

            if word.start is None or word.end is None:
                continue

            text = str(word.word).strip()

            if not text:
                continue

            all_words.append({
                "text": text,
                "start": max(0.0, float(word.start)),
                "end": max(0.0, float(word.end))
            })

    if not all_words:
        raise RuntimeError(
            "Whisper did not detect any usable words."
        )

    print(f"\nDetected words: {len(all_words)}")

    caption_count = create_ass(all_words)

    print(f"Caption lines: {caption_count}")

    # FFmpeg subtitles filter.
    # ASS path is escaped for FFmpeg filter syntax.
    ass_path = str(ASS_FILE.resolve())
    ass_path = ass_path.replace("\\", "/")
    ass_path = ass_path.replace(":", r"\:")
    ass_path = ass_path.replace("'", r"\'")

    subtitle_filter = (
        f"subtitles='{ass_path}':"
        "fontsdir='/usr/share/fonts/truetype/noto'"
    )

    print("\nRendering caption test video...")

    run([
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i", str(SOURCE),
        "-vf", subtitle_filter,
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-t", f"{source_duration:.6f}",
        str(OUTPUT)
    ])

    output_duration = get_duration(OUTPUT)

    if abs(output_duration - source_duration) > 0.20:
        raise RuntimeError(
            "Output duration differs from original. "
            "Original video remains untouched."
        )

    if OUTPUT.stat().st_size < 50000:
        raise RuntimeError(
            "Output video is unexpectedly small."
        )

    report = {
        "status": "success",
        "source": SOURCE.name,
        "output": OUTPUT.name,
        "language": LANGUAGE,
        "model": MODEL_NAME,
        "detected_language": getattr(info, "language", None),
        "word_count": len(all_words),
        "caption_lines": caption_count,
        "source_duration": round(source_duration, 3),
        "output_duration": round(output_duration, 3),
        "word_timestamps": True,
        "original_modified": False
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
    print("CAPTION TEST COMPLETED")
    print("=" * 55)
    print(f"Output: {OUTPUT.name}")
    print(f"Words: {len(all_words)}")
    print(f"Caption lines: {caption_count}")
    print(f"Duration: {output_duration:.2f} seconds")
    print("Original video was not modified.")
    print(f"Report: {REPORT.name}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("\nCAPTION TEST FAILED")
        print(error)
        raise
