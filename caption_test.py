
import json
import re
import subprocess
import sys
import math
from pathlib import Path
from difflib import SequenceMatcher

from faster_whisper import WhisperModel
from PIL import Image, ImageDraw, ImageFont, ImageFilter

VIDEO = Path("final_output.mp4")
STORY = Path("story_output.json")
AUDIO = Path("audio_files")
OUTPUT = Path("captions_test.mp4")
REPORT = Path("caption_test_report_v6.json")

FPS = 24
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
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-3000:])
    return p.stdout.strip()


def get_duration(path):
    return float(run_cmd([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ]))


def normalize(word):
    return re.sub(r"[^\w]", "", str(word).lower(), flags=re.UNICODE)


def weighted_fill(script_words, left, right, duration):
    missing = list(range(left[0] + 1, right[0]))
    if not missing:
        return {}
    start = max(0.0, left[1])
    end = max(start + 0.04, right[1])
    weights = [max(1, len(normalize(script_words[i]))) for i in missing]
    total = sum(weights)
    span = max(0.04 * len(missing), end - start)
    span = min(span, max(0.04 * len(missing), duration - start))
    cursor = start
    out = {}
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
    heard = [normalize(w.get("text", "")) for w in heard_words]
    anchors = {}
    used_heard = set()

    matcher = SequenceMatcher(None, script, heard, autojunk=False)
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            i, j = block.a + k, block.b + k
            if script[i] and heard[j]:
                anchors[i] = (heard_words[j]["start"], heard_words[j]["end"])
                used_heard.add(j)

    last_j = -1
    for i, word in enumerate(script):
        if not word or i in anchors:
            continue
        best = None
        best_score = 0.0
        for j, heard_word in enumerate(heard):
            if j in used_heard or j <= last_j or not heard_word:
                continue
            score = SequenceMatcher(None, word, heard_word).ratio()
            if score > best_score:
                best_score, best = score, j
        if best is not None and best_score >= 0.72:
            anchors[i] = (heard_words[best]["start"], heard_words[best]["end"])
            used_heard.add(best)
            last_j = best

    clean = {}
    previous_start = -1.0
    for i in sorted(anchors):
        a, b = anchors[i]
        a = max(0.0, min(duration, float(a)))
        b = max(a + 0.035, min(duration, float(b)))
        if a >= previous_start:
            clean[i] = (a, b)
            previous_start = a
    anchors = clean

    if not anchors:
        return _distribute_all(script_words, duration)

    result = [None] * n
    for i, timing in anchors.items():
        result[i] = timing

    anchor_ids = sorted(anchors)
    boundaries = [(-1, 0.0)] + [(i, anchors[i][0]) for i in anchor_ids] + [(n, duration)]
    for left, right in zip(boundaries, boundaries[1:]):
        fills = weighted_fill(script_words, left, right, duration)
        for i, timing in fills.items():
            result[i] = timing

    for i in range(n):
        if result[i] is None:
            result[i] = (0.0, max(0.04, duration / n))

    fixed = []
    previous = 0.0
    for a, b in result:
        a = max(previous, min(duration, float(a)))
        b = max(a + 0.035, min(duration, float(b)))
        if b <= a:
            b = min(duration, a + 0.04)
        fixed.append((a, b))
        previous = a
    return fixed


def _distribute_all(words, duration):
    weights = [max(1, len(normalize(w))) for w in words]
    total = sum(weights) or 1
    cursor = 0.0
    out = []
    for weight in weights:
        step = duration * weight / total
        out.append((cursor, min(duration, cursor + step)))
        cursor += step
    return out


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
            ["fc-match", "-f", "%{file}", "Noto Sans Devanagari:style=Bold"],
            text=True
        ).strip()
        if Path(result).exists():
            return result
    except Exception:
        pass
    raise FileNotFoundError("Noto Sans Devanagari font not found. Install fonts-noto-core.")


def get_video_size():
    data = json.loads(run_cmd([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", str(VIDEO)
    ]))
    return int(data["streams"][0]["width"]), int(data["streams"][0]["height"])


