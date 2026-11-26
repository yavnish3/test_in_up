"""Posting loop."""

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)

TIMES = {
    "carousel": [(1, 47), (5, 47), (9, 47), (13, 47), (17, 47), (21, 47)],
}
EVERY = {"reel": timedelta(hours=5)}
CSV = {"reel": "posted.csv", "carousel": "posted_posts.csv"}
BUDGET = 5 * 3600 + 30 * 60
START = time.time()


def last_posted_at(kind):
    import csv
    with open(os.path.join(HERE, CSV[kind]), encoding="utf-8") as f:
        times = [datetime.fromisoformat(r["posted_at"]) for r in csv.DictReader(f) if r["posted_at"]]
    times = [t if t.tzinfo else t.replace(tzinfo=timezone.utc) for t in times]
    return max(times) if times else None


def next_slot(now, kind):
    if kind in EVERY:
        last = last_posted_at(kind)
        return max(last + EVERY[kind], now) if last else now
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
    for _ in range(5):
        try:
            git("pull", "--rebase")
            git("push")
            return
        except subprocess.CalledProcessError:
            time.sleep(10)
    print(f"Warning: could not push {csv_name}")


def post(kind):
    git("pull", "--rebase", check=False)
    result = subprocess.run([sys.executable, "-u", "post_next.py", kind], cwd=HERE,
                            capture_output=True, text=True)
    print(result.stdout, result.stderr, flush=True)
    save(CSV[kind])
    return "Nothing to post" in result.stdout


def main():
    kind = os.environ.get("LOOP_KIND", "")
    if kind not in TIMES and kind not in EVERY:
        sys.exit("Set LOOP_KIND to reel or carousel")

    if os.environ.get("POST_NOW", "no") == "yes":
        print(f"POST NOW: {kind}", flush=True)
    else:
        git("pull", "--rebase", check=False)
        now = datetime.now(timezone.utc)
        slot = next_slot(now, kind)
        wait = (slot - now).total_seconds()
        if wait > BUDGET:
            print(f"Next {kind} at {slot:%H:%M} UTC is beyond this run; handing over to the next run.")
            time.sleep(BUDGET)
            return
        print(f"Next: {kind} at {slot:%Y-%m-%d %H:%M} UTC, sleeping {wait / 60:.0f} min", flush=True)
        time.sleep(max(0, wait))
    if post(kind):
        print(f"No {kind} ready right now; checking again in 1 hour.", flush=True)
        time.sleep(3600)


if __name__ == "__main__":
    main()
