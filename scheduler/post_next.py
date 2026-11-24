"""
Post the next SQL reel or carousel to Instagram.

Media lives in a public Cloudflare R2 bucket (MEDIA_BASE_URL):
    reels/SQLxxx.mp4          reel video
    covers/SQLxxx.jpg         reel cover
    carousels/SQLxxx/01.jpg   carousel slides (01.jpg ... 10.jpg)

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
import sys
import time
from datetime import datetime, timezone

import requests

from upload import check, create_container, graph_host, load_env, publish, wait_until_ready

HERE = os.path.dirname(os.path.abspath(__file__))
POSTED = {"reel": "posted.csv", "carousel": "posted_posts.csv"}


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
    return {pid: f"{r['caption'].strip()}\n\n{r['hashtags'].strip()}" for pid, r in rows.items()}


def carousel_queue():
    with open(os.path.join(HERE, "carousels.json"), encoding="utf-8") as f:
        return json.load(f)  # {id: {"caption": ..., "slides": [...]}}


def post_reel(base, user_id, token, media, post_id, caption):
    video_url = f"{media}/reels/{post_id}.mp4"
    cover_url = f"{media}/covers/{post_id}.jpg"
    if not reachable(video_url):
        raise SystemExit(f"Video not found in R2: {video_url}")
    if not reachable(cover_url):
        print(f"Warning: no cover at {cover_url}, posting without a custom cover")
        cover_url = None
    container_id = create_container(base, user_id, token, caption,
                                    video_url=video_url, cover_url=cover_url)
    wait_until_ready(base, container_id, token)
    return publish(base, user_id, token, container_id)


def post_carousel(base, user_id, token, media, post_id, item):
    urls = [f"{media}/carousels/{post_id}/{s}" for s in item["slides"]]
    missing = [u for u in urls if not reachable(u)]
    if missing:
        raise SystemExit(f"Slides not found in R2: {missing[:2]}")
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
            limited = "request limit" in str(e).lower() or "'code': 4," in str(e)
            wait = 900 if limited else 120
            print(f"{post_id} failed ({e}). Retrying in {wait}s (attempt {attempt + 1}/3)...")
            time.sleep(wait)
    mark_posted(kind, post_id, media_id)
    print(f"Posted {kind} {post_id}")


if __name__ == "__main__":
    main()
