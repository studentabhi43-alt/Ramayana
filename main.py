import os
import re
import json
import time
import threading
import requests

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED


# ============================================================
# BADSAH V10 — PARALLEL AI RACE ENGINE
# GEMINI FAST MODELS + GROQ
# FIRST VALID RESULT WINS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

OUTPUT_FILE = BASE_DIR / "story_output.json"
RESEARCH_FILE = BASE_DIR / "research_sources.json"
REPORT_FILE = BASE_DIR / "fact_generation_report.json"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

# Fast Gemini models: try in this order.
GEMINI_MODELS = [
    item.strip()
    for item in os.getenv(
        "GEMINI_MODELS",
        "gemini-3.8-flash,gemini-3.8-flash-lite"
    ).split(",")
    if item.strip()
]

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-20b"
).strip()

GROQ_RETRY_WINDOW = 180
GROQ_RETRY_INTERVAL = 5

REQUEST_TIMEOUT = (15, 90)

TOTAL_SCENES = 7
MIN_SCENE_WORDS = 11
MAX_SCENE_WORDS = 24

winner_event = threading.Event()


# ============================================================
# HTTP
# ============================================================

def new_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "BADSAH-V10/1.0"
    })
    return session


# ============================================================
# JSON UTILITIES
# ============================================================

def extract_json(raw):

    if not raw:
        raise ValueError("Empty AI response.")

    raw = raw.strip()

    raw = re.sub(
        r"^```(?:json)?\s*",
        "",
        raw,
        flags=re.IGNORECASE
    )

    raw = re.sub(r"\s*```$", "", raw)

    # Find a JSON object or array.
    start_positions = [
        position
        for position in (
            raw.find("{"),
            raw.find("[")
        )
        if position >= 0
    ]

    if not start_positions:
        raise ValueError("No JSON found.")

    start = min(start_positions)

    opening = raw[start]
    closing = "}" if opening == "{" else "]"

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(raw)):

        char = raw[index]

        if in_string:

            if escaped:
                escaped = False

            elif char == "\\":
                escaped = True

            elif char == '"':
                in_string = False

            continue

        if char == '"':
            in_string = True

        elif char == opening:
            depth += 1

        elif char == closing:
            depth -= 1

            if depth == 0:
                return json.loads(raw[start:index + 1])

    raise ValueError("Incomplete JSON response.")


def save_json(path, data):

    temporary = path.with_suffix(path.suffix + ".tmp")

    temporary.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=4
        ),
        encoding="utf-8"
    )

    temporary.replace(path)


# ============================================================
# SCRIPT PROMPT
# ============================================================

SCRIPT_PROMPT = """
You are BADSAH, a professional Indian scripture documentary
researcher and short-video scriptwriter.

Generate ONE complete episode about a genuinely interesting
lesser-known fact or contrast from Indian scriptures.

Possible areas:
- Ramayana
- Mahabharata
- Bhagavad Gita
- Puranas
- Vedic literature
- Radha-Krishna traditions
- Valmiki Ramayana vs Ramcharitmanas
- Different regional retellings

IMPORTANT FACTUAL RULES:

1. Never invent a verse, chapter, kand, parva or quotation.
2. Clearly distinguish primary scripture, later retelling,
   regional tradition, popular belief and interpretation.
3. Never present an unverified claim as confirmed fact.
4. Never fabricate source URLs.
5. If a precise reference is uncertain, say so.
6. Keep the narration respectful.
7. Do not create a fake mystery.
8. Do not add unsupported claims for dramatic effect.

VIDEO STYLE:
- Balanced cinematic and informative.
- Natural Hindi narration, mainly in Devanagari.
- Easy-to-understand spoken language.
- Strong opening hook.
- Seven connected scenes.
- Approximately 40–55 seconds overall.
- Topic-specific documentary visuals.
- No fixed fictional characters.

RETURN ONLY THIS JSON OBJECT:

{
  "topic": "topic name",
  "title": "engaging video title",
  "central_question": "main question",
  "topic_category": "comparison or hidden detail or textual fact",
  "summary": "short factual summary",
  "claims": [
    {
      "claim_id": "C1",
      "claim": "specific factual statement",
      "evidence_type": "primary text / later retelling / regional tradition / interpretation",
      "scripture_reference": "exact reference if known, otherwise state uncertainty",
      "limitations": "what the evidence does not establish"
    }
  ],
  "sources": [
    {
      "source_name": "source name",
      "source_url": "real URL if actually known",
      "source_type": "primary text / translation / scholarly reference"
    }
  ],
  "important_distinction": "important clarification",
  "conclusion": "balanced conclusion",
  "scenes": [
    {
      "scene_id": 1,
      "start_time": "00:00",
      "end_time": "00:07",
      "target_duration_seconds": 7,
      "scene_time_description": "Scene 1",
      "visible_characters": [],
      "dialogue": "Hindi narration in Devanagari",
      "image_prompt": "detailed documentary image description",
      "video_motion_prompt": "camera and environmental movement",
      "claim_refs": ["C1"]
    }
  ]
}

SCENE RULES:

Exactly 7 scenes.

Scene timings:
1. 00:00–00:07
2. 00:07–00:14
3. 00:14–00:21
4. 00:21–00:28
5. 00:28–00:35
6. 00:35–00:42
7. 00:42–00:49

Each dialogue must contain 11–24 words.

Every scene must have:
- scene_id
- dialogue
- image_prompt
- video_motion_prompt
- claim_refs

Every claim_refs entry must refer to a claim_id in claims.

Use [] for visible_characters.

Do not add markdown or explanations.
Return valid JSON only.
"""


