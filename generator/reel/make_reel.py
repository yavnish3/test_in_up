"""
Make a Gen Z style animated reel (1080x1920, <= 60 s) for a generated carousel post.

Pipeline:
  1. Gemini writes the voiceover (Devanagari "say" for the TTS + Roman "cap" for
     captions) for: hook -> 4 teaching beats (picked from the carousel slides) ->
     mistake -> recap/CTA, plus the reel caption.
  2. edge-tts (hi-IN-SwaraNeural, same voice as SQL001-081) speaks each beat and
     gives word timings.
  3. scene.html animates the carousel content on those word timings; Playwright
     captures frames -> ffmpeg -> voice mixed in.

Usage:
    python generator/reel/make_reel.py generator/content/SQL082.json
Output: generator/out/reel_<id>/<id>.mp4, <id>.jpg (cover), reel.json (script + caption)
"""

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
# Default voice: "gemini" (the Gen Z girl Instagram creator vibe the user picked).
# REEL_VOICE=<name> forces another one, REEL_VOICE=random picks one at random.
#   name: (engine, voice, rate, script) ; script "deva" = Hindi in Devanagari, "roman" = Roman Hinglish
VOICES = {
    "swara": ("edge", "hi-IN-SwaraNeural", "+30%", "deva"),
    "neerja_expressive": ("edge", "en-IN-NeerjaExpressiveNeural", "+20%", "roman"),
    "neerja": ("edge", "en-IN-NeerjaNeural", "+20%", "roman"),
    "gemini": ("gemini", "Kore", None, "roman"),
}
ENGINE, VOICE, RATE, SCRIPT = VOICES["swara"]


def pick_voice():
    import random
    global ENGINE, VOICE, RATE, SCRIPT
    name = os.environ.get("REEL_VOICE") or "gemini"
    if name == "random":
        name = random.choice(list(VOICES))
    ENGINE, VOICE, RATE, SCRIPT = VOICES[name]
    print(f"  voice: {name}", flush=True)
    return name
GEMINI_TTS_MODELS = ["gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview"]
TTS_STYLE = ("Read this as a fast-talking, energetic young Indian Gen Z girl making an Instagram reel. "
             "Natural Hinglish, quick pace, no long pauses, upbeat: ")
MAX_TEMPO = 1.35  # Gemini TTS speaks slowly; speed it up (pitch kept) by at most this much
GAP, HOOK_GAP, TAIL = 0.18, 0.1, 0.25
MIN_SECONDS, MAX_SECONDS = 20, 90  # Instagram accepts 3 s - 15 min; keep reels 20-90 s

