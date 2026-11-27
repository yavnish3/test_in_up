"""Make a reel."""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.dirname(HERE)
sys.path.insert(0, GEN)

FPS = 30
VOICES = {
    "swara": ("edge", "hi-IN-SwaraNeural", "+30%", "deva"),
    "neerja_expressive": ("edge", "en-IN-NeerjaExpressiveNeural", "+20%", "roman"),
    "neerja": ("edge", "en-IN-NeerjaNeural", "+20%", "roman"),
    "gemini": ("gemini", "Laomedeia", None, "roman"),
}
ENGINE, VOICE, RATE, SCRIPT = VOICES["swara"]


def pick_voice():
    import random
    global ENGINE, VOICE, RATE, SCRIPT
    name = os.environ.get("REEL_VOICE") or "neerja_expressive"
    if name == "random":
        name = random.choice(list(VOICES))
    ENGINE, VOICE, RATE, SCRIPT = VOICES[name]
    print(f"  voice: {name}", flush=True)
    return name
GEMINI_TTS_MODELS = ["gemini-2.5-flash-preview-tts", "gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview",
                     "gemini-3.8-flash-lite-tts"]  # 2.5 first: the expressive voice the user approved
MAX_TEMPO = 1.35
GAP, HOOK_GAP, TAIL = 0.18, 0.1, 0.25
MIN_SECONDS, MAX_SECONDS = 20, 90

STYLE = """
You write the voiceover for a 45-75 second Instagram Reel of "The 30 sec developers" (@the30secdev, SQL in Hinglish).
GOAL: the viewer must actually UNDERSTAND the topic after watching. Teach it like a
good teacher talking to a friend: what it is, why it matters, how to use it (walk through
the example shown on screen), and what the result / output means. Every sentence must
teach something concrete. No filler, no hype, no "save karo / follow karo / comment karo" or
any question for the viewer in the last beat.
STORY: tell ONE mini story with named Indian people (e.g. Rahul, Amit, Priya) and ONE small example
table that you keep using through the whole reel, like a real-world interview trap.
QUIZ: one beat (b2, b3 or b4) asks the viewer to PREDICT the result ("Toh batao, kitni rows aayengi?"),
then says the common wrong answer ("Zyadatar log bolenge 2 rows...") and then "Galat!" and the right
answer with the reason. That beat uses the "quiz" visual.
The SQL must be 100% correct. Accuracy rules:
- A code "output" must be what that query really returns (rows / values, e.g. "Kabir" or
  "name: Kabir | Riya"), or for EXPLAIN the real plan line. Never a made-up timing as the output
  of a normal SELECT.
- No performance claims unless they are generally true for MySQL and PostgreSQL. Prefer
  correctness reasons (e.g. "NOT EXISTS is NULL-safe") over "X is faster than Y".
- Every number, table row and result shown must match each other and the query.
Language: simple, clear Hinglish, the voice is a young FEMALE creator (feminine verbs:
"batati hoon", "samjhati hoon"). Friendly and modern, but at most ONE light word like
"yaar" or "bhai" in the whole beat; no slang like "no cap", "fr", "bestie", "it's giving".

QUERY TOPICS: if the topic is an interview question / a query to write, the query is the hero.
Use this plan: b1 = the sample data ("table") and what we must find; b2 = ONE "query" walkthrough with
the FULL, runnable query (SELECT ... FROM ... ;, or the full CREATE/ALTER/INSERT/UPDATE/DELETE statement for DDL/DML topics like partitioning or indexes; 4-7 lines, one clause per line); its cap EXPLAINS each
clause in order in Hinglish (what it does and why) - do NOT just read the code aloud, e.g.
"Pehle users table lo, phir LEFT JOIN se har user ke orders jodo; jinka order nahi mila unka order id
NULL aata hai, aur WHERE wahi users rakhta hai" - so b2 may use 35-55 words; b3 = how the query runs on the
sample data / the result rows, as the QUIZ beat (predict the output -> common wrong answer -> right answer); b4 = an alternative query ("query", also full) or the
trade-off. Most words go to explaining the query.

Use your OWN fresh example (new table / story / numbers), but the reel MUST TEACH every point in
"must_teach" (taken from the carousel): say each one clearly in the voice AND show it on screen
(a checklist / flow / compare / code / query item). Explain the WHY and the HOW, not only the what:
e.g. for SQL injection show the attacker's input, the query it turns into, and why that returns
every row. A viewer who only watches the reel must understand as much as the carousel reader.
DEFINITION: beat b1 MUST start by defining the topic in one simple line ("<topic> matlab ..." /
"<topic> yaani ..."), and b1's visual MUST be "define" (the term + its meaning).

Pick the visuals that fit THIS topic (any JOIN / anti-join topic MUST include one "venn" beat; aggregates -> bars, transactions / order -> timeline,
queries -> query walkthrough...), and a colour "theme" for the mood of the topic:
"fire" (performance, speed, slow queries), "ocean" (joins, relations), "matrix" (data quality, NULLs,
cleaning), "gold" (transactions, money, banking), "candy" (functions, strings, dates), "neon" (anything else).

Return JSON: {"theme": "...", "beats": [...], "caption": "..."}
beats = exactly 7, in this order, ids: "hook", "b1", "b2", "b3", "b4", "galti", "recap"
  hook:  a question that states the real problem this topic solves (__W_HOOK__ words). No visual needed.
  b1-b4: teach the topic step by step (__W_BEAT__ words each; a "query" walkthrough beat needs 6-8 words
         PER query line, e.g. 5 lines -> 30-40 words); together they explain it fully.
  galti: the common mistake, why it is wrong, and the right way (__W_GALTI__ words)
  recap: 1-2 punchy takeaways and one strong closing line the viewer will remember (__W_RECAP__ words).
         No question, no call to action. Visual: "checklist" or "kinetic".
Each beat (except hook) has:
  "title": short on-screen heading (<= 22 chars, Hinglish, one **bold** word)
  "visual": what the screen shows WHILE this beat is spoken. Every element has "at": one word
      copied exactly from this beat's cap; the element appears when that word is spoken,
      so pick the word where you talk about it. Types (use at least 4 different types overall,
      never the same type twice in a row):
    {"type":"code","file":"x.sql","lines":[{"code":"<= 40 chars","at":"word"}, ... max 7],
       "output":"<= 60 chars result shown after RUN (optional)","output_at":"word"}
    {"type":"query","file":"x.sql","lines":[{"code":"<= 40 chars, one clause","at":"word","explain":"4-7 Hinglish words: what it does + why"}, ... 3-7],
       "output":"real result rows, <= 60 chars","output_at":"word"}   (WALKTHROUGH: full query shown, each clause lit + explained as you say it)
    {"type":"table","columns":["<= 10 chars", ... max 4],"rows":[[...], ... max 4],
       "row_at":["word for row 1", ...],"highlight":[row indexes]}
    {"type":"flow","steps":[{"text":"<= 16 chars","at":"word"}, ... 3-5]}   (how it works, step by step)
    {"type":"stat","value":100000,"prefix":"","suffix":" rows","label":"<= 26 chars","at":"word"}
    {"type":"compare","left":{"label":"<= 12 chars","at":"word","points":[{"text":"<= 20 chars","at":"word"}, ... max 3]},
                      "right":{ same }}
    {"type":"chat","name":"<= 16 chars","messages":[{"side":"l|r","text":"<= 40 chars Gen Z style","at":"word"}, ... max 4]}
    {"type":"checklist","items":[{"text":"<= 30 chars","at":"word"}, ... max 4]}   (best for recap)
    {"type":"venn","left":"users","right":"orders","highlight":"left_only|both|right_only|left|all",
       "label":"<= 26 chars","left_at":"word","right_at":"word","at":"word"}   (JOIN topics: which part is returned)
    {"type":"bars","unit":"k","bars":[{"label":"<= 8 chars","value":90,"at":"word"}, ... 2-5]}   (GROUP BY / SUM / COUNT / AVG)
    {"type":"timeline","events":[{"text":"<= 14 chars","note":"<= 26 chars","at":"word"}, ... 3-5]}   (transactions, execution order, steps in time)
    {"type":"kinetic","lines":[{"text":"<= 12 chars","at":"word"}, ... max 3]}  (big words, use sparingly)
    {"type":"define","term":"<= 24 chars, the topic","meaning":"<= 80 chars, simple ROMAN HINGLISH definition (not English), e.g. Input mein SQL ghusa ke DB ko bewakoof banana","at":"word","meaning_at":"word"}
       (ONLY for b1: the definition card)
    {"type":"quiz","question":"<= 34 chars, e.g. Kitni rows aayengi?","q_at":"word",
       "wrong":"<= 22 chars common wrong answer","wrong_at":"word","right":"<= 22 chars right answer","right_at":"word"}
       (exactly ONE quiz beat among b2-b4; right_at = the word right after "Galat")
__SAYCAP__
  "cues": 3-5 extra effects on exact words (spread across the beat, something new every 2-3 seconds; at least one
     "zoom" or "shake" per beat), each {"word": "<word from this beat's cap>", "do": "...", "target": ...}
     "kinetic" -> big sticker text <target> (<= 14 chars, e.g. "SLOW 🐢", "FULL SCAN", "0.2 ms ⚡")
     "emoji"   -> emoji burst <target>
     "flash"   -> quick white flash (big reveal)
     "zoom"    -> punch-in on visual element number <target> (1 = first element)
     "shake"   -> shake element <target> (wrong / slow / error)
caption: reel caption like the carousel's (hook line + emoji, 3-4 "✅" lines,
"SQL Series · Part N", "Save karo 📌 · Follow karo @the30secdev daily SQL ke liye!", 30 hashtags).
"""


