
import os
import re
import json
import base64
import asyncio
import time
import subprocess
from pathlib import Path

import requests
import edge_tts


# =====================================================
# BADSAH AUDIO ENGINE
# Scripture Facts / Contrasting Facts
# =====================================================

BASE_DIR = Path(__file__).resolve().parent

STORY_FILE = BASE_DIR / "story_output.json"
AUDIO_DIR = BASE_DIR / "audio_files"
REPORT_FILE = BASE_DIR / "audio_timing_report.json"

AUDIO_DIR.mkdir(parents=True, exist_ok=True)

SARVAM_API_KEY = os.getenv(
    "SARVAM_API_KEY", ""
).strip()

SARVAM_URL = "https://api.sarvam.ai/text-to-speech"

SARVAM_MODEL = "bulbul:v4-flash"

DEFAULT_SARVAM_VOICE = os.getenv(
    "SARVAM_SPEAKER",
    "shubh_enhi_ads"
).strip()

EDGE_MALE = "hi-IN-MadhurNeural"
EDGE_FEMALE = "hi-IN-SwaraNeural"

MAX_CHARACTERS = 2500
MIN_AUDIO_SIZE = 1000

EXPECTED_SCENES = 7

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "BADSAH-AudioEngine/1.0"
})


# =====================================================
# TEXT UTILITIES
# =====================================================

def clean_text(text):

    text = str(text or "").strip()

    text = re.sub(r"[*#_~`]", "", text)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def safe_scene_id(value):

    value = str(value)

    if not re.fullmatch(
        r"[A-Za-z0-9_-]+",
        value
    ):
        raise ValueError(
            f"Invalid scene ID: {value}"
        )

    return value


# =====================================================
# LOAD STORY
# =====================================================

def load_story():

    if not STORY_FILE.exists():

        raise FileNotFoundError(
            "story_output.json not found. Run main.py first."
        )

    with open(
        STORY_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        data = json.load(file)

    # Supports both:
    # {"scenes": [...]}
    # and old format: [...]

    if isinstance(data, dict):

        scenes = data.get("scenes")

        if scenes is None:

            raise ValueError(
                "story_output.json has no scenes array."
            )

    elif isinstance(data, list):

        scenes = data

    else:

        raise ValueError(
            "Invalid story_output.json format."
        )

    if not isinstance(scenes, list):

        raise ValueError(
            "Scenes must be a list."
        )

    if len(scenes) != EXPECTED_SCENES:

        raise ValueError(
            f"Expected {EXPECTED_SCENES} scenes, "
            f"found {len(scenes)}."
        )

    for index, scene in enumerate(
        scenes,
        start=1
    ):

        if not isinstance(scene, dict):

            raise ValueError(
                f"Scene {index} is invalid."
            )

        scene["scene_id"] = safe_scene_id(
            scene.get("scene_id", index)
        )

        dialogue = clean_text(
            scene.get("dialogue", "")
        )

        if len(dialogue) < 2:

            raise ValueError(
                f"Scene {index} has empty dialogue."
            )

        scene["dialogue"] = dialogue

    return scenes


# =====================================================
# AUDIO VALIDATION
# =====================================================

def validate_audio(path):

    if not path.exists():
        return False

    if path.stat().st_size < MIN_AUDIO_SIZE:
        return False

    try:

        with open(path, "rb") as audio:

            header = audio.read(3)

        return (
            header == b"ID3"
            or header[:2] == b"\xff\xfb"
            or header[:2] == b"\xff\xf3"
            or header[:2] == b"\xff\xf2"
        )

    except Exception:

        return False


def get_audio_duration(path):

    command = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path)
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=30
    )

    if result.returncode != 0:

        raise RuntimeError(
            "FFprobe failed: "
            + result.stderr[:300]
        )

    duration = float(
        result.stdout.strip()
    )

    if duration <= 0:

        raise ValueError(
            "Invalid audio duration."
        )

    return round(duration, 3)


# =====================================================
# SCENE TIMING
# =====================================================

def get_target_duration(scene):

    # First preference: explicit duration.
    value = scene.get(
        "target_duration_seconds"
    )

    # Otherwise calculate from start/end.
    if value is None:

        start = scene.get("start_seconds")
        end = scene.get("end_seconds")

        if start is None:
            start = scene.get("start")

        if end is None:
            end = scene.get("end")

        if start is not None and end is not None:

            try:

                value = float(end) - float(start)

            except (TypeError, ValueError):

                value = None

    if value is None:

        return None

    try:

        value = float(value)

    except (TypeError, ValueError):

        raise ValueError(
            f"Invalid duration in scene "
            f"{scene.get('scene_id')}."
        )

    if value <= 0:

        raise ValueError(
            f"Scene {scene.get('scene_id')} "
            "has non-positive duration."
        )

    return round(value, 3)


