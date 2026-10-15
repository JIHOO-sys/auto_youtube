#!/usr/bin/env python3
"""make.py - build a vertical Short from a script: Pixabay clips + Google TTS narration + pop captions.

    python3 make.py script.json --sheet DIR   # candidate thumbnails per scene, pick ids into "clips"
    python3 make.py script.json [-o out.mp4]

script.json:
    {"title": "상단 고정 제목\\n*강조*는 노란색",
     "style": "optional "pick": 하루한픽 layout - white header/footer, no TTS, original-audio scenes only,
               with "comment" (one reaction line under the video) and "credit" (출처 line)",
     "voice": "optional Google TTS voice name (default VOICE)",
     "source": "optional local long-form video; then scenes use "src": [start seconds, ...] instead of query,
                or {"orig": [start, end], "lines": [[start, "도겸", "what they say"], ...]} to play the original
                moment with its own sound, captioned per line with the speaker's name ("" when unsure)",
     "scenes": [{"say": "나레이션 문장, *강조 단어*는 노란 자막", "query": "english pixabay search",
                 "clips": [123, 456]}]}   # optional Pixabay ids chosen from --sheet

Reads PIXABAY_API_KEY and GOOGLE_TTS_KEY from the environment. Needs ffmpeg/ffprobe (with libass).
"""
import argparse, base64, json, random, os, subprocess, sys, tempfile, urllib.parse, urllib.request

VOICE = "ko-KR-Chirp3-HD-Kore"
BRAND = "대신봐드림"  # channel name shown in the pick-style header
FONT_URL = "https://raw.githubusercontent.com/orioncactus/pretendard/main/packages/pretendard/dist/public/static/Pretendard-ExtraBold.otf"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
MAX_TTS_CHARS = 700  # per Short; keeps Google TTS far inside its free tier
# 16:9 source -> 9:16: sharp picture across the middle, blurred zoomed copy behind it
FIT = ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5,"
       "eq=brightness=-0.12[bg];[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,setsar=1")
# "pick" style: picture in a 1080x810 band on white, header (brand + title) above, comment + credit below
PICK_TOP = 520
FIT_PICK = (f"[0:v]scale=1080:810:force_original_aspect_ratio=increase,crop=1080:810,setsar=1,"
            f"pad=1080:1920:0:{PICK_TOP}:white,fps=30")
# vertical (phone-shot) source: full-screen picture, white title band over the top
FIT_PICK_V = f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,drawbox=0:0:1080:{PICK_TOP - 20}:white:t=fill,fps=30"
GREEN = r"&H3CFF5A&"  # pick-style speech captions, like the variety-show subtitles viewers know
CUT = 2.5      # seconds per stock clip; fast cuts read as current
CHUNK = 9      # max chars per caption pop
YELLOW = r"{\c&H00E0FF&}"
OLD_ID = 100000  # ponytail: Pixabay ids below this are ~2015-2021 uploads; tune if picks look dated

def get(url, data=None, headers={}):
    # Pixabay 403s the default urllib User-Agent
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0", **headers})
    with urllib.request.urlopen(req) as r:
        return r.read()

def font():
    path = os.path.join(CACHE, "Pretendard-ExtraBold.otf")
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        open(path, "wb").write(get(FONT_URL))
    return CACHE

def tts(text, out, voice=VOICE):
    body = {"input": {"text": text.replace("*", "")}, "voice": {"languageCode": "ko-KR", "name": voice},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 44100, "speakingRate": 1.2}}
    r = get(f"https://texttospeech.googleapis.com/v1/text:synthesize?key={os.environ['GOOGLE_TTS_KEY']}",
            json.dumps(body).encode(), {"Content-Type": "application/json"})
    open(out, "wb").write(base64.b64decode(json.loads(r)["audioContent"]))

