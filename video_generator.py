import json
import subprocess
import shutil
import re
from pathlib import Path

# =====================================================
# BADSAH VIDEO GENERATOR
# Scripture Hidden Facts / Contrasting Facts
# =====================================================

BASE_DIR = Path(__file__).resolve().parent

STORY_FILE = BASE_DIR / "story_output.json"
IMAGE_DIR = BASE_DIR / "images"
AUDIO_DIR = BASE_DIR / "audio_files"

TEMP_DIR = BASE_DIR / "video_temp"

OUTPUT_FILE = BASE_DIR / "final_output.mp4"
REPORT_FILE = BASE_DIR / "video_generation_report.json"

WIDTH = 1080
HEIGHT = 1920
FPS = 30

EXPECTED_SCENES = 7

VIDEO_CRF = "20"
VIDEO_PRESET = "medium"

# =====================================================
# COMMAND UTILITIES
# =====================================================

def run_command(command):

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Command failed:\n"
            + " ".join(command)
            + "\n\n"
            + result.stderr[-4000:]
        )

    return result


def check_ffmpeg():

    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "FFmpeg is not installed or not available in PATH."
        )

    if not shutil.which("ffprobe"):
        raise RuntimeError(
            "FFprobe is not installed or not available in PATH."
        )

    print("FFmpeg and FFprobe detected.")


# =====================================================
# LOAD STORY
# =====================================================

def load_scenes():

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

    if isinstance(data, dict):

        scenes = data.get("scenes")

    elif isinstance(data, list):

        scenes = data

    else:

        scenes = None

    if not isinstance(scenes, list):

        raise ValueError(
            "Invalid story_output.json: scenes array missing."
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

        scene_id = str(
            scene.get("scene_id", index)
        )

        if not re.fullmatch(
            r"[A-Za-z0-9_-]+",
            scene_id
        ):

            raise ValueError(
                f"Invalid scene ID: {scene_id}"
            )

        scene["scene_id"] = scene_id

    return scenes


# =====================================================
# AUDIO DURATION
# =====================================================

def get_duration(audio_path):

    result = run_command([
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path)
    ])

    try:

        duration = float(
            result.stdout.strip()
        )

    except ValueError:

        raise ValueError(
            f"Could not read audio duration: {audio_path}"
        )

    if duration <= 0:

        raise ValueError(
            f"Invalid audio duration: {audio_path}"
        )

    return duration


# =====================================================
# IMAGE VALIDATION
# =====================================================

def validate_files(scenes):

    checked = []

    for index, scene in enumerate(
        scenes,
        start=1
    ):

        scene_id = scene["scene_id"]

        image_path = (
            IMAGE_DIR / f"scene_{scene_id}.png"
        )

        audio_path = (
            AUDIO_DIR / f"scene_{scene_id}.mp3"
        )

        if not image_path.exists():

            raise FileNotFoundError(
                f"Missing image: {image_path}"
            )

        if image_path.stat().st_size < 1000:

            raise ValueError(
                f"Image file is too small: {image_path}"
            )

        if not audio_path.exists():

            raise FileNotFoundError(
                f"Missing audio: {audio_path}"
            )

        if audio_path.stat().st_size < 1000:

            raise ValueError(
                f"Audio file is too small: {audio_path}"
            )

        duration = get_duration(audio_path)

        checked.append({
            "scene_id": scene_id,
            "image": image_path,
            "audio": audio_path,
            "duration": duration
        })

        print(
            f"Scene {index}: "
            f"Image OK | Audio OK | "
            f"{duration:.2f}s"
        )

    return checked


# =====================================================
# CREATE ONE SCENE VIDEO
# =====================================================

def create_scene_video(scene, index):

    scene_id = scene["scene_id"]

    image_path = scene["image"]
    audio_path = scene["audio"]

    duration = scene["duration"]

    frames = max(
        1,
        round(duration * FPS)
    )

    output_path = (
        TEMP_DIR / f"scene_{index:02d}.mp4"
    )

    # Alternate zoom direction for visual variety.
    if index % 2 == 0:

        zoom_filter = (
            "zoompan="
            "z='min(zoom+0.0005,1.08)':"
            "x='iw/2-(iw/zoom/2)':"
            "y='ih/2-(ih/zoom/2)':"
            f"d={frames}:"
            f"s={WIDTH}x{HEIGHT}:"
            f"fps={FPS}"
        )

    else:

        zoom_filter = (
            "zoompan="
            "z='min(zoom+0.0005,1.08)':"
            "x='iw/2-(iw/zoom/2)':"
            "y='ih/2-(ih/zoom/2)':"
            f"d={frames}:"
            f"s={WIDTH}x{HEIGHT}:"
            f"fps={FPS}"
        )

    video_filter = (
        "scale=1200:2134:force_original_aspect_ratio=increase,"
        "crop=1200:2134,"
        + zoom_filter
        + ","
        "format=yuv420p"
    )

    command = [
        "ffmpeg",
        "-y",

        "-loop", "1",
        "-framerate", str(FPS),
        "-i", str(image_path),

        "-i", str(audio_path),

        "-vf", video_filter,

        "-map", "0:v:0",
        "-map", "1:a:0",

        "-frames:v", str(frames),

        "-c:v", "libx264",
        "-preset", VIDEO_PRESET,
        "-crf", VIDEO_CRF,

        "-pix_fmt", "yuv420p",

        "-c:a", "aac",
        "-b:a", "192k",

        "-ar", "48000",

        "-t", f"{duration:.3f}",

        "-movflags", "+faststart",

        "-shortest",

        str(output_path)
    ]

    print(
        f"\nRendering scene {index}/{EXPECTED_SCENES}..."
    )

    run_command(command)

    if not output_path.exists():

        raise RuntimeError(
            f"Scene video was not created: {output_path}"
        )

    if output_path.stat().st_size < 10000:

        raise RuntimeError(
            f"Scene video is unexpectedly small: {output_path}"
        )

    print(
        f"Scene {index} completed: "
        f"{output_path.name}"
    )

    return output_path


