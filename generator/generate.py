"""
Auto-generate the next SQL carousel posts (SQL082, SQL083, ...) and keep a stock
of ready, unposted carousels on Cloudinary.

For each new post:
  1. Gemini picks the topic (the previous post's "next", else a new one) and
     writes the content JSON in the same format as content/SQL001..081.json.
  2. render.py turns it into 10 PNG slides (1080x1080) with post_template.html.
     If text overflows, Gemini is asked to shorten it (up to 3 tries).
  3. Slides + caption.txt go to Cloudinary insta/post/<id>/, and the post is
     added to scheduler/carousels.json so the Carousel loop posts it.

Usage:
    python generator/generate.py            # top up the stock (default 5)
    python generator/generate.py --check    # exit 0 if new posts are needed, else 1
    python generator/generate.py --count 1  # make exactly 1 new post
    python generator/generate.py --preview  # make the next post in generator/out/ only (no upload, no save)

Env: GEMINI_API_KEY (+ optional GEMINI_API_KEY_2 used when the first is busy), MEDIA_BASE_URL (https://res.cloudinary.com/<cloud>),
     CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET, optional GEMINI_MODEL, STOCK.
"""

import csv
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCHED = os.path.join(ROOT, "scheduler")
CONTENT = os.path.join(HERE, "content")
OUT = os.path.join(HERE, "out")
TOPICS = os.path.join(HERE, "topics.csv")
CAROUSELS = os.path.join(SCHED, "carousels.json")
POSTED = os.path.join(SCHED, "posted_posts.csv")
STOCK = int(os.environ.get("STOCK", "5"))
MODELS = [os.environ.get("GEMINI_MODEL", "gemini-flash-latest"), "gemini-flash-lite-latest"]  # 2nd = fallback when busy
EXAMPLES = ["SQL045", "SQL068"]
MAX_PART = 4  # a topic can go up to Part 4 when it needs more detail
SLIDE_TYPES = {"concept", "code", "table", "compare", "mistake", "recap"}

sys.path.insert(0, HERE)


def load_env():
    path = os.path.join(ROOT, "..", ".env")  # local runs: in_up/.env
    if os.path.exists(path):
        for line in open(path):
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def carousels():
    with open(CAROUSELS, encoding="utf-8") as f:
        return json.load(f)


def posted_ids():
    with open(POSTED, encoding="utf-8") as f:
        return {r["id"] for r in csv.DictReader(f)}


def stock_left():
    done = posted_ids()
    return [pid for pid in carousels() if pid not in done]


