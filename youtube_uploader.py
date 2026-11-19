
import os
import sys
import json
import subprocess
from datetime import datetime

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

VIDEO = "badsah_final.mp4"
SCRIPT = "story_output.json"

if not os.path.isfile(VIDEO) or not os.path.isfile(SCRIPT):
    sys.exit("Video or story_output.json missing")

with open(SCRIPT, encoding="utf-8") as f:
    scenes = json.load(f)

if not isinstance(scenes, list):
    sys.exit("Invalid story format")

dialogue = " ".join(
    str(scene.get("dialogue", "")) for scene in scenes
)

# Topic-based metadata
topics = [
    {
        "keys": ["योगः कर्मसु कौशलम्", "2.50", "भगवद गीता", "गीता"],
        "title": "क्या गीता का 'योगः कर्मसु कौशलम्' श्लोक बाद में जोड़ा गया?",
        "tags": ["Bhagavad Gita", "Bhagavad Gita 2.50",
                 "Yogah Karmasu Kaushalam", "Mahabharata",
                 "Krishna", "Sanskrit"]
    },
    {
        "keys": ["रामायण", "राम", "सीता"],
        "title": "रामायण का एक अनसुना रहस्य | VEDIC GURU BADSAH",
        "tags": ["Ramayana", "Lord Rama", "Sita", "Hindu Scriptures"]
    },
    {
        "keys": ["हनुमान", "बजरंगबली"],
        "title": "हनुमान जी से जुड़ा अनसुना रहस्य | VEDIC GURU BADSAH",
        "tags": ["Hanuman", "Hanuman Ji", "Ramayana", "Hindu Scriptures"]
    },
    {
        "keys": ["महाभारत", "अर्जुन", "कृष्ण"],
        "title": "महाभारत का अनसुना रहस्य | VEDIC GURU BADSAH",
        "tags": ["Mahabharata", "Krishna", "Arjuna", "Hindu Scriptures"]
    }
]

matched = next(
    (item for item in topics
     if any(key in dialogue for key in item["keys"])),
    None
)

if matched:
    title = matched["title"]
    topic_tags = matched["tags"]
else:
    first = next(
        (str(s.get("dialogue", "")).strip()
         for s in scenes if s.get("dialogue")),
        "Hindu Scriptures Explained"
    )
    title = first[:85].rstrip(" ।?") + " | VEDIC GURU BADSAH"
    topic_tags = ["Hindu Scriptures", "Indian History",
                  "Vedic Knowledge"]

description = (
    "VEDIC GURU BADSAH presents a source-aware exploration "
    "of Hindu scriptures and traditions.\n\n"
    "इस वीडियो में जानिए:\n"
    + "\n".join(
        "- " + str(s.get("dialogue", "")).strip()
        for s in scenes if s.get("dialogue")
    )
    + "\n\n#Shorts #HinduScriptures #VedicGuruBadsah"
)

tags = list(dict.fromkeys(
    topic_tags + [
        "VEDIC GURU BADSAH",
        "Hindu mythology",
        "Sanatan Dharma",
        "Hindu Knowledge",
        "Shorts"
    ]
))

# Verify video format
probe = subprocess.run(
    [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,width,height",
        "-show_entries", "format=duration",
        "-of", "json", VIDEO
    ],
    capture_output=True, text=True, check=True
)

info = json.loads(probe.stdout)
video_stream = next(
    s for s in info["streams"] if s["codec_type"] == "video"
)

width = int(video_stream["width"])
height = int(video_stream["height"])
duration = float(info["format"]["duration"])

if height <= width or duration > 180:
    sys.exit("Video does not meet Shorts format requirements")

print("Title:", title)
print("Duration:", duration)
print("Format:", width, "x", height)

credentials = Credentials(
    token=None,
    refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
    token_uri="https://oauth2.googleapis.com/token",
    client_id=os.environ["YOUTUBE_CLIENT_ID"],
    client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
    scopes=["https://www.googleapis.com/auth/youtube.upload"]
)

credentials.refresh(Request())

youtube = build(
    "youtube", "v3",
    credentials=credentials,
    cache_discovery=False
)

body = {
    "snippet": {
        "title": title,
        "description": description,
        "tags": tags,
        "categoryId": "27"
    },
    "status": {
        "privacyStatus": "public",
        "selfDeclaredMadeForKids": False
    }
}

request = youtube.videos().insert(
    part="snippet,status",
    body=body,
    media_body=MediaFileUpload(
        VIDEO,
        chunksize=5 * 1024 * 1024,
        resumable=True
    )
)

response = request.execute()

print("PUBLIC YOUTUBE UPLOAD SUCCESSFUL")
print("VIDEO URL: https://www.youtube.com/watch?v=" + response["id"])
