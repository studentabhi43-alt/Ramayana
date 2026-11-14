
import json
import re
import subprocess
import sys
from pathlib import Path
from difflib import SequenceMatcher

from faster_whisper import WhisperModel
from PIL import Image, ImageDraw, ImageFont

VIDEO = Path("final_output.mp4")
STORY = Path("story_output.json")
AUDIO = Path("audio_files")
OUTPUT = Path("captions_test.mp4")
REPORT = Path("caption_test_report_v6.json")

FPS = 24
FONT_NAME = "Noto Sans Devanagari"
NORMAL_SIZE = 39
ACTIVE_SIZE = 47
GAP = 13
CAPTION_Y = 0.81



def run_cmd(args):
    p = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if p.returncode:
        raise RuntimeError(p.stderr[-3000:])

    return p.stdout.strip()


def get_duration(path):
    return float(run_cmd([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ]))


def normalize(word):
    return re.sub(
        r"[^\w]", "", str(word).lower(),
        flags=re.UNICODE
    )


def get_font_path():
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.otf",
        "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"
    ]

    for path in candidates:
        if Path(path).exists():
            return path

    try:
        result = subprocess.check_output(
            [
                "fc-match", "-f", "%{file}",
                "Noto Sans Devanagari:style=Bold"
            ],
            text=True
        ).strip()

        if Path(result).exists():
            return result
    except Exception:
        pass

    raise FileNotFoundError(
        "Noto Sans Devanagari font not found. "
        "Install fonts-noto-core in GitHub Actions."
    )


def align_words(script_words, heard_words, duration):
    script = [normalize(w) for w in script_words]
    heard = [normalize(w["text"]) for w in heard_words]
    anchors = {}

    matcher = SequenceMatcher(
        None, script, heard, autojunk=False
    )

    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            i = block.a + k
            j = block.b + k

            anchors[i] = (
                heard_words[j]["start"],
                heard_words[j]["end"]
            )

    used = set()

    for i, word in enumerate(script):
        if i in anchors or not word:
            continue

        best_score = 0
        best_index = None

        for j, heard in enumerate(heard):
            if j in used or not heard:
                continue

            score = SequenceMatcher(
                None, word, heard
            ).ratio()

            if score > best_score:
                best_score = score
                best_index = j

        if best_index is not None and best_score >= 0.68:
            anchors[i] = (
                heard_words[best_index]["start"],
                heard_words[best_index]["end"]
            )
            used.add(best_index)

    result = [None] * len(script_words)

    for i, timing in anchors.items():
        result[i] = timing

    ids = sorted(anchors)

    boundaries = (
        [(-1, 0.0)]
        + [(i, anchors[i][0]) for i in ids]
        + [(len(script_words), duration)]
    )

    for (left_i, left_t), (right_i, right_t) in zip(
        boundaries, boundaries[1:]
    ):
        missing = list(range(left_i + 1, right_i))

        if not missing:
            continue

        if left_i >= 0 and result[left_i]:
            left_t = max(left_t, result[left_i][1])

        span = max(
            0.04 * len(missing),
            right_t - left_t
        )

        weights = [
            max(1, len(normalize(script_words[k])))
            for k in missing
        ]

        total = sum(weights)
        cursor = left_t

        for k, weight in zip(missing, weights):
            step = span * weight / total
            result[k] = (
                cursor,
                min(duration, cursor + step)
            )
            cursor += step

    fixed = []

    for start, end in result:
        start = max(0.0, min(duration, start))
        end = max(start + 0.04, min(duration, end))
        fixed.append((start, end))

    return fixed


def get_video_size():
    data = json.loads(run_cmd([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json", str(VIDEO)
    ]))

    return (
        int(data["streams"][0]["width"]),
        int(data["streams"][0]["height"])
    )


def make_track(words, font):
    widths = []

    for word in words:
        box = font.getbbox(word)
        widths.append(max(1, box[2] - box[0]))

    centers = [0.0]

    for i in range(1, len(words)):
        distance = (
            widths[i - 1] / 2
            + widths[i] / 2
            + GAP
        )
        centers.append(centers[-1] + distance)

    return centers


def get_progress(t, words):
    starts = [w["start"] for w in words]

    if t < starts[0]:
        return None, None

    i = 0

    # Find the currently active word
    lo, hi = 0, len(starts)

    while lo < hi:
        mid = (lo + hi) // 2

        if starts[mid] <= t:
            lo = mid + 1
        else:
            hi = mid

    i = max(0, lo - 1)

    if i >= len(words):
        return None, None

    if i == len(words) - 1:
        return i, float(i)

    current_start = words[i]["start"]
    next_start = words[i + 1]["start"]

    if next_start <= current_start:
        return i, float(i)

    fraction = (
        (t - current_start)
        / (next_start - current_start)
    )

    fraction = max(0.0, min(1.0, fraction))

    return i, i + fraction


