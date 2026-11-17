
"""
VEDIC GURU BADSAH - MAIN AUTOMATION POST-PRODUCTION
Integrated from the tested caption_test_v7.py.

- Removes a detected silent ~3-second opening from final_output.mp4.
- Uses Faster-Whisper Hindi word timestamps and the V7 breath-group caption style.
- Places assets/logo.png as a small (85px wide) top-right watermark for the full episode.
- Preserves the original narration audio.
- Adds the existing 4-second closing card so the existing duration verification passes.
- Optional assets/hanuman_flight.png progress overlay.
"""

import json
import math
import re
import shutil
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel
from PIL import Image, ImageDraw, ImageFont, ImageFilter

BASE = Path(__file__).resolve().parent
VIDEO = BASE / "final_output.mp4"
STORY = BASE / "story_output.json"
AUDIO = BASE / "audio_files"
ASSETS = BASE / "assets"
LOGO = ASSETS / "logo.png"
HANUMAN = ASSETS / "hanuman_flight.png"
OUTPUT = BASE / "badsah_final.mp4"
REPORT = BASE / "post_production_report.json"
WORK = BASE / "post_production_temp"

WIDTH, HEIGHT = 1080, 1920
FPS = 24
LOGO_WIDTH = 85
LOGO_MARGIN = 28
OUTRO_SECONDS = 4.0

MAX_WORDS_PER_GROUP = 5
MAX_GROUP_SECONDS = 2.35
MIN_GROUP_SECONDS = 0.55
CAPTION_Y = 0.80
FONT_SIZE = 43
MIN_FONT_SIZE = 29
BOX_PAD_X = 30
BOX_PAD_Y = 19
WORD_GAP = 15
BOX_RADIUS = 28

BOX_TOP = (83, 35, 22, 232)
BOX_BOTTOM = (34, 13, 12, 238)
GOLD = (255, 207, 92, 255)
WHITE = (255, 250, 239, 255)
BORDER = (235, 177, 67, 235)


def run_cmd(args):
    p = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    if p.returncode:
        raise RuntimeError(p.stderr[-5000:])
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
        r"[^\w]", "",
        str(word).lower(),
        flags=re.UNICODE
    )


def distribute_all(words, duration):
    weights = [max(1, len(normalize(w))) for w in words]
    total = sum(weights) or 1
    cursor, out = 0.0, []

    for weight in weights:
        step = duration * weight / total
        out.append((cursor, min(duration, cursor + step)))
        cursor += step

    return out


def weighted_fill(script_words, left, right, duration):
    missing = list(range(left[0] + 1, right[0]))

    if not missing:
        return {}

    start = max(0.0, left[1])
    end = max(start + 0.04, right[1])

    weights = [
        max(1, len(normalize(script_words[i])))
        for i in missing
    ]

    total = sum(weights)
    span = max(0.04 * len(missing), end - start)
    span = min(
        span,
        max(0.04 * len(missing), duration - start)
    )

    cursor, out = start, {}

    for i, weight in zip(missing, weights):
        step = span * weight / total
        a = min(duration, cursor)
        b = min(duration, max(a + 0.035, cursor + step))
        out[i] = (a, b)
        cursor += step

    return out


def align_words(script_words, heard_words, duration):
    n = len(script_words)

    if not n:
        return []

    script = [normalize(w) for w in script_words]
    heard = [
        normalize(w.get("text", ""))
        for w in heard_words
    ]

    anchors, used_heard = {}, set()

    matcher = SequenceMatcher(
        None, script, heard, autojunk=False
    )

    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            i, j = block.a + k, block.b + k

            if script[i] and heard[j]:
                anchors[i] = (
                    heard_words[j]["start"],
                    heard_words[j]["end"]
                )
                used_heard.add(j)

    last_j = -1

    for i, word in enumerate(script):
        if not word or i in anchors:
            continue

        best, best_score = None, 0.0

        for j, heard_word in enumerate(heard):
            if j in used_heard or j <= last_j or not heard_word:
                continue

            score = SequenceMatcher(
                None, word, heard_word
            ).ratio()

            if score > best_score:
                best_score, best = score, j

        if best is not None and best_score >= 0.72:
            anchors[i] = (
                heard_words[best]["start"],
                heard_words[best]["end"]
            )
            used_heard.add(best)
            last_j = best

    clean, previous_start = {}, -1.0

    for i in sorted(anchors):
        a, b = anchors[i]

        a = max(0.0, min(duration, float(a)))
        b = max(a + 0.035, min(duration, float(b)))

        if a >= previous_start:
            clean[i] = (a, b)
            previous_start = a

    anchors = clean

    if not anchors:
        return distribute_all(script_words, duration)

    result = [None] * n

    for i, timing in anchors.items():
        result[i] = timing

    boundaries = [(-1, 0.0)] + [
        (i, anchors[i][0])
        for i in sorted(anchors)
    ] + [(n, duration)]

    for left, right in zip(boundaries, boundaries[1:]):
        for i, timing in weighted_fill(
            script_words, left, right, duration
        ).items():
            result[i] = timing

    for i in range(n):
        if result[i] is None:
            result[i] = (
                0.0,
                max(0.04, duration / n)
            )

    fixed, previous = [], 0.0

    for a, b in result:
        a = max(previous, min(duration, float(a)))
        b = max(a + 0.035, min(duration, float(b)))

        if b <= a:
            b = min(duration, a + 0.04)

        fixed.append((a, b))
        previous = a

    return fixed