SAYCAP = {
    "deva": """Each beat has:
  "say": what the TTS speaks: Hindi words in Devanagari, English/tech words in Latin
         (e.g. "EXPLAIN लगाओ और plan देखो, no cap!"). SQL keywords stay English.
  "cap": the SAME sentence in Roman Hinglish with EXACTLY the same number of words as "say"
         (word by word, same order). Count carefully.
Total words of all "say" must be 135-155 (about 50-70 seconds of speech).""",
    "roman": """Each beat has:
  "cap": the sentence in natural Roman Hinglish (it is spoken by the voice AND shown as captions),
         e.g. "EXPLAIN lagao aur plan dekho, no cap!". SQL keywords stay English.
  "say": same text as "cap".
Total words of all beats must be __TOTAL__ (about 55-70 seconds of speech).""",
}
WORDS = {"edge": ("10-14", "24-30", "18-24", "14-20", "135-155"),
         "gemini": ("10-14", "22-28", "16-20", "12-16", "130-150")}


def style():
    w = WORDS[ENGINE]
    tone = os.environ.get("REEL_TONE", "").strip()
    base = STYLE
    if tone:
        base = re.sub(r'Friendly and modern, but at most ONE light word like\n"yaar" or "bhai" in the whole beat; no slang like "no cap", "fr", "bestie", "it\'s giving"\.',
                      "Gen Z desi creator energy: use Gen Z phrases (bro, scene kya hai, literally, no cap, full on, "
                      "lowkey, sach mein, ekdum, chill) - at least ONE in every beat and 5+ in the whole reel.", base)
    return (base.replace("__SAYCAP__", SAYCAP[SCRIPT].replace("__TOTAL__", w[4]))
            .replace("__W_HOOK__", w[0]).replace("__W_BEAT__", w[1])
            .replace("__W_GALTI__", w[2]).replace("__W_RECAP__", w[3])
            + (f"\nTONE (overrides the tone rules above, the teaching rules still apply): {tone}\n" if tone else ""))


