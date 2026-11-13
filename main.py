
import os
import re
import json
import sys
import time
import requests
from pathlib import Path
from urllib.parse import quote

# ============================================================
# BADSAH SCRIPTURE FACT ENGINE V1
# Automatic topic discovery + grounded research + 7 scenes
# Compatible with existing image_generator.py and audio_generator.py
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

STORY_FILE = BASE_DIR / "story_output.json"
SOURCES_FILE = BASE_DIR / "research_sources.json"
REPORT_FILE = BASE_DIR / "fact_generation_report.json"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    + quote(GEMINI_MODEL, safe="")
    + ":generateContent"
)

TIMEOUT = (15, 120)
TOTAL_SCENES = 7

SCENE_TIMINGS = [
    ("00:00", "00:05.5", 5.5),
    ("00:05.5", "00:11", 5.5),
    ("00:11", "00:16.5", 5.5),
    ("00:16.5", "00:22", 5.5),
    ("00:22", "00:27.5", 5.5),
    ("00:27.5", "00:33", 5.5),
    ("00:33", "00:39", 6.0),
]

SCRIPTURE_DOMAINS = [
    "Ramayana",
    "Mahabharata",
    "Bhagavad Gita",
    "Puranas",
    "Radha Krishna traditions",
    "Vedic literature",
    "other relevant Indian scriptures and traditional texts"
]


# ============================================================
# GEMINI REQUEST
# ============================================================

def gemini_request(prompt, use_google_search=False):

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing in GitHub Secrets.")

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.25,
            "maxOutputTokens": 7000
        }
    }

    if use_google_search:
        payload["tools"] = [
            {"google_search": {}}
        ]

    response = requests.post(
        API_URL,
        headers=headers,
        json=payload,
        timeout=TIMEOUT
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Gemini API error {response.status_code}: "
            f"{response.text[:1200]}"
        )

    data = response.json()

    candidates = data.get("candidates", [])

    if not candidates:
        raise RuntimeError("Gemini returned no candidates.")

    candidate = candidates[0]

    if candidate.get("finishReason") == "MAX_TOKENS":
        raise RuntimeError("Gemini response was truncated.")

    parts = candidate.get("content", {}).get("parts", [])

    text = "".join(
        part.get("text", "")
        for part in parts
    ).strip()

    if not text:
        raise RuntimeError("Gemini returned an empty response.")

    grounding = candidate.get(
        "groundingMetadata", {}
    )

    return text, grounding


# ============================================================
# JSON EXTRACTION
# ============================================================

def extract_json(raw_text):

    if not raw_text:
        raise ValueError("Empty AI response.")

    cleaned = raw_text.strip()

    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE
    )

    cleaned = re.sub(r"\s*```$", "", cleaned)

    # Find the first JSON object or array.
    starts = [
        position for position in [
            cleaned.find("{"),
            cleaned.find("[")
        ] if position != -1
    ]

    if not starts:
        raise ValueError("No JSON object or array found.")

    start = min(starts)
    opening = cleaned[start]
    closing = "}" if opening == "{" else "]"

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(cleaned)):

        char = cleaned[index]

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
                return json.loads(cleaned[start:index + 1])

    raise ValueError("Incomplete JSON response.")


# ============================================================
# AUTOMATIC TOPIC + SCRIPTURE RESEARCH
# ============================================================