def split_into_breath_groups(words):
    groups = []
    current = []
    for word in words:
        if current:
            span = word["end"] - current[0]["start"]
            should_break = (
                len(current) >= MAX_WORDS_PER_GROUP
                or span > MAX_GROUP_SECONDS
                or (re.search(r"[,;:।!?]", current[-1]["word"]) is not None
                    and span >= MIN_GROUP_SECONDS)
            )
            if should_break:
                groups.append(current)
                current = []
        current.append(word)
        span_now = current[-1]["end"] - current[0]["start"]
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
    box = draw.textbbox((0, 0), text, font=font, stroke_width=1)
    return max(1, box[2] - box[0])


def fit_group_font(draw, words, font_path, max_width):
    size = FONT_SIZE
    while size >= MIN_FONT_SIZE:
        font = ImageFont.truetype(font_path, size)
        total = sum(text_width(draw, w["word"], font) for w in words)
        total += WORD_GAP * max(0, len(words) - 1) + BOX_PAD_X * 2
        if total <= max_width:
            return font, total
        size -= 2
    font = ImageFont.truetype(font_path, MIN_FONT_SIZE)
    total = sum(text_width(draw, w["word"], font) for w in words)
    total += WORD_GAP * max(0, len(words)-1) + BOX_PAD_X*2
    return font, min(max_width, total)


def ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def active_word_index(group, t):
    for i, word in enumerate(group):
        if word["start"] <= t < word["end"]:
            return i
    previous = [i for i, word in enumerate(group) if word["start"] <= t]
    if previous:
        return previous[-1]
    return 0


def draw_gradient_box(canvas, bounds, radius):
    x1, y1, x2, y2 = [int(v) for v in bounds]
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    box = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pix = box.load()
    for y in range(h):
        f = y / max(1, h - 1)
        c = tuple(int(BOX_TOP[k] * (1-f) + BOX_BOTTOM[k] * f) for k in range(4))
        for x in range(w):
            pix[x, y] = c
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w-1, h-1), radius=radius, fill=255)
    box.putalpha(Image.composite(box.getchannel("A"), Image.new("L", (w, h), 0), mask))
    canvas.alpha_composite(box, (x1, y1))
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((x1, y1, x2, y2), radius=radius, outline=BORDER, width=2)


def render_frame(width, height, t, groups, font_path):
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    active_group = None
    for group in groups:
        if group[0]["start"] <= t <= group[-1]["end"] + 0.18:
            active_group = group
            break
    if active_group is None:
        return canvas

    start = active_group[0]["start"]
    end = active_group[-1]["end"]
    fade_in = ease((t - start) / 0.12)
    fade_out = ease((end + 0.16 - t) / 0.16)
    opacity = max(0.0, min(1.0, fade_in, fade_out))
    if opacity <= 0:
        return canvas

    draw = ImageDraw.Draw(canvas)
    max_width = int(width * 0.92)
    font, _ = fit_group_font(draw, active_group, font_path, max_width)
    word_widths = [text_width(draw, w["word"], font) for w in active_group]
    content_width = sum(word_widths) + WORD_GAP * max(0, len(active_group)-1)
    box_width = min(width - 12, content_width + BOX_PAD_X * 2)
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
    x2, y2 = x1 + box_width, y1 + box_height

    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_layer)
    sd.rounded_rectangle((x1+2, y1+7, x2+2, y2+7), radius=BOX_RADIUS, fill=(0, 0, 0, int(125*opacity)))
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(9))
    canvas.alpha_composite(shadow_layer)
    draw_gradient_box(canvas, (x1, y1, x2, y2), BOX_RADIUS)

    draw = ImageDraw.Draw(canvas)
    current = active_word_index(active_group, t)
    cursor = center_x - content_width // 2
    baseline_y = center_y
    for i, item in enumerate(active_group):
        word = item["word"]
        w = word_widths[i]
        color = GOLD if i == current else WHITE
        x = cursor
        draw.text((x+1, baseline_y+2), word, font=font, fill=(0, 0, 0, int(150*opacity)), anchor="lm", stroke_width=1, stroke_fill=(0, 0, 0, int(110*opacity)))
        draw.text((x, baseline_y), word, font=font,
                  fill=(color[0], color[1], color[2], int(255*opacity)),
                  anchor="lm", stroke_width=1,
                  stroke_fill=(105, 65, 25, int(190*opacity)) if i == current else (55, 35, 25, int(150*opacity)))
        cursor += w + WORD_GAP
    return canvas


