"""
Post the next SQL reel or carousel to Instagram.

Media lives on Cloudinary (MEDIA_BASE_URL = https://res.cloudinary.com/<cloud>):
    video/upload/insta/reel/SQLxxx.mp4         reel video
    image/upload/insta/thumbnails/SQLxxx.jpg         reel cover
    image/upload/insta/post/SQLxxx/01.jpg   carousel slides (01.jpg ... 10.jpg)
Uploaded from the Mac with cloud_upload.py.

Captions: reels from sql_reel_posts.csv, carousels from carousels.json.
Progress: posted.csv (reels) and posted_posts.csv (carousels). Posted ids are
never posted again.

Usage:
    python post_next.py reel
    python post_next.py carousel
    python post_next.py reel --dry-run     # show what would be posted
"""

import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

from upload import check, create_container, graph_host, load_env, publish, wait_until_ready

HERE = os.path.dirname(os.path.abspath(__file__))
POSTED = {"reel": "posted.csv", "carousel": "posted_posts.csv"}


# Instagram allows at most 30 hashtags per post. Captions get topped up to 30
# from this pool (relevant tags only; ones already in the caption are skipped).
MAX_TAGS = 30
TAG_POOL = """#sql #learnsql #sqlinhindi #sqltutorial #sqlforbeginners #sqlqueries #sqlserver
#mysql #postgresql #database #databases #dbms #rdbms #dataanalyst #dataanalytics
#dataanalysis #datascience #dataengineering #dataengineer #bigdata #analytics #coding
#programming #codinglife #coder #developer #softwaredeveloper #techhindi #codinginhindi
#learncoding #programminglife #interviewprep #sqlinterview #placement #techjobs
#careerintech #businessintelligence #powerbi #excel #python""".split()


def fill_hashtags(caption):
    have = re.findall(r"#\w+", caption)
    seen = {t.lower() for t in have}
    extra = []
    for tag in TAG_POOL:
        if len(have) + len(extra) >= MAX_TAGS:
            break
        if tag.lower() not in seen:
            extra.append(tag)
            seen.add(tag.lower())
    if not extra:
        return caption
    out = caption.rstrip() + " " + " ".join(extra)
    return out if len(out) <= 2200 else caption  # Instagram caption limit


def load_posted(kind):
    path = os.path.join(HERE, POSTED[kind])
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {row["id"] for row in csv.DictReader(f)}


def mark_posted(kind, post_id, media_id):
    path = os.path.join(HERE, POSTED[kind])
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["id", "media_id", "posted_at"])
        w.writerow([post_id, media_id, datetime.now(timezone.utc).isoformat(timespec="seconds")])


def reachable(url):
    try:
        return requests.head(url, timeout=20).status_code == 200
    except requests.RequestException:
        return False


def reel_queue():
    with open(os.path.join(HERE, "sql_reel_posts.csv"), encoding="utf-8-sig") as f:
        rows = {r["id"].strip(): r for r in csv.DictReader(f)}
    return {pid: f"{r['caption'].strip()}\n\n{(r.get('hashtags') or '').strip()}".strip() for pid, r in rows.items()}


def carousel_queue():
    with open(os.path.join(HERE, "carousels.json"), encoding="utf-8") as f:
        return json.load(f)  # {id: {"caption": ..., "slides": [...]}}


def post_reel(base, user_id, token, media, post_id, caption):
    video_url = f"{media}/video/upload/insta/reel/{post_id}.mp4"
    cover_url = f"{media}/image/upload/insta/thumbnails/{post_id}.jpg"
    if not reachable(video_url):
        raise SystemExit(f"Video not found on Cloudinary: {video_url}")
    if not reachable(cover_url):
        print(f"Warning: no cover at {cover_url}, posting without a custom cover")
        cover_url = None
    container_id = create_container(base, user_id, token, caption,
                                    video_url=video_url, cover_url=cover_url)
    wait_until_ready(base, container_id, token)
    return publish(base, user_id, token, container_id)


def post_carousel(base, user_id, token, media, post_id, item):
    urls = [f"{media}/image/upload/insta/post/{post_id}/{s}" for s in item["slides"]]
    missing = [u for u in urls if not reachable(u)]
    if missing:
        raise SystemExit(f"Slides not found on Cloudinary: {missing[:2]}")
    children = []
    for url in urls:
        data = check(requests.post(f"{base}/{user_id}/media", data={
            "image_url": url, "is_carousel_item": "true", "access_token": token}, timeout=60))
        children.append(data["id"])
    print(f"Created {len(children)} slide containers")
    data = check(requests.post(f"{base}/{user_id}/media", data={
        "media_type": "CAROUSEL", "children": ",".join(children),
        "caption": item["caption"], "access_token": token}, timeout=60))
    wait_until_ready(base, data["id"], token)
    return publish(base, user_id, token, data["id"])