def targets(s):
    t = s.get("type")
    if t == "concept":
        out = list(s.get("points", [])[:4])
        return out + ([s["note"]] if s.get("note") and len(s.get("points", [])) <= 3 else [])
    if t == "code":
        return [ln for ln in str(s.get("code", "")).split("\n")[:10]]
    if t == "table":
        return [" | ".join(map(str, r)) for r in s.get("rows", [])[:5]] + ([s["note"]] if s.get("note") else [])
    if t == "compare":
        return [s["left"]["label"], s["right"]["label"]]
    if t == "mistake":
        return ["GALAT: " + s.get("wrong", ""), "SAHI: " + s.get("right", ""), s.get("why", "")]
    if t == "recap":
        return list(s.get("points", [])[:4])
    return []


def must_teach(post):
    """The carousel's key points the reel has to cover: recap points + concept slide titles + the mistake."""
    clean = lambda t: re.sub(r"\[\[|\]\]|\*\*", "", str(t)).strip()
    pts = [clean(p) for s in post["slides"] if s.get("type") == "recap" for p in s.get("points", [])]
    pts += [clean(s.get("title")) for s in post["slides"] if s.get("type") in ("concept", "code") and s.get("title")]
    mk = next((s for s in post["slides"] if s.get("type") == "mistake"), None)
    if mk:
        pts.append("Common mistake: " + clean(mk.get("wrong")) + " -> " + clean(mk.get("right")))
    return list(dict.fromkeys(p for p in pts if p))[:10]


KEY_STOP = {"hota", "hoti", "karna", "karo", "jaata", "jaati", "sirf", "kabhi", "hamesha", "zaroor", "pehle",
            "baad", "liye", "wala", "wali", "matlab", "bahut", "query", "table", "using", "always", "never",
            "karta", "karte", "karti", "sakta", "sakte", "rakho", "banta", "nahin", "aapka", "apna", "dekho"}


def missing_points(post, caps):
    """Recap points whose key words never appear in the reel voice."""
    said = set(re.findall(r"[a-z0-9_]+", caps.lower()))
    miss = []
    for s in post["slides"]:
        if s.get("type") != "recap":
            continue
        for p in s.get("points", []):
            keys = {w for w in re.findall(r"[a-z0-9_]+", re.sub(r"\*\*|\[\[|\]\]", "", p).lower())
                    if len(w) >= 5 and w not in KEY_STOP}
            if keys and not keys & said:
                miss.append(re.sub(r"\*\*|\[\[|\]\]", "", p))
    return miss


def ask_script(post, feedback=None, previous=None, attempt=1):
    from generate import ask_writer
    slides = [{"index": i, **s, "targets": targets(s)} for i, s in enumerate(post["slides"][:6])]
    prompt = (style() + "\nThe post (carousel content) this reel is about:\n"
              + json.dumps({"part": post["part"], "topic": post["topic"], "hook": post["hook"],
                            "next": post.get("next"), "must_teach": must_teach(post), "slides": slides,
                            "mistake": {**post["slides"][6], "targets": targets(post["slides"][6])},
                            "recap": {**post["slides"][7], "targets": targets(post["slides"][7])}},
                           ensure_ascii=False))
    if feedback:
        prompt += f"\n\nFix this problem from your last attempt: {feedback}"
    if previous:
        prompt += ("\nYour last attempt (keep everything that was fine, change only what the problem needs):\n"
                   + json.dumps(previous, ensure_ascii=False))
    return ask_writer(prompt, attempt)


VISUALS = {"venn": "left", "bars": "bars", "timeline": "events", "query": "lines", "code": "lines", "table": "columns", "flow": "steps", "stat": "value", "compare": "left",
           "chat": "messages", "checklist": "items", "kinetic": "lines", "quiz": "question", "cliff": "question",
           "define": "meaning"}


AUTO_EMOJI = ["🔥", "⚡", "🤯", "💯", "👀", "🚀"]


def auto_cues(b, i):
    """Keep every beat lively: top up to 3 effects (2 on the hook), spread over the beat, on real words."""
    want = 2 if i == 0 else 3
    words = [w for w in b["cap"].split() if len(re.sub(r"[^A-Za-z0-9]", "", w)) >= 4]
    used = {re.sub(r"[^a-z0-9]", "", str(c.get("word", "")).lower()) for c in b["cues"]}
    kinds = ["zoom", "emoji", "shake"] if i else ["emoji", "zoom"]
    for k, pos in enumerate((0.3, 0.6, 0.85)):
        if len(b["cues"]) >= want or not words:
            break
        w = words[min(len(words) - 1, int(pos * len(words)))]
        key = re.sub(r"[^a-z0-9]", "", w.lower())
        if key in used:
            continue
        do = kinds[k % len(kinds)]
        b["cues"].append({"word": w, "do": do, "target": AUTO_EMOJI[(i + k) % len(AUTO_EMOJI)] if do == "emoji" else 1})
        used.add(key)


