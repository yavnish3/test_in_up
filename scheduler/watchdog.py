"""Health checks + safe auto-fixes for the posting / generating setup."""

import base64
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GEN = os.path.join(ROOT, "generator")
REPO = os.environ.get("GITHUB_REPOSITORY", "yavnish3/test_in_up")
YT_REPO = "yavnish3/test_y_30sec"
GH = "https://api.github.com"
IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(timezone.utc)
STATE = os.path.join(HERE, "watchdog_state.json")
REPORT = os.path.join(HERE, "watchdog_report.md")
HEALTH = os.path.join(HERE, "model_health.json")
LOOPS = {"generate_loop.yml": "Generate loop", "carousel_loop.yml": "Carousel loop", "reel_loop.yml": "Reel loop"}
TEXT_MODELS = ["gemini-3-flash-preview", "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.1-flash-lite"]
TAG_WORDS = ("excited", "playful", "energetic", "teasing", "confident", "laughs")

problems, fixes, oks = [], [], []


def bad(msg):
    problems.append(msg)
    print("PROBLEM:", msg, flush=True)


def fixed(msg):
    fixes.append(msg)
    print("FIXED:", msg, flush=True)


def ok(msg):
    oks.append(msg)
    print("ok:", msg, flush=True)


def gh_headers():
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    return {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"} if tok else {}


def gh_get(path, repo=REPO, **params):
    r = requests.get(f"{GH}/repos/{repo}/{path}", headers=gh_headers(), params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def media():
    base = os.environ.get("MEDIA_BASE_URL", "").rstrip("/")
    return base, base.rsplit("/", 1)[-1] if base else ""


def cld_auth():
    k, s = os.environ.get("CLOUDINARY_API_KEY"), os.environ.get("CLOUDINARY_API_SECRET")
    return (k, s) if k and s else None


def gemini_keys():
    names = ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY_{i}" for i in range(2, 10)]
    keys = [os.environ.get(n, "").strip() for n in names]
    keys += [k.strip() for k in os.environ.get("GEMINI_API_KEYS", "").split(",")]
    return list(dict.fromkeys(k for k in keys if k))


# ---------------------------------------------------------------- 1. loops alive (+ restart)

def check_loops():
    for wf, name in LOOPS.items():
        try:
            runs = gh_get(f"actions/workflows/{wf}/runs", per_page=10)["workflow_runs"]
        except requests.RequestException as e:
            bad(f"could not read {name} runs ({e})")
            continue
        active = [r for r in runs if r["status"] in ("in_progress", "queued", "waiting", "pending", "requested")]
        if active:
            ok(f"{name} running")
            continue
        last = runs[0] if runs else None
        if last and last["status"] == "completed" and \
                NOW - datetime.fromisoformat(last["updated_at"].replace("Z", "+00:00")) < timedelta(minutes=3):
            ok(f"{name} restarting (run just finished)")
            continue
        r = subprocess.run(["gh", "workflow", "run", wf, "--ref", "main"], capture_output=True, text=True)
        if r.returncode == 0:
            fixed(f"{name} had no active run: started it again")
        else:
            bad(f"{name} is not running and could not be restarted: {r.stderr.strip()[:150]}")
    try:
        runs = requests.get(f"{GH}/repos/{YT_REPO}/actions/runs", params={"per_page": 5}, timeout=30).json()["workflow_runs"]
        if any(r["status"] in ("in_progress", "queued", "waiting", "pending") for r in runs):
            ok("YouTube loop running")
        else:
            tok = os.environ.get("YT_REPO_TOKEN")
            if tok:
                r = requests.post(f"{GH}/repos/{YT_REPO}/actions/workflows/yt_loop.yml/dispatches",
                                  headers={"Authorization": f"Bearer {tok}"}, json={"ref": "main"}, timeout=30)
                (fixed if r.status_code == 204 else bad)(f"YouTube loop was stopped: restart -> {r.status_code}")
            else:
                bad("YouTube loop is NOT running (click Run workflow on yavnish3/test_y_30sec, or add a YT_REPO_TOKEN secret "
                    "so the watchdog can restart it)")
    except (requests.RequestException, KeyError) as e:
        bad(f"could not read YouTube loop runs ({e})")


# ---------------------------------------------------------------- 2. recent workflow failures

def check_failures():
    try:
        runs = gh_get("actions/runs", per_page=30)["workflow_runs"]
    except requests.RequestException as e:
        bad(f"could not read workflow runs ({e})")
        return
    day = [r for r in runs if NOW - datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) < timedelta(hours=24)]
    failed = [r for r in day if r["conclusion"] in ("failure", "timed_out", "startup_failure")]
    if failed:
        bad("failed runs in the last 24 h: " + ", ".join(f"{r['name']} ({r['conclusion']}, {r['created_at'][:16]})"
                                                         for r in failed[:5]))
    else:
        ok("no failed runs in the last 24 h")


# ---------------------------------------------------------------- 3. posting freshness

def last_time(rows, col="posted_at"):
    ts = [datetime.fromisoformat(r[col]) for r in rows if r.get(col)]
    ts = [t if t.tzinfo else t.replace(tzinfo=timezone.utc) for t in ts]
    return max(ts) if ts else None


def check_posting():
    for name, path, limit in (("Reel", "posted.csv", 6.5), ("Carousel", "posted_posts.csv", 5.5)):
        rows = read_csv(os.path.join(HERE, path))
        t = last_time(rows)
        ids = [r["id"] for r in rows]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            bad(f"{name}s posted more than once: {dup}")
        if not t:
            bad(f"no {name.lower()} posted yet")
        elif NOW - t > timedelta(hours=limit):
            bad(f"last {name.lower()} was posted {(NOW - t).total_seconds() / 3600:.1f} h ago (expected every <= {limit - 1} h)")
        else:
            ok(f"last {name.lower()} {(NOW - t).total_seconds() / 3600:.1f} h ago ({len(rows)} posted)")
    try:
        txt = requests.get(f"https://raw.githubusercontent.com/{YT_REPO}/main/yt/yt_posted.csv",
                           params={"t": int(time.time())}, timeout=30).text
        rows = list(csv.DictReader(io.StringIO(txt)))
        t = last_time(rows)
        if t and NOW - t > timedelta(hours=5.5):
            bad(f"last YouTube Short was {(NOW - t).total_seconds() / 3600:.1f} h ago (expected every 4 h)")
        elif t:
            ok(f"last YouTube Short {(NOW - t).total_seconds() / 3600:.1f} h ago ({len(rows)} uploaded)")
        log = requests.get(f"https://raw.githubusercontent.com/{YT_REPO}/main/yt/last_run.log",
                           params={"t": int(time.time())}, timeout=30).text
        m = re.search(r"exit code: (\d+)", log)
        if m and m.group(1) not in ("0", "3"):
            bad(f"last YouTube run failed (exit {m.group(1)}): {log.strip().splitlines()[-1][:150]}")
        if "missing secrets: none" not in log and "missing secrets" in log:
            bad("YouTube loop reports missing secrets: " + re.search(r"missing secrets: (.*)", log).group(1)[:120])
    except (requests.RequestException, AttributeError) as e:
        bad(f"could not read YouTube status ({e})")


# ---------------------------------------------------------------- 4. queues + media on Cloudinary

def head(url):
    try:
        return requests.head(url, timeout=30, allow_redirects=True).ok
    except requests.RequestException:
        return False


def check_queues():
    base, _ = media()
    if not base:
        bad("MEDIA_BASE_URL not set: media checks skipped")
        return
    reels = read_csv(os.path.join(HERE, "sql_reel_posts.csv"))
    posted = {r["id"] for r in read_csv(os.path.join(HERE, "posted.csv"))}
    todo = [r["id"] for r in reels if r["id"] not in posted]
    missing = [p for p in todo[:4] if not head(f"{base}/video/upload/insta/reel/{p}.mp4")]
    if missing:
        bad(f"next reels have no video on Cloudinary: {missing}")
    else:
        ok(f"next reels have videos ({len(todo)} queued)")
    if len(todo) < 3:
        bad(f"only {len(todo)} reels left in the queue")
    car = json.load(open(os.path.join(HERE, "carousels.json"), encoding="utf-8"))
    cposted = {r["id"] for r in read_csv(os.path.join(HERE, "posted_posts.csv"))}
    ctodo = [p for p in sorted(car) if p not in cposted]
    cmiss = [p for p in ctodo[:3]
             if not head(f"{base}/image/upload/insta/post/{p}/{os.path.splitext(car[p]['slides'][0])[0]}.png")
             and not head(f"{base}/image/upload/insta/post/{p}/{car[p]['slides'][0]}")]
    if cmiss:
        bad(f"next carousels have no slides on Cloudinary: {cmiss}")
    else:
        ok(f"next carousels have slides ({len(ctodo)} queued)")
    if len(ctodo) < 3:
        bad(f"only {len(ctodo)} carousels left in the queue")


# ---------------------------------------------------------------- 5. AI model health -> model order for the generator

def check_models():
    keys = gemini_keys()
    if not keys:
        bad("no Gemini key: model check skipped")
        return
    good, down = [], []
    for m in TEXT_MODELS:
        alive = False
        for k in keys[:2]:
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                                  headers={"x-goog-api-key": k}, timeout=40,
                                  json={"contents": [{"parts": [{"text": "Reply: ok"}]}]})
                if r.ok:
                    alive = True
                    break
            except requests.RequestException:
                pass
        (good if alive else down).append(m)
    old = {}
    try:
        old = json.load(open(HEALTH, encoding="utf-8"))
    except (OSError, ValueError):
        pass
    json.dump({"text_order": good + down, "down": down, "checked": int(time.time())},
              open(HEALTH, "w", encoding="utf-8"), indent=1)
    if down:
        msg = f"AI models not answering: {down} -> moved to the end of the list"
        (fixed if set(down) != set(old.get("down", [])) else ok)(msg)
    else:
        ok("all Gemini text models answer")
    if not good:
        bad("NO Gemini text model answers (generator will fall back to Groq / GitHub Models)")
    gk = os.environ.get("GROQ_API_KEY")
    if gk:
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {gk}"},
                              timeout=40, json={"model": "openai/gpt-oss-120b", "max_completion_tokens": 50,
                                                "reasoning_effort": "low", "messages": [{"role": "user", "content": "ok"}]})
            (ok if r.ok else bad)(f"Groq backup {'answers' if r.ok else 'fails: ' + str(r.status_code)}")
        except requests.RequestException as e:
            bad(f"Groq backup unreachable ({e})")


