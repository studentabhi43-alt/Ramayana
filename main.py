
import os
import re
import json
import time
import threading
import requests

from pathlib import Path
from concurrent.futures import (
    ThreadPoolExecutor,
    wait,
    FIRST_COMPLETED
)

# =====================================================
# BADSAH SCRIPTURE ENGINE V9
# PARALLEL GEMINI + GROQ
# AUTOMATIC RETRIES + JSON VALIDATION
# =====================================================

BASE_DIR = Path(__file__).resolve().parent

OUTPUT_FILE = BASE_DIR / "story_output.json"
RESEARCH_FILE = BASE_DIR / "research_sources.json"
REPORT_FILE = BASE_DIR / "fact_generation_report.json"

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY", ""
).strip()

GROQ_API_KEY = os.getenv(
    "GROQ_API_KEY", ""
).strip()

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.8-flash"
).strip()

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-20b"
).strip()

TOTAL_SCENES = 7

MIN_WORDS = 95
MAX_WORDS = 145

MIN_SCENE_WORDS = 11
MAX_SCENE_WORDS = 24

REQUEST_TIMEOUT = (15, 90)
RETRY_DELAY = 4
PROVIDER_RETRY_SECONDS = 100

winner_event = threading.Event()

session = requests.Session()

# =====================================================
# SCRIPTURE TOPIC AREAS
# =====================================================

TOPIC_AREAS = [
    "Ramayana",
    "Mahabharata",
    "Bhagavad Gita",
    "Puranas",
    "Vedic literature",
    "Radha Krishna traditions",
    "Valmiki Ramayana and Ramcharitmanas",
    "different regional versions of Indian epics"
]

# =====================================================
# RESEARCH PROMPT
# =====================================================

RESEARCH_PROMPT = """
You are BADSAH's scripture research assistant.

Your task is to discover ONE interesting, lesser-known,
well-supported topic from Indian scriptures and traditions.

Possible areas:
Ramayana, Mahabharata, Bhagavad Gita, Puranas,
Vedic literature, Radha-Krishna traditions,
regional retellings and differences between texts.

RESEARCH RULES:

1. Prefer primary scripture sources and reliable translations.
2. Search for actual textual evidence.
3. Never invent a verse, chapter, kand, parva or quotation.
4. Clearly distinguish original text, later retelling,
   regional tradition, interpretation and popular belief.
5. Do not present folklore as universally accepted scripture.
6. Do not make sensational claims without evidence.
7. If two texts differ, identify both texts accurately.
8. If evidence is uncertain, explain the uncertainty.
9. Do not fabricate source URLs.
10. Do not invent historical facts.

Return JSON with this structure:

{
  "topic": "topic name",
  "title": "short engaging title",
  "central_question": "question answered by the video",
  "topic_category": "comparison / hidden detail / textual fact",
  "summary": "short factual summary",
  "claims": [
    {
      "claim_id": "C1",
      "claim": "factual statement",
      "evidence_type": "primary text / later retelling / tradition / interpretation",
      "source_urls": ["exact URL used"],
      "limitations": "what this evidence does not establish"
    }
  ],
  "important_distinction": "important clarification",
  "conclusion": "balanced conclusion",
  "research_warnings": []
}

Include at least 3 useful claims.

Use Google Search for research.
Return JSON only.
"""

# =====================================================
# SCRIPT PROMPT
# =====================================================