def check_script(sc, post):
    beats = sc.get("beats") or []
    if len(beats) != 7:
        raise ValueError(f"need 7 beats, got {len(beats)}")
    for i, b in enumerate(beats):
        b["id"] = ["hook", "b1", "b2", "b3", "b4", "galti", "recap"][i]
        if i > 0:
            v = b.get("visual")
            if not isinstance(v, dict) or v.get("type") not in VISUALS:
                raise ValueError(f"beat {b['id']}: visual.type must be one of {sorted(VISUALS)}")
            need = VISUALS[v["type"]]
            if not v.get(need):
                raise ValueError(f"beat {b['id']}: {v['type']} visual needs '{need}'")
            if v["type"] == "query":
                full = " ".join(str(l.get("code", "")) for l in v["lines"]).upper()
                is_select = "SELECT" in full and "FROM" in full
                is_other = re.search(r"\b(CREATE|ALTER|INSERT|UPDATE|DELETE|MERGE|DROP|TRUNCATE|GRANT|EXPLAIN|BEGIN|START TRANSACTION)\b", full)
                if len(v["lines"]) < 3 or not (is_select or is_other):
                    raise ValueError(f"beat {b['id']}: a query visual must hold the FULL statement, 3-7 lines "
                                     f"(SELECT ... FROM ..., or CREATE/ALTER/INSERT/UPDATE/DELETE ... for DDL/DML topics)")
                if not all(len(str(l.get("explain", "")).split()) >= 4 for l in v["lines"]):
                    raise ValueError(f"beat {b['id']}: every query line needs an 'explain' of 4-7 Hinglish words "
                                     f"saying what the clause does and why (e.g. 'Har user rakho, order ho ya na ho')")
                code_words = set(re.findall(r"[a-z_]+", full.lower()))
                said = re.findall(r"[a-z_]+", str(b.get("cap", "")).lower())
                need = max(28, 6 * len(v["lines"]))
                reads_code = said and sum(w in code_words for w in said) / len(said) > 0.5
                if reads_code or len(str(b.get("cap", "")).split()) < need:
                    lead = ["Pehle,", "Phir,", "Uske baad,", "Phir,", "Uske baad,", "Phir,", "Aur"]
                    parts = []
                    for k, l in enumerate(v["lines"]):
                        intro = "Aakhir mein," if k == len(v["lines"]) - 1 and k > 0 else lead[min(k, len(lead) - 1)]
                        ex = str(l["explain"]).strip().rstrip(".")
                        first = re.sub(r"[^a-z ]", "", ex.lower()).split()[:2]
                        if first and (first[0] in ("pehle", "phir", "aakhir", "aur") or first == ["uske", "baad"]):
                            ex = re.sub(r"^\W*(pehle|phir|aakhir mein|aur|uske baad)\W*", "", ex, flags=re.I)
                        if len(ex) > 1 and ex[0].isupper() and ex[1].islower():
                            ex = ex[0].lower() + ex[1:]
                        sentence = f"{intro} {ex}."
                        l["at"] = sentence.split()[0]
                        parts.append(sentence)
                    b["cap"] = b["say"] = " ".join(parts)
                    print(f"  {b['id']}: voice now explains each query line ({len(b['cap'].split())} words)", flush=True)
            if v["type"] in ("code", "query") and any(len(str(l.get("code", ""))) > 44 for l in v["lines"]):
                raise ValueError(f"beat {b['id']}: code lines must be <= 40 chars (split long clauses over two lines)")
            if v["type"] == "table" and (len(v["columns"]) > 4 or len(v.get("rows", [])) > 5):
                raise ValueError(f"beat {b['id']}: table max 4 columns, 4 rows")
            if len(str(b.get("title", ""))) > 30:
                raise ValueError(f"beat {b['id']}: title must be <= 22 chars")
            if i > 1 and v["type"] != "query" and v["type"] == beats[i - 1].get("visual", {}).get("type"):
                raise ValueError(f"beat {b['id']}: don't use the same visual type twice in a row")
        if SCRIPT == "roman":
            b["say"] = b.get("cap") or b.get("say")
        if not b.get("say") or not b.get("cap"):
            raise ValueError(f"beat {i + 1}: say/cap missing")
        capw = {re.sub(r"[^a-z0-9]", "", w.lower()) for w in b["cap"].split()}
        b["cues"] = [c for c in (b.get("cues") or []) if isinstance(c, dict)
                     and re.sub(r"[^a-z0-9]", "", str(c.get("word", "")).lower()) in capw
                     and c.get("do") in ("pop", "highlight", "zoom", "shake", "kinetic", "emoji", "flash")]
        auto_cues(b, i)
        if SCRIPT == "deva" and not re.search(r"[\u0900-\u097F]", b["say"]):
            raise ValueError(f'beat {i + 1}: "say" must have Hindi words in Devanagari')
    if beats[1].get("visual", {}).get("type") != "define" or not re.search(
            r"\b(matlab|yaani|yani|means|kehte|definition|ka matlab)\b", beats[1]["cap"].lower()):
        raise ValueError('b1 must define the topic first ("<topic> matlab ...") with the "define" visual (term + meaning)')
    miss = missing_points(post, " ".join(b["cap"] for b in beats))
    if len(miss) > 1:
        raise ValueError(f"the reel must teach the carousel's key points; these are missing from the voice: {miss}")
    kinds = [b.get("visual", {}).get("type") for b in beats[1:]]
    if kinds[:4].count("quiz") != 1 or "quiz" in kinds[:1]:
        raise ValueError('exactly ONE of b2, b3, b4 must use the "quiz" visual (predict -> wrong answer -> right answer)')
    if "cliff" in kinds:
        raise ValueError('do not use the "cliff" visual; the recap ends with takeaways (checklist / kinetic)')
    q = next(b["visual"] for b in beats if b.get("visual", {}).get("type") == "quiz")
    if not (q.get("wrong") and q.get("right")) or len(str(q["wrong"])) > 26 or len(str(q["right"])) > 26:
        raise ValueError("quiz visual needs short 'wrong' and 'right' answers (<= 22 chars each)")
    if os.environ.get("REEL_TONE", "").strip():
        slang = r"\b(bro|scene|literally|no cap|full on|lowkey|sach mein|ekdum|chill|bhai|yaar)\b"
        n = len(re.findall(slang, " ".join(b["cap"] for b in beats).lower()))
        if n < 5:
            raise ValueError(f"Gen Z tone: only {n} Gen Z phrases; use at least one per beat (bro, scene kya hai, "
                             f"literally, no cap, full on, lowkey, ekdum...) and 5+ in total")
    if re.search(r"\b(comment|next reel|agli reel)\b", beats[-1]["cap"].lower()):
        raise ValueError("the recap beat must not ask for comments or promise a next reel")
    return sc