# ---------------------------------------------------------------- 6. Instagram token, Cloudinary usage

def check_accounts():
    uid, tok = os.environ.get("IG_USER_ID"), os.environ.get("IG_ACCESS_TOKEN")
    if uid and tok:
        try:
            r = requests.get(f"https://graph.facebook.com/v23.0/{uid}", params={"fields": "username", "access_token": tok},
                             timeout=30)
            if r.ok:
                ok(f"Instagram token works (@{r.json().get('username')})")
            else:
                bad(f"Instagram token problem: {r.text[:160]}")
        except requests.RequestException as e:
            bad(f"Instagram API unreachable ({e})")
    auth = cld_auth()
    _, cloud = media()
    if auth and cloud:
        try:
            u = requests.get(f"https://api.cloudinary.com/v1_1/{cloud}/usage", auth=auth, timeout=30).json()
            used, lim = u.get("credits", {}).get("usage", 0), u.get("credits", {}).get("limit", 25) or 25
            (bad if used / lim > 0.8 else ok)(f"Cloudinary credits {used}/{lim}")
        except (requests.RequestException, ValueError) as e:
            bad(f"Cloudinary usage unreadable ({e})")


# ---------------------------------------------------------------- 7. QA of new AI posts (+ regenerate bad reels)

def voice_problem(heard, script_words):
    hw = words(heard)
    leak = [t for t in TAG_WORDS if t in hw]
    if leak:
        return f"voice reads audio tags aloud ({leak})"
    if script_words:
        extra = [w for w in hw if w not in script_words and len(w) > 3]
        if hw and len(extra) / len(hw) > 0.25:
            return f"voice says lines that are not in the script ({len(extra)} extra words)"
    if len(hw) < 40:
        return f"voice too short / silent ({len(hw)} words heard)"
    return None