def main():
    if not VIDEO.exists():
        raise FileNotFoundError("final_output.mp4 missing")
    if not STORY.exists():
        raise FileNotFoundError("story_output.json missing")

    scenes = json.loads(STORY.read_text(encoding="utf-8"))
    if isinstance(scenes, dict):
        scenes = scenes.get("scenes", scenes.get("story", []))
    if not scenes:
        raise ValueError("No scenes found in story_output.json")

    print("Loading Hindi speech model...")
    model = WhisperModel("small", device="cpu", compute_type="int8")
    all_words = []
    scene_report = []
    timeline = 0.0

    for number, scene in enumerate(scenes, 1):
        scene_id = str(scene.get("scene_id", number))
        audio = AUDIO / f"scene_{scene_id}.mp3"
        if not audio.exists():
            raise FileNotFoundError(f"Missing audio: {audio}")
        script_words = str(scene.get("dialogue", "")).split()
        if not script_words:
            continue
        audio_duration = get_duration(audio)
        print(f"Aligning scene {scene_id}...")
        segments, _ = model.transcribe(
            str(audio), language="hi", word_timestamps=True,
            beam_size=5, vad_filter=False
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
        timings = align_words(script_words, heard_words, audio_duration)
        for word, (a, b) in zip(script_words, timings):
            all_words.append({"word": word, "start": timeline+a, "end": timeline+b})
        scene_report.append({
            "scene_id": scene_id,
            "audio_duration": round(audio_duration, 3),
            "script_words": len(script_words),
            "whisper_words": len(heard_words),
            "alignment_note": "Whisper anchors with interpolation for unmatched words"
        })
        timeline += audio_duration

    if not all_words:
        raise ValueError("No caption words generated")

    groups = split_into_breath_groups(all_words)
    video_width, video_height = get_video_size()
    width, height = max(2, video_width // 2), max(2, video_height // 2)
    font_path = get_font_path()
    video_duration = get_duration(VIDEO)
    total_frames = int(math.ceil(video_duration * FPS))
    if total_frames <= 0:
        raise ValueError("Invalid video duration")

    print(f"Creating {len(groups)} premium breath-group captions...")
    OUTPUT.unlink(missing_ok=True)

    ffmpeg = subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(VIDEO),
        "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{width}x{height}", "-r", str(FPS), "-i", "pipe:0",
        "-filter_complex",
        f"[1:v]scale={video_width}:{video_height}:flags=lanczos[cap];[0:v][cap]overlay=0:0:format=auto[out]",
        "-map", "[out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-profile:v", "main", "-level:v", "4.0",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-movflags", "+faststart", str(OUTPUT)
    ], stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        for frame_number in range(total_frames):
            t = frame_number / FPS
            frame = render_frame(width, height, t, groups, font_path)
            ffmpeg.stdin.write(frame.tobytes())
            if frame_number % (FPS * 5) == 0:
                print(f"Rendering: {frame_number}/{total_frames}")
        ffmpeg.stdin.close()
        error = ffmpeg.stderr.read().decode("utf-8", errors="replace")
        return_code = ffmpeg.wait()
        if return_code != 0:
            raise RuntimeError(error[-3000:])
    except Exception:
        if ffmpeg.poll() is None:
            ffmpeg.kill()
            ffmpeg.wait()
        raise

    if not OUTPUT.exists() or OUTPUT.stat().st_size == 0:
        raise RuntimeError("Caption video was not created")

    report = {
        "version": "V7",
        "status": "video_generated",
        "output_video": str(OUTPUT),
        "caption_video_generated": True,
        "caption_style": "Premium maroon-and-gold rounded breath-group bubble",
        "grouping": "Words grouped by punctuation, duration and readability",
        "active_word": "Gold highlight; other words white",
        "background": "Transparent outside rounded caption bubble",
        "shadow": "Soft drop shadow and subtle text shadow",
        "animation": "Smooth fade and scale transition between caption groups",
        "fps": FPS,
        "video_codec": "H.264",
        "pixel_format": "yuv420p",
        "audio_codec": "AAC",
        "caption_groups": len(groups),
        "timeline_audio_seconds": round(timeline, 3),
        "video_seconds": round(video_duration, 3),
        "timing_note": "Whisper timestamps where matched; unmatched words interpolated.",
        "scenes": scene_report
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SUCCESS: captions_test.mp4 generated")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ERROR:", error, file=sys.stderr)
        sys.exit(1)