def topics():
    with open(TOPICS, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------- Gemini ----------

RULES = """
You write Instagram carousel posts for "The 30 sec developers" (@the30secdev), an Indian SQL-teaching page.
Language: friendly desi Hinglish (Roman script), like a dost explaining. Words like
"bole toh", "yaar", "bhai", "simple funda", desi analogies (chai, Swiggy, cricket,
UPI, Aadhaar...). Technical terms stay in English. Accurate SQL only.

Return ONE JSON object with exactly these keys:
  id, part, module, topic, next, hook, cover_sticker, slides, caption, revisit_of
Rules:
- "slides" = EXACTLY 8 slides. Slide 7 has type "mistake", slide 8 has type "recap".
  Slides 1-6 use types: concept, code, table, compare (use at least one code and
  one table or compare). Follow the examples' fields exactly:
    concept: title, sticker, points (2-4), optional note + who
    code:    title, sticker, file (name.sql), code, optional note + who
    table:   title, sticker, columns, rows, optional highlight (row indexes), note, who
    compare: title, left {label, points(3)}, right {label, points(3)}, optional note + who
    mistake: wrong, right, why
    recap:   points (4)
- "who" labels: SIMPLE BHASHA MEIN, BHAI TIP 💡, PRO MOVE, FUN FACT, INTERVIEW TIP, DHYAAN DO.
- Formatting: [[word]] = highlighted words in titles/hook (1 per title),
  **bold** for key words in points/notes. Max 1 emoji per point.
- KEEP IT SHORT so it fits 1080x1080 slides:
  hook <= 45 chars with SHORT words (big cover font) and [[only 1-2 short words]],
  topic <= 22 chars, title <= 28 chars, each point <= 48 chars, note <= 80 chars,
  code <= 9 lines and <= 32 chars per line, table <= 4 columns and <= 4 rows,
  cell <= 12 chars, compare points <= 22 chars, mistake wrong/right <= 70 chars.
- "next": the topic of the following post (short, <= 18 chars), a natural next step.
- "caption": hook line + emoji, blank line, "Is post mein:" + 4-5 "✅ ..." lines,
  blank line, "SQL Series · Part {part}", "Save karo 📌 · Dost ko bhejo 🔁 · Follow karo @the30secdev daily SQL ke liye!",
  blank line, exactly 30 hashtags (Instagram max) starting with #sql: topic-specific ones first,
  then broad ones (#sqlinhindi #learnsql #dataanalyst #datascience #coding ...). No duplicates.
- Prefer a NEW topic. Each covered topic below shows what that post explained.
  You MAY continue a covered topic with another part when it needs more detail
  (something important missing or explained too shallowly in ALL its earlier parts).
  Then set "revisit_of": "<id of the FIRST post of that topic>", name the topic
  "<topic> Part N" (N = next part number, shown below), explain ONLY new material and
  never repeat points from any earlier part. Max Part 4 per topic.
  For a new topic set "revisit_of": null. Go deeper: advanced
  SQL, real interview questions, query optimization, real-world case studies,
  database design, PostgreSQL/MySQL features.
"""


def gemini_keys():
    """All configured Gemini keys; the 2nd is tried when the 1st is busy / over its limit."""
    keys = [os.environ.get(k, "").strip() for k in ("GEMINI_API_KEY", "GEMINI_API_KEY_2")]
    keys = [k for k in keys if k]
    if not keys:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return keys


def ask_gemini(prompt):
    import requests
    combos = [(m, k) for k in gemini_keys() for m in MODELS]  # every model on every key
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9}}
    for attempt in range(3 * len(combos)):
        model, key = combos[attempt % len(combos)]
        tag = f"{model} (key {gemini_keys().index(key) + 1})"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        t0 = time.time()
        try:
            resp = requests.post(url, headers={"x-goog-api-key": key}, json=body, timeout=300)
        except requests.RequestException as e:
            print(f"{tag}: no answer ({type(e).__name__}), trying again", flush=True)
            continue
        if resp.status_code in (429, 500, 503):  # free-tier limit / busy
            print(f"{tag}: busy ({resp.status_code}), trying again", flush=True)
            if (attempt + 1) % len(combos) == 0:  # all busy: wait before the next round
                time.sleep(20 * (attempt + 1) // len(combos))
            continue
        resp.raise_for_status()
        print(f"{tag}: answered in {time.time() - t0:.0f}s", flush=True)
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(re.sub(r"^```(json)?|```$", "", text.strip()))
    raise RuntimeError("Gemini did not answer")


def build_prompt(pid, part, topic, feedback=None, previous=None):
    rows = topics()
    n_parts = {t["id"]: sum(r.get("revisit_of") == t["id"] for r in rows) for t in rows}
    covered = "\n".join(
        f"{t['id']}: {t['topic']} ({t['module']}) - covered: {t.get('description') or '-'}"
        + (f" [part of {t['revisit_of']}]" if t.get("revisit_of") else "")
        + (f" [next part would be Part {2 + n_parts[t['id']]}]"
           if not t.get("revisit_of") and 0 < n_parts[t["id"]] + 1 < MAX_PART else "")
        for t in rows)
    examples = "\n\n".join(open(os.path.join(CONTENT, f"{e}.json"), encoding="utf-8").read()
                           for e in EXAMPLES)
    want = (f'Topic for this post: "{topic}".' if topic
            else "Choose the best next topic yourself (not in the covered list).")
    prompt = (f"{RULES}\nAlready covered topics:\n{covered}\n\nTwo example posts:\n{examples}\n\n"
              f'Now write post id "{pid}", part {part}. {want}')
    if feedback:
        prompt += (f"\n\nYour previous attempt did not fit on the slides: {feedback}\n"
                   f"Shorten those slides (fewer/shorter points, shorter code). Previous attempt:\n"
                   f"{json.dumps(previous, ensure_ascii=False)}")
    return prompt

STOP = {"aur", "and", "vs", "ka", "ki", "ke", "kya", "hai", "hain", "the", "of", "in", "sql", "kaise", "se", "mein",
        "kyun", "chahiye", "hota", "hote", "karo", "kab", "deep", "dive", "basic", "advanced", "intro",
        "database", "table", "tables", "query", "queries", "data"}


def words(text):
    out = set()
    for w in re.findall(r"[a-z0-9_]+", text.lower()):
        if w in STOP or len(w) < 3:
            continue
        if len(w) > 5 and w.endswith("ing"):
            w = w[:-3]                      # indexing -> index
        elif len(w) > 4 and re.search(r"(xes|ses|ches|shes)$", w):
            w = w[:-2]                      # indexes -> index
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]                      # procedures -> procedure
        out.add(w)
    return out