def transcribe(mp3_url, skip=0):
    try:
        audio = requests.get(mp3_url, timeout=120)
        audio.raise_for_status()
    except requests.RequestException:
        return None
    data = base64.b64encode(audio.content).decode()
    combos = [(k, m) for m in ("gemini-3-flash-preview", "gemini-flash-lite-latest", "gemini-3.1-flash-lite")
              for k in gemini_keys()[:2]][skip:]
    for k, m in combos:
        if True:
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                                  headers={"x-goog-api-key": k}, timeout=120, json={"contents": [{"parts": [
                                      {"inline_data": {"mime_type": "audio/mp3", "data": data}},
                                      {"text": "Transcribe EVERY spoken word exactly in Roman script. Output only the transcript."}]}]})
                if r.ok:
                    return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            except (requests.RequestException, KeyError, IndexError):
                pass
    return None


FIXQ = os.path.join(HERE, "fix_queue.json")


def queue_fix(kind, pid):
    try:
        q = json.load(open(FIXQ, encoding="utf-8"))
    except (OSError, ValueError):
        q = {"carousels": [], "reels": []}
    if pid not in q.setdefault(kind, []):
        q[kind].append(pid)
    json.dump(q, open(FIXQ, "w", encoding="utf-8"), indent=1)


def vision_bad(images, what, skip=0):
    """Ask Gemini to look at images; returns {index: reason} for images with broken layout."""
    parts = []
    for k, data in enumerate(images, 1):
        parts += [{"text": f"Image {k}:"}, {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(data).decode()}}]
    parts.append({"text": f"These are {what}. Check ONLY layout defects: text overlapping other text or a sticker/box, "
                          "text cut off at an edge or inside its box, or text going outside the frame. Ignore style, "
                          "colours, emojis and intentional decorations. Answer ONLY JSON: "
                          '{"bad": [{"image": <number>, "why": "<short>"}]} (empty list if all fine).'})
    combos = [(k, m) for m in ("gemini-3-flash-preview", "gemini-flash-lite-latest") for k in gemini_keys()[:2]][skip:]
    for k, m in combos:
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                              headers={"x-goog-api-key": k}, timeout=120,
                              json={"contents": [{"parts": parts}], "generationConfig": {"responseMimeType": "application/json"}})
            if r.ok:
                t = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                return {int(x["image"]): x.get("why", "") for x in json.loads(t).get("bad", []) if str(x.get("image", "")).isdigit()}
        except (requests.RequestException, KeyError, IndexError, ValueError):
            pass
    return None