def get_font_path():
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Black.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
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
        "Noto Sans Devanagari font missing. Install fonts-noto-core."
    )


def split_into_breath_groups(words):
    groups, current = [], []

    for word in words:
        if current:
            span = word["end"] - current[0]["start"]

            should_break = (
                len(current) >= MAX_WORDS_PER_GROUP
                or span > MAX_GROUP_SECONDS
                or (
                    re.search(
                        r"[,;:।!?]",
                        current[-1]["word"]
                    ) is not None
                    and span >= MIN_GROUP_SECONDS
                )
            )

            if should_break:
                groups.append(current)
                current = []

        current.append(word)

        span_now = (
            current[-1]["end"] - current[0]["start"]
        )

        if re.search(r"[।!?]", word["word"]):
            groups.append(current)
            current = []

        elif span_now >= MAX_GROUP_SECONDS:
            groups.append(current)
            current = []

    if current:
        groups.append(current)

    return groups


def text_width(draw, text, font):
    box = draw.textbbox(
        (0, 0),
        text,
        font=font,
        stroke_width=1
    )
    return max(1, box[2] - box[0])


def fit_group_font(draw, words, font_path, max_width):
    size = FONT_SIZE

    while size >= MIN_FONT_SIZE:
        font = ImageFont.truetype(font_path, size)

        total = sum(
            text_width(draw, w["word"], font)
            for w in words
        )

        total += (
            WORD_GAP * max(0, len(words) - 1)
            + BOX_PAD_X * 2
        )

        if total <= max_width:
            return font, total

        size -= 2

    font = ImageFont.truetype(
        font_path,
        MIN_FONT_SIZE
    )

    total = sum(
        text_width(draw, w["word"], font)
        for w in words
    )

    total += (
        WORD_GAP * max(0, len(words) - 1)
        + BOX_PAD_X * 2
    )

    return font, min(max_width, total)


def ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def active_word_index(group, t):
    for i, word in enumerate(group):
        if word["start"] <= t < word["end"]:
            return i

    previous = [
        i for i, word in enumerate(group)
        if word["start"] <= t
    ]

    return previous[-1] if previous else 0


def draw_gradient_box(canvas, bounds, radius):
    x1, y1, x2, y2 = [
        int(v) for v in bounds
    ]

    w = max(1, x2 - x1)
    h = max(1, y2 - y1)

    box = Image.new(
        "RGBA",
        (w, h),
        (0, 0, 0, 0)
    )

    pix = box.load()

    for y in range(h):
        f = y / max(1, h - 1)

        color = tuple(
            int(
                BOX_TOP[k] * (1 - f)
                + BOX_BOTTOM[k] * f
            )
            for k in range(4)
        )

        for x in range(w):
            pix[x, y] = color

    mask = Image.new("L", (w, h), 0)

    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, w - 1, h - 1),
        radius=radius,
        fill=255
    )

    box.putalpha(
        Image.composite(
            box.getchannel("A"),
            Image.new("L", (w, h), 0),
            mask
        )
    )

    canvas.alpha_composite(box, (x1, y1))

    ImageDraw.Draw(canvas).rounded_rectangle(
        (x1, y1, x2, y2),
        radius=radius,
        outline=BORDER,
        width=2
    )