def pixabay(**params):
    q = urllib.parse.urlencode({"key": os.environ["PIXABAY_API_KEY"], "safesearch": "true", **params})
    return json.loads(get(f"https://pixabay.com/api/videos/?{q}"))["hits"]

def search(query):
    hits = pixabay(q=query, per_page=30, video_type="film")[:12]
    # keep relevance order, but vertical first and the dated-looking early stock (low ids) last
    hits.sort(key=lambda h: (h["id"] < OLD_ID, h["videos"]["medium"]["width"] > h["videos"]["medium"]["height"]))
    return hits

def clip_urls(scene, n, used):
    """Clips the script picked by id (from --sheet), else best search hits."""
    if scene.get("clips"):
        hits = [pixabay(id=i)[0] for i in scene["clips"]]
    else:
        hits = [h for h in search(scene["query"]) if h["id"] not in used]
    if not hits:
        sys.exit(f"no pixabay video for query: {scene['query']!r}")
    picked = [hits[i % len(hits)] for i in range(n)]
    used.update(h["id"] for h in picked)
    return [h["videos"]["medium"]["url"] or h["videos"]["small"]["url"] for h in picked]

def sheet(script, outdir):
    """Contact sheet of the top 8 candidates per scene, labelled 0-7, so a human/Claude can pick clip ids."""
    os.makedirs(outdir, exist_ok=True)
    for i, s in enumerate(script["scenes"]):
        hits = search(s["query"])[:8]
        with tempfile.TemporaryDirectory() as tmp:
            for n, h in enumerate(hits):
                # thumbnails come in mixed formats/sizes; normalise each before tiling
                raw = os.path.join(tmp, f"raw{n}")
                open(raw, "wb").write(get(h["videos"]["medium"]["thumbnail"]))
                ff("-i", raw, "-vf", "scale=360:360:force_original_aspect_ratio=decrease,pad=360:360:(ow-iw)/2:(oh-ih)/2,"
                   f"drawtext=fontfile={os.path.join(font(), 'Pretendard-ExtraBold.otf')}:text='{n}':x=12:y=8:"
                   "fontsize=56:fontcolor=yellow:borderw=4", os.path.join(tmp, f"{n:02d}.png"))
            out = os.path.join(outdir, f"scene_{i}.jpg")
            if hits:
                ff("-i", os.path.join(tmp, "%02d.png"), "-vf", "tile=4x2", "-frames:v", "1", out)
        print(f"scene {i} [{s['query']}] {out if hits else 'NO RESULTS'}  " + " ".join(f"{n}={h['id']}" for n, h in enumerate(hits)))

def duration(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", path]).strip())

def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)

def chunks(say):
    """Split narration into short caption pops, keeping *highlight* spans across splits."""
    out, cur, hl = [], [], False
    for word in say.split():
        styled = YELLOW if hl else ""  # highlight may continue from the previous chunk
        for ch in word:
            if ch == "*":
                hl = not hl
                styled += YELLOW if hl else r"{\c&HFFFFFF&}"
            else:
                styled += ch
        plain = "".join(w for w, _ in cur) + word.replace("*", "")
        if cur and len(plain) > CHUNK:
            out.append(cur); cur = []
        cur.append((word.replace("*", ""), styled))
    out.append(cur)
    # each chunk: (plain length for timing, styled ASS text that resets colour at the end)
    return [(len("".join(p for p, _ in c)), " ".join(s for _, s in c) + r"{\c&HFFFFFF&}") for c in out]