def similar_topic(topic):
    """A covered topic whose key words all appear in the new topic (e.g. INDEX vs Indexes aur B-Tree)."""
    new = words(topic)
    for t in topics():
        old = words(t["topic"])
        if old and (old <= new or new <= old):
            return t
    return None


def validate(c, pid, part):
    c["id"], c["part"] = pid, part
    for k in ("module", "topic", "hook", "slides", "caption"):
        if not c.get(k):
            raise ValueError(f"missing {k}")
    if len(c["topic"]) > 24:  # longer names run under the "Save kar lo" sticker on the cover
        raise ValueError(f'topic "{c["topic"]}" is {len(c["topic"])} chars; keep it <= 22 (short name)')
    if len(re.sub(r"\[\[|\]\]", "", c["hook"])) > 50:
        raise ValueError("hook is too long; keep it <= 45 chars")
    s = c["slides"]
    if len(s) != 8:
        raise ValueError(f"{len(s)} slides, need 8")
    if s[6].get("type") != "mistake" or s[7].get("type") != "recap":
        raise ValueError("slide 7 must be mistake, slide 8 recap")
    bad = [x.get("type") for x in s if x.get("type") not in SLIDE_TYPES]
    if bad:
        raise ValueError(f"unknown slide types {bad}")
    rows = topics()
    rv = c.get("revisit_of") or None
    if rv:
        first = next((t for t in rows if t["id"] == rv), None)
        if not first:
            raise ValueError(f"revisit_of {rv} is not a covered id")
        rv = first.get("revisit_of") or rv  # always point at the first part
        n = 2 + sum(t.get("revisit_of") == rv for t in rows)
        if n > MAX_PART:
            raise ValueError(f"{rv} already has {n - 1} parts (max {MAX_PART}); pick another topic")
        base = re.sub(r"\s*part\s*\d+\s*$", "", c["topic"], flags=re.I).strip()
        c["topic"] = f"{base} Part {n}"
    else:
        old = similar_topic(c["topic"])
        if old:
            first = old.get("revisit_of") or old["id"]
            raise ValueError(f'topic "{c["topic"]}" is too close to {old["id"]} "{old["topic"]}". '
                             f"Pick a different topic, or if it needs more detail, "
                             f'set "revisit_of": "{first}" and cover only new material')
    c["revisit_of"] = rv
    return c


# ---------- Cloudinary ----------