def render_frame(width, height, t, groups, font_path):
    canvas = Image.new(
        "RGBA",
        (width, height),
        (0, 0, 0, 0)
    )

    active_group = None

    for group in groups:
        if (
            group[0]["start"]
            <= t
            <= group[-1]["end"] + 0.18
        ):
            active_group = group
            break

    if active_group is None:
        return canvas

    start = active_group[0]["start"]
    end = active_group[-1]["end"]

    fade_in = ease((t - start) / 0.12)
    fade_out = ease((end + 0.16 - t) / 0.16)

    opacity = max(
        0.0,
        min(1.0, fade_in, fade_out)
    )

    if opacity <= 0:
        return canvas

    draw = ImageDraw.Draw(canvas)
    max_width = int(width * 0.92)

    font, _ = fit_group_font(
        draw,
        active_group,
        font_path,
        max_width
    )

    word_widths = [
        text_width(draw, w["word"], font)
        for w in active_group
    ]

    content_width = (
        sum(word_widths)
        + WORD_GAP * max(0, len(active_group) - 1)
    )

    box_width = min(
        width - 12,
        content_width + BOX_PAD_X * 2
    )

    bbox = font.getbbox("अग")
    text_height = max(1, bbox[3] - bbox[1])
    box_height = text_height + BOX_PAD_Y * 2

    scale = 0.96 + 0.04 * fade_in

    box_width = int(box_width * scale)
    box_height = int(box_height * scale)

    center_x = width // 2
    center_y = int(height * CAPTION_Y)

    x1 = center_x - box_width // 2
    y1 = center_y - box_height // 2
    x2 = x1 + box_width
    y2 = y1 + box_height

    shadow = Image.new(
        "RGBA",
        canvas.size,
        (0, 0, 0, 0)
    )

    ImageDraw.Draw(shadow).rounded_rectangle(
        (x1 + 2, y1 + 7, x2 + 2, y2 + 7),
        radius=BOX_RADIUS,
        fill=(0, 0, 0, int(125 * opacity))
    )

    canvas.alpha_composite(
        shadow.filter(ImageFilter.GaussianBlur(9))
    )

    draw_gradient_box(
        canvas,
        (x1, y1, x2, y2),
        BOX_RADIUS
    )

    draw = ImageDraw.Draw(canvas)
    current = active_word_index(active_group, t)
    cursor = center_x - content_width // 2

    for i, item in enumerate(active_group):
        word = item["word"]
        color = GOLD if i == current else WHITE

        draw.text(
            (cursor + 1, center_y + 2),
            word,
            font=font,
            fill=(0, 0, 0, int(150 * opacity)),
            anchor="lm",
            stroke_width=1,
            stroke_fill=(0, 0, 0, int(110 * opacity))
        )

        draw.text(
            (cursor, center_y),
            word,
            font=font,
            fill=(
                color[0],
                color[1],
                color[2],
                int(255 * opacity)
            ),
            anchor="lm",
            stroke_width=1,
            stroke_fill=(
                (105, 65, 25, int(190 * opacity))
                if i == current
                else (55, 35, 25, int(150 * opacity))
            )
        )

        cursor += word_widths[i] + WORD_GAP

    return canvas


def load_scenes():
    data = json.loads(
        STORY.read_text(encoding="utf-8")
    )

    if isinstance(data, dict):
        data = data.get(
            "scenes",
            data.get("story", [])
        )

    if not isinstance(data, list) or len(data) != 7:
        raise ValueError(
            "story_output.json must contain exactly 7 scenes."
        )

    return data


def create_outro(path):
    image = Image.new(
        "RGB",
        (WIDTH, HEIGHT),
        (12, 9, 7)
    )

    draw = ImageDraw.Draw(image)

    for y in range(HEIGHT):
        glow = int(
            10 + 22 * (
                1 - abs(y - HEIGHT / 2) / (HEIGHT / 2)
            )
        )

        draw.line(
            (0, y, WIDTH, y),
            fill=(
                glow + 5,
                int(glow * 0.72),
                int(glow * 0.36)
            )
        )

    gold = (231, 190, 105)
    pale = (255, 226, 165)
    font = get_font_path()

    draw.rounded_rectangle(
        (95, 570, 985, 1320),
        radius=48,
        fill=(35, 23, 13),
        outline=gold,
        width=6
    )

    draw.line(
        (540, 625, 540, 1265),
        fill=gold,
        width=5
    )

    draw.text(
        (540, 790),
        "VEDIC GURU",
        font=ImageFont.truetype(font, 68),
        fill=gold,
        anchor="mm"
    )

    draw.text(
        (540, 900),
        "BADSAH",
        font=ImageFont.truetype(font, 100),
        fill=pale,
        anchor="mm"
    )

    draw.text(
        (540, 1470),
        "आपका विचार क्या है?",
        font=ImageFont.truetype(font, 52),
        fill=(255, 245, 225),
        anchor="mm"
    )

    draw.text(
        (540, 1560),
        "अपना जवाब कमेंट में लिखें",
        font=ImageFont.truetype(font, 34),
        fill=gold,
        anchor="mm"
    )

    image.save(path)