# ============================================================
# VALIDATE AI RESULT
# ============================================================

def word_count(text):
    return len(re.findall(r"\S+", str(text).strip()))


def validate_result(data, provider):

    if not isinstance(data, dict):
        raise ValueError("Response must be a JSON object.")

    required = [
        "topic",
        "title",
        "claims",
        "sources",
        "scenes",
        "important_distinction",
        "conclusion"
    ]

    for field in required:

        if not data.get(field):
            raise ValueError(
                f"Missing required field: {field}"
            )

    claims = data["claims"]
    scenes = data["scenes"]

    if not isinstance(claims, list) or not claims:
        raise ValueError("No research claims returned.")

    if not isinstance(scenes, list):
        raise ValueError("Scenes must be a list.")

    if len(scenes) != TOTAL_SCENES:
        raise ValueError(
            f"Expected 7 scenes, got {len(scenes)}."
        )

    claim_ids = set()

    for claim in claims:

        if not isinstance(claim, dict):
            raise ValueError("Invalid claim object.")

        for field in (
            "claim_id",
            "claim",
            "evidence_type",
            "limitations"
        ):

            if not claim.get(field):
                raise ValueError(
                    f"Claim missing {field}."
                )

        claim_ids.add(str(claim["claim_id"]))

    timings = [
        ("00:00", "00:07"),
        ("00:07", "00:14"),
        ("00:14", "00:21"),
        ("00:21", "00:28"),
        ("00:28", "00:35"),
        ("00:35", "00:42"),
        ("00:42", "00:49")
    ]

    cleaned_scenes = []
    total_words = 0

    for index, scene in enumerate(scenes):

        if not isinstance(scene, dict):
            raise ValueError("Invalid scene.")

        required_scene_fields = [
            "dialogue",
            "image_prompt",
            "video_motion_prompt",
            "claim_refs"
        ]

        for field in required_scene_fields:

            if not scene.get(field):
                raise ValueError(
                    f"Scene {index + 1}: missing {field}."
                )

        dialogue = str(scene["dialogue"]).strip()
        words = word_count(dialogue)

        if not MIN_SCENE_WORDS <= words <= MAX_SCENE_WORDS:
            raise ValueError(
                f"Scene {index + 1}: invalid word count {words}."
            )

        refs = scene["claim_refs"]

        if not isinstance(refs, list) or not refs:
            raise ValueError(
                f"Scene {index + 1}: missing claim references."
            )

        unknown_refs = set(
            str(ref) for ref in refs
        ) - claim_ids

        if unknown_refs:
            raise ValueError(
                f"Scene {index + 1}: unknown claims {unknown_refs}."
            )

        start, end = timings[index]

        cleaned_scenes.append({
            "scene_id": index + 1,
            "start_time": start,
            "end_time": end,
            "target_duration_seconds": 7,
            "scene_time_description": (
                f"Scene {index + 1}, approximately 7 seconds"
            ),
            "visible_characters": [],
            "dialogue": dialogue,
            "image_prompt": str(scene["image_prompt"]).strip(),
            "video_motion_prompt": str(
                scene["video_motion_prompt"]
            ).strip(),
            "claim_refs": [
                str(ref) for ref in refs
            ]
        })

        total_words += words

    if not 80 <= total_words <= 168:
        raise ValueError(
            f"Total dialogue word count is {total_words}."
        )

    data["scenes"] = cleaned_scenes
    data["provider"] = provider

    return data


# ============================================================
# GEMINI API
# ============================================================

