"""
Upload a video (as a Reel) to Instagram using the official Instagram Graph API.

Usage:
    python upload.py path/to/video.mp4 "My caption #hashtag"
    python upload.py https://example.com/video.mp4 "Caption"   # public URL also works

Config is read from a .env file in this folder (or environment variables):
    IG_USER_ID=1784xxxxxxxxxxxx
    IG_ACCESS_TOKEN=EAAG... or IGAA...
"""

import os
import sys
import time

import requests

API_VERSION = os.environ.get("IG_API_VERSION", "v23.0")


def load_env(path=".env"):
    """Tiny .env loader so no extra package is needed."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def graph_host(token):
    # Tokens from "Instagram Login" start with IGAA -> graph.instagram.com
    # Tokens from "Facebook Login" (Page-linked account) start with EAA -> graph.facebook.com
    host = "graph.instagram.com" if token.startswith("IG") else "graph.facebook.com"
    return f"https://{host}/{API_VERSION}"


def check(resp):
    data = resp.json()
    if resp.status_code >= 400 or "error" in data:
        raise RuntimeError(f"API error ({resp.status_code}): {data}")
    return data


def create_container(base, user_id, token, caption, video_url=None, cover_url=None):
    params = {"media_type": "REELS", "caption": caption, "access_token": token}
    if cover_url:
        params["cover_url"] = cover_url
    if video_url:
        params["video_url"] = video_url
    else:
        params["upload_type"] = "resumable"
    data = check(requests.post(f"{base}/{user_id}/media", data=params))
    print(f"Container created: {data['id']}")
    return data["id"]


def upload_local_file(container_id, token, file_path):
    size = os.path.getsize(file_path)
    url = f"https://rupload.facebook.com/ig-api-upload/{API_VERSION}/{container_id}"
    headers = {
        "Authorization": f"OAuth {token}",
        "offset": "0",
        "file_size": str(size),
        "Content-Type": "application/octet-stream",
    }
    print(f"Uploading {file_path} ({size / 1024 / 1024:.1f} MB)...")
    with open(file_path, "rb") as f:
        body = f.read()  # send raw bytes; streaming the file object is rejected
    # The upload server sometimes answers ProcessingFailedError when busy or
    # throttled; retrying the same container after a pause usually works.
    waits = [60, 120, 240, 480]
    for attempt in range(len(waits) + 1):
        resp = requests.post(url, headers=headers, data=body)
        if resp.ok and resp.json().get("success"):
            print(f"Upload response: {resp.json()}")
            return
        print(f"Upload attempt {attempt + 1} failed: {resp.status_code} {resp.text[:200]}")
        if attempt < len(waits):
            print(f"Retrying in {waits[attempt]}s...")
            time.sleep(waits[attempt])
    raise RuntimeError("Video upload failed after all retries")


def wait_until_ready(base, container_id, token, timeout=600):
    start = time.time()
    while time.time() - start < timeout:
        data = check(requests.get(
            f"{base}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
        ))
        status = data.get("status_code")
        print(f"Processing status: {status}")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Video processing failed: {data}")
        time.sleep(20)  # poll slowly: frequent polling hits Meta's app request limit
    raise TimeoutError("Video was not processed in time")


def publish(base, user_id, token, container_id):
    data = check(requests.post(
        f"{base}/{user_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
    ))
    media_id = data["id"]
    info = check(requests.get(
        f"{base}/{media_id}", params={"fields": "permalink", "access_token": token}
    ))
    print(f"Published! Media ID: {media_id}")
    print(f"Link: {info.get('permalink')}")
    return media_id


def main():
    load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    video = sys.argv[1]
    caption = sys.argv[2] if len(sys.argv) > 2 else ""

    user_id = os.environ.get("IG_USER_ID")
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not user_id or not token:
        sys.exit("Set IG_USER_ID and IG_ACCESS_TOKEN in .env")

    base = graph_host(token)
    is_url = video.startswith("http://") or video.startswith("https://")
    if not is_url and not os.path.isfile(video):
        sys.exit(f"File not found: {video}")

    container_id = create_container(base, user_id, token, caption,
                                    video_url=video if is_url else None)
    if not is_url:
        upload_local_file(container_id, token, video)
    wait_until_ready(base, container_id, token)
    publish(base, user_id, token, container_id)


if __name__ == "__main__":
    main()