def build_script_prompt(research):

    research_text = json.dumps(
        research,
        ensure_ascii=False,
        indent=2
    )

    return f"""
You are the professional scriptwriter of BADSAH.

Create a premium 7-scene vertical video script
about the supplied scripture research.

RESEARCH MATERIAL:
{research_text}

CONTENT STYLE:
- Balanced cinematic + informative.
- Natural Hindi narration with familiar English terms.
- Write narration primarily in Devanagari.
- Engaging, emotional and easy to understand.
- Respectful treatment of all religious traditions.
- No unnecessary exaggeration.
- No fictional characters.
- No recurring character requirement.

FACTUAL RULES:
1. Use ONLY the supplied research.
2. Never invent scripture references or quotations.
3. Never add claims not supported by the research.
4. Clearly distinguish different texts and traditions.
5. Never describe an interpretation as an explicit verse.
6. Preserve important limitations and uncertainty.
7. Do not create a fake mystery.
8. Keep every scene connected to the topic.

VIDEO STRUCTURE:
Exactly 7 scenes.
Target video length: approximately 40–55 seconds.
Each scene should contain concise narration.
Scene 1: strong but factual hook.
Scenes 2–5: explain the evidence and details.
Scene 6: explain the contrast or important distinction.
Scene 7: thoughtful conclusion and memorable ending.

TIMING:
Scene 1: 00:00–00:07
Scene 2: 00:07–00:14
Scene 3: 00:14–00:21
Scene 4: 00:21–00:28
Scene 5: 00:28–00:35
Scene 6: 00:35–00:42
Scene 7: 00:42–00:49

OUTPUT FORMAT:
Return ONLY a valid JSON array containing exactly 7 objects.

Each object MUST contain:

scene_id
start_time
end_time
target_duration_seconds
scene_time_description
visible_characters
dialogue
image_prompt
video_motion_prompt
claim_refs

RULES FOR FIELDS:

scene_id:
Use 1 to 7.

visible_characters:
Always use an empty list [].
No fixed characters are required.

dialogue:
Narration only.
Use natural spoken Hindi in Devanagari.
Keep each scene between 11 and 24 words.
Do not use speaker labels.

image_prompt:
Describe a detailed, topic-specific documentary visual.
Use manuscripts, historical locations, temples, objects,
maps, illustrations and symbolic scenes where appropriate.
Avoid unrelated fantasy characters.

video_motion_prompt:
Describe camera movement, environmental movement
and cinematic visual progression.

claim_refs:
A list containing one or more exact claim_id values
from the supplied research.

Never invent claim IDs.

Return valid JSON only.
No markdown.
No explanation.
"""

# =====================================================
# JSON EXTRACTION
# =====================================================

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

    raw = re.sub(
        r"\s*```$",
        "",
        raw
    )

    start = raw.find("[")
    end = raw.rfind("]")

    if start >= 0 and end > start:
        return json.loads(raw[start:end + 1])

    start = raw.find("{")
    end = raw.rfind("}")

    if start >= 0 and end > start:
        return json.loads(raw[start:end + 1])

    raise ValueError("No valid JSON found.")


# =====================================================
# WORD COUNT
# =====================================================

def count_words(text):

    return len(
        re.findall(r"\S+", text.strip())
    )


# =====================================================
# VALIDATE RESEARCH
# =====================================================

def validate_research(research, grounding_urls):

    if not isinstance(research, dict):
        raise ValueError("Research must be a JSON object.")

    required = [
        "topic",
        "title",
        "central_question",
        "claims",
        "important_distinction",
        "conclusion"
    ]

    for field in required:

        if not research.get(field):
            raise ValueError(
                f"Research missing field: {field}"
            )

    claims = research["claims"]

    if not isinstance(claims, list) or len(claims) < 3:
        raise ValueError(
            "Research must contain at least 3 claims."
        )

    if not grounding_urls:
        raise ValueError(
            "Google Search returned no grounding URLs."
        )

    verified_urls = set(grounding_urls)

    for index, claim in enumerate(claims, start=1):

        if not isinstance(claim, dict):
            raise ValueError(
                f"Research claim {index} is invalid."
            )

        for field in (
            "claim_id",
            "claim",
            "evidence_type",
            "source_urls"
        ):

            if not claim.get(field):
                raise ValueError(
                    f"Claim {index} missing {field}."
                )

        if not isinstance(claim["source_urls"], list):
            raise ValueError(
                f"Claim {index} source_urls must be a list."
            )

        matched = [
            url for url in claim["source_urls"]
            if url in verified_urls
        ]

        if not matched:
            raise ValueError(
                f"Claim {index} has no URL matching "
                "Google Search grounding."
            )

        claim["source_urls"] = matched

    return research


# =====================================================
# VALIDATE SCRIPT
# =====================================================