# =====================================================
# SARVAM VOICE
# =====================================================

def get_sarvam_speaker(scene):

    return (
        scene.get("sarvam_speaker")
        or scene.get("speaker_id")
        or DEFAULT_SARVAM_VOICE
    )


def generate_sarvam(
    text,
    output_path,
    speaker
):

    if not SARVAM_API_KEY:

        print(
            "SARVAM_API_KEY missing. "
            "Using backup voice."
        )

        return False

    if len(text) > MAX_CHARACTERS:

        print(
            "Sarvam text length limit exceeded."
        )

        return False

    payload = {
        "text": text,
        "target_language_code": "hi-IN",
        "speaker": speaker,
        "model": SARVAM_MODEL,
        "pace": 1.0,
        "speech_sample_rate": 24000,
        "output_audio_codec": "mp3"
    }

    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    for attempt in range(1, 3):

        temporary_path = output_path.with_suffix(
            ".sarvam.tmp.mp3"
        )

        try:

            response = SESSION.post(
                SARVAM_URL,
                headers=headers,
                json=payload,
                timeout=90
            )

            if response.status_code != 200:

                print(
                    f"Sarvam HTTP {response.status_code}: "
                    f"{response.text[:250]}"
                )

                if response.status_code in (
                    400, 401, 402, 403
                ):

                    return False

                if (
                    response.status_code == 429
                    or response.status_code >= 500
                ):

                    if attempt < 2:

                        time.sleep(3)

                        continue

                    return False

                return False

            data = response.json()

            audios = data.get(
                "audios",
                []
            )

            if not audios:

                raise ValueError(
                    "Sarvam returned empty audio."
                )

            audio_bytes = base64.b64decode(
                audios[0]
            )

            temporary_path.write_bytes(
                audio_bytes
            )

            if not validate_audio(temporary_path):

                raise ValueError(
                    "Sarvam returned invalid MP3."
                )

            temporary_path.replace(
                output_path
            )

            print(
                "Sarvam audio saved:",
                output_path.name
            )

            return True

        except Exception as error:

            temporary_path.unlink(
                missing_ok=True
            )

            print(
                f"Sarvam attempt {attempt} failed: {error}"
            )

            if attempt < 2:

                time.sleep(2)

    return False


# =====================================================
# MICROSOFT EDGE TTS BACKUP
# =====================================================

async def generate_edge(
    text,
    output_path,
    voice
):

    for attempt in range(1, 4):

        temporary_path = output_path.with_suffix(
            ".edge.tmp.mp3"
        )

        try:

            communicate = edge_tts.Communicate(
                text,
                voice
            )

            await communicate.save(
                str(temporary_path)
            )

            if not validate_audio(temporary_path):

                raise ValueError(
                    "Edge TTS returned invalid MP3."
                )

            temporary_path.replace(
                output_path
            )

            print(
                "Edge TTS audio saved:",
                output_path.name
            )

            return True

        except Exception as error:

            temporary_path.unlink(
                missing_ok=True
            )

            print(
                f"Edge TTS attempt {attempt} failed: {error}"
            )

            if attempt < 3:

                await asyncio.sleep(2)

    return False


# =====================================================
# GENERATE ONE SCENE
# =====================================================

