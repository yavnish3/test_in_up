"""Make the next topic."""

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
MODELS = [os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview"), "gemini-flash-latest",
          "gemini-flash-lite-latest", "gemini-3.1-flash-lite"]


def _healthy_order(models):
    """Use the watchdog's latest model check (scheduler/model_health.json): models that did not answer go last."""
    try:
        h = json.load(open(os.path.join(SCHED_DIR_FOR_HEALTH, "model_health.json"), encoding="utf-8"))
        if time.time() - h.get("checked", 0) < 12 * 3600:
            down = set(h.get("down", []))
            return [m for m in models if m not in down] + [m for m in models if m in down]
    except (OSError, ValueError):
        pass
    return models


SCHED_DIR_FOR_HEALTH = os.path.join(os.path.dirname(HERE), "scheduler")
MODELS = _healthy_order(MODELS)
EXAMPLES = ["SQL045", "SQL068"]
MAX_PART = 4
SLIDE_TYPES = {"concept", "code", "table", "compare", "mistake", "recap"}

sys.path.insert(0, HERE)


def load_env():
    path = os.path.join(ROOT, "..", ".env")
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


RULES = """
You write Instagram carousel posts for "The 30 sec developers" (@the30secdev), an Indian SQL-teaching page.
Language: friendly desi Hinglish (Roman script), like a dost explaining. Words like
"bole toh", "yaar", "bhai", "simple funda", desi analogies (chai, Swiggy, cricket,
UPI, Aadhaar...). Technical terms stay in English. Accurate SQL only.
Query topics (interview questions / "write a query"): the query is the hero. Show the sample
table, the FULL query on a code slide, then a breakdown slide that explains it clause by clause
(SELECT / FROM / JOIN / ON / WHERE / GROUP BY ...), then the result table.
Accuracy: example tables, query and result must match each other exactly. No speed claims
unless generally true for MySQL and PostgreSQL; prefer correctness reasons (NULL-safe, readable).

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
- "next": the topic of the following post (short, <= 18 chars), a natural next step that is a NEW topic
  (NOT in the covered list below and not this post's topic).
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
    names = ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY_{i}" for i in range(2, 10)]
    keys = [os.environ.get(n, "").strip() for n in names]
    keys += [k.strip() for k in os.environ.get("GEMINI_API_KEYS", "").split(",")]
    keys = list(dict.fromkeys(k for k in keys if k))
    if not keys:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return keys


BACKUPS = [
    ("groq", "https://api.groq.com/openai/v1/chat/completions", ("GROQ_API_KEY",),
     os.environ.get("GROQ_MODELS", "openai/gpt-oss-120b,qwen/qwen3.8-27b")),
    ("github", "https://models.github.ai/inference/chat/completions", ("GH_MODELS_TOKEN", "GITHUB_TOKEN"),
     os.environ.get("GITHUB_MODELS", "openai/gpt-4.1-mini,openai/gpt-4o-mini,meta/Llama-3.3-70B-Instruct")),
    ("openrouter", "https://openrouter.ai/api/v1/chat/completions", ("OPENROUTER_API_KEY",),
     os.environ.get("OPENROUTER_MODELS", "google/gemma-4-31b-it:free,nvidia/nemotron-3-ultra-550b-a55b:free")),
]


def backup_options(name, model):
    """Groq's reasoning models spend the whole default budget thinking and return nothing:
    give them room, keep thinking short, and ask for a JSON object."""
    if name != "groq":
        return {"max_tokens": 12000}
    opts = {"max_completion_tokens": 12000, "response_format": {"type": "json_object"}}
    if "gpt-oss" in model:
        opts["reasoning_effort"] = "low"
    elif "qwen3" in model:
        opts["reasoning_effort"] = "none"
    return opts


def ask_backup(prompt, only=None):
    import requests
    for name, url, key_vars, models in BACKUPS:
        if only and name != only:
            continue
        key = next((os.environ.get(v, "").strip() for v in key_vars if os.environ.get(v, "").strip()), "")
        if not key:
            continue
        for model in [m.strip() for m in models.split(",") if m.strip()]:
            try:
                r = requests.post(url, headers={"Authorization": f"Bearer {key}"},
                                  json={"model": model, "temperature": 0.9, **backup_options(name, model), "messages": [
                                      {"role": "user", "content": prompt + "\n\nAnswer with ONLY the JSON object."}]},
                                  timeout=300)
                if not r.ok:
                    print(f"{name} {model}: {r.status_code} {r.text[:100]}", flush=True)
                    continue
                text = r.json()["choices"][0]["message"]["content"] or ""
                answer = json.loads(text[text.index("{"):text.rindex("}") + 1])
                print(f"{name} {model}: answered", flush=True)
                return answer
            except (requests.RequestException, ValueError, KeyError, IndexError) as e:
                print(f"{name} {model}: failed ({type(e).__name__})", flush=True)
    return None


WRITERS = {1: "gemini", 2: "gemini", 3: "groq", 4: "github", 5: "gemini", 6: "backup"}


def ask_writer(prompt, attempt):
    """Rotate writers across attempts so one model's repeated mistake gets a second opinion."""
    w = WRITERS.get(attempt, "gemini")
    if w != "gemini":
        print(f"  writer for attempt {attempt}: {w}", flush=True)
        answer = ask_backup(prompt, None if w == "backup" else w)
        if answer is not None:
            return answer
        print(f"  {w} unavailable, using Gemini", flush=True)
    return ask_gemini(prompt)


