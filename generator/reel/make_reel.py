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
    "gemini": ("gemini", "Zephyr", None, "roman"),
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
GEMINI_TTS_MODELS = ["gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview", "gemini-3.8-flash-lite-tts",
                     "gemini-2.5-flash-preview-tts"]
MAX_TEMPO = 1.35
GAP, HOOK_GAP, TAIL = 0.18, 0.1, 0.25
MIN_SECONDS, MAX_SECONDS = 20, 90

STYLE = """
You write the voiceover for a 45-75 second Instagram Reel of "The 30 sec developers" (@the30secdev, SQL in Hinglish).
GOAL: the viewer must actually UNDERSTAND the topic after watching. Teach it like a
good teacher talking to a friend: what it is, why it matters, how to use it (walk through
the example shown on screen), and what the result / output means. Every sentence must
teach something concrete. No filler, no hype, no "save karo / follow karo" in the voice.
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
sample data / the result rows ("table" or "flow"); b4 = an alternative query ("query", also full) or the
trade-off. Most words go to explaining the query.

Do NOT copy the carousel post. The post below is only the topic reference: make the reel
feel like a real Instagram reel with its OWN fresh examples, mini story, numbers, and
visuals (new example tables, a flow of how it works, a Gen Z chat, a big stat...).

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
  recap: 2-3 key takeaways, nothing else (__W_RECAP__ words)
Each beat (except hook) has:
  "title": short on-screen heading (<= 22 chars, Hinglish, one **bold** word)
  "visual": what the screen shows WHILE this beat is spoken. Every element has "at": one word
      copied exactly from this beat's cap; the element appears when that word is spoken,
      so pick the word where you talk about it. Types (use at least 4 different types overall,
      never the same type twice in a row):
    {"type":"code","file":"x.sql","lines":[{"code":"<= 30 chars","at":"word"}, ... max 7],
       "output":"<= 60 chars result shown after RUN (optional)","output_at":"word"}
    {"type":"query","file":"x.sql","lines":[{"code":"<= 30 chars, one clause","at":"word","explain":"4-7 Hinglish words: what it does + why"}, ... 3-7],
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
__SAYCAP__
  "cues": 2-4 extra effects on exact words, each {"word": "<word from this beat's cap>", "do": "...", "target": ...}
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
         "gemini": ("8-11", "16-20", "13-16", "10-13", "100-115")}


def style():
    w = WORDS[ENGINE]
    tone = os.environ.get("REEL_TONE", "").strip()
    return (STYLE.replace("__SAYCAP__", SAYCAP[SCRIPT].replace("__TOTAL__", w[4]))
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


def ask_script(post, feedback=None, previous=None, attempt=1):
    from generate import ask_writer
    slides = [{"index": i, **s, "targets": targets(s)} for i, s in enumerate(post["slides"][:6])]
    prompt = (style() + "\nThe post (carousel content) this reel is about:\n"
              + json.dumps({"part": post["part"], "topic": post["topic"], "hook": post["hook"],
                            "next": post.get("next"), "slides": slides,
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
           "chat": "messages", "checklist": "items", "kinetic": "lines"}


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
                        if len(ex) > 1 and ex[0].isupper() and ex[1].islower():
                            ex = ex[0].lower() + ex[1:]
                        sentence = f"{intro} {ex}."
                        l["at"] = sentence.split()[0]
                        parts.append(sentence)
                    b["cap"] = b["say"] = " ".join(parts)
                    print(f"  {b['id']}: voice now explains each query line ({len(b['cap'].split())} words)", flush=True)
            if v["type"] in ("code", "query") and any(len(str(l.get("code", ""))) > 34 for l in v["lines"]):
                raise ValueError(f"beat {b['id']}: code lines must be <= 30 chars")
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
        if SCRIPT == "deva" and not re.search(r"[\u0900-\u097F]", b["say"]):
            raise ValueError(f'beat {i + 1}: "say" must have Hindi words in Devanagari')
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


def gemini_tts(text, wav, trim=True):
    import base64
    import time
    import wave
    import requests
    from generate import gemini_keys
    combos = [(m, k) for k in gemini_keys() for m in GEMINI_TTS_MODELS]
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


def gemini_tts_once(texts, wd):
    full = os.path.join(wd, "voice", "full.wav")
    gemini_tts("\n\n".join(texts), full, trim=False)
    out = subprocess.run(["ffmpeg", "-i", full, "-af", "silencedetect=noise=-40dB:d=0.2", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    total = duration(full)
    gaps = [(e - st, (st + e) / 2) for st, e in zip(starts, ends) if st > 0.3 and e < total - 0.3]
    need = len(texts) - 1
    if len(gaps) < need:
        return None
    cuts = sorted(m for _, m in sorted(gaps, reverse=True)[:need])
    bounds = [0.0] + cuts + [total]
    words = [len(t.split()) for t in texts]
    lens = []
    for i in range(len(texts)):
        seg = bounds[i + 1] - bounds[i]
        expect = total * words[i] / sum(words)
        if not 0.45 <= seg / expect <= 2.2:
            return None
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
        lens = gemini_tts_once([b["say"] for b in sc["beats"]], wd)
        if lens is None:
            print("  could not split the voice cleanly, using one request per beat", flush=True)
            lens = [gemini_tts(b["say"], os.path.join(wd, "voice", f"beat_{i}.wav"))
                    for i, b in enumerate(sc["beats"])]
        gaps = HOOK_GAP + GAP * (len(lens) - 1)
        tempo = min(MAX_TEMPO, max(1.0, sum(lens) / (80 - gaps)))
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
            "theme": THEMES[theme_of(post, theme)]}


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


def mix(wd, tl, silent, final):
    inputs, filters, labels = ["-i", silent], [], []
    for i, b in enumerate(tl["beats"]):
        inputs += ["-i", os.path.join(wd, "voice", f"beat_{i}.mp3")]
        ms = int(round(b["voice_start"] * 1000))
        filters.append(f"[{i + 1}:a]adelay={ms}|{ms},volume=1.6[v{i}]")
        labels.append(f"[v{i}]")
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,"
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
    tl = json.loads(re.search(r"const TL = (\{.*?\}); const CAPS", old, re.S).group(1))
    caps = re.search(r"const CAPS = (\[.*?\]); const R =", old, re.S).group(1)
    reel = re.search(r"const R = (\{.*\});</script>", old, re.S).group(1)
    for f in ("reel_lib.js", "reel_base.css", "gsap.min.js"):
        shutil.copy(os.path.join(HERE, f), wd)
    html = (open(os.path.join(HERE, "scene.html"), encoding="utf-8").read()
            .replace("__TL__", json.dumps(tl, ensure_ascii=False)).replace("__CAPS__", caps).replace("__REEL__", reel))
    scene = os.path.join(wd, "scene.html")
    open(scene, "w", encoding="utf-8").write(html)
    pid = os.path.basename(wd).replace("reel_", "")
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