def fetch(url):
    try:
        r = requests.get(url, timeout=60)
        return r.content if r.ok else None
    except requests.RequestException:
        return None


def settled_times(pid):
    """65% into each beat: the visual is fully on screen and no swipe transition is running."""
    try:
        sc = json.load(open(os.path.join(GEN, "content", "reels", f"{pid}.json"), encoding="utf-8"))
        return [round(a + 0.65 * (z - a), 2) for a, z in sc.get("beat_times", []) if z - a > 1.5]
    except (OSError, ValueError):
        return []


def check_visuals(base, pid, n_slides, reel_len, carousel_posted, reel_posted):
    """Carousel slides + reel frames: layout defects confirmed by two looks -> queue a re-render / rebuild."""
    slides = [fetch(f"{base}/image/upload/w_540,f_jpg/insta/post/{pid}/{k:02d}.png") for k in range(1, n_slides + 1)]
    slides = [s for s in slides if s]
    if len(slides) == n_slides:
        first = vision_bad(slides, "the 10 slides of an Instagram carousel post")
        if first:
            idx = sorted(first)
            again = vision_bad([slides[i - 1] for i in idx if 0 < i <= len(slides)], "Instagram carousel slides", skip=2)
            if again:
                why = "; ".join(f"slide {i}: {first[i]}" for i in idx)
                if carousel_posted:
                    bad(f"{pid}: carousel layout problem ({why}) - already posted")
                else:
                    queue_fix("carousels", pid)
                    fixed(f"{pid}: carousel layout problem ({why}) -> queued for re-render in the next Generate run")
                    return False
            else:
                print(f"{pid}: carousel layout doubt not confirmed - ignored ({first})", flush=True)
    if reel_len and not reel_posted:
        times = settled_times(pid)
        frames = [fetch(f"{base}/video/upload/so_{t},w_540,f_jpg/insta/reel/{pid}.jpg") for t in times]
        frames = [f for f in frames if f]
        if times and len(frames) >= len(times) - 1:
            first = vision_bad(frames, "frames of a vertical Instagram reel (captions at the bottom are expected)")
            if first:
                idx = sorted(first)
                again = vision_bad([frames[i - 1] for i in idx if 0 < i <= len(frames)], "reel frames", skip=2)
                if again:
                    drop_reel_from_queue(pid, "reel frames have overlapping / cut-off text (" +
                                         "; ".join(f"{times[i - 1]}s: {first[i]}" for i in idx if 0 < i <= len(times)) + ")")
                    return False
                print(f"{pid}: reel layout doubt not confirmed - ignored ({first})", flush=True)
    return True