def main():
    load_env(os.path.join(HERE, ".env"))
    args = sys.argv[1:]
    kind = next((a for a in args if a in POSTED), None)
    if not kind:
        sys.exit("Usage: python post_next.py reel|carousel [--dry-run]")
    dry_run = "--dry-run" in args

    queue = reel_queue() if kind == "reel" else carousel_queue()
    posted = load_posted(kind)
    todo = sorted(pid for pid in queue if pid not in posted)
    if not todo:
        print(f"Nothing to post: every {kind} is already posted.")
        return
    post_id = todo[0]
    item = queue[post_id]
    original = item
    item = fill_hashtags(item) if kind == "reel" else {**item, "caption": fill_hashtags(item["caption"])}
    print(f"=== {kind} {post_id} ({len(todo)} left) ===")
    print(item if kind == "reel" else item["caption"])
    if dry_run:
        return

    user_id = os.environ["IG_USER_ID"]
    token = os.environ["IG_ACCESS_TOKEN"]
    media = os.environ["MEDIA_BASE_URL"].rstrip("/")
    base = graph_host(token)

    # Rate limit (#4): wait 15 min and retry (max 3 times so the job stays short).
    # Other errors (e.g. Instagram processing hiccups): retry after 2 min, 3 attempts.
    for attempt in range(1, 4):
        try:
            if kind == "reel":
                media_id = post_reel(base, user_id, token, media, post_id, item)
            else:
                media_id = post_carousel(base, user_id, token, media, post_id, item)
            break
        except RuntimeError as e:
            if attempt == 3:
                raise
            if "hashtag" in str(e).lower() or "caption" in str(e).lower():
                print("Instagram rejected the caption: using the original hashtags")
                item = original
            limited = "request limit" in str(e).lower() or "'code': 4," in str(e)
            wait = 900 if limited else 120
            print(f"{post_id} failed ({e}). Retrying in {wait}s (attempt {attempt + 1}/3)...")
            time.sleep(wait)
    mark_posted(kind, post_id, media_id)
    print(f"Posted {kind} {post_id}")
    delete_from_cloudinary(kind, post_id, item, media)


YT_POSTED_URL = "https://raw.githubusercontent.com/yavnish3/test_y_30sec/main/yt/yt_posted.csv"


def posted_on_both():
    """Reel ids already on Instagram and on YouTube. Empty if YouTube's list can't be read."""
    import io
    try:
        resp = requests.get(YT_POSTED_URL, params={"t": int(time.time())}, timeout=30)
        resp.raise_for_status()
        yt = {r["id"] for r in csv.DictReader(io.StringIO(resp.text))}
    except Exception as e:  # noqa: BLE001
        print(f"Could not read YouTube's posted list ({e}): keeping the video")
        return []
    return sorted(load_posted("reel") & yt)[-100:]  # Cloudinary deletes up to 100 per call


def delete_from_cloudinary(kind, post_id, item, media):
    """After a successful post, remove its files from Cloudinary (needs
    CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET). Never fails the post."""
    key = os.environ.get("CLOUDINARY_API_KEY")
    secret = os.environ.get("CLOUDINARY_API_SECRET")
    if not key or not secret:
        print("Cloudinary keys not set: keeping the files")
        return
    cloud = media.rstrip("/").rsplit("/", 1)[-1]
    if kind == "reel":
        # insta/reel/<id>.mp4 is shared with the YouTube loop (yavnish3/test_y_30sec):
        # delete a video only once it is posted on BOTH Instagram and YouTube.
        groups = {"video": [f"insta/reel/{i}" for i in posted_on_both()], "image": [f"insta/thumbnails/{post_id}"]}
        if not groups["video"]:
            del groups["video"]
    else:
        stems = [os.path.splitext(s)[0] for s in item["slides"]]
        groups = {"image": [f"insta/post/{post_id}/{s}" for s in stems],
                  "raw": [f"insta/post/{post_id}/caption.txt"]}
    for rtype, ids in groups.items():
        try:
            resp = requests.delete(
                f"https://api.cloudinary.com/v1_1/{cloud}/resources/{rtype}/upload",
                params=[("public_ids[]", i) for i in ids], auth=(key, secret), timeout=60)
            resp.raise_for_status()
            gone = [i for i, v in resp.json().get("deleted", {}).items() if v == "deleted"]
            print(f"Deleted from Cloudinary ({rtype}): {len(gone)}/{len(ids)}")
        except requests.RequestException as e:
            print(f"Warning: could not delete {rtype} files from Cloudinary: {e}")
    if kind == "carousel":  # the now-empty folder insta/post/<id> stays otherwise
        try:
            time.sleep(5)
            resp = requests.delete(f"https://api.cloudinary.com/v1_1/{cloud}/folders/insta/post/{post_id}",
                                   auth=(key, secret), timeout=60)
            print(f"Deleted folder insta/post/{post_id}: {resp.status_code} {resp.text[:100]}")
        except requests.RequestException as e:
            print(f"Warning: could not delete folder insta/post/{post_id}: {e}")


if __name__ == "__main__":
    main()