def validate_story(story, research):

    if not isinstance(story, list):
        raise ValueError("Story must be a JSON array.")

    if len(story) != TOTAL_SCENES:
        raise ValueError(
            f"Expected 7 scenes, received {len(story)}."
        )

    claims = {
        str(item["claim_id"])
        for item in research["claims"]
    }

    timings = [
        ("00:00", "00:07"),
        ("00:07", "00:14"),
        ("00:14", "00:21"),
        ("00:21", "00:28"),
        ("00:28", "00:35"),
        ("00:35", "00:42"),
        ("00:42", "00:49")
    ]

    total_words = 0
    scene_counts = []
    cleaned = []

    for index, scene in enumerate(story):

        number = index + 1

        if not isinstance(scene, dict):
            raise ValueError(
                f"Scene {number} is invalid."
            )

        required = [
            "dialogue",
            "image_prompt",
            "video_motion_prompt",
            "claim_refs"
        ]

        for field in required:

            if not scene.get(field):
                raise ValueError(
                    f"Scene {number}: missing {field}."
                )

        dialogue = str(
            scene["dialogue"]
        ).strip()

        image_prompt = str(
            scene["image_prompt"]
        ).strip()

        motion_prompt = str(
            scene["video_motion_prompt"]
        ).strip()

        words = count_words(dialogue)

        if not MIN_SCENE_WORDS <= words <= MAX_SCENE_WORDS:
            raise ValueError(
                f"Scene {number}: {words} words. "
                f"Required {MIN_SCENE_WORDS}-{MAX_SCENE_WORDS}."
            )

        if not image_prompt or not motion_prompt:
            raise ValueError(
                f"Scene {number}: empty visual prompt."
            )

        claim_refs = scene["claim_refs"]

        if not isinstance(claim_refs, list) or not claim_refs:
            raise ValueError(
                f"Scene {number}: no claim references."
            )

        unknown = set(
            map(str, claim_refs)
        ) - claims

        if unknown:
            raise ValueError(
                f"Scene {number}: unknown claims {unknown}."
            )

        start, end = timings[index]

        cleaned.append({
            "scene_id": number,
            "start_time": start,
            "end_time": end,
            "target_duration_seconds": 7.0,
            "scene_time_description": (
                f"Scene {number}, approximately 7 seconds."
            ),
            "visible_characters": [],
            "dialogue": dialogue,
            "image_prompt": image_prompt,
            "video_motion_prompt": motion_prompt,
            "claim_refs": list(map(str, claim_refs))
        })

        total_words += words
        scene_counts.append(words)

    if not MIN_WORDS <= total_words <= MAX_WORDS:
        raise ValueError(
            f"Total dialogue words: {total_words}. "
            f"Required {MIN_WORDS}-{MAX_WORDS}."
        )

    return cleaned, total_words, scene_counts


# =====================================================
# GEMINI REQUEST
# =====================================================

def request_gemini(prompt, use_search=False):

    if not GEMINI_API_KEY:
        raise RuntimeError("Gemini API key missing.")

    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{GEMINI_MODEL}:generateContent"
    )

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "temperature": 0.35,
            "responseMimeType": "application/json",
            "maxOutputTokens": 12000
        }
    }

    if use_search:
        payload["tools"] = [{
            "google_search": {}
        }]

    response = session.post(
        url,
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT
    )

    if response.status_code != 200:

        if response.status_code in (400, 401, 403, 404):
            raise RuntimeError(
                f"PERMANENT HTTP {response.status_code}: "
                f"{response.text[:1000]}"
            )

        raise ConnectionError(
            f"Gemini HTTP {response.status_code}: "
            f"{response.text[:700]}"
        )

    data = response.json()

    candidates = data.get("candidates", [])

    if not candidates:
        raise ValueError("Gemini returned no candidates.")

    candidate = candidates[0]

    if candidate.get("finishReason") == "MAX_TOKENS":
        raise ValueError("Gemini response was truncated.")

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

    for chunk in metadata.get("groundingChunks", []):

        web_data = chunk.get("web", {})

        uri = web_data.get("uri")

        if uri and uri not in grounding_urls:
            grounding_urls.append(uri)

    return raw, grounding_urls


# =====================================================
# RESEARCH WORKER
# =====================================================

def research_worker():

    print("\n[GEMINI] Starting scripture research.")

    deadline = (
        time.monotonic() + PROVIDER_RETRY_SECONDS
    )

    attempt = 0

    while time.monotonic() < deadline:

        attempt += 1

        try:

            print(
                f"[GEMINI] Research attempt {attempt}"
            )

            raw, grounding_urls = request_gemini(
                RESEARCH_PROMPT,
                use_search=True
            )

            research = json.loads(raw)

            research = validate_research(
                research,
                grounding_urls
            )

            # Store only source URLs actually returned
            # by Gemini Google Search grounding.
            sources = []

            for index, url in enumerate(
                grounding_urls,
                start=1
            ):

                sources.append({
                    "source_id": f"S{index}",
                    "url": url
                })

            research["grounded_sources"] = sources

            print(
                "[GEMINI] Research validated:",
                research["topic"]
            )

            return research

        except Exception as error:

            message = str(error)

            print(
                "[GEMINI] Research failed:",
                message[:700]
            )

            if (
                "PERMANENT HTTP 401" in message
                or "PERMANENT HTTP 403" in message
                or "PERMANENT HTTP 404" in message
            ):
                raise

            remaining = deadline - time.monotonic()

            if remaining <= 0:
                break

            time.sleep(
                min(RETRY_DELAY, remaining)
            )

    raise RuntimeError(
        "Gemini research failed after retries."
    )


