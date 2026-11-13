
import os
import re
import json
import time
import base64
import requests

from pathlib import Path
from io import BytesIO
from urllib.parse import quote
from PIL import Image


# =====================================================
# BADSAH IMAGE GENERATOR
# SCRIPTURE HIDDEN FACTS / CONTRASTING FACTS
# =====================================================

BASE_DIR = Path(__file__).resolve().parent

STORY_FILE = BASE_DIR / "story_output.json"
IMAGE_DIR = BASE_DIR / "images"

CLOUDFLARE_WORKER_URL = os.getenv(
    "CLOUDFLARE_WORKER_URL", ""
).strip()

POLLINATIONS_API_KEY = os.getenv(
    "POLLINATIONS_API_KEY", ""
).strip()

POLLINATIONS_URL = "https://gen.pollinations.ai/image/"

POLLINATIONS_MODEL = os.getenv(
    "POLLINATIONS_MODEL",
    "flux"
).strip()

IMAGE_WIDTH = 768
IMAGE_HEIGHT = 1365

EXPECTED_SCENES = 7
MAX_RETRIES = 2
RETRY_DELAY = 3
REQUEST_TIMEOUT = 120

session = requests.Session()

session.headers.update({
    "User-Agent": "BADSAH-Scripture-ImageEngine/1.0"
})


# =====================================================
# LOAD AND VALIDATE STORY
# =====================================================

def load_story():

    if not STORY_FILE.exists():
        raise FileNotFoundError(
            "story_output.json not found. Run main.py first."
        )

    content = STORY_FILE.read_text(
        encoding="utf-8"
    ).strip()

    if content.startswith("```json"):
        content = content[7:]

    elif content.startswith("```"):
        content = content[3:]

    if content.endswith("```"):
        content = content[:-3]

    data = json.loads(content.strip())

    # New main.py format may store scenes directly
    # or inside a dictionary.
    if isinstance(data, dict):
        scenes = data.get("scenes")

        if scenes is None:
            raise ValueError(
                "story_output.json has no 'scenes' array."
            )

    elif isinstance(data, list):
        scenes = data

    else:
        raise ValueError(
            "Invalid story_output.json format."
        )

    if not isinstance(scenes, list):
        raise ValueError("Scenes must be a JSON array.")

    if len(scenes) != EXPECTED_SCENES:
        raise ValueError(
            f"Expected {EXPECTED_SCENES} scenes, "
            f"found {len(scenes)}."
        )

    cleaned = []

    for index, scene in enumerate(scenes, start=1):

        if not isinstance(scene, dict):
            raise ValueError(
                f"Scene {index} is not a JSON object."
            )

        scene_id = scene.get("scene_id", index)

        if not scene.get("image_prompt"):
            raise ValueError(
                f"Scene {scene_id} has no image_prompt."
            )

        scene["scene_id"] = str(scene_id)

        cleaned.append(scene)

    return cleaned


# =====================================================
# BUILD DOCUMENTARY VISUAL PROMPT
# =====================================================