def upload(path, public_id, folder, kind):
    import requests
    cloud = os.environ["MEDIA_BASE_URL"].rstrip("/").rsplit("/", 1)[-1]
    key, secret = os.environ["CLOUDINARY_API_KEY"], os.environ["CLOUDINARY_API_SECRET"]
    params = {"public_id": public_id, "asset_folder": folder,
              "overwrite": "true", "timestamp": str(int(time.time()))}
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params)) + secret
    params.update(api_key=key, signature=hashlib.sha1(to_sign.encode()).hexdigest())
    for attempt in range(3):
        with open(path, "rb") as f:
            resp = requests.post(f"https://api.cloudinary.com/v1_1/{cloud}/{kind}/upload",
                                 data=params, files={"file": f}, timeout=300)
        if resp.ok:
            return
        print(f"  upload failed ({resp.status_code}): {resp.text[:150]}")
        time.sleep(10)
    raise RuntimeError(f"Could not upload {public_id}")


# ---------- main ----------

def make_post(pid, part, topic):
    from render import render  # needs playwright
    feedback = previous = best = None
    for attempt in range(1, 5):
        print(f"{pid}: asking Gemini (attempt {attempt}) topic={topic or 'auto'}", flush=True)
        raw = None
        try:
            raw = ask_gemini(build_prompt(pid, part, topic, feedback, previous))
            c = validate(raw, pid, part)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            print(f"  bad answer: {e}", flush=True)
            feedback, previous = str(e), raw
            continue
        warn = render(c, OUT)
        if not warn:
            return c
        print(f"  slides too full: {warn}", flush=True)
        feedback, previous, best = warn, c, c
    if best is not None:  # valid but a bit full after all tries: use it (template auto-shrinks)
        print("  using the last valid attempt", flush=True)
        render(best, OUT)
        return best
    raise RuntimeError(f"{pid}: Gemini could not produce a valid post")

def main():
    load_env()
    args = sys.argv[1:]
    left = stock_left()
    need = STOCK - len(left)
    if "--count" in args:
        need = int(args[args.index("--count") + 1])
    if "--check" in args:
        print(f"Unposted carousels ready: {len(left)} (stock target {STOCK})")
        sys.exit(0 if need > 0 else 1)
    if "--preview" in args:
        need = 1
    if need <= 0:
        print(f"Stock is fine: {len(left)} unposted carousels ready.")
        return

    for _ in range(need):
        data = carousels()
        last = max(data)  # e.g. SQL081
        part = int(last[3:]) + 1
        pid = f"SQL{part:03d}"
        prev_file = os.path.join(CONTENT, f"{last}.json")
        topic = None
        if os.path.exists(prev_file):
            topic = json.load(open(prev_file, encoding="utf-8")).get("next")
        if topic and similar_topic(topic):
            topic = None

        c = make_post(pid, part, topic)
        if "--preview" in args:
            print(json.dumps(c, ensure_ascii=False, indent=1))
            print(f"Preview only: see {os.path.join(OUT, pid)}")
            return
        folder = os.path.join(OUT, pid)
        slides = sorted(f for f in os.listdir(folder) if f.endswith(".png"))
        for s in slides:
            upload(os.path.join(folder, s), f"insta/post/{pid}/{s[:-4]}", f"insta/post/{pid}", "image")
        upload(os.path.join(folder, "caption.txt"), f"insta/post/{pid}/caption.txt",
               f"insta/post/{pid}", "raw")

        with open(os.path.join(CONTENT, f"{pid}.json"), "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
        with open(TOPICS, "a", newline="", encoding="utf-8") as f:
            recap = next((x.get("points", []) for x in c["slides"] if x.get("type") == "recap"), [])
            desc = ", ".join(re.sub(r"\*\*|\[\[|\]\]", "", p) for p in recap)
            csv.writer(f).writerow([pid, c["module"], c["topic"], desc, c.get("revisit_of") or ""])
        data[pid] = {"caption": c["caption"].strip(), "slides": [s[:-4] + ".jpg" for s in slides]}
        with open(CAROUSELS, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(f"{pid}: ready ({c['topic']}), next: {c.get('next')}", flush=True)


if __name__ == "__main__":
    main()
