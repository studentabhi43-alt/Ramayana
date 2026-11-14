
import json
import re
import subprocess
import sys
from pathlib import Path
from difflib import SequenceMatcher
from faster_whisper import WhisperModel

VIDEO = Path("final_output.mp4")
STORY = Path("story_output.json")
AUDIO = Path("audio_files")
OUT = Path("captions_test.mp4")
TEMP = Path("caption_test_temp")
FONT = "Noto Sans Devanagari"


def cmd(args):
    p = subprocess.run(
        args, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True
    )
    if p.returncode:
        raise RuntimeError(p.stderr[-2500:])
    return p.stdout.strip()


def duration(p):
    return float(cmd([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(p)
    ]))


def norm(s):
    return re.sub(r"[^\w]", "", str(s).lower(), flags=re.UNICODE)


def ts(t):
    c = max(0, round(t * 100))
    h, c = divmod(c, 360000)
    m, c = divmod(c, 6000)
    s, c = divmod(c, 100)
    return f"{h}:{m:02}:{s:02}.{c:02}"


def fit_times(words, heard, dur):
    a = [norm(x) for x in words]
    b = [norm(x["text"]) for x in heard]
    anchors = {}

    sm = SequenceMatcher(None, a, b, autojunk=False)

    for block in sm.get_matching_blocks():
        for k in range(block.size):
            i, j = block.a + k, block.b + k
            anchors[i] = (
                heard[j]["start"],
                heard[j]["end"]
            )

    # Fuzzy spelling anchors for Hindi ASR variations
    used = set()

    for i, x in enumerate(a):
        if i in anchors or not x:
            continue

        best = (0, None)

        for j, y in enumerate(b):
            if j in used or not y:
                continue

            score = SequenceMatcher(None, x, y).ratio()

            if score > best[0]:
                best = (score, j)

        if best[0] >= 0.68:
            j = best[1]
            anchors[i] = (
                heard[j]["start"],
                heard[j]["end"]
            )
            used.add(j)

    # Fit unmatched script words between Whisper anchors
    out = [None] * len(words)

    for i, (s, e) in anchors.items():
        out[i] = (max(0, s), min(dur, e))

    ids = sorted(anchors)

    bounds = (
        [(-1, 0.0)]
        + [(i, anchors[i][0]) for i in ids]
        + [(len(words), dur)]
    )

    for (li, lt), (ri, rt) in zip(bounds, bounds[1:]):
        miss = list(range(li + 1, ri))

        if not miss:
            continue

        if li >= 0 and out[li]:
            lt = max(lt, out[li][1])

        span = max(0.03 * len(miss), rt - lt)

        weights = [
            max(1, len(norm(words[k])))
            for k in miss
        ]

        total = sum(weights)
        cur = lt

        for k, w in zip(miss, weights):
            step = span * w / total
            out[k] = (cur, min(dur, cur + step))
            cur += step

    return [
        (max(0, s), min(dur, max(s + 0.04, e)))
        for s, e in out
    ]


def main():
    if not VIDEO.exists() or not STORY.exists():
        raise FileNotFoundError(
            "Need final_output.mp4 and story_output.json "
            "in repository root."
        )

    scenes = json.loads(
        STORY.read_text(encoding="utf-8")
    )

    if isinstance(scenes, dict):
        scenes = scenes.get(
            "scenes",
            scenes.get("story", [])
        )

    model = WhisperModel(
        "small",
        device="cpu",
        compute_type="int8"
    )

    allw = []
    report = []
    offset = 0.0

    for n, sc in enumerate(scenes, 1):
        sid = str(sc.get("scene_id", n))
        ap = AUDIO / f"scene_{sid}.mp3"

        if not ap.exists():
            raise FileNotFoundError(f"Missing {ap}")

        words = str(sc.get("dialogue", "")).split()
        dur = duration(ap)

        segs, _ = model.transcribe(
            str(ap),
            language="hi",
            word_timestamps=True,
            beam_size=5,
            vad_filter=False
        )

        heard = []

        for seg in segs:
            for w in (seg.words or []):
                if w.start is not None and w.end is not None:
                    heard.append({
                        "text": w.word.strip(),
                        "start": float(w.start),
                        "end": float(w.end)
                    })

        times = fit_times(words, heard, dur)

        for word, (s, e) in zip(words, times):
            allw.append({
                "word": word,
                "start": offset + s,
                "end": offset + e
            })

        report.append({
            "scene_id": sid,
            "script_words": len(words),
            "whisper_words": len(heard),
            "duration": dur
        })

        offset += dur

    probe = json.loads(cmd([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json", str(VIDEO)
    ]))

    width = int(probe["streams"][0]["width"])
    height = int(probe["streams"][0]["height"])

    TEMP.mkdir(exist_ok=True)
    ass = TEMP / "captions.ass"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{FONT},58,&H00FFFFFF,&H00FFFFFF,&H00000000,&H66FFFFFF,0,0,0,0,100,100,0,0,3,10,0,2,70,70,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []

    for i, w in enumerate(allw):
        shown = allw[
            max(0, i - 1):min(len(allw), i + 3)
        ]

        parts = []

        for j, x in enumerate(shown, start=max(0, i - 1)):
            t = (
                x["word"]
                .replace("{", r"\{")
                .replace("}", r"\}")
            )

            if j == i:
                parts.append(
                    r"{\c&H0033CCFF&\b1\fscx112\fscy112}"
                    + t + r"{\rCap}"
                )
            else:
                parts.append(t)

        line = "   ".join(parts)

        events.append(
            f"Dialogue: 0,{ts(w['start'])},"
            f"{ts(w['end'])},Cap,,0,0,0,,"
            f"{{\\fad(45,55)}}{line}"
        )

    ass.write_text(
        header + "\n".join(events) + "\n",
        encoding="utf-8-sig"
    )

    assarg = (
        str(ass.resolve())
        .replace("\\", "/")
        .replace(":", r"\:")
    )

    cmd([
        "ffmpeg", "-y",
        "-i", str(VIDEO),
        "-vf", f"subtitles='{assarg}'",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "19",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(OUT)
    ])

    reportdata = {
        "version": "V4",
        "status": "video_generated",
        "output": str(OUT),
        "caption_video_generated": OUT.exists(),
        "caption_words": len(allw),
        "timing": (
            "Whisper word timestamps; unmatched words "
            "fitted between anchors"
        ),
        "scenes": report
    }

    Path("caption_test_report_v4.json").write_text(
        json.dumps(reportdata, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("SUCCESS:", OUT)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)