def build_prompt(scene):

    scene_id = scene["scene_id"]

    image_description = str(
        scene.get("image_prompt", "")
    ).strip()

    motion_description = str(
        scene.get("video_motion_prompt", "")
    ).strip()

    topic = str(
        scene.get("topic", "")
    ).strip()

    category = str(
        scene.get("topic_category", "")
    ).strip()

    source_refs = scene.get(
        "source_refs", []
    )

    if isinstance(source_refs, list):
        source_text = ", ".join(
            str(item) for item in source_refs
        )
    else:
        source_text = str(source_refs)

    prompt = f"""
BADSAH — PREMIUM SCRIPTURE KNOWLEDGE DOCUMENTARY.

SCENE:
{scene_id} OF 7.

TOPIC:
{topic}

CATEGORY:
{category}

VISUAL DESCRIPTION:
{image_description}

SCENE ACTION / MOTION CONTEXT:
{motion_description}

RELATED SOURCE REFERENCES:
{source_text}

VISUAL DIRECTION:

Create a premium cinematic documentary-style visual
that directly represents the scene description.

Use suitable visual elements such as:
- Ancient Indian manuscripts and handwritten scriptures.
- Traditional temples and historical architecture.
- Ancient Indian landscapes and locations.
- Maps, symbols, objects and historical settings.
- Traditional paintings and carefully researched visual motifs.
- Cinematic symbolic illustrations when a literal scene
  cannot be reliably represented.

For comparisons between scriptures or traditions,
make the two visual contexts clearly distinguishable.

For a manuscript scene, show realistic ancient paper,
ink, handwritten Sanskrit-style lettering and traditional
manuscript details.

For a temple or historical location, show appropriate
Indian architecture, natural materials and period atmosphere.

For a philosophical or spiritual concept, use respectful,
meaningful symbolic imagery.

ACCURACY RULES:

1. Follow the supplied image description.
2. Do not invent additional historical events.
3. Do not add random gods, sages or mythological characters.
4. Do not depict a specific deity unless the scene asks for it.
5. Do not mix unrelated scripture traditions.
6. Do not create fake readable quotations or verse references.
7. Do not add modern objects to ancient settings.
8. Do not add fictional characters from another story.
9. Do not turn every scene into a temple image.
10. Keep the visual relevant to the narration.

VISUAL QUALITY:

Premium cinematic documentary photography and illustration.
Highly detailed environments and objects.
Natural cinematic lighting.
Rich but realistic Indian cultural atmosphere.
Professional depth and composition.
Careful material and texture details.
Balanced cinematic colour grading.
Clear visual storytelling.
Vertical 9:16 composition.

IMPORTANT:

This is an informative scripture documentary,
not a fictional fantasy story.

No subtitles.
No captions.
No logos.
No watermark.
No borders.
No random text.
No unrelated characters.
"""

    return prompt.strip()


# =====================================================
# VALIDATE AND SAVE IMAGE
# =====================================================

def save_valid_image(image_bytes, output_path):

    if not image_bytes or len(image_bytes) < 1000:
        raise ValueError(
            "Image response is empty or too small."
        )

    try:

        with Image.open(
            BytesIO(image_bytes)
        ) as image:

            image.load()

            if image.width < 256 or image.height < 256:
                raise ValueError(
                    "Image resolution is too small."
                )

            if image.format not in (
                "PNG", "JPEG", "WEBP"
            ):
                raise ValueError(
                    f"Unsupported image format: {image.format}"
                )

            image = image.convert("RGB")

            image.save(
                output_path,
                format="PNG",
                optimize=True
            )

        with Image.open(output_path) as check:
            check.verify()

        if output_path.stat().st_size < 1000:
            raise ValueError(
                "Saved image is too small."
            )

        return True

    except Exception as error:

        output_path.unlink(missing_ok=True)

        raise ValueError(
            f"Image validation failed: {error}"
        )


# =====================================================
# EXTRACT CLOUDFLARE IMAGE
# =====================================================

def extract_cloudflare_image(response):

    content_type = response.headers.get(
        "Content-Type", ""
    ).lower()

    if "application/json" in content_type:

        data = response.json()

        encoded = data.get("image")

        if (
            not encoded
            and isinstance(data.get("data"), list)
            and data["data"]
        ):

            first_item = data["data"][0]

            if isinstance(first_item, dict):
                encoded = first_item.get("b64_json")

        if not encoded:
            raise ValueError(
                "Cloudflare JSON response contains no image."
            )

        if encoded.startswith("data:"):
            encoded = encoded.split(",", 1)[1]

        return base64.b64decode(encoded)

    if "image/" in content_type:
        return response.content

    raise ValueError(
        f"Unexpected Cloudflare content type: {content_type}"
    )


# =====================================================
# PRIMARY: CLOUDFLARE
# =====================================================