def ask_gemini(prompt):
    import requests
    combos = [(m, k) for k in gemini_keys() for m in MODELS]
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9}}
    for attempt in range(3 * len(combos)):
        model, key = combos[attempt % len(combos)]
        tag = f"{model} (key {gemini_keys().index(key) + 1})"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        t0 = time.time()
        try:
            resp = requests.post(url, headers={"x-goog-api-key": key}, json=body, timeout=120)
        except requests.RequestException as e:
            print(f"{tag}: no answer ({type(e).__name__}), trying again", flush=True)
            continue
        if resp.status_code in (429, 500, 503):
            print(f"{tag}: busy ({resp.status_code}), trying again", flush=True)
            if (attempt + 1) % len(combos) == 0:
                answer = ask_backup(prompt)
                if answer is not None:
                    return answer
                time.sleep(20 * (attempt + 1) // len(combos))
            continue
        resp.raise_for_status()
        print(f"{tag}: answered in {time.time() - t0:.0f}s", flush=True)
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(re.sub(r"^```(json)?|```$", "", text.strip()))
    raise RuntimeError("Gemini did not answer")


INTERVIEW_SLOTS = {1, 3}  # part % 5: 2 of every 5 topics (about 2 a day) are interview query questions


def is_interview(part):
    return part % 5 in INTERVIEW_SLOTS


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
    want = (f'Topic for this post: "{topic}" (it was promised as "Next" in the previous post, '
            f'so keep EXACTLY this topic name).' if topic
            else "Choose the best next topic yourself (not in the covered list).")
    if is_interview(part):
        want += (" This is an INTERVIEW QUERY QUESTION post (module \"Interview Prep\"): one real SQL interview"
                 " problem - the sample table(s), what we must find, the FULL query, a clause-by-clause breakdown"
                 " and the exact result rows.")
    if is_interview(part + 1):
        want += (' "next" MUST be the title of a real SQL INTERVIEW QUERY question (<= 18 chars, e.g. "Duplicate'
                 ' Emails", "Consecutive Logins", "Dept Top Earner"), not covered yet.')
    else:
        want += ' "next" must be a concept topic (not an interview query question).'
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
    text = re.sub(r"\b(partition|group|order)\s+by\b", r"\1by", text.lower())
    for w in re.findall(r"[a-z0-9_]+", text):
        if w in STOP or len(w) < 3:
            continue
        if len(w) > 5 and w.endswith("ing"):
            w = w[:-3]
        elif len(w) > 4 and re.search(r"(xes|ses|ches|shes)$", w):
            w = w[:-2]
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


def similar_topic(topic):
    new = words(topic)
    for t in topics():
        old = words(t["topic"])
        if old and (old <= new or new <= old):
            return t
    return None


def validate(c, pid, part, promised=None):
    if is_interview(part):
        c["interview"] = True
        c["module"] = "Interview Prep"
    if part > 81 and c.get("caption"):
        c["caption"] = re.sub(r"(Part\s*\d+)\s*/\s*81\b", r"\1", c["caption"])
    c["id"], c["part"] = pid, part
    for k in ("module", "topic", "hook", "slides", "caption"):
        if not c.get(k):
            raise ValueError(f"missing {k}")
    if c.get("next") and len(c["next"]) > 22:
        raise ValueError(f'"next" topic "{c["next"]}" is too long; keep it <= 18 chars')
    if c.get("next"):
        dup = similar_topic(c["next"])
        if dup or words(c["next"]) & words(c.get("topic", "")) == words(c["next"]):
            raise ValueError(f'"next" topic "{c["next"]}" is already covered'
                             f'{" (" + dup["id"] + " " + dup["topic"] + ")" if dup else ""}; pick a NEW next topic')
    if len(c["topic"]) > 24:
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
    if promised:
        c["topic"] = promised
        old = similar_topic(promised)
        rv = (old.get("revisit_of") or old["id"]) if old else None
    if rv:
        first = next((t for t in rows if t["id"] == rv), None)
        if not first:
            raise ValueError(f"revisit_of {rv} is not a covered id")
        rv = first.get("revisit_of") or rv
        n = 2 + sum(t.get("revisit_of") == rv for t in rows)
        if n > MAX_PART:
            raise ValueError(f"{rv} already has {n - 1} parts (max {MAX_PART}); pick another topic")
        base = re.sub(r"\s*part\s*\d+\s*$", "", c["topic"], flags=re.I).strip()
        suffix = f" Part {n}"
        while len(base) + len(suffix) > 24 and " " in base:
            base = base.rsplit(" ", 1)[0].rstrip(" -:,")
            if base.lower().endswith((" vs", " aur", " and", " &")):
                base = base.rsplit(" ", 1)[0]
        c["topic"] = base + suffix
    else:
        old = similar_topic(c["topic"])
        if old:
            first = old.get("revisit_of") or old["id"]
            raise ValueError(f'topic "{c["topic"]}" is too close to {old["id"]} "{old["topic"]}". '
                             f"Pick a different topic, or if it needs more detail, "
                             f'set "revisit_of": "{first}" and cover only new material')
    c["revisit_of"] = rv
    return c


def upload(path, public_id, folder, kind):
    import requests
    cloud = os.environ["MEDIA_BASE_URL"].rstrip("/").rsplit("/", 1)[-1]
    key, secret = os.environ["CLOUDINARY_API_KEY"], os.environ["CLOUDINARY_API_SECRET"]
    params = {"public_id": public_id, "asset_folder": folder, "invalidate": "true",
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


def make_post(pid, part, topic):
    from render import render
    feedback = previous = best = None
    for attempt in range(1, 5):
        print(f"{pid}: asking AI (attempt {attempt}) topic={topic or 'auto'}", flush=True)
        raw = None
        try:
            raw = ask_writer(build_prompt(pid, part, topic, feedback, previous), attempt)
            c = validate(raw, pid, part, topic)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            print(f"  bad answer: {e}", flush=True)
            feedback, previous = str(e), raw
            continue
        warn = render(c, OUT)
        if not warn:
            return c
        print(f"  slides too full: {warn}", flush=True)
        feedback, previous, best = warn, c, c
    if best is not None:
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
    if "--preview" not in args and "--no-reel" not in args:
        fix_flagged_carousels()
        retry_missing_reels()
    if need <= 0:
        print(f"Stock is fine: {len(left)} unposted carousels ready.")
        return

    for _ in range(need):
        data = carousels()
        last = max(data)
        part = int(last[3:]) + 1
        pid = f"SQL{part:03d}"
        prev_file = os.path.join(CONTENT, f"{last}.json")
        topic = None
        if os.path.exists(prev_file):
            topic = json.load(open(prev_file, encoding="utf-8")).get("next")

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
        if "--no-reel" not in args:
            make_reel_for(c)


REELS_CSV = os.path.join(SCHED, "sql_reel_posts.csv")


def make_reel_for(c):
    pid = c["id"]
    try:
        sys.path.insert(0, os.path.join(HERE, "reel"))
        from make_reel import make_reel
        video, cover, sc = make_reel(c, OUT)
        upload(video, f"insta/reel/{pid}", "insta/reel", "video")
        upload(cover, f"insta/thumbnails/{pid}", "insta/thumbnails", "image")
        os.makedirs(os.path.join(CONTENT, "reels"), exist_ok=True)
        json.dump(sc, open(os.path.join(CONTENT, "reels", f"{pid}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)  # the watchdog checks the voice against this script
        caption = (sc.get("caption") or c["caption"]).strip()
        with open(REELS_CSV, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([pid, c["module"], c["topic"], c.get("revisit_of") or "",
                                    f"Part {c['part']} | {c['topic']}", caption, ""])
        print(f"{pid}: reel ready", flush=True)
        return True
    except Exception as e:
        print(f"{pid}: reel failed ({type(e).__name__}: {e}); the carousel is still queued", flush=True)
        return False


FIX_QUEUE = os.path.join(SCHED, "fix_queue.json")


def fix_flagged_carousels():
    """Re-render (with the layout auto-fixes) and re-upload carousels the watchdog flagged, if not posted yet."""
    try:
        q = json.load(open(FIX_QUEUE, encoding="utf-8"))
    except (OSError, ValueError):
        return
    from render import render
    with open(os.path.join(SCHED, "posted_posts.csv"), encoding="utf-8") as f:
        posted = {r["id"] for r in csv.DictReader(f)}
    left = []
    for pid in q.get("carousels", []):
        path = os.path.join(CONTENT, f"{pid}.json")
        if pid in posted or not os.path.exists(path):
            continue
        try:
            c = json.load(open(path, encoding="utf-8"))
            warn = render(c, OUT)
            folder = os.path.join(OUT, pid)
            for s in sorted(f for f in os.listdir(folder) if f.endswith(".png")):
                upload(os.path.join(folder, s), f"insta/post/{pid}/{s[:-4]}", f"insta/post/{pid}", "image")
            print(f"{pid}: carousel re-rendered and re-uploaded (watchdog fix){' - ' + warn if warn else ''}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"{pid}: carousel fix failed ({e})", flush=True)
            left.append(pid)
    q["carousels"] = left
    json.dump(q, open(FIX_QUEUE, "w", encoding="utf-8"), indent=1)


FIRST_AUTO, MAX_REEL_TRIES, RETRIES_PER_RUN = 82, 3, 2


def retry_missing_reels():
    with open(REELS_CSV, encoding="utf-8-sig") as f:
        have = {r["id"] for r in csv.DictReader(f)}
    todo = []
    for name in sorted(os.listdir(CONTENT)):
        pid = name[:-5]
        if not (name.endswith(".json") and pid[3:].isdigit() and int(pid[3:]) >= FIRST_AUTO) or pid in have:
            continue
        path = os.path.join(CONTENT, name)
        c = json.load(open(path, encoding="utf-8"))
        if c.get("reel_tries", 1) < MAX_REEL_TRIES:
            todo.append((path, c))
    for path, c in todo[:RETRIES_PER_RUN]:
        print(f"{c['id']}: reel missing, trying again (try {c.get('reel_tries', 1) + 1}/{MAX_REEL_TRIES})", flush=True)
        ok = make_reel_for(c)
        if not ok:
            c["reel_tries"] = c.get("reel_tries", 1) + 1
            with open(path, "w", encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