# =====================================================
# GROQ REQUEST
# =====================================================

def request_groq(prompt):

    if not GROQ_API_KEY:
        raise RuntimeError("Groq API key missing.")

    url = (
        "https://api.groq.com/openai/v1/"
        "chat/completions"
    )

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are BADSAH's professional "
                    "scriptwriter. Follow the supplied "
                    "research strictly. Return valid JSON only."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.5,
        "max_completion_tokens": 8192
    }

    response = session.post(
        url,
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT
    )

    if response.status_code != 200:

        if response.status_code in (400, 401, 403, 404):
            raise RuntimeError(
                f"PERMANENT HTTP {response.status_code}: "
                f"{response.text[:1000]}"
            )

        raise ConnectionError(
            f"Groq HTTP {response.status_code}: "
            f"{response.text[:700]}"
        )

    data = response.json()

    choices = data.get("choices", [])

    if not choices:
        raise ValueError("Groq returned no choices.")

    choice = choices[0]

    if choice.get("finish_reason") == "length":
        raise ValueError("Groq output was truncated.")

    raw = choice.get(
        "message", {}
    ).get("content", "")

    if not raw:
        raise ValueError("Groq returned empty content.")

    return raw


# =====================================================
# GEMINI SCRIPT WORKER
# =====================================================

def gemini_script_worker(prompt, research):

    deadline = (
        time.monotonic() + PROVIDER_RETRY_SECONDS
    )

    attempt = 0

    print("\n[GEMINI] Script generation started.")

    while time.monotonic() < deadline:

        if winner_event.is_set():
            return None

        attempt += 1

        try:

            raw, _ = request_gemini(
                prompt,
                use_search=False
            )

            story = extract_json(raw)

            clean, words, counts = validate_story(
                story,
                research
            )

            if winner_event.is_set():
                return None

            print(
                f"[GEMINI] Valid script: {words} words."
            )

            return {
                "provider": "GEMINI",
                "model": GEMINI_MODEL,
                "story": clean,
                "word_count": words,
                "scene_counts": counts,
                "attempts": attempt
            }

        except Exception as error:

            print(
                f"[GEMINI] Script attempt {attempt} failed: "
                f"{str(error)[:600]}"
            )

            message = str(error)

            if (
                "PERMANENT HTTP 401" in message
                or "PERMANENT HTTP 403" in message
                or "PERMANENT HTTP 404" in message
            ):
                return None

            remaining = deadline - time.monotonic()

            if remaining <= 0:
                break

            time.sleep(
                min(RETRY_DELAY, remaining)
            )

    return None


# =====================================================
# GROQ SCRIPT WORKER
# =====================================================

def groq_script_worker(prompt, research):

    if not GROQ_API_KEY:
        print("[GROQ] API key missing.")
        return None

    deadline = (
        time.monotonic() + PROVIDER_RETRY_SECONDS
    )

    attempt = 0

    print("\n[GROQ] Script generation started in parallel.")

    while time.monotonic() < deadline:

        if winner_event.is_set():
            return None

        attempt += 1

        try:

            raw = request_groq(prompt)

            story = extract_json(raw)

            clean, words, counts = validate_story(
                story,
                research
            )

            if winner_event.is_set():
                return None

            print(
                f"[GROQ] Valid script: {words} words."
            )

            return {
                "provider": "GROQ",
                "model": GROQ_MODEL,
                "story": clean,
                "word_count": words,
                "scene_counts": counts,
                "attempts": attempt
            }

        except Exception as error:

            message = str(error)

            print(
                f"[GROQ] Attempt {attempt} failed: "
                f"{message[:700]}"
            )

            if (
                "PERMANENT HTTP 401" in message
                or "PERMANENT HTTP 403" in message
                or "PERMANENT HTTP 404" in message
            ):
                return None

            remaining = deadline - time.monotonic()

            if remaining <= 0:
                break

            time.sleep(
                min(RETRY_DELAY, remaining)
            )

    return None


# =====================================================
# SAFE JSON SAVE
# =====================================================

def save_json(path, data):

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=4
        ),
        encoding="utf-8"
    )

    temporary.replace(path)


# =====================================================
# PARALLEL SCRIPT ENGINE
# =====================================================