def gemini_request(model):

    session = new_session()

    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{model}:generateContent"
    )

    payload = {
        "contents": [{
            "parts": [{
                "text": SCRIPT_PROMPT
            }]
        }],
        "tools": [{
            "google_search": {}
        }],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 12000
        }
    }

    response = session.post(
        url,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY
        },
        json=payload,
        timeout=REQUEST_TIMEOUT
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"Gemini HTTP {response.status_code}: "
            f"{response.text[:700]}"
        )

    result = response.json()

    candidates = result.get("candidates", [])

    if not candidates:
        raise ValueError("Gemini returned no candidates.")

    candidate = candidates[0]

    parts = candidate.get(
        "content", {}
    ).get("parts", [])

    raw = "".join(
        part.get("text", "")
        for part in parts
    )

    if not raw:
        raise ValueError("Gemini returned empty text.")

    grounding_urls = []

    metadata = candidate.get(
        "groundingMetadata", {}
    )

    for item in metadata.get("groundingChunks", []):

        web = item.get("web", {})
        uri = web.get("uri")

        if uri and uri not in grounding_urls:
            grounding_urls.append(uri)

    data = extract_json(raw)

    if not grounding_urls:
        raise ValueError(
            "Gemini did not return Google Search grounding URLs."
        )

    data = validate_result(data, "GEMINI")

    data["_grounding_urls"] = grounding_urls

    return data


# ============================================================
# GEMINI WORKER
# Switch fast model on failure
# ============================================================

def gemini_worker():

    if not GEMINI_API_KEY:
        print("[GEMINI] API key missing.")
        return None

    for model in GEMINI_MODELS:

        if winner_event.is_set():
            return None

        print(f"\n[GEMINI] Trying fast model: {model}")

        # Model errors cause a switch to the next fast model.
        # Temporary errors also move to the next model.
        try:

            result = gemini_request(model)

            if winner_event.is_set():
                return None

            result["_model"] = model

            print(
                f"[GEMINI] VALID RESULT from {model}"
            )

            return result

        except Exception as error:

            print(
                f"[GEMINI] {model} failed: "
                f"{str(error)[:500]}"
            )

            print("[GEMINI] Switching to next fast model.")

    print("[GEMINI] All configured fast models failed.")
    return None


# ============================================================
# GROQ API
# ============================================================

def groq_request():

    session = new_session()

    url = (
        "https://api.groq.com/openai/v1/"
        "chat/completions"
    )

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are BADSAH's scripture documentary "
                    "researcher and professional Hindi scriptwriter. "
                    "Return valid JSON only. Never invent sources."
                )
            },
            {
                "role": "user",
                "content": SCRIPT_PROMPT
            }
        ],
        "temperature": 0.4,
        "max_tokens": 12000
    }

    response = session.post(
        url,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=REQUEST_TIMEOUT
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"Groq HTTP {response.status_code}: "
            f"{response.text[:700]}"
        )

    result = response.json()

    choices = result.get("choices", [])

    if not choices:
        raise ValueError("Groq returned no choices.")

    choice = choices[0]

    if choice.get("finish_reason") == "length":
        raise ValueError("Groq response was truncated.")

    raw = choice.get(
        "message", {}
    ).get("content", "")

    data = extract_json(raw)

    return validate_result(data, "GROQ")


# ============================================================
# GROQ WORKER
# RETRY EVERY 5 SECONDS, MAX 3 MINUTES
# ============================================================

def groq_worker():

    if not GROQ_API_KEY:
        print("[GROQ] API key missing.")
        return None

    start = time.monotonic()
    attempt = 0

    print(
        f"\n[GROQ] Starting parallel race with {GROQ_MODEL}"
    )

    while (
        time.monotonic() - start
    ) < GROQ_RETRY_WINDOW:

        if winner_event.is_set():
            return None

        attempt += 1

        elapsed = int(
            time.monotonic() - start
        )

        print(
            f"[GROQ] Attempt {attempt} | "
            f"{elapsed}/{GROQ_RETRY_WINDOW} seconds"
        )

        try:

            result = groq_request()

            if winner_event.is_set():
                return None

            result["_model"] = GROQ_MODEL

            print(
                "[GROQ] VALID RESULT RECEIVED."
            )

            return result

        except Exception as error:

            print(
                f"[GROQ] Attempt {attempt} failed: "
                f"{str(error)[:500]}"
            )

            remaining = (
                GROQ_RETRY_WINDOW
                - (time.monotonic() - start)
            )

            if remaining <= 0:
                break

            print(
                f"[GROQ] Retrying in {GROQ_RETRY_INTERVAL} seconds."
            )

            # Wait can be interrupted if another provider wins.
            winner_event.wait(
                min(GROQ_RETRY_INTERVAL, remaining)
            )

    print("[GROQ] Three-minute retry window completed.")
    return None