def words(t):
    return re.findall(r"[a-z0-9]+", (t or "").lower())


def drop_reel_from_queue(pid, why):
    """Remove an unposted reel from the queue so the next Generate run rebuilds it (max 3 tries)."""
    path = os.path.join(GEN, "content", f"{pid}.json")
    try:
        c = json.load(open(path, encoding="utf-8"))
    except OSError:
        return bad(f"{pid}: {why} (no content file, cannot rebuild)")
    tries = c.get("reel_tries", 1)
    if tries >= 3:
        return bad(f"{pid}: {why} - already rebuilt {tries} times, leaving it")
    rows = read_csv(os.path.join(HERE, "sql_reel_posts.csv"))
    with open(os.path.join(HERE, "sql_reel_posts.csv"), encoding="utf-8-sig") as f:
        fields = next(csv.reader(f))
    with open(os.path.join(HERE, "sql_reel_posts.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(r for r in rows if r["id"] != pid)
    c["reel_tries"] = tries + 1
    json.dump(c, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    fixed(f"{pid}: {why} -> removed from the reel queue; the next Generate run rebuilds it (try {tries + 1}/3)")


def qa_posts(state):
    base, cloud = media()
    auth = cld_auth()
    if not (base and auth):
        return bad("Cloudinary not configured: post QA skipped")
    content = os.path.join(GEN, "content")
    ids = sorted(f[:-5] for f in os.listdir(content) if re.fullmatch(r"SQL\d{3}\.json", f) and int(f[3:6]) >= 82)
    done = set(state.get("qa_done", []))
    posted = {r["id"] for r in read_csv(os.path.join(HERE, "posted.csv"))}
    queued = {r["id"] for r in read_csv(os.path.join(HERE, "sql_reel_posts.csv"))}
    for pid in [p for p in ids if p not in done][-3:]:
        c = json.load(open(os.path.join(content, f"{pid}.json"), encoding="utf-8"))
        issues = []
        cap = c.get("caption", "")
        if re.search(r"Part\s*\d+\s*/\s*81", cap) and int(pid[3:]) > 81:
            issues.append("caption says /81")
        if len(re.findall(r"#\w+", cap)) > 30:
            issues.append("more than 30 hashtags")
        if c.get("next") and c["next"].strip().lower() == c.get("topic", "").strip().lower():
            issues.append("next topic equals this topic")
        slides_ok = head(f"{base}/image/upload/insta/post/{pid}/01.png") and head(f"{base}/image/upload/insta/post/{pid}/10.png")
        if not slides_ok:
            issues.append("carousel slides missing on Cloudinary")
        if pid not in queued:
            issues.append("reel not in the queue yet (Generate will retry)")
            print(f"{pid}: " + "; ".join(issues), flush=True)
            if [i for i in issues if not i.startswith("reel not in")]:
                bad(f"{pid}: " + "; ".join(issues))
            continue
        try:
            info = requests.get(f"https://api.cloudinary.com/v1_1/{cloud}/resources/video/upload/insta/reel/{pid}",
                                params={"media_metadata": "true"}, auth=auth, timeout=30).json()
        except (requests.RequestException, ValueError):
            info = {}
        dur = info.get("duration") or 0
        reel_bad = None
        if not info.get("public_id"):
            if not head(f"{base}/video/upload/insta/reel/{pid}.mp4"):
                reel_bad = "reel video missing on Cloudinary"
            else:
                issues.append("could not read reel info from Cloudinary")
        elif not dur:
            issues.append("Cloudinary did not report the reel length")
        elif not 20 <= dur <= 95:
            reel_bad = f"reel length {dur:.0f}s"
        elif (info.get("width"), info.get("height")) != (1080, 1920):
            issues.append(f"reel size {info.get('width')}x{info.get('height')}")
        if not reel_bad:
            script_path = os.path.join(content, "reels", f"{pid}.json")
            sw = set()
            if os.path.exists(script_path):
                sc = json.load(open(script_path, encoding="utf-8"))
                sw = set(words(" ".join(b.get("say", "") for b in sc.get("beats", []))))
            url = f"{base}/video/upload/insta/reel/{pid}.mp3"
            heard = transcribe(url)
            if heard:
                first = voice_problem(heard, sw)
                if first:  # transcription can hallucinate: act only if a second, different transcription agrees
                    again = transcribe(url, skip=3)
                    second = voice_problem(again, sw) if again else None
                    if second:
                        reel_bad = first
                    else:
                        print(f"{pid}: '{first}' not confirmed by a second transcription - ignored", flush=True)
            if not cover_ok(base, pid):
                issues.append("reel cover missing")
        cposted = pid in {r["id"] for r in read_csv(os.path.join(HERE, "posted_posts.csv"))}
        if not reel_bad and slides_ok:
            if not check_visuals(base, pid, 10, dur if pid in queued else 0, cposted, pid in posted):
                issues.append("layout problem queued for a fix")
        if reel_bad:
            if pid in posted:
                bad(f"{pid}: {reel_bad} (already posted, cannot fix)")
            else:
                drop_reel_from_queue(pid, reel_bad)
        if issues:
            bad(f"{pid}: " + "; ".join(issues))
        if not reel_bad and not issues:
            ok(f"{pid} QA passed ({c.get('topic')}, reel {dur:.0f}s)")
        if not reel_bad:
            done.add(pid)
    state["qa_done"] = sorted(done)


def cover_ok(base, pid):
    return head(f"{base}/image/upload/insta/thumbnails/{pid}.jpg")


# ---------------------------------------------------------------- 8. topic repeats

def check_topics():
    rows = read_csv(os.path.join(GEN, "topics.csv"))
    names = [r["topic"].strip().lower() for r in rows]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        bad(f"topics repeated: {dup}")
    else:
        ok(f"{len(rows)} topics, no exact repeats")


# ---------------------------------------------------------------- report

def report(state):
    stamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    lines = [f"# Watchdog report - {stamp}", "",
             f"**{len(problems)} problem(s), {len(fixes)} auto-fix(es), {len(oks)} ok**", ""]
    if fixes:
        lines += ["## Auto-fixed"] + [f"- {x}" for x in fixes] + [""]
    if problems:
        lines += ["## Needs attention"] + [f"- {x}" for x in problems] + [""]
    lines += ["## OK"] + [f"- {x}" for x in oks] + [""]
    open(REPORT, "w", encoding="utf-8").write("\n".join(lines))
    state["last_run"] = stamp
    json.dump(state, open(STATE, "w", encoding="utf-8"), indent=1)
    if problems and gh_headers():
        body = "\n".join(lines)
        try:
            issues = requests.get(f"{GH}/repos/{REPO}/issues", headers=gh_headers(),
                                  params={"state": "open", "labels": "watchdog"}, timeout=30).json()
            if isinstance(issues, list) and issues:
                requests.post(f"{GH}/repos/{REPO}/issues/{issues[0]['number']}/comments", headers=gh_headers(),
                              json={"body": body}, timeout=30)
            else:
                requests.post(f"{GH}/repos/{REPO}/issues", headers=gh_headers(), timeout=30,
                              json={"title": "🚨 Watchdog: needs attention", "body": body, "labels": ["watchdog"]})
        except requests.RequestException as e:
            print("could not post the issue:", e)


def save():
    files = ["scheduler/watchdog_report.md", "scheduler/watchdog_state.json", "scheduler/model_health.json",
             "scheduler/fix_queue.json",
             "scheduler/sql_reel_posts.csv", "generator/content"]
    subprocess.run(["git", "add", *files], cwd=ROOT)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        return
    subprocess.run(["git", "commit", "-q", "-m", "Watchdog report"], cwd=ROOT)
    for _ in range(5):
        if subprocess.run(["git", "pull", "-q", "--rebase"], cwd=ROOT).returncode == 0 and \
                subprocess.run(["git", "push", "-q"], cwd=ROOT).returncode == 0:
            return
        time.sleep(10)
    print("could not push the watchdog report")


def main():
    state = load_state()
    for check in (check_loops, check_failures, check_posting, check_queues, check_models, check_accounts,
                  lambda: qa_posts(state), check_topics):
        try:
            check()
        except Exception as e:  # noqa: BLE001 - one broken check must not stop the others
            bad(f"check {getattr(check, '__name__', 'qa')} crashed: {type(e).__name__}: {e}")
    report(state)
    print(f"\n{len(problems)} problems, {len(fixes)} fixes, {len(oks)} ok", flush=True)
    if "--no-save" not in sys.argv:
        save()


if __name__ == "__main__":
    main()
