"""
Self-restarting posting loop for ONE kind of post (LOOP_KIND = reel | carousel).

Runs inside one GitHub Actions job for about 5.5 hours: sleeps until each posting
time, posts with post_next.py, saves the posted CSV to the repo, and repeats.
The workflow (reel_loop.yml / carousel_loop.yml) then starts a fresh run of
itself. When the series is finished it writes .loop_done_<kind> so the workflow
stops restarting itself.

Posting times (UTC):
  reels      00:17 06:17 12:17 18:17              (IST 05:47 11:47 17:47 23:47)
  carousels  01:47 05:47 09:47 13:47 17:47 21:47  (IST 07:17 11:17 15:17 19:17 23:17 03:17)

POST_NOW=yes posts once right away when the run starts (only for hand-started runs).
"""

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)

TIMES = {
    "reel": [(0, 17), (6, 17), (12, 17), (18, 17)],
    "carousel": [(1, 47), (5, 47), (9, 47), (13, 47), (17, 47), (21, 47)],
}
CSV = {"reel": "posted.csv", "carousel": "posted_posts.csv"}
BUDGET = 5 * 3600 + 30 * 60  # GitHub stops a job at 6 h; leave room to post and restart
START = time.time()


def next_slot(now, kind):
    slots = []
    for day in (0, 1):
        d = (now + timedelta(days=day)).replace(second=0, microsecond=0)
        slots += [d.replace(hour=h, minute=m) for h, m in TIMES[kind]]
    return min(s for s in slots if s > now)


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=REPO_ROOT, check=check)


def save(csv_name):
    git("add", f"scheduler/{csv_name}", check=False)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT).returncode == 0:
        return
    git("commit", "-m", f"Update {csv_name}")
    for _ in range(5):  # the other loop may push at the same time
        try:
            git("pull", "--rebase")
            git("push")
            return
        except subprocess.CalledProcessError:
            time.sleep(10)
    print(f"Warning: could not push {csv_name}")


def post(kind):
    """Post the next item and save progress. Returns True when the series is finished."""
    git("pull", "--rebase", check=False)  # pick up manual runs / other changes
    result = subprocess.run([sys.executable, "-u", "post_next.py", kind], cwd=HERE,
                            capture_output=True, text=True)
    print(result.stdout, result.stderr, flush=True)
    save(CSV[kind])
    return "Nothing to post" in result.stdout


def main():
    kind = os.environ.get("LOOP_KIND", "")
    if kind not in TIMES:
        sys.exit("Set LOOP_KIND to reel or carousel")
    done_file = os.path.join(HERE, f".loop_done_{kind}")

    finished = False
    if os.environ.get("POST_NOW", "no") == "yes":
        print(f"POST NOW: {kind}", flush=True)
        finished = post(kind)
    while not finished:
        now = datetime.now(timezone.utc)
        slot = next_slot(now, kind)
        wait = (slot - now).total_seconds()
        if time.time() - START + wait > BUDGET:
            print(f"Next {kind} at {slot:%H:%M} UTC is beyond this run; handing over to the next run.")
            return
        print(f"Next: {kind} at {slot:%Y-%m-%d %H:%M} UTC, sleeping {wait / 60:.0f} min", flush=True)
        time.sleep(max(0, wait))
        finished = post(kind)
    print(f"All {kind}s are posted. Stopping the {kind} loop.")
    open(done_file, "w").close()


if __name__ == "__main__":
    main()