# =====================================================
# CONCATENATE SCENES
# =====================================================

def create_concat_file(scene_files):

    concat_file = TEMP_DIR / "concat_list.txt"

    lines = []

    for file_path in scene_files:

        # Absolute paths with escaped single quotes.
        safe_path = str(
            file_path.resolve()
        ).replace("'", "'\\''")

        lines.append(
            f"file '{safe_path}'"
        )

    concat_file.write_text(
        "\n".join(lines),
        encoding="utf-8"
    )

    return concat_file


def merge_scenes(scene_files):

    concat_file = create_concat_file(
        scene_files
    )

    temporary_output = (
        BASE_DIR / "final_output_temp.mp4"
    )

    command = [
        "ffmpeg",
        "-y",

        "-f", "concat",
        "-safe", "0",

        "-i", str(concat_file),

        "-c", "copy",

        "-movflags", "+faststart",

        str(temporary_output)
    ]

    print("\nMerging all scenes...")

    run_command(command)

    if not temporary_output.exists():

        raise RuntimeError(
            "Merged video was not created."
        )

    if temporary_output.stat().st_size < 50000:

        raise RuntimeError(
            "Merged video is unexpectedly small."
        )

    temporary_output.replace(
        OUTPUT_FILE
    )

    print("All scenes merged successfully.")


# =====================================================
# FINAL VIDEO VALIDATION
# =====================================================

def validate_final_video():

    result = run_command([
        "ffprobe",
        "-v", "error",
        "-show_entries",
        "stream=codec_type,width,height,codec_name",
        "-show_entries",
        "format=duration,size",
        "-of", "json",
        str(OUTPUT_FILE)
    ])

    data = json.loads(
        result.stdout
    )

    streams = data.get(
        "streams",
        []
    )

    video_streams = [
        stream for stream in streams
        if stream.get("codec_type") == "video"
    ]

    audio_streams = [
        stream for stream in streams
        if stream.get("codec_type") == "audio"
    ]

    if not video_streams:

        raise RuntimeError(
            "Final video has no video stream."
        )

    if not audio_streams:

        raise RuntimeError(
            "Final video has no audio stream."
        )

    video = video_streams[0]

    if (
        video.get("width") != WIDTH
        or video.get("height") != HEIGHT
    ):

        raise RuntimeError(
            "Final video resolution is incorrect."
        )

    duration = float(
        data["format"]["duration"]
    )

    size = int(
        data["format"]["size"]
    )

    return {
        "file": OUTPUT_FILE.name,
        "resolution": f"{WIDTH}x{HEIGHT}",
        "fps": FPS,
        "duration_seconds": round(duration, 3),
        "size_bytes": size,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio_streams[0].get("codec_name"),
        "has_video": True,
        "has_audio": True
    }


# =====================================================
# MAIN VIDEO ENGINE
# =====================================================

def main():

    print("\n")
    print("=" * 60)
    print("BADSAH CINEMATIC VIDEO GENERATOR")
    print("=" * 60)

    check_ffmpeg()

    scenes = load_scenes()

    print(
        "\nTotal scenes:",
        len(scenes)
    )

    # Recreate temporary folder.
    if TEMP_DIR.exists():

        shutil.rmtree(
            TEMP_DIR
        )

    TEMP_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # Validate all input files first.
    checked_scenes = validate_files(
        scenes
    )

    total_audio = sum(
        scene["duration"]
        for scene in checked_scenes
    )

    print(
        f"\nTotal voice-over duration: "
        f"{total_audio:.2f} seconds"
    )

    # Render each scene.
    scene_videos = []

    for index, scene in enumerate(
        checked_scenes,
        start=1
    ):

        video_file = create_scene_video(
            scene,
            index
        )

        scene_videos.append(
            video_file
        )

    # Merge all scenes.
    merge_scenes(
        scene_videos
    )

    # Validate final output.
    report = validate_final_video()

    report["scene_count"] = len(scenes)

    report["scene_durations"] = [
        {
            "scene_id": scene["scene_id"],
            "duration_seconds": round(
                scene["duration"],
                3
            )
        }
        for scene in checked_scenes
    ]

    REPORT_FILE.write_text(
        json.dumps(
            report,
            indent=4,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    # Remove temporary files after successful validation.
    shutil.rmtree(
        TEMP_DIR,
        ignore_errors=True
    )

    temporary_output = (
        BASE_DIR / "final_output_temp.mp4"
    )

    temporary_output.unlink(
        missing_ok=True
    )

    print("\n")
    print("=" * 60)
    print("BADSAH VIDEO GENERATION COMPLETED")
    print("=" * 60)

    print(
        "Final video:",
        OUTPUT_FILE
    )

    print(
        "Resolution:",
        report["resolution"]
    )

    print(
        "Duration:",
        report["duration_seconds"],
        "seconds"
    )

    print(
        "File size:",
        round(
            report["size_bytes"] / (1024 * 1024),
            2
        ),
        "MB"
    )

    print(
        "Video codec:",
        report["video_codec"]
    )

    print(
        "Audio codec:",
        report["audio_codec"]
    )

    print(
        "\nReport saved:",
        REPORT_FILE
    )


# =====================================================
# ENTRY POINT
# =====================================================

if __name__ == "__main__":

    main()