def ts(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"

def ass(title, timeline, cap_y=1180, pick=None):
    head = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,Pretendard ExtraBold,88,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,7,0,8,60,60,230,1
Style: Cap,Pretendard ExtraBold,96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,9,5,5,70,70,0,1
Style: PTitle,Pretendard ExtraBold,80,&H00000000,&H00000000,&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,60,60,1430,1
Style: PBrand,Pretendard ExtraBold,50,&H007E2EFF,&H007E2EFF,&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,1,0,0,8,60,60,190,1
Style: PCap,Pretendard ExtraBold,72,&H005AFF3C,&H005AFF3C,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,7,0,5,60,60,0,1
Style: PNote,Pretendard ExtraBold,66,&H00000000,&H00000000,&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,1,0,0,8,60,60,1385,1
Style: PCredit,Pretendard ExtraBold,44,&H00777777,&H00777777,&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,60,60,150,1
Style: PNoteV,Pretendard ExtraBold,58,&H005AFF3C,&H005AFF3C,&H00000000,&H00000000,0,0,0,0,100,100,0,0,3,14,0,8,60,60,540,1
Style: PCreditV,Pretendard ExtraBold,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,4,0,2,60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    end = timeline[-1][1] if timeline else 0
    t = title.replace("\\n", "\n").replace("\n", r"\N")
    hl, base = (r"{\c&H7E2EFF&}", r"{\c&H000000&}") if pick else (YELLOW, r"{\c&HFFFFFF&}")
    while "*" in t:
        t = t.replace("*", hl, 1).replace("*", base, 1)
    if pick:
        v = "V" if pick.get("vertical") else ""
        note = f"* {pick['comment']} *" if v and pick.get("comment") else pick.get("comment", "")
        lines = [f"Dialogue: 1,{ts(0)},{ts(end)},PBrand,,0,0,0,,{BRAND}",
                 f"Dialogue: 1,{ts(0)},{ts(end)},PTitle,,0,0,0,,{t}",
                 f"Dialogue: 1,{ts(0)},{ts(end)},PNote{v},,0,0,0,,{note}",
                 f"Dialogue: 1,{ts(0)},{ts(end)},PCredit{v},,0,0,0,,{pick.get('credit', '')}"]
    else:
        lines = [f"Dialogue: 1,{ts(0)},{ts(end)},Title,,0,0,0,,{t}"]
    pop = r"{\pos(540,%d)\fscx75\fscy75\t(0,90,\fscx105\fscy105)\t(90,160,\fscx100\fscy100)}" % cap_y
    lines += [f"Dialogue: 0,{ts(a)},{ts(b)},{'PCap' if pick else 'Cap'},,0,0,0,,{pop}{text}" for a, b, text in timeline]
    return head + "\n".join(lines) + "\n"

def make(script, out):
    with tempfile.TemporaryDirectory() as tmp:
        used, fontsdir, t = set(), font(), 0.0
        pick = script if script.get("style") == "pick" else None
        if pick:
            w, h = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                            "stream=width,height", "-of", "csv=p=0", script["source"]]).decode().split(",")[:2]
            pick = {**pick, "vertical": int(h) > int(w)}
        reset = "{\\c%s}" % GREEN if pick else "{\\c&HFFFFFF&}"
        vparts, aparts, timeline = [], [], []
        for i, s in enumerate(script["scenes"]):
            wav = os.path.join(tmp, f"{i}.wav")
            if s.get("orig"):
                # the people's own voices: play the source moment with its sound, captioned
                a, b = s["orig"]
                ff("-ss", f"{a:.2f}", "-t", f"{b - a:.2f}", "-i", script["source"], "-vn",
                   "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", wav)
                if s.get("lines"):
                    # [[start sec, speaker or "", text], ...] -> one caption per line, speaker name in pink
                    d = b - a
                    for k, (lt, who, text) in enumerate(s["lines"]):
                        end = s["lines"][k + 1][0] if k + 1 < len(s["lines"]) else b
                        name = f"{{\\c&H7E2EFF&}}{who}{reset} " if who else ""
                        timeline.append((t + max(lt - a, 0), t + min(end, b) - a, name + text))
                    s = {**s, "say": "", "src": [a]}
                else:
                    s = {**s, "say": s.get("caption", ""), "src": [a]}
            else:
                tts(s["say"], wav, script.get("voice", VOICE))
            d = duration(wav)
            aparts.append(wav)
            # captions: spread over the scene by character count
            cs = chunks(s["say"]) if s["say"] else []; total = sum(n for n, _ in cs) or 1; c = t
            for n, text in cs:
                timeline.append((c, c + d * n / total, text)); c += d * n / total
            if s.get("src"):
                # review mode: cuts of the source video at the given start times, fitted over a blurred copy
                starts = s["src"]
                for j, st in enumerate(starts):
                    seg = os.path.join(tmp, f"{i}_{j}.mp4")
                    ff("-ss", f"{st:.2f}", "-i", script["source"], "-t", f"{d / len(starts):.3f}", "-an",
                       "-filter_complex", (FIT_PICK_V if pick["vertical"] else FIT_PICK) if pick else FIT, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", seg)
                    vparts.append(seg)
                t += d
                continue
            # video: cut the scene into ~CUT-second stock clips
            k = max(1, round(d / CUT))
            for j, url in enumerate(clip_urls(s, k, used)):
                src, seg = os.path.join(tmp, f"{i}_{j}.src.mp4"), os.path.join(tmp, f"{i}_{j}.mp4")
                open(src, "wb").write(get(url))
                ff("-stream_loop", "-1", "-i", src, "-t", f"{d / k:.3f}", "-an", "-vf",
                   "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,"
                   "eq=saturation=1.15:contrast=1.05,setsar=1",
                   "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", seg)
                vparts.append(seg)
            t += d
        lst = lambda name, parts: (open(os.path.join(tmp, name), "w").write("".join(f"file '{p}'\n" for p in parts)), os.path.join(tmp, name))[1]
        ff("-f", "concat", "-safe", "0", "-i", lst("v.txt", vparts), "-c", "copy", os.path.join(tmp, "v.mp4"))
        ff("-f", "concat", "-safe", "0", "-i", lst("a.txt", aparts), "-c", "copy", os.path.join(tmp, "a.wav"))
        sub = os.path.join(tmp, "s.ass")
        cap_y = (1480 if pick["vertical"] else PICK_TOP + 700) if pick else 1440 if script.get("source") else 1180
        open(sub, "w").write(ass(script.get("title", ""), timeline, cap_y, pick))
        # no background music: original voices and the narration only
        ff("-i", os.path.join(tmp, "v.mp4"), "-i", os.path.join(tmp, "a.wav"),
           "-vf", f"subtitles={sub}:fontsdir={fontsdir}", "-map", "0:v", "-map", "1:a", "-t", f"{t:.3f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out)
    return out

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("script"); p.add_argument("-o", "--out", default="short.mp4"); p.add_argument("--sheet")
    a = p.parse_args()
    script = json.load(open(a.script))
    says = [i for i, s in enumerate(script["scenes"]) if s.get("say")]
    if script.get("style") == "pick" and says: sys.exit("pick style has no narration: use orig scenes only")
    # review style: narration only as the opening hook and the closing line; the middle is the people themselves
    if script.get("source") and set(says) - {0, len(script["scenes"]) - 1}:
        sys.exit("narration only in the first and last scene; middle scenes must be orig")
    need = (["GOOGLE_TTS_KEY"] if says else []) + ([] if script.get("source") else ["PIXABAY_API_KEY"])
    missing = [k for k in need if not os.environ.get(k)]
    if missing: sys.exit(f"missing env: {', '.join(missing)}")
    if a.sheet:
        sheet(script, a.sheet); sys.exit()
    chars = sum(len(s.get("say", "")) for s in script["scenes"])
    # free-tier guard: 1M TTS chars/month free; 9 shorts/day x 700 x 31 = ~20% of it
    if chars > MAX_TTS_CHARS: sys.exit(f"script too long for the free TTS budget: {chars} > {MAX_TTS_CHARS} chars")
    out = make(script, a.out)
    d = duration(out)
    print(f"{out} ({d:.1f}s)")
    if d > 59: print("warning: over 59s", file=sys.stderr)