async def tts_beat(text, path, rate=RATE):
    import edge_tts
    comm = edge_tts.Communicate(text, VOICE, rate=rate, boundary="WordBoundary")
    words = []
    with open(path, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append({"w": ch["text"], "t": ch["offset"] / 1e7, "d": ch["duration"] / 1e7})
    return words


def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", path])
    return float(out.strip())


TTS_LOCK = []


def gemini_tts(text, wav, trim=True):
    import base64
    import time
    import wave
    import requests
    from generate import gemini_keys
    combos = TTS_LOCK[:1] or [(m, k) for k in gemini_keys() for m in GEMINI_TTS_MODELS]
    voice = os.environ.get("REEL_GEMINI_VOICE", "").strip() or VOICE
    body = {"contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    for attempt in range(5 * len(combos)):
        model, key = combos[attempt % len(combos)]
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              headers={"x-goog-api-key": key}, json=body, timeout=180)
        except requests.RequestException:
            continue
        if r.status_code in (429, 500, 503):
            print(f"  {model} (key {gemini_keys().index(key) + 1}): busy ({r.status_code})", flush=True)
            if (attempt + 1) % len(combos) == 0:
                time.sleep(30 * (attempt + 1) // len(combos))
            continue
        r.raise_for_status()
        if not TTS_LOCK:
            TTS_LOCK.append((model, key))
        pcm = base64.b64decode(r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
        raw = wav + ".raw.wav"
        with wave.open(raw, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(pcm)
        if trim:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-af", TRIM, wav], check=True)
            os.remove(raw)
        else:
            os.replace(raw, wav)
        return duration(wav)
    raise RuntimeError("Gemini TTS did not answer")


TRIM = ("silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
        "silenceremove=start_periods=1:start_threshold=-45dB,areverse")


TAGS = {"hook": "[excited]", "b1": "[excited]", "b2": "[energetic]", "b3": "[energetic]", "b4": "[playful]",
        "galti": "[teasing]", "recap": "[confident]"}


def tagged(b):
    """Gemini TTS audio tags for an energetic Gen Z delivery (not spoken, not shown in captions)."""
    say = re.sub(r"\b(Galat|galat)\b", r"[laughs] \1", b["say"], count=1)
    return f"{TAGS.get(b.get('id'), '[energetic]')} {say}"


def gemini_tts_once(texts, wd):
    """One TTS request for the whole script (one consistent voice), then cut it into beats at the
    pause nearest to where each beat should end (by word count)."""
    full = os.path.join(wd, "voice", "full.wav")
    gemini_tts("\n\n".join(texts), full, trim=False)
    out = subprocess.run(["ffmpeg", "-i", full, "-af", "silencedetect=noise=-38dB:d=0.12", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    total = duration(full)
    mids = [((st + e) / 2, e - st) for st, e in zip(starts, ends) if st > 0.3 and e < total - 0.3]
    words = [len(re.sub(r"\[[^]]*\]", "", t).split()) for t in texts]
    cum, cuts, last = 0, [], 0.0
    for i in range(len(texts) - 1):
        cum += words[i]
        want = total * cum / sum(words)
        win = 0.35 * total * words[i] / sum(words) + 0.6
        near = [(abs(m - want) - 0.4 * d, m) for m, d in mids if m > last + 0.4 and abs(m - want) <= win]
        if not near:
            return None
        last = min(near)[1]
        cuts.append(last)
    bounds = [0.0] + cuts + [total]
    lens = []
    for i in range(len(texts)):
        wav = os.path.join(wd, "voice", f"beat_{i}.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", full, "-ss", f"{bounds[i]:.3f}",
                        "-to", f"{bounds[i + 1]:.3f}", "-af", TRIM, wav], check=True)
        lens.append(duration(wav))
    return lens


def spread_words(cap, t0, length):
    ws = cap.split()
    weight = [len(w) + 2 for w in ws]
    total, acc, out = sum(weight), 0, []
    for w, k in zip(ws, weight):
        out.append({"w": w, "t": round(t0 + 0.05 + length * acc / total, 3), "d": 0.2})
        acc += k
    return out


def build_timeline(sc, wd, rate=RATE):
    os.makedirs(os.path.join(wd, "voice"), exist_ok=True)
    if ENGINE == "gemini":
        lens = gemini_tts_once([tagged(b) for b in sc["beats"]], wd)
        if lens is None:
            print("  could not split the voice cleanly, using one request per beat", flush=True)
            lens = [gemini_tts(tagged(b), os.path.join(wd, "voice", f"beat_{i}.wav"))
                    for i, b in enumerate(sc["beats"])]
        gaps = HOOK_GAP + GAP * (len(lens) - 1)
        tempo = min(MAX_TEMPO, max(1.1, sum(lens) / (80 - gaps)))  # >= 1.1x: snappier reels
        beats, t = [], 0.0
        for i, b in enumerate(sc["beats"]):
            wav, mp3 = os.path.join(wd, "voice", f"beat_{i}.wav"), os.path.join(wd, "voice", f"beat_{i}.mp3")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-af", f"atempo={tempo:.3f}",
                            "-ar", "44100", mp3], check=True)
            speech = duration(mp3)
            dur = speech + (HOOK_GAP if i == 0 else GAP)
            beats.append({"id": b["id"], "start": round(t, 3), "end": round(t + dur, 3),
                          "voice_start": round(t, 3), "words": spread_words(b["cap"], t, speech)})
            t += dur
        print(f"  gemini voice: {sum(lens):.1f}s raw, tempo x{tempo:.2f}", flush=True)
        return {"fps": FPS, "duration": round(t, 3), "beats": beats}

    beats, t = [], 0.0
    for i, b in enumerate(sc["beats"]):
        mp3 = os.path.join(wd, "voice", f"beat_{i}.mp3")
        words = asyncio.run(tts_beat(b["say"], mp3, rate))
        vlen = duration(mp3)
        speech = min(vlen, words[-1]["t"] + words[-1]["d"] + TAIL) if words else vlen
        dur = speech + (HOOK_GAP if i == 0 else GAP)
        cap = b["cap"].split()
        n = len(words)
        cw = [{"w": c, "t": round(t + words[min(n - 1, j * n // len(cap))]["t"], 3), "d": 0.2}
              for j, c in enumerate(cap)] if n else []
        beats.append({"id": b["id"], "start": round(t, 3), "end": round(t + dur, 3),
                      "voice_start": round(t, 3), "words": cw})
        t += dur
    return {"fps": FPS, "duration": round(t, 3), "beats": beats}


THEMES = {
    "neon":   ["#C6FF3D", "#FF4FD8", "#3DF5FF", "#0B0716"],
    "fire":   ["#FFC93D", "#FF5A36", "#FF9F45", "#140806"],
    "ocean":  ["#3DF5FF", "#4F7BFF", "#9DFFDF", "#05101C"],
    "matrix": ["#5CFF8A", "#00C26E", "#C6FF3D", "#03100A"],
    "gold":   ["#FFD23F", "#FF7EB6", "#B79BFF", "#100C04"],
    "candy":  ["#FF7EB6", "#B79BFF", "#7CC4FF", "#120818"],
    "interview": ["#FFD23F", "#FF3B3B", "#FFFFFF", "#0A0A0A"],
}


def theme_of(post, theme=None):
    names = list(THEMES)
    return theme if theme in THEMES else names[(post.get("part") or 0) % len(names)]


def thumb_data(post, theme=None):
    code = ""
    for s in post.get("slides", []):
        if s.get("type") == "code" and s.get("code"):
            lines = [ln for ln in str(s["code"]).split("\n") if ln.strip() and not ln.strip().startswith("--")]
            code = " ".join(" ".join(lines).split())
            break
    if len(code) > 150:
        code = code[:150].rsplit(" ", 1)[0] + " ..."
    return {"part": post.get("part"), "hook": re.sub(r"\[\[|\]\]", "", str(post.get("hook", ""))),
            "emoji": post.get("cover_sticker") or "", "topic": post.get("topic", ""), "code": code,
            "theme": THEMES["interview" if post.get("interview") else theme_of(post, theme)],
            "interview": bool(post.get("interview"))}


async def render_thumb(data, out_jpg):
    from playwright.async_api import async_playwright
    html = open(os.path.join(HERE, "thumb.html"), encoding="utf-8").read().replace(
        "__THUMB__", json.dumps(data, ensure_ascii=False))
    tmp = out_jpg + ".html"
    open(tmp, "w", encoding="utf-8").write(html)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1080, "height": 1920})
        await pg.goto("file://" + os.path.abspath(tmp))
        await pg.evaluate("document.fonts.ready.then(() => true)")
        await pg.wait_for_function("window.ready === true")
        await pg.wait_for_timeout(300)
        await pg.screenshot(path=out_jpg, type="jpeg", quality=92)
        await b.close()
    os.remove(tmp)


async def capture(scene, out_mp4, cover_jpg, dur):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1080, "height": 1920})
        await pg.goto("file://" + scene)
        await pg.evaluate("document.fonts.ready.then(() => true)")
        await pg.wait_for_timeout(800)
        ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe",
                               "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264",
                               "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium",
                               "-r", str(FPS), out_mp4], stdin=subprocess.PIPE)
        n = round(dur * FPS)
        for i in range(n):
            await pg.evaluate(f"window.renderFrame({i / FPS})")
            ff.stdin.write(await pg.screenshot(type="jpeg", quality=92))
            if i % (FPS * 10) == 0:
                print(f"  frame {i}/{n}", flush=True)
        ff.stdin.close()
        ff.wait()
        await pg.evaluate("window.renderFrame(1.2)")
        await pg.screenshot(path=cover_jpg, type="jpeg", quality=92)
        await b.close()


OUTRO = 2.2


def add_outro(tl):
    """Extra seconds after the voice: a 'screenshot le lo' cheat sheet, then a cut back to the hook (loop)."""
    if "outro" not in tl:
        tl["outro"] = round(tl["duration"], 3)
        tl["duration"] = round(tl["duration"] + OUTRO, 3)
    return tl


def sfx_times(sc, tl):
    """Whoosh on every beat change, a 'ding' when the quiz answer and the cliffhanger CTA appear."""
    norm = lambda w: re.sub(r"[^a-z0-9]", "", str(w).lower())
    out = [{"t": round(b["start"], 3), "s": "whoosh"} for b in tl["beats"][1:]]
    for b, tb in zip(sc["beats"], tl["beats"]):
        v = b.get("visual") or {}
        key = v.get("right_at") if v.get("type") == "quiz" else v.get("cta_at") if v.get("type") == "cliff" else None
        hit = next((w["t"] for w in tb["words"] if key and norm(w["w"]) == norm(key)), None)
        if hit is not None:
            out.append({"t": round(hit, 3), "s": "drop" if v.get("type") == "quiz" else "ding"})
            if v.get("type") == "quiz":
                out.append({"t": round(max(tb["start"], hit - 1.3), 3), "s": "riser"})
        if v.get("type") in ("code", "query"):
            for ln in v.get("lines") or []:
                t = next((w["t"] for w in tb["words"] if norm(w["w"]) == norm(ln.get("at"))), None)
                if t is not None:
                    out.append({"t": round(t, 3), "s": "type" if v["type"] == "code" else "tick"})
        for c in b.get("cues") or []:
            t = next((w["t"] for w in tb["words"] if norm(w["w"]) == norm(c.get("word"))), None)
            if t is not None and c.get("do") in ("kinetic", "emoji", "zoom", "shake", "flash"):
                out.append({"t": round(t + 0.05, 3), "s": "pop"})
    if tl.get("outro"):
        out += [{"t": tl["outro"], "s": "ding"}, {"t": round(tl["duration"] - 0.4, 3), "s": "whoosh"}]
    return sorted(out, key=lambda e: e["t"])


CHORDS = [(220, 261.63, 329.63), (174.61, 220, 261.63), (261.63, 329.63, 392), (196, 246.94, 293.66)]


def music_expr(dur):
    """Original synth loop (Am-F-C-G, 100 bpm): soft pad, bass, kick, offbeat hat. No samples, no copyright."""
    c = "floor(mod(t,9.6)/2.4)"
    pick = lambda k: "if(lt(%s,1),%s,if(lt(%s,2),%s,if(lt(%s,3),%s,%s)))" % (
        c, CHORDS[0][k], c, CHORDS[1][k], c, CHORDS[2][k], CHORDS[3][k])
    r, th, fi = pick(0), pick(1), pick(2)
    e = (f"0.045*(sin(2*PI*({r})*t)+sin(2*PI*({th})*t)+sin(2*PI*({fi})*t))*(0.65+0.35*sin(2*PI*0.25*t))"
         f"+0.07*sin(PI*({r})*t)*exp(-3*mod(t,0.6))"
         f"+0.22*sin(2*PI*52*t)*exp(-14*mod(t,0.6))"
         f"+0.025*(2*random(0)-1)*exp(-45*mod(t+0.3,0.6))")
    return f"aevalsrc=exprs='{e}':s=44100:d={dur:.2f}"


def mix(wd, tl, silent, final):
    inputs, filters, labels = ["-i", silent], [], []
    for i, b in enumerate(tl["beats"]):
        inputs += ["-i", os.path.join(wd, "voice", f"beat_{i}.mp3")]
        ms = int(round(b["voice_start"] * 1000))
        filters.append(f"[{i + 1}:a]adelay={ms}|{ms},volume=1.6[v{i}]")
        labels.append(f"[v{i}]")
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,"
                   f"aresample=44100,aformat=channel_layouts=mono,asplit=2[vo][key]")
    filters.append(f"{music_expr(tl['duration'] + 0.5)},volume=0.55,afade=t=in:d=0.8,"
                   f"afade=t=out:st={max(0, tl['duration'] - 1.2):.2f}:d=1.2[mraw]")
    filters.append("[mraw][key]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=350[mu]")
    fx = []
    for k, e in enumerate(tl.get("sfx", [])):
        ms = int(round(max(0, e["t"] - (0.12 if e["s"] == "whoosh" else 0)) * 1000))
        if e["s"] == "drop":
            ms = max(0, ms - 30)
        if e["s"] == "whoosh":
            src = "aevalsrc=exprs='0.35*(2*random(0)-1)*sin(PI*t/0.32)':s=44100:d=0.32,highpass=f=900,lowpass=f=6000"
        elif e["s"] == "type":
            src = ("aevalsrc=exprs='0.22*(2*random(0)-1)*exp(-60*mod(t,0.07))*lt(t,0.6)':s=44100:d=0.6,"
                   "highpass=f=1800,lowpass=f=7000")
        elif e["s"] == "tick":
            src = "aevalsrc=exprs='0.25*sin(2*PI*1800*t)*exp(-60*t)':s=44100:d=0.08"
        elif e["s"] == "riser":
            src = ("aevalsrc=exprs='(0.05+0.18*t/1.3)*((2*random(0)-1)*0.5+sin(2*PI*(200+700*t*t)*t))':s=44100:d=1.3,"
                   "highpass=f=300")
        elif e["s"] == "drop":
            src = "aevalsrc=exprs='0.55*sin(2*PI*(48+60*exp(-8*t))*t)*exp(-3.2*t)+0.2*(2*random(0)-1)*exp(-40*t)':s=44100:d=1.1"
        elif e["s"] == "pop":
            src = "aevalsrc=exprs='0.32*sin(2*PI*(520+900*exp(-30*t))*t)*exp(-22*t)':s=44100:d=0.18"
        else:
            src = "aevalsrc=exprs='0.30*sin(2*PI*1320*t)*exp(-9*t)+0.18*sin(2*PI*1980*t)*exp(-12*t)':s=44100:d=0.5"
        filters.append(f"{src},adelay={ms}|{ms}[fx{k}]")
        fx.append(f"[fx{k}]")
    filters.append(f"[vo][mu]{''.join(fx)}amix=inputs={2 + len(fx)}:normalize=0:duration=first,"
                   f"alimiter=limit=0.89:level=disabled[a]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                    "-t", str(tl["duration"]), "-movflags", "+faststart", final], check=True)


def make_reel(post, out_root):
    pid = post["id"]
    voice_name = pick_voice()
    wd = os.path.join(out_root, f"reel_{pid}")
    shutil.rmtree(wd, ignore_errors=True)
    os.makedirs(wd)
    feedback = None
    best = None
    previous = None
    for attempt in range(1, 7):
        print(f"{pid} reel: asking AI for the script (attempt {attempt})", flush=True)
        raw = None
        try:
            raw = ask_script(post, feedback, previous, attempt)
            sc = check_script(raw, post)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            print(f"  bad script: {e}", flush=True)
            feedback, previous = str(e), raw if isinstance(raw, dict) else None
            continue
        try:
            tl = build_timeline(sc, wd)
        except RuntimeError as e:
            if ENGINE != "gemini":
                raise
            print(f"  {e}: switching to the backup voice (neerja_expressive)", flush=True)
            os.environ["REEL_VOICE"] = voice_name = "neerja_expressive"
            pick_voice()
            tl = build_timeline(sc, wd)
        d = tl["duration"]
        words = sum(len(b["say"].split()) for b in sc["beats"])
        print(f"  voice: {d:.1f}s ({words} words)", flush=True)
        if MIN_SECONDS <= d <= MAX_SECONDS:
            break
        if d < MAX_SECONDS and (best is None or d > best[1]["duration"]):
            best = (sc, tl)
        need = round(words * 54 / d)
        feedback = (f"the reel is {d:.0f}s with {words} words; it must be 20-90s. "
                    f"Write about {need} words in total"
                    + (" (add a concrete example / one more detail per beat)." if d < MIN_SECONDS else " (cut words)."))
    else:
        if best is None:
            raise RuntimeError(f"{pid}: could not make a reel script of 20-90 seconds")
        sc, tl = best
        for rate in (("+22%", "+15%", "+8%") if ENGINE == "edge" else ()):
            tl = build_timeline(sc, wd, rate)
            print(f"  slower voice {rate}: {tl['duration']:.1f}s", flush=True)
            if tl["duration"] >= MIN_SECONDS:
                break
        if not MIN_SECONDS <= tl["duration"] <= MAX_SECONDS:
            raise RuntimeError(f"{pid}: reel is {tl['duration']:.0f}s, outside 20-90 s")

    add_outro(tl)
    tl["sfx"] = sfx_times(sc, tl)
    for f in ("reel_lib.js", "reel_base.css", "gsap.min.js"):
        shutil.copy(os.path.join(HERE, f), wd)
    html = open(os.path.join(HERE, "scene.html"), encoding="utf-8").read()
    caps = [[w["w"] for w in b["words"]] for b in tl["beats"]]
    html = (html.replace("__TL__", json.dumps(tl, ensure_ascii=False))
                .replace("__CAPS__", json.dumps(caps, ensure_ascii=False))
                .replace("__REEL__", json.dumps({"post": post, "beats": sc["beats"], "theme": sc.get("theme")},
                                             ensure_ascii=False)))
    scene = os.path.join(wd, "scene.html")
    open(scene, "w", encoding="utf-8").write(html)

    silent, final, cover = (os.path.join(wd, "silent.mp4"), os.path.join(wd, f"{pid}.mp4"),
                            os.path.join(wd, f"{pid}.jpg"))
    print("  rendering frames...", flush=True)
    asyncio.run(capture(scene, silent, cover, tl["duration"]))
    asyncio.run(render_thumb(thumb_data(post, sc.get("theme")), cover))
    mix(wd, tl, silent, final)
    json.dump({"voice": voice_name, "script": sc, "caption": sc.get("caption", "")},
              open(os.path.join(wd, "reel.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  done: {final}", flush=True)
    return final, cover, sc


def rerender(wd):
    old = open(os.path.join(wd, "scene.html"), encoding="utf-8").read()
    tl = add_outro(json.loads(re.search(r"const TL = (\{.*?\}); const CAPS", old, re.S).group(1)))
    caps = re.search(r"const CAPS = (\[.*?\]); const R =", old, re.S).group(1)
    reel = re.search(r"const R = (\{.*\});</script>", old, re.S).group(1)
    for f in ("reel_lib.js", "reel_base.css", "gsap.min.js"):
        shutil.copy(os.path.join(HERE, f), wd)
    html = (open(os.path.join(HERE, "scene.html"), encoding="utf-8").read()
            .replace("__TL__", json.dumps(tl, ensure_ascii=False)).replace("__CAPS__", caps).replace("__REEL__", reel))
    scene = os.path.join(wd, "scene.html")
    open(scene, "w", encoding="utf-8").write(html)
    pid = os.path.basename(wd).replace("reel_", "")
    try:
        tl["sfx"] = sfx_times({"beats": json.loads(reel)["beats"]}, tl)
    except (ValueError, KeyError):
        pass
    frame = os.path.join(wd, "frame.jpg")
    asyncio.run(capture(scene, os.path.join(wd, "silent.mp4"), frame, tl["duration"]))
    if os.path.exists(frame):
        os.remove(frame)
    mix(wd, tl, os.path.join(wd, "silent.mp4"), os.path.join(wd, f"{pid}.mp4"))
    print(f"  re-rendered: {os.path.join(wd, pid + '.mp4')}", flush=True)


if __name__ == "__main__":
    from generate import load_env
    load_env()
    if sys.argv[1:2] == ["--thumb"]:
        post = json.load(open(sys.argv[2], encoding="utf-8"))
        asyncio.run(render_thumb(thumb_data(post, sys.argv[4] if len(sys.argv) > 4 else None), sys.argv[3]))
        sys.exit()
    if sys.argv[1:2] == ["--rerender"]:
        for wd in sys.argv[2:]:
            rerender(os.path.abspath(wd))
    else:
        for path in sys.argv[1:]:
            make_reel(json.load(open(path, encoding="utf-8")), os.path.join(GEN, "out"))