STYLE = """
You write the voiceover for a 45-75 second Instagram Reel of "The 30 sec developers" (@the30secdev, SQL in Hinglish).
Style: GEN Z Hinglish, the voice is a young FEMALE creator (feminine verbs: "batati hoon",
"samjhati hoon"). Fast, punchy, meme-y but the SQL must be 100% correct.
Use Gen Z words naturally: "bro", "no cap", "lowkey", "fr", "literally", "vibe",
"red flag", "main character", "scene kya hai", "it's giving", "bestie", "chill".
Desi touch too: "yaar", "bhai", "arre". Max 1-2 slang words per sentence.

Return JSON: {"beats": [...], "caption": "..."}
beats = exactly 7, in this order:
  1. {"id":"hook","slide":"hook", ...}  scroll-stopping first line (__W_HOOK__ words)
  2-5. four teaching beats, each {"id":"b1".."b4","slide":<index 0-5 of the post's slides>}
       pick 4 DIFFERENT slides that teach best (prefer code/table/compare), in a logical order.
       Talk about exactly what that slide shows, with a quick example. __W_BEAT__ words each.
  6. {"id":"galti","slide":"mistake", ...}  the common mistake + fix (__W_GALTI__ words)
  7. {"id":"recap","slide":"recap", ...}  quick recap + "save karo, follow karo" CTA (__W_RECAP__ words)
__SAYCAP__
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
# per-beat word counts (hook, teaching beat, galti, recap) + total, by engine
WORDS = {"edge": ("10-14", "24-30", "18-24", "14-20", "135-155"),
         "gemini": ("8-11", "16-20", "13-16", "10-13", "100-115")}


def style():
    w = WORDS[ENGINE]
    return (STYLE.replace("__SAYCAP__", SAYCAP[SCRIPT].replace("__TOTAL__", w[4]))
            .replace("__W_HOOK__", w[0]).replace("__W_BEAT__", w[1])
            .replace("__W_GALTI__", w[2]).replace("__W_RECAP__", w[3]))


def ask_script(post, feedback=None):
    from generate import ask_gemini
    slides = [{"index": i, **s} for i, s in enumerate(post["slides"][:6])]
    prompt = (style() + "\nThe post (carousel content) this reel is about:\n"
              + json.dumps({"part": post["part"], "topic": post["topic"], "hook": post["hook"],
                            "next": post.get("next"), "slides": slides,
                            "mistake": post["slides"][6], "recap": post["slides"][7]},
                           ensure_ascii=False))
    if feedback:
        prompt += f"\n\nFix this problem from your last attempt: {feedback}"
    return ask_gemini(prompt)


def check_script(sc, post):
    beats = sc.get("beats") or []
    if len(beats) != 7:
        raise ValueError(f"need 7 beats, got {len(beats)}")
    want = ["hook", None, None, None, None, "mistake", "recap"]
    seen = set()
    for i, b in enumerate(beats):
        b["id"] = ["hook", "b1", "b2", "b3", "b4", "galti", "recap"][i]
        if want[i]:
            b["slide"] = want[i]
        else:
            s = b.get("slide")
            if not isinstance(s, int) or not 0 <= s <= 5 or s in seen:
                raise ValueError(f"beat {i + 1}: slide must be a new index 0-5, got {s}")
            seen.add(s)
        if SCRIPT == "roman":
            b["say"] = b.get("cap") or b.get("say")
        if not b.get("say") or not b.get("cap"):
            raise ValueError(f"beat {i + 1}: say/cap missing")
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


def gemini_tts(text, wav):
    """Gemini TTS -> 24 kHz mono WAV with leading/trailing silence trimmed. Returns seconds."""
    import base64
    import time
    import wave
    import requests
    from generate import gemini_keys
    combos = [(m, k) for k in gemini_keys() for m in GEMINI_TTS_MODELS]
    body = {"contents": [{"parts": [{"text": TTS_STYLE + text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}}}}
    for attempt in range(5 * len(combos)):
        model, key = combos[attempt % len(combos)]
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              headers={"x-goog-api-key": key}, json=body, timeout=180)
        except requests.RequestException:
            continue
        if r.status_code in (429, 500, 503):
            print(f"  {model} (key {gemini_keys().index(key) + 1}): busy ({r.status_code})", flush=True)
            if (attempt + 1) % len(combos) == 0:  # every model on every key is busy: wait
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
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-af",
                        "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                        "silenceremove=start_periods=1:start_threshold=-45dB,areverse", wav], check=True)
        os.remove(raw)
        return duration(wav)
    raise RuntimeError("Gemini TTS did not answer")


def spread_words(cap, t0, length):
    """No word timings from Gemini TTS: spread the caption words by their length."""
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
        lens = []
        for i, b in enumerate(sc["beats"]):
            lens.append(gemini_tts(b["say"], os.path.join(wd, "voice", f"beat_{i}.wav")))
        gaps = HOOK_GAP + GAP * (len(lens) - 1)
        tempo = min(MAX_TEMPO, max(1.0, sum(lens) / (80 - gaps)))  # only speed up very long ones
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
        # captions: Roman words spread over the spoken word timings (counts may differ a bit)
        cap = b["cap"].split()
        n = len(words)
        cw = [{"w": c, "t": round(t + words[min(n - 1, j * n // len(cap))]["t"], 3), "d": 0.2}
              for j, c in enumerate(cap)] if n else []
        beats.append({"id": b["id"], "start": round(t, 3), "end": round(t + dur, 3),
                      "voice_start": round(t, 3), "words": cw})
        t += dur
    return {"fps": FPS, "duration": round(t, 3), "beats": beats}


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
    best = None  # (script, timeline) closest to the 50-59 s window
    for attempt in range(1, 5):
        print(f"{pid} reel: asking Gemini for the script (attempt {attempt})", flush=True)
        try:
            sc = check_script(ask_script(post, feedback), post)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            print(f"  bad script: {e}", flush=True)
            feedback = str(e)
            continue
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
        # a little short: speak the same script slower to stretch it into the window
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
                .replace("__REEL__", json.dumps({"post": post, "beats": sc["beats"]}, ensure_ascii=False)))
    scene = os.path.join(wd, "scene.html")
    open(scene, "w", encoding="utf-8").write(html)

    silent, final, cover = (os.path.join(wd, "silent.mp4"), os.path.join(wd, f"{pid}.mp4"),
                            os.path.join(wd, f"{pid}.jpg"))
    print("  rendering frames...", flush=True)
    asyncio.run(capture(scene, silent, cover, tl["duration"]))
    mix(wd, tl, silent, final)
    json.dump({"voice": voice_name, "script": sc, "caption": sc.get("caption", "")},
              open(os.path.join(wd, "reel.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  done: {final}", flush=True)
    return final, cover, sc


if __name__ == "__main__":
    from generate import load_env
    load_env()
    for path in sys.argv[1:]:
        make_reel(json.load(open(path, encoding="utf-8")), os.path.join(GEN, "out"))
