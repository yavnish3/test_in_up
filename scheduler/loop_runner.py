"""
Plan B for when GitHub's own cron schedule does not fire.

Runs inside one GitHub Actions job for about 5.5 hours: sleeps until each posting
time, posts (reel or carousel), saves the posted CSV to the repo, and repeats.
The workflow (post_loop.yml) then starts a fresh run of itself, so the loop
keeps going without GitHub's scheduler. When both series are finished it
writes .loop_done so the workflow stops restarting itself.

Posting times (UTC):
  reels      00:17 06:17 12:17 18:17              (IST 05:47 11:47 17:47 23:47)
  carousels  01:47 05:47 09:47 13:47 17:47 21:47  (IST 07:17 11:17 15:17 19:17 23:17 03:17)
"""

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
DONE_FILE = os.path.join(HERE, ".loop_done")

REEL_TIMES = [(0, 17), (6, 17), (12, 17), (18, 17)]
CAROUSEL_TIMES = [(1, 47), (5, 47), (9, 47), (13, 47), (17, 47), (21, 47)]
BUDGET = 5 * 3600 + 30 * 60  # GitHub stops a job at 6 h; leave room to post and restart
START = time.time()


def next_slot(now):
    slots = []
    for day in (0, 1):
        d = (now + timedelta(days=day)).replace(second=0, microsecond=0)
        slots += [(d.replace(hour=h, minute=m), "reel") for h, m in REEL_TIMES]
        slots += [(d.replace(hour=h, minute=m), "carousel") for h, m in CAROUSEL_TIMES]
    return min((s for s in slots if s[0] > now), key=lambda s: s[0])


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=REPO_ROOT, check=check)


def save(csv_name):
    git("add", f"scheduler/{csv_name}", check=False)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT).returncode == 0:
        return
    git("commit", "-m", f"Update {csv_name}")
    for _ in range(3):
        try:
            git("pull", "--rebase")
            git("push")
            return
        except subprocess.CalledProcessError:
            time.sleep(10)
    print(f"Warning: could not push {csv_name}")


def post(kind, finished):
    """Post the next reel/carousel and save progress. Returns True when both series are done."""
    git("pull", "--rebase", check=False)  # pick up manual runs / other changes
    result = subprocess.run([sys.executable, "-u", "post_next.py", kind], cwd=HERE,
                            capture_output=True, text=True)
    print(result.stdout, result.stderr, flush=True)
    save("posted.csv" if kind == "reel" else "posted_posts.csv")
    if "Nothing to post" in result.stdout:
        finished[kind] = True
    return all(finished.values())


def main():
    finished = {"reel": False, "carousel": False}
    # Optional: post right away when this run starts (workflow input "post_now").
    # Only the first, hand-started run uses it; the auto-started runs get "none".
    now_kinds = {"reel": ["reel"], "carousel": ["carousel"],
                 "both": ["reel", "carousel"]}.get(os.environ.get("POST_NOW", "none"), [])
    for kind in now_kinds:
        print(f"POST NOW: {kind}", flush=True)
        if post(kind, finished):
            break
    while not all(finished.values()):
        now = datetime.now(timezone.utc)
        slot, kind = next_slot(now)
        if finished[kind]:
            time.sleep(max(0, (slot - now).total_seconds()) + 1)
            continue
        wait = (slot - now).total_seconds()
        if time.time() - START + wait > BUDGET:
            print(f"Next {kind} at {slot:%H:%M} UTC is beyond this run; handing over to the next run.")
            return
        print(f"Next: {kind} at {slot:%Y-%m-%d %H:%M} UTC, sleeping {wait / 60:.0f} min", flush=True)
        time.sleep(max(0, wait))
        post(kind, finished)
    print("Both series are finished. Stopping the loop.")
    open(DONE_FILE, "w").close()

if __name__ == "__main__":
    main()