def main():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(
                f"{tool} is not installed."
            )

    for path in (VIDEO, STORY, LOGO):
        if not path.exists():
            raise FileNotFoundError(
                f"Required file missing: {path}"
            )

    WORK.mkdir(
        parents=True,
        exist_ok=True
    )

    scenes = load_scenes()

    # Audio durations define the exact episode timeline.
    scene_audio = []

    for i, scene in enumerate(scenes, 1):
        sid = str(scene.get("scene_id", i))
        audio = AUDIO / f"scene_{sid}.mp3"

        if not audio.exists():
            raise FileNotFoundError(
                f"Missing narration audio: {audio}"
            )

        scene_audio.append(
            (scene, audio, get_duration(audio))
        )

    narration_duration = sum(
        item[2] for item in scene_audio
    )

    source_duration = get_duration(VIDEO)
    extra = source_duration - narration_duration

    # Existing generator's opening is silent and about 3 seconds.
    if abs(extra) <= 1.0:
        intro_seconds = 0.0

    elif 2.0 <= extra <= 4.0:
        intro_seconds = extra

    else:
        raise RuntimeError(
            f"Cannot safely align video/audio: "
            f"source={source_duration:.2f}s, "
            f"scene audio={narration_duration:.2f}s, "
            f"difference={extra:.2f}s. "
            "Expected no opening or an approximately 3-second silent intro."
        )

    print(f"Source video: {source_duration:.3f}s")
    print(f"Narration timeline: {narration_duration:.3f}s")
    print(f"Removing opening: {intro_seconds:.3f}s")

    # Run Hindi Whisper word timestamps scene by scene.
    print(
        "Loading Faster-Whisper small Hindi model (CPU int8)..."
    )

    model = WhisperModel(
        "small",
        device="cpu",
        compute_type="int8"
    )

    all_words = []
    scene_report = []
    timeline = 0.0

    for scene, audio, audio_duration in scene_audio:
        sid = str(scene.get("scene_id", ""))
        script_words = str(
            scene.get("dialogue", "")
        ).split()

        if not script_words:
            timeline += audio_duration
            continue

        print(
            f"Aligning Hindi narration for scene {sid}..."
        )

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
                if (
                    word.start is not None
                    and word.end is not None
                ):
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

        for word, (a, b) in zip(script_words, timings):
            all_words.append({
                "word": word,
                "start": timeline + a,
                "end": timeline + b
            })

        scene_report.append({
            "scene_id": sid,
            "audio_duration": round(audio_duration, 3),
            "script_words": len(script_words),
            "whisper_words": len(heard_words)
        })

        timeline += audio_duration

    if not all_words:
        raise RuntimeError(
            "No caption words were generated."
        )

    groups = split_into_breath_groups(all_words)
    font_path = get_font_path()

    # The base video is trimmed before captions are rendered.
    # Frame 0 is the first story frame, not the logo intro.
    dimensions = json.loads(run_cmd([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        str(VIDEO)
    ]))

    video_width = int(
        dimensions["streams"][0]["width"]
    )

    video_height = int(
        dimensions["streams"][0]["height"]
    )

    width = video_width // 2
    height = video_height // 2

    total_frames = int(
        math.ceil(narration_duration * FPS)
    )

    # FFmpeg inputs: trimmed episode, small corner logo,
    # caption RGBA pipe, and optional Hanuman progress image.
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-ss", f"{intro_seconds:.6f}",
        "-i", str(VIDEO),
        "-loop", "1",
        "-i", str(LOGO),
        "-f", "rawvideo",
        "-pix_fmt", "rgba",
        "-s", f"{width}x{height}",
        "-r", str(FPS),
        "-i", "pipe:0"
    ]

    has_hanuman = HANUMAN.exists()

    if has_hanuman:
        command += [
            "-loop", "1",
            "-i", str(HANUMAN)
        ]

    filters = [
        f"[2:v]scale={video_width}:{video_height}:flags=lanczos[cap]",
        "[0:v][cap]overlay=0:0:format=auto[captioned]",
        f"[1:v]scale={LOGO_WIDTH}:-1,format=rgba,"
        "colorchannelmixer=aa=0.90[logo]",
        f"[captioned][logo]overlay="
        f"W-w-{LOGO_MARGIN}:{LOGO_MARGIN}[branded]"
    ]

    last = "branded"

    if has_hanuman:
        filters += [
            "[3:v]scale=105:75,format=rgba[hanuman]",

            f"[{last}]drawbox=x=70:y=1790:w=940:h=5:"
            "color=0x8B6A32@0.95:t=fill[track]",

            f"[track][hanuman]overlay="
            f"x='70+(940-105)*min(t/{narration_duration:.6f},1)':"
            "y=1705[vmain]"
        ]

        last = "vmain"

    main_video = WORK / "episode_v7_branded.mp4"

    command += [
        "-filter_complex",
        ";".join(filters),

        "-map", f"[{last}]",
        "-map", "0:a:0",

        "-t", f"{narration_duration:.6f}",
        "-r", str(FPS),

        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "19",
        "-pix_fmt", "yuv420p",
        "-profile:v", "main",
        "-level:v", "4.0",

        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",

        "-movflags", "+faststart",
        str(main_video)
    ]

    ffmpeg = subprocess.Popen(
        command,
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
                groups,
                font_path
            )

            ffmpeg.stdin.write(frame.tobytes())

            if frame_number % (FPS * 5) == 0:
                print(
                    f"Rendering captions: "
                    f"{frame_number}/{total_frames}"
                )

        ffmpeg.stdin.close()

        error = ffmpeg.stderr.read().decode(
            "utf-8",
            errors="replace"
        )

        code = ffmpeg.wait()

        if code:
            raise RuntimeError(error[-5000:])

    except Exception:
        if ffmpeg.poll() is None:
            ffmpeg.kill()
            ffmpeg.wait()
        raise

    if (
        not main_video.exists()
        or main_video.stat().st_size == 0
    ):
        raise RuntimeError(
            "Captioned branded episode was not created."
        )

    actual_main = get_duration(main_video)

    if abs(actual_main - narration_duration) > 1.3:
        raise RuntimeError(
            f"Episode duration mismatch: "
            f"rendered={actual_main:.2f}s, "
            f"audio={narration_duration:.2f}s."
        )

    # Four-second closing card: no opening card or logo intro.
    outro_image = WORK / "outro.png"
    outro_video = WORK / "outro.mp4"

    create_outro(outro_image)

    run_cmd([
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",

        "-loop", "1",
        "-framerate", str(FPS),
        "-i", str(outro_image),

        "-f", "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=48000",

        "-loop", "1",
        "-i", str(LOGO),

        "-t", str(OUTRO_SECONDS),

        "-filter_complex",
        f"[0:v]scale={WIDTH}:{HEIGHT},format=yuv420p[bg];"
        f"[2:v]scale={LOGO_WIDTH}:-1,format=rgba,"
        "colorchannelmixer=aa=0.90[logo];"
        f"[bg][logo]overlay="
        f"W-w-{LOGO_MARGIN}:{LOGO_MARGIN}[vout]",

        "-map", "[vout]",
        "-map", "1:a:0",

        "-r", str(FPS),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",

        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",

        "-shortest",
        str(outro_video)
    ])

    concat_file = WORK / "concat.txt"

    concat_file.write_text(
        "file '" + main_video.resolve().as_posix() + "'\n"
        "file '" + outro_video.resolve().as_posix() + "'\n",
        encoding="utf-8"
    )

    run_cmd([
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",

        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),

        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "19",
        "-pix_fmt", "yuv420p",

        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",

        "-movflags", "+faststart",
        str(OUTPUT)
    ])

    final_duration = get_duration(OUTPUT)

    if final_duration <= source_duration:
        raise RuntimeError(
            f"Final video {final_duration:.2f}s must be longer "
            f"than source {source_duration:.2f}s for the "
            "existing workflow check."
        )

    report = {
        "status": "success",
        "output": OUTPUT.name,
        "source_duration_seconds": round(source_duration, 3),
        "removed_opening_seconds": round(intro_seconds, 3),
        "narration_duration_seconds": round(
            narration_duration, 3
        ),
        "final_duration_seconds": round(
            final_duration, 3
        ),
        "caption_engine": (
            "V7 Faster-Whisper Hindi word timestamps"
        ),
        "caption_style": (
            "Premium maroon-and-gold rounded breath-group bubble"
        ),
        "caption_groups": len(groups),
        "active_word": "Gold; remaining words white",
        "logo": (
            "assets/logo.png; 85px wide; top-right from "
            "first story frame to last narration frame"
        ),
        "hanuman_progress": has_hanuman,
        "outro_seconds": OUTRO_SECONDS,
        "original_narration_audio_preserved": True,
        "scenes": scene_report
    }

    REPORT.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        )
    )

    print(
        "BADSAH MAIN AUTOMATION POST-PRODUCTION COMPLETE"
    )

    print(f"SUCCESS: {OUTPUT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            "POST-PRODUCTION ERROR:",
            exc,
            file=sys.stderr
        )
        raise