async def generate_scene(scene, index):

    scene_id = scene["scene_id"]

    text = clean_text(
        scene["dialogue"]
    )

    target_duration = get_target_duration(
        scene
    )

    output_path = (
        AUDIO_DIR / f"scene_{scene_id}.mp3"
    )

    print("\n" + "=" * 50)

    print(
        f"BADSAH AUDIO — SCENE {index}/{EXPECTED_SCENES}"
    )

    print("=" * 50)

    print("Dialogue:", text)

    print(
        "Target duration:",
        target_duration if target_duration else "Not specified"
    )

    # -------------------------------------------------
    # PRIMARY: SARVAM
    # -------------------------------------------------

    speaker = get_sarvam_speaker(scene)

    print(
        "Primary voice: Sarvam /",
        speaker
    )

    success = await asyncio.to_thread(
        generate_sarvam,
        text,
        output_path,
        speaker
    )

    provider = "Sarvam"

    # -------------------------------------------------
    # BACKUP: EDGE TTS
    # -------------------------------------------------

    if not success:

        print(
            "Switching to Microsoft Edge TTS..."
        )

        gender = str(
            scene.get(
                "voice_gender",
                "male"
            )
        ).lower()

        voice = (
            EDGE_FEMALE
            if gender in (
                "female",
                "woman",
                "girl"
            )
            else EDGE_MALE
        )

        success = await generate_edge(
            text,
            output_path,
            voice
        )

        provider = "Microsoft Edge TTS"

    if not success:

        raise RuntimeError(
            f"Both voice providers failed for scene {scene_id}."
        )

    # -------------------------------------------------
    # CHECK REAL AUDIO DURATION
    # -------------------------------------------------

    actual_duration = get_audio_duration(
        output_path
    )

    difference = None
    within_target = None

    if target_duration is not None:

        difference = round(
            actual_duration - target_duration,
            3
        )

        within_target = (
            actual_duration <= target_duration + 1.0
        )

        if not within_target:

            print(
                "WARNING: Audio is longer than planned scene."
            )

            print(
                "Audio will not be cut or artificially sped up."
            )

    print(
        "Actual duration:",
        actual_duration,
        "seconds"
    )

    return {
        "scene_id": scene_id,
        "audio_file": f"audio_files/{output_path.name}",
        "provider": provider,
        "target_duration_seconds": target_duration,
        "actual_duration_seconds": actual_duration,
        "difference_seconds": difference,
        "within_target": within_target,
        "dialogue": text
    }


# =====================================================
# SAVE AUDIO REPORT
# =====================================================

def save_report(records):

    total_actual = sum(
        item["actual_duration_seconds"]
        for item in records
    )

    targets = [
        item["target_duration_seconds"]
        for item in records
        if item["target_duration_seconds"] is not None
    ]

    total_target = (
        sum(targets)
        if targets
        else None
    )

    all_within_target = all(
        item["within_target"] is not False
        for item in records
    )

    report = {
        "engine": "BADSAH AUDIO ENGINE",
        "scene_count": len(records),
        "planned_total_seconds": (
            round(total_target, 3)
            if total_target is not None
            else None
        ),
        "actual_total_audio_seconds": round(
            total_actual,
            3
        ),
        "final_target_min_seconds": 30,
        "final_target_max_seconds": 55,
        "all_scenes_within_target": all_within_target,
        "final_duration_within_target": (
            30 <= total_actual <= 55
        ),
        "scenes": records
    }

    REPORT_FILE.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=4
        ),
        encoding="utf-8"
    )

    return report


# =====================================================
# MAIN
# =====================================================

async def main():

    print("\n" + "=" * 55)

    print(
        "BADSAH SCRIPTURE AUDIO GENERATION ENGINE"
    )

    print(
        "SARVAM PRIMARY + EDGE TTS BACKUP"
    )

    print("=" * 55)

    scenes = load_story()

    print(
        "Total scenes:",
        len(scenes)
    )

    print(
        "Sarvam API:",
        "CONFIGURED" if SARVAM_API_KEY else "NOT CONFIGURED"
    )

    records = []
    failed = []

    # Remove old files for these scene IDs only.
    for scene in scenes:

        old_file = (
            AUDIO_DIR /
            f"scene_{scene['scene_id']}.mp3"
        )

        old_file.unlink(
            missing_ok=True
        )

    # Sequential generation.
    for index, scene in enumerate(
        scenes,
        start=1
    ):

        try:

            result = await generate_scene(
                scene,
                index
            )

            records.append(result)

        except Exception as error:

            failed.append({
                "scene_id": scene["scene_id"],
                "error": str(error)
            })

            print(
                f"FAILED scene {scene['scene_id']}: {error}"
            )

    if failed:

        failure_report = {
            "failed_scenes": failed,
            "successful_scenes": records
        }

        REPORT_FILE.write_text(
            json.dumps(
                failure_report,
                ensure_ascii=False,
                indent=4
            ),
            encoding="utf-8"
        )

        raise RuntimeError(
            "Audio generation incomplete. "
            "Check audio_timing_report.json."
        )

    report = save_report(records)

    print("\n" + "=" * 55)

    print(
        "BADSAH AUDIO GENERATION REPORT"
    )

    print("=" * 55)

    print(
        "Scenes generated:",
        len(records)
    )

    print(
        "Total audio duration:",
        report["actual_total_audio_seconds"],
        "seconds"
    )

    print(
        "Within 30–55 seconds:",
        report["final_duration_within_target"]
    )

    print(
        "Audio folder:",
        AUDIO_DIR
    )

    print(
        "Report:",
        REPORT_FILE
    )

    print("\nALL SCENE AUDIO FILES GENERATED.")


# =====================================================
# ENTRY POINT
# =====================================================

if __name__ == "__main__":

    asyncio.run(main())