def render_frame(
    width, height, t, words,
    font_normal, font_active, track
):
    # Half-resolution transparent canvas
    canvas = Image.new(
        "RGBA",
        (width, height),
        (0, 0, 0, 0)
    )

    if not words:
        return canvas

    active, progress = get_progress(t, words)

    if active is None:
        return canvas

    # Four-word moving window
    center_index = int(progress)

    first = max(0, center_index - 1)
    last = min(len(words), center_index + 3)

    # Smoothly move the complete word train left
    if active >= len(track) - 1:
        track_position = track[-1]
    else:
        fraction = progress - active
        track_position = (
            track[active]
            + fraction * (
                track[active + 1] - track[active]
            )
        )

    center_x = width / 2
    y = int(height * CAPTION_Y)

    draw = ImageDraw.Draw(canvas)

    for i in range(first, last):
        x = center_x + track[i] - track_position

        if x < -width / 2 or x > width * 1.5:
            continue

        is_active = (i == active)

        font = font_active if is_active else font_normal

        color = (
            (255, 205, 65, 255)
            if is_active
            else (255, 255, 255, 255)
        )

        # Bubble-like thick rounded lettering.
        # Stroke uses the same color; no text box or background.
        draw.text(
            (int(x), y),
            words[i]["word"],
            font=font,
            fill=color,
            anchor="mm",
            stroke_width=2 if is_active else 1,
            stroke_fill=color
        )

    return canvas


def main():
    if not VIDEO.exists():
        raise FileNotFoundError("final_output.mp4 missing")

    if not STORY.exists():
        raise FileNotFoundError("story_output.json missing")

    scenes = json.loads(
        STORY.read_text(encoding="utf-8")
    )

    if isinstance(scenes, dict):
        scenes = scenes.get(
            "scenes",
            scenes.get("story", [])
        )

    if not scenes:
        raise ValueError("No scenes found")

    print("Loading Hindi speech model...")

    model = WhisperModel(
        "small",
        device="cpu",
        compute_type="int8"
    )

    all_words = []
    timeline = 0.0
    scene_report = []

    for number, scene in enumerate(scenes, 1):
        scene_id = str(scene.get("scene_id", number))
        audio = AUDIO / f"scene_{scene_id}.mp3"

        if not audio.exists():
            raise FileNotFoundError(f"Missing {audio}")

        script_words = str(
            scene.get("dialogue", "")
        ).split()

        audio_duration = get_duration(audio)

        print(f"Aligning scene {scene_id}...")

        segments, _ = model.transcribe(
            str(audio),
            language="hi",
            word_timestamps=True,
            beam_size=5,
            vad_filter=False
        )

        heard_words = []

        for segment in segments:
            for word in (segment.words or []):
                if word.start is not None and word.end is not None:
                    heard_words.append({
                        "text": word.word.strip(),
                        "start": float(word.start),
                        "end": float(word.end)
                    })

        timings = align_words(
            script_words,
            heard_words,
            audio_duration
        )

        for word, (start, end) in zip(
            script_words, timings
        ):
            all_words.append({
                "word": word,
                "start": timeline + start,
                "end": timeline + end
            })

        scene_report.append({
            "scene_id": scene_id,
            "audio_duration": audio_duration,
            "script_words": len(script_words),
            "whisper_words": len(heard_words)
        })

        timeline += audio_duration

    if not all_words:
        raise ValueError("No caption words generated")

    video_width, video_height = get_video_size()

    # Render at half resolution to reduce processing load.
    width = video_width // 2
    height = video_height // 2

    font_path = get_font_path()

    font_normal = ImageFont.truetype(
        font_path, NORMAL_SIZE
    )

    font_active = ImageFont.truetype(
        font_path, ACTIVE_SIZE
    )

    track = make_track(
        [w["word"] for w in all_words],
        font_active
    )

    video_duration = get_duration(VIDEO)
    total_frames = int(video_duration * FPS)

    print("Creating smooth transparent caption animation...")

    OUTPUT.unlink(missing_ok=True)

    ffmpeg = subprocess.Popen(
        [
            "ffmpeg", "-y",
            "-i", str(VIDEO),
            "-f", "rawvideo",
            "-pix_fmt", "rgba",
            "-s", f"{width}x{height}",
            "-r", str(FPS),
            "-i", "pipe:0",
            "-filter_complex",
            (
                "[1:v]scale="
                f"{video_width}:{video_height}:flags=lanczos[cap];"
                "[0:v][cap]overlay=0:0:format=auto[out]"
            ),
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "19",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(OUTPUT)
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    try:
        for frame_number in range(total_frames):
            t = frame_number / FPS

            frame = render_frame(
                width,
                height,
                t,
                all_words,
                font_normal,
                font_active,
                track
            )

            ffmpeg.stdin.write(frame.tobytes())

            if frame_number % (FPS * 5) == 0:
                print(
                    f"Rendering: {frame_number}/{total_frames}"
                )

        ffmpeg.stdin.close()
        error = ffmpeg.stderr.read().decode(
            "utf-8", errors="replace"
        )
        return_code = ffmpeg.wait()

        if return_code != 0:
            raise RuntimeError(error[-3000:])

    except Exception:
        if ffmpeg.poll() is None:
            ffmpeg.kill()
            ffmpeg.wait()
        raise

    report = {
        "version": "V6",
        "status": "video_generated",
        "output_video": str(OUTPUT),
        "caption_video_generated": OUTPUT.exists(),
        "animation": "Continuous right-to-left word train",
        "normal_text": "White",
        "active_text": "Golden, enlarged and bold",
        "background": "Transparent",
        "font_style": "Rounded bold Devanagari",
        "visible_words": "Up to four",
        "fps": FPS,
        "scenes": scene_report
    }

    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("SUCCESS: captions_test.mp4 generated")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ERROR:", error, file=sys.stderr)
        sys.exit(1)
