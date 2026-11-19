import os
import sys
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

VIDEO = "badsah_final.mp4"

if not os.path.isfile(VIDEO):
    sys.exit("ERROR: badsah_final.mp4 not found")

client_id = os.environ["YOUTUBE_CLIENT_ID"]
client_secret = os.environ["YOUTUBE_CLIENT_SECRET"]
refresh_token = os.environ["YOUTUBE_REFRESH_TOKEN"]

credentials = Credentials(
    token=None,
    refresh_token=refresh_token,
    token_uri="https://oauth2.googleapis.com/token",
    client_id=client_id,
    client_secret=client_secret,
    scopes=["https://www.googleapis.com/auth/youtube.upload"]
)

credentials.refresh(Request())

youtube = build(
    "youtube", "v3",
    credentials=credentials,
    cache_discovery=False
)

date = datetime.now(timezone.utc).strftime("%d %B %Y")

body = {
    "snippet": {
        "title": f"VEDIC GURU BADSAH | {date} #Shorts",
        "description": (
            "Discover lesser-known stories and details from Hindu scriptures.\n\n"
            "#VedicGuruBadsah #HinduScriptures #Ramayana #Mahabharata #Shorts"
        ),
        "tags": [
            "VEDIC GURU BADSAH",
            "Hindu Scriptures",
            "Ramayana",
            "Mahabharata",
            "Hindu mythology",
            "Shorts"
        ],
        "categoryId": "27"
    },
    "status": {
        "privacyStatus": "private",
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

print("YOUTUBE UPLOAD SUCCESSFUL")
print("VIDEO ID:", response["id"])
print("VIDEO URL: https://www.youtube.com/watch?v=" + response["id"])