def generate_cloudflare(prompt, output_path):

    if not CLOUDFLARE_WORKER_URL:
        print("Cloudflare Worker URL is missing.")
        return False

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            print(
                f"Cloudflare attempt {attempt}/{MAX_RETRIES}"
            )

            response = session.post(
                CLOUDFLARE_WORKER_URL,
                json={
                    "prompt": prompt
                },
                headers={
                    "Content-Type": "application/json"
                },
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()

            image_bytes = extract_cloudflare_image(
                response
            )

            save_valid_image(
                image_bytes,
                output_path
            )

            print("Cloudflare image generated successfully.")
            return True

        except Exception as error:

            print(
                "Cloudflare error:",
                str(error)[:400]
            )

            output_path.unlink(missing_ok=True)

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    return False


# =====================================================
# BACKUP: POLLINATIONS
# =====================================================

def generate_pollinations(prompt, output_path):

    if not POLLINATIONS_API_KEY:
        print("Pollinations API key is missing.")
        return False

    encoded_prompt = quote(
        prompt,
        safe=""
    )

    url = POLLINATIONS_URL + encoded_prompt

    headers = {
        "Authorization": (
            f"Bearer {POLLINATIONS_API_KEY}"
        ),
        "Accept": "image/*"
    }

    params = {
        "model": POLLINATIONS_MODEL,
        "width": IMAGE_WIDTH,
        "height": IMAGE_HEIGHT,
        "nologo": "true"
    }

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            print(
                f"Pollinations attempt {attempt}/{MAX_RETRIES}"
            )

            response = session.get(
                url,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()

            content_type = response.headers.get(
                "Content-Type", ""
            ).lower()

            if "image/" not in content_type:
                raise ValueError(
                    "Pollinations did not return an image: "
                    + response.text[:300]
                )

            save_valid_image(
                response.content,
                output_path
            )

            print("Pollinations image generated successfully.")
            return True

        except Exception as error:

            print(
                "Pollinations error:",
                str(error)[:400]
            )

            output_path.unlink(missing_ok=True)

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    return False


# =====================================================
# GENERATE ONE SCENE IMAGE
# =====================================================

def generate_one_scene(scene, index, total):

    scene_id = scene["scene_id"]

    output_path = (
        IMAGE_DIR / f"scene_{scene_id}.png"
    )

    prompt = build_prompt(scene)

    print("\n" + "=" * 55)
    print(f"BADSAH IMAGE — SCENE {index}/{total}")
    print("=" * 55)

    print("Scene ID:", scene_id)
    print(
        "Image description:",
        str(scene.get("image_prompt", ""))[:500]
    )

    # Primary provider
    success = generate_cloudflare(
        prompt,
        output_path
    )

    if success:
        return "Cloudflare"

    # Backup provider
    print("Cloudflare unavailable. Trying backup...")

    success = generate_pollinations(
        prompt,
        output_path
    )

    if success:
        return "Pollinations"

    raise RuntimeError(
        f"Both image providers failed for scene {scene_id}."
    )


# =====================================================
# MAIN IMAGE ENGINE
# =====================================================

def generate_images():

    print("\n")
    print("=" * 55)
    print("BADSAH SCRIPTURE IMAGE GENERATION ENGINE")
    print("=" * 55)

    IMAGE_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    scenes = load_story()

    print("Total scenes:", len(scenes))
    print(
        "Cloudflare configured:",
        bool(CLOUDFLARE_WORKER_URL)
    )
    print(
        "Pollinations configured:",
        bool(POLLINATIONS_API_KEY)
    )

    results = {
        "Cloudflare": [],
        "Pollinations": [],
        "Failed": []
    }

    # Sequential generation reduces rate-limit pressure.
    for index, scene in enumerate(
        scenes,
        start=1
    ):

        scene_id = scene["scene_id"]

        try:

            provider = generate_one_scene(
                scene,
                index,
                len(scenes)
            )

            results[provider].append(scene_id)

        except Exception as error:

            print(
                f"FAILED scene {scene_id}: {error}"
            )

            results["Failed"].append(scene_id)

    # Final report
    successful = (
        len(results["Cloudflare"])
        + len(results["Pollinations"])
    )

    report = {
        "total_scenes": len(scenes),
        "successful": successful,
        "cloudflare": results["Cloudflare"],
        "pollinations": results["Pollinations"],
        "failed": results["Failed"]
    }

    report_file = (
        BASE_DIR / "image_generation_report.json"
    )

    report_file.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("\n" + "=" * 55)
    print("IMAGE GENERATION REPORT")
    print("=" * 55)

    print("Cloudflare:", len(results["Cloudflare"]))
    print("Pollinations:", len(results["Pollinations"]))
    print("Failed:", len(results["Failed"]))
    print(f"Successful: {successful}/{len(scenes)}")

    if results["Failed"]:
        raise RuntimeError(
            "Image generation incomplete. "
            "See image_generation_report.json."
        )

    print("\nALL SCENE IMAGES GENERATED.")
    print("BADSAH IMAGE ENGINE COMPLETED.")


# =====================================================
# ENTRY POINT
# =====================================================

if __name__ == "__main__":
    generate_images()