def generate_parallel_script(research):

    winner_event.clear()

    prompt = build_script_prompt(research)

    workers = {}

    executor = ThreadPoolExecutor(
        max_workers=2,
        thread_name_prefix="BADSAH-SCRIPT"
    )

    winner = None

    try:

        if GEMINI_API_KEY:

            future = executor.submit(
                gemini_script_worker,
                prompt,
                research
            )

            workers[future] = "GEMINI"

        if GROQ_API_KEY:

            future = executor.submit(
                groq_script_worker,
                prompt,
                research
            )

            workers[future] = "GROQ"

        pending = set(workers)

        while pending:

            completed, pending = wait(
                pending,
                return_when=FIRST_COMPLETED
            )

            for future in completed:

                provider = workers[future]

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
                    print("SCRIPT WINNER:", winner["provider"])
                    print("MODEL:", winner["model"])
                    print("=" * 55)

                    break

            if winner:
                break

        if winner is None:

            raise RuntimeError(
                "Both Gemini and Groq failed to produce "
                "a valid script."
            )

    finally:

        winner_event.set()

        for future in workers:

            if not future.done():
                future.cancel()

        executor.shutdown(
            wait=True,
            cancel_futures=True
        )

    return winner


# =====================================================
# MAIN
# =====================================================

def main():

    print("\n" + "=" * 60)
    print("BADSAH SCRIPTURE HIDDEN FACTS ENGINE V9")
    print("GEMINI RESEARCH + PARALLEL GEMINI/GROQ SCRIPT")
    print("=" * 60)

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is required for Google Search research."
        )

    if not GROQ_API_KEY:
        print(
            "[WARNING] GROQ_API_KEY missing. "
            "Only Gemini script generation will run."
        )

    # -------------------------------------------------
    # PHASE 1: RESEARCH
    # -------------------------------------------------

    research = research_worker()

    save_json(
        RESEARCH_FILE,
        research
    )

    print(
        "\nResearch saved:",
        RESEARCH_FILE.name
    )

    # -------------------------------------------------
    # PHASE 2: PARALLEL SCRIPT GENERATION
    # -------------------------------------------------

    winner = generate_parallel_script(
        research
    )

    # -------------------------------------------------
    # PHASE 3: FINAL VALIDATION
    # -------------------------------------------------

    story, word_count, counts = validate_story(
        winner["story"],
        research
    )

    # -------------------------------------------------
    # PHASE 4: SAVE OUTPUT
    # -------------------------------------------------

    save_json(
        OUTPUT_FILE,
        story
    )

    report = {
        "engine": "BADSAH SCRIPTURE ENGINE V9",
        "status": "SUCCESS",
        "research_provider": "GEMINI GOOGLE SEARCH",
        "script_strategy": "PARALLEL",
        "winning_provider": winner["provider"],
        "winning_model": winner["model"],
        "gemini_model": GEMINI_MODEL,
        "groq_model": GROQ_MODEL,
        "topic": research["topic"],
        "title": research["title"],
        "total_scenes": TOTAL_SCENES,
        "total_dialogue_words": word_count,
        "scene_word_counts": counts,
        "grounded_source_count": len(
            research["grounded_sources"]
        ),
        "research_claim_count": len(
            research["claims"]
        ),
        "winning_provider_attempts": winner["attempts"],
        "output_file": OUTPUT_FILE.name,
        "research_file": RESEARCH_FILE.name,
        "verification_note": (
            "Google Search grounding URLs were checked against "
            "claim source URLs. This does not replace manual "
            "verification of the original scripture editions."
        )
    }

    save_json(
        REPORT_FILE,
        report
    )

    # -------------------------------------------------
    # PHASE 5: DISPLAY RESULT
    # -------------------------------------------------

    print("\n" + "=" * 60)
    print("BADSAH SCRIPT GENERATION SUCCESS")
    print("=" * 60)

    print("Topic:", research["topic"])
    print("Winner:", winner["provider"])
    print("Model:", winner["model"])
    print("Scenes:", TOTAL_SCENES)
    print("Dialogue words:", word_count)
    print(
        "Grounded URLs:",
        len(research["grounded_sources"])
    )

    print("\nSCENE DIALOGUES")

    for index, scene in enumerate(story):

        print(
            f"\nScene {index + 1}: "
            f"{counts[index]} words"
        )

        print(scene["dialogue"])

    print("\nFiles saved:")
    print(OUTPUT_FILE.name)
    print(RESEARCH_FILE.name)
    print(REPORT_FILE.name)

    print("\nBADSAH SCRIPT ENGINE COMPLETED.")
    print("=" * 60)


# =====================================================
# ENTRY POINT
# =====================================================

if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print("\nBADSAH ENGINE FAILED:")
        print(str(error))

        raise