def research_topic():

    print("\n" + "=" * 60)
    print("BADSAH: AUTOMATIC SCRIPTURE RESEARCH")
    print("=" * 60)

    prompt = """
You are BADSAH's scripture research assistant.

Your task is to independently discover ONE interesting,
lesser-known, accurate and respectful topic from Indian
scriptures and traditional literature.

Choose a topic suitable for a 39-second educational video.

Possible areas:
- Ramayana
- Mahabharata
- Bhagavad Gita
- Puranas
- Radha-Krishna traditions
- Vedic literature
- Important traditional texts and their different versions

RESEARCH RULES:

1. Select the topic yourself. Do not ask the user.
2. Search the web using Google Search.
3. Prefer primary scripture texts, reliable translations,
   established publishers, universities, academic sources
   and reputable reference institutions.
4. Find exact scripture references wherever possible:
   work, book/kanda, chapter/sarga, verse/shloka.
5. Never invent a verse number, quotation or chapter.
6. Clearly distinguish original scripture, later retelling,
   regional tradition, interpretation and popular belief.
7. Do not present a popular belief as an explicit scripture fact.
8. For comparisons, identify the exact texts being compared.
9. If evidence is uncertain, say so.
10. Never create a mystery by inventing missing information.
11. Reject topics whose central claim cannot be supported.
12. Use at least two independent useful web sources where possible.
13. A search result is not proof that a verse exists.
14. Do not fabricate source URLs.

Return ONLY one JSON object in this structure:

{
  "topic": "Selected topic",
  "title": "Short engaging video title",
  "central_question": "Question explored by the video",
  "topic_category": "Hidden fact or contrasting fact",
  "summary": "Short factual summary",
  "claims": [
    {
      "claim_id": "C1",
      "claim": "Specific factual claim",
      "scripture_reference": "Exact reference if found",
      "evidence_type": "primary text, later retelling, tradition, interpretation or popular belief",
      "confidence": "high, medium or low",
      "limitations": "What cannot be established"
    }
  ],
  "important_distinction": "Important distinction between versions or traditions",
  "conclusion": "Careful factual conclusion",
  "source_notes": [
    {
      "work": "Text or source name",
      "reference": "Book, chapter, verse or section if available",
      "url": "Actual source URL if available",
      "source_type": "primary text, translation, academic or reference"
    }
  ],
  "research_warnings": []
}

If you cannot find adequate evidence, return:
{"rejected": true, "reason": "Explain why the topic cannot be supported."}
"""

    raw, grounding = gemini_request(
        prompt,
        use_google_search=True
    )

    research = extract_json(raw)

    if research.get("rejected"):
        raise RuntimeError(
            "Research topic rejected: "
            + str(research.get("reason", "Insufficient evidence"))
        )

    claims = research.get("claims", [])

    if not isinstance(claims, list) or not claims:
        raise RuntimeError("Research contains no factual claims.")

    # Collect actual Google grounding URLs.
    grounding_sources = []

    for chunk in grounding.get("groundingChunks", []):

        web_data = chunk.get("web", {})

        url = web_data.get("uri", "")
        title = web_data.get("title", "")

        if url.startswith("http"):
            grounding_sources.append({
                "title": title,
                "url": url
            })

    # Deduplicate URLs.
    unique_sources = {}
    for source in grounding_sources:
        unique_sources[source["url"]] = source

    grounding_sources = list(unique_sources.values())

    if not grounding_sources:
        raise RuntimeError(
            "Google Search grounding returned no usable source URLs. "
            "Refusing to generate an unsupported video."
        )

    research["grounding_sources"] = grounding_sources

    research["research_status"] = (
        "AI_RESEARCHED_REQUIRES_HUMAN_VERIFICATION"
    )

    research["grounding_source_count"] = len(grounding_sources)

    print("Selected topic:", research.get("topic"))
    print("Claims discovered:", len(claims))
    print("Grounding URLs:", len(grounding_sources))

    return research


# ============================================================
# GENERATE HINGLISH SCRIPT
# ============================================================

