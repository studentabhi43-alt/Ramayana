#!/usr/bin/env python3
"""
BADSAH PREMIUM HINDI CAPTION DIAGNOSTIC V3

Text source: story_output.json
Audio source: audio_files/scene_<id>.mp3
Output: caption_test_report.json

Checks all scenes, even when alignment is weak.
Original files are never modified.
"""

import json
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from difflib import SequenceMatcher

BASE = Path(__file__).resolve().parent
STORY = BASE / "story_output.json"
AUDIO_DIR = BASE / "audio_files"
REPORT = BASE / "caption_test_report.json"

MODEL_NAME = "small"
LANGUAGE = "hi"


def duration(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path)
        ],
        capture_output=True,
        text=True,
        check=True
    )
    return float(result.stdout.strip())


def normalize_word(word):
    word = unicodedata.normalize("NFKC", str(word))
    word = word.lower()
    word = re.sub(r"[^\w\u0900-\u097F]", "", word)
    return word.strip()


def get_script_words(dialogue):
    return re.findall(r"\S+", str(dialogue).strip())


def transcribe(audio_path, model):
    print(f"Transcribing {audio_path.name}...")

    segments, info = model.transcribe(
        str(audio_path),
        language=LANGUAGE,
        word_timestamps=True,
        beam_size=5,
        vad_filter=False
    )

    words = []

    for segment in segments:
        if not segment.words:
            continue

        for word in segment.words:
            text = str(word.word).strip()

            if not normalize_word(text):
                continue

            words.append({
                "text": text,
                "start": round(float(word.start), 3),
                "end": round(float(word.end), 3)
            })

    return words


def compare_words(script, detected):
    script_norm = [normalize_word(w) for w in script]
    audio_norm = [normalize_word(w["text"]) for w in detected]

    matcher = SequenceMatcher(
        None,
        script_norm,
        audio_norm,
        autojunk=False
    )

    matched_script = set()
    matched_audio = set()
    matching_pairs = []

    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            si = block.a + offset
            ai = block.b + offset

            matched_script.add(si)
            matched_audio.add(ai)

            matching_pairs.append({
                "script_index": si,
                "audio_index": ai,
                "script_word": script[si],
                "whisper_word": detected[ai]["text"],
                "audio_start": detected[ai]["start"],
                "audio_end": detected[ai]["end"]
            })

    ratio = len(matched_script) / max(1, len(script))

    missing_script = [
        {
            "index": i,
            "word": word
        }
        for i, word in enumerate(script)
        if i not in matched_script
    ]

    extra_audio = [
        {
            "index": i,
            "word": word["text"],
            "start": word["start"],
            "end": word["end"]
        }
        for i, word in enumerate(detected)
        if i not in matched_audio
    ]

    return {
        "match_ratio": round(ratio, 3),
        "match_percent": round(ratio * 100, 1),
        "matched_count": len(matched_script),
        "script_count": len(script),
        "whisper_count": len(detected),
        "matching_pairs": matching_pairs,
        "unmatched_script_words": missing_script,
        "unmatched_whisper_words": extra_audio
    }


def main():
    print("=" * 55)
    print("BADSAH CAPTION DIAGNOSTIC V3")
    print("=" * 55)

    for tool in ("ffprobe",):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} is not installed.")

    if not STORY.is_file():
        raise FileNotFoundError("story_output.json missing.")

    story = json.loads(STORY.read_text(encoding="utf-8"))

    if not isinstance(story, list) or not story:
        raise RuntimeError("Story must be a non-empty JSON list.")

    from faster_whisper import WhisperModel

    print("\nLoading Whisper Hindi model...")

    model = WhisperModel(
        MODEL_NAME,
        device="cpu",
        compute_type="int8"
    )

    scene_reports = []
    total_script = 0
    total_matched = 0

    for index, scene in enumerate(story, start=1):
        scene_id = str(
            scene.get("scene_id")
            or scene.get("scene_number")
            or index
        )

        dialogue = str(scene.get("dialogue", "")).strip()
        audio_path = AUDIO_DIR / f"scene_{scene_id}.mp3"

        print(f"\nChecking Scene {scene_id}")

        if not dialogue:
            scene_reports.append({
                "scene_id": scene_id,
                "status": "error",
                "error": "Empty dialogue"
            })
            continue

        if not audio_path.is_file():
            scene_reports.append({
                "scene_id": scene_id,
                "status": "error",
                "error": f"Missing audio: {audio_path.name}"
            })
            continue

        try:
            audio_duration = duration(audio_path)
            script = get_script_words(dialogue)
            detected = transcribe(audio_path, model)

            comparison = compare_words(script, detected)

            total_script += comparison["script_count"]
            total_matched += comparison["matched_count"]

            scene_reports.append({
                "scene_id": scene_id,
                "status": "checked",
                "dialogue": dialogue,
                "audio_file": audio_path.name,
                "audio_duration": round(audio_duration, 3),
                "script_words": script,
                "whisper_words": detected,
                **comparison
            })

            print(
                f"Scene {scene_id}: "
                f"{comparison['match_percent']}% matched "
                f"({comparison['matched_count']}/"
                f"{comparison['script_count']})"
            )

            if comparison["unmatched_script_words"]:
                print("Unmatched script words:")
                print(
                    ", ".join(
                        x["word"]
                        for x in comparison["unmatched_script_words"]
                    )
                )

        except Exception as error:
            scene_reports.append({
                "scene_id": scene_id,
                "status": "error",
                "error": str(error)
            })
            print(f"Scene {scene_id} error: {error}")

    overall = total_matched / max(1, total_script)

    report = {
        "version": "V3",
        "status": "diagnostic_complete",
        "language": LANGUAGE,
        "model": MODEL_NAME,
        "purpose": "Hindi script versus Whisper word comparison",
        "overall_match_percent": round(overall * 100, 1),
        "total_script_words": total_script,
        "total_matched_words": total_matched,
        "scenes_checked": len(scene_reports),
        "scenes": scene_reports,
        "caption_video_generated": False,
        "original_files_modified": False
    }

    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("\n" + "=" * 55)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 55)
    print(f"Overall match: {overall * 100:.1f}%")
    print(f"Report: {REPORT.name}")


if __name__ == "__main__":
    main()