# ============================================================
# PARALLEL RACE
# FIRST VALID RESULT WINS
# ============================================================

def run_parallel_race():

    winner_event.clear()

    executor = ThreadPoolExecutor(
        max_workers=2,
        thread_name_prefix="BADSAH"
    )

    futures = {}

    if GEMINI_API_KEY:
        future = executor.submit(gemini_worker)
        futures[future] = "GEMINI"

    if GROQ_API_KEY:
        future = executor.submit(groq_worker)
        futures[future] = "GROQ"

    if not futures:
        executor.shutdown(wait=False)
        raise RuntimeError(
            "Neither Gemini nor Groq API key is configured."
        )

    winner = None

    try:

        pending = set(futures)

        while pending:

            completed, pending = wait(
                pending,
                return_when=FIRST_COMPLETED
            )

            for future in completed:

                provider = futures[future]

                try:
                    result = future.result()

                except Exception as error:

                    print(
                        f"[{provider}] Worker error: {error}"
                    )

                    result = None

                if result is not None:

                    winner = result

                    winner_event.set()

                    print("\n" + "=" * 55)
                    print("FIRST VALID RESULT WINS")
                    print("WINNER:", provider)
                    print("MODEL:", result["_model"])
                    print("=" * 55)

                    break

            if winner:
                break

    finally:

        winner_event.set()

        for future in futures:
            future.cancel()

        # Do not hold up the winning result waiting for the loser.
        executor.shutdown(
            wait=False,
            cancel_futures=True
        )

    if winner is None:
        raise RuntimeError(
            "Both providers failed to produce a valid result."
        )

    return winner


# ============================================================
# SAVE FINAL EPISODE
# ============================================================

def save_episode(winner):

    scenes = winner["scenes"]

    # Compatible with image/audio/video generators:
    # story_output.json contains a scene list.
    save_json(
        OUTPUT_FILE,
        scenes
    )

    if winner["provider"] == "GEMINI":

        sources = {
            "provider": "GEMINI GOOGLE SEARCH",
            "model": winner["_model"],
            "verification_status": (
                "Google Search grounding URLs returned; "
                "scripture references still require manual verification."
            ),
            "sources": [
                {
                    "source_id": f"S{index}",
                    "url": url
                }
                for index, url in enumerate(
                    winner.get("_grounding_urls", []),
                    start=1
                )
            ]
        }

    else:

        sources = {
            "provider": "GROQ",
            "model": winner["_model"],
            "verification_status": (
                "AI-generated source suggestions; "
                "not independently verified by Google Search."
            ),
            "sources": winner.get("sources", [])
        }

    save_json(
        RESEARCH_FILE,
        sources
    )

    total_words = sum(
        word_count(scene["dialogue"])
        for scene in scenes
    )

    report = {
        "engine": "BADSAH V10 PARALLEL RACE",
        "status": "SUCCESS",
        "winner": winner["provider"],
        "winning_model": winner["_model"],
        "topic": winner["topic"],
        "title": winner["title"],
        "total_scenes": len(scenes),
        "total_dialogue_words": total_words,
        "source_verification": sources[
            "verification_status"
        ],
        "output_file": OUTPUT_FILE.name,
        "research_file": RESEARCH_FILE.name
    }

    save_json(
        REPORT_FILE,
        report
    )

    return report


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n" + "=" * 60)
    print("BADSAH V10 — PARALLEL AI RACE")
    print("=" * 60)

    print("Gemini models:", GEMINI_MODELS)
    print("Groq model:", GROQ_MODEL)
    print("Groq retry window:", GROQ_RETRY_WINDOW, "seconds")
    print("Groq retry interval:", GROQ_RETRY_INTERVAL, "seconds")

    print("\nBoth providers are starting together.")

    winner = run_parallel_race()

    report = save_episode(winner)

    print("\n" + "=" * 60)
    print("BADSAH SCRIPT GENERATION SUCCESS")
    print("=" * 60)

    print("Topic:", report["topic"])
    print("Winner:", report["winner"])
    print("Model:", report["winning_model"])
    print("Scenes:", report["total_scenes"])
    print("Dialogue words:", report["total_dialogue_words"])

    print("\nSCENE DIALOGUES")

    for scene in winner["scenes"]:

        print(
            f"\nScene {scene['scene_id']}:"
        )

        print(scene["dialogue"])

    print("\nSaved:")
    print(OUTPUT_FILE.name)
    print(RESEARCH_FILE.name)
    print(REPORT_FILE.name)

    print("\nBADSAH V10 COMPLETED.")


if __name__ == "__main__":
    main()