def generate_script(research):

    print("\n" + "=" * 60)
    print("BADSAH: GENERATING SEVEN SCENES")
    print("=" * 60)

    research_text = json.dumps(
        research,
        ensure_ascii=False,
        indent=2
    )

    prompt = f"""
You are the chief factual video writer of BADSAH.

Create one premium, cinematic and informative scripture-based
YouTube Short using ONLY the research material below.

RESEARCH:
{research_text}

EDITORIAL RULES:

1. Exactly 7 scenes.
2. Target total narration: approximately 90-110 words.
3. Language: natural, simple Hinglish.
4. Prefer Hindi in Devanagari with commonly used English terms.
5. Make it understandable to ordinary viewers.
6. Balanced cinematic + informative storytelling.
7. Scene 1 must have a powerful factual hook.
8. Explain the actual scripture reference naturally.
9. Clearly identify different versions and traditions.
10. Never exaggerate a claim.
11. Never add a fact absent from the research.
12. Never invent quotations, verses or references.
13. If the research says a detail is uncertain, preserve that uncertainty.
14. Respect all religious traditions.
15. No fictional characters or unrelated fantasy plot.
16. No fixed character bible.
17. Every image prompt must describe a visual relevant to that scene.
18. Use manuscripts, scripture pages, maps, historical settings,
    symbolic illustrations, temples, landscapes and relevant objects.
19. Do not put written text or fake scripture verses inside images.
20. Keep dialogue suitable for spoken narration.

Return ONLY a valid JSON array containing exactly seven objects.

Each object must contain:

{
  "scene_id": 1,
  "start_time": "00:00",
  "end_time": "00:05.5",
  "target_duration_seconds": 5.5,
  "dialogue": "Hinglish narration",
  "image_prompt": "Detailed cinematic visual prompt",
  "video_motion_prompt": "Camera and environmental motion",
  "source_refs": ["C1"]
}

The source_refs field must contain only claim IDs from the research.

Use these exact scene timings:

Scene 1: 00:00 to 00:05.5
Scene 2: 00:05.5 to 00:11
Scene 3: 00:11 to 00:16.5
Scene 4: 00:16.5 to 00:22
Scene 5: 00:22 to 00:27.5
Scene 6: 00:27.5 to 00:33
Scene 7: 00:33 to 00:39

Scene progression:
1. Hook
2. Introduce the event or question
3. First textual evidence
4. Second source or contrasting version
5. Explain the difference
6. What the evidence actually establishes
7. Memorable conclusion

Do not add any new unsupported information.
Return JSON only.
"""

    raw, _ = gemini_request(prompt, use_google_search=False)

    story = extract_json(raw)

    if not isinstance(story, list):
        raise ValueError("Script must be a JSON array.")

    if len(story) != TOTAL_SCENES:
        raise ValueError(
            f"Expected 7 scenes, received {len(story)}."
        )

    valid_claim_ids = {
        str(claim.get("claim_id"))
        for claim in research.get("claims", [])
        if claim.get("claim_id")
    }

    cleaned = []
    all_scene_claims = set()

    for index, scene in enumerate(story):

        if not isinstance(scene, dict):
            raise ValueError(f"Scene {index + 1} is invalid.")

        for field in [
            "dialogue",
            "image_prompt",
            "video_motion_prompt"
        ]:
            if not isinstance(scene.get(field), str):
                raise ValueError(
                    f"Scene {index + 1} is missing {field}."
                )

            if len(scene[field].strip()) < 5:
                raise ValueError(
                    f"Scene {index + 1} has empty {field}."
                )

        dialogue = re.sub(
            r"[*#_~`]",
            "",
            scene["dialogue"]
        ).strip()

        if len(dialogue.split()) < 5:
            raise ValueError(
                f"Scene {index + 1} dialogue is too short."
            )

        refs = scene.get("source_refs", [])

        if not isinstance(refs, list):
            raise ValueError(
                f"Scene {index + 1} has invalid source_refs."
            )

        unknown_refs = set(map(str, refs)) - valid_claim_ids

        if unknown_refs:
            raise ValueError(
                f"Scene {index + 1} uses unknown claims: "
                + ", ".join(unknown_refs)
            )

        all_scene_claims.update(map(str, refs))

        start, end, duration = SCENE_TIMINGS[index]

        cleaned.append({
            "scene_id": index + 1,
            "start_time": start,
            "end_time": end,
            "target_duration_seconds": duration,
            "dialogue": dialogue,
            "image_prompt": scene["image_prompt"].strip(),
            "video_motion_prompt": scene[
                "video_motion_prompt"
            ].strip(),
            "source_refs": list(map(str, refs))
        })

    if not all_scene_claims:
        raise ValueError(
            "No research claims were linked to the scenes."
        )

    return cleaned


# ============================================================
# SAVE JSON SAFELY
# ============================================================

def save_json(path, data):

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    temporary.replace(path)


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.monotonic()

    print("\n")
    print("=" * 60)
    print("BADSAH SCRIPTURE HIDDEN FACTS ENGINE")
    print("Automatic Topic | Google Search | Hinglish | 7 Scenes")
    print("=" * 60)

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Add GEMINI_API_KEY to GitHub Actions Secrets."
        )

    # Phase 1: automatic research
    research = research_topic()

    # Save research separately.
    save_json(SOURCES_FILE, research)

    # Phase 2: script generation
    story = generate_script(research)

    # Save video-ready scene list.
    save_json(STORY_FILE, story)

    elapsed = round(
        time.monotonic() - started,
        2
    )

    report = {
        "engine": "BADSAH Scripture Fact Engine V1",
        "status": "SCRIPT_GENERATED",
        "topic": research.get("topic"),
        "title": research.get("title"),
        "category": research.get("topic_category"),
        "scene_count": len(story),
        "research_status": research.get("research_status"),
        "grounding_source_count": research.get(
            "grounding_source_count", 0
        ),
        "grounding_sources": research.get(
            "grounding_sources", []
        ),
        "research_warnings": research.get(
            "research_warnings", []
        ),
        "human_verification_required": True,
        "generation_time_seconds": elapsed
    }

    save_json(REPORT_FILE, report)

    print("\n" + "=" * 60)
    print("BADSAH SCRIPT GENERATION SUCCESSFUL")
    print("=" * 60)

    print("Topic:", research.get("topic"))
    print("Title:", research.get("title"))
    print("Scenes:", len(story))
    print("Research sources:", report["grounding_source_count"])
    print("Research status:", report["research_status"])
    print("Human verification required: YES")
    print("Generation time:", elapsed, "seconds")

    print("\nSCENE DIALOGUES")

    for scene in story:
        print(
            f"\nScene {scene['scene_id']}: "
            f"{scene['dialogue']}"
        )

    print("\nSaved files:")
    print(STORY_FILE.name)
    print(SOURCES_FILE.name)
    print(REPORT_FILE.name)

    print("\nNEXT:")
    print("Run image_generator.py")
    print("Then run audio_generator.py")
    print("Then run video_generator.py")

    print("=" * 60)


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print("\nBADSAH FACT ENGINE FAILED")
        print("Reason:", error)

        sys.exit(1)
