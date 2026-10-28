#!/usr/bin/env python3
"""make.py - build a vertical Short from a script: Pixabay clips + Google TTS narration + pop captions.

    python3 make.py script.json --sheet DIR   # candidate thumbnails per scene, pick ids into "clips"
    python3 make.py script.json [-o out.mp4]
    python3 make.py script.json --frames DIR  # framing check: is everything that matters inside the shown window?
    python3 make.py source.mp4 --motion       # per-second motion: scenes must come from the moving parts

script.json:
    {"title": "상단 고정 제목\\n*강조*는 노란색",
     "style": "optional "pick": 하루한픽 layout - white header/footer, no TTS, original-audio scenes only,
               with "comment" (one reaction line under the video) and "credit" (출처 line)",
     "voice": "optional Google TTS voice name (default VOICE), or "supertonic:F4" for the free local Supertonic model;
               a character series sets its own. Supertonic lines may carry <laugh> <sigh> <breath> (never captioned)",
     "rate": "optional speaking rate (default 1.0), e.g. 0.9 for a sleepy character",
     "outro": "optional line shown over the last OUTRO seconds with a bouncing arrow down at the channel name
               (bottom-left of the Shorts player), e.g. "사쿠라의 다른 이야기가 궁금하다면"; the video gets no longer",
     "dub": "optional true for animal sources: narration (the animal's inner voice) may sit on any scene,
             with the source's own sound kept quietly underneath",
     "source": "optional local long-form video; then scenes use "src": [start seconds, ...] instead of query,
                or {"orig": [start, end], "lines": [[start, "도겸", "what they say"], ...]} to play the original
                moment with its own sound, captioned per line with the speaker's name ("" when unsure)",
     "next": "optional part-1 teaser, e.g. "다음 화: 샤바니, 딸에게 혼나다" - takes the outro's place for NEXT_DUR s",
     "prev": "optional part-2 opener, e.g. "지난 화: 키요마사가 아빠한테 덤볐다" - first PREV_DUR s under the badge",
     "badge": "optional series badge shown top-left of the picture all along, e.g. "샤바니 #12"",
     a "say" scene may set "silent": true - the line shows as the usual caption but is not voiced; the source's sound
                plays at full volume for as long as the line takes to read (or "dur" seconds)
     any source scene may set "cx" / "cy": where the animal is in the SOURCE frame (0..1, default 0.5) - wide sources are
                cropped around it to fill over half the screen - and "zoom" (1..2.5, default 1): closer in, for far shots
                where the animal would be small
     "max_len": "optional cap in seconds instead of MAX_LEN, only for a character intro",
     any source scene must set "subject": [x0, y0, x1, y1] - the main character's whole body for the whole scene (never
                cut; it must fill SUBJECT_MIN of the picture) - and may set "box": [x0, y0, x1, y1]
     a scene may set "cutaway": true when the story shows what the main character deals with (the other animal, the toy,
                the food) without the character in it: "subject" is then that animal / thing, held to the same rules (0..1 of the SOURCE frame) around everything that must be seen
                for the whole scene - the character's full body, what it wants (toy, food), other animals; the zoom never
                cuts into it (then "cx"/"cy" are not needed and "zoom" is only an upper limit). Check with --frames
     "cut_bottom": "optional share of the source height to drop, e.g. 0.2 when the source has subtitles burned in"
     "hook": "optional {"at": [start, end], "cx": .., "zoom": ..} - the funniest moment (<= HOOK_MAX s, own sound, no
              caption) flashed first, before scene 1"
     any scene may add "cover": [[from, to (seconds into the scene), x, y, width as a share of the 1080 px frame], ...]
                - a big pulsing pink heart hiding that spot (mating and the like)
     any scene may add "fx": [[seconds into the scene, kind, x, y], ...] - a small manga-style mark by the animal's face,
                x, y = where in the SOURCE frame (0..1 from the left / top); kinds: FX below
     "scenes": [{"say": "나레이션 문장, *강조 단어*는 노란 자막", "query": "english pixabay search",
                 "clips": [123, 456]}]}   # optional Pixabay ids chosen from --sheet

Reads PIXABAY_API_KEY and GOOGLE_TTS_KEY from the environment. Needs ffmpeg/ffprobe (with libass).
"""
import argparse, base64, json, random, os, re, subprocess, sys, tempfile, urllib.parse, urllib.request

VOICE = "ko-KR-Chirp3-HD-Leda"  # the channel's fixed character voice (light, young)
BRAND = "돌뚜뿌꾸"  # channel name shown in the pick-style header
FONT_URL = "https://raw.githubusercontent.com/orioncactus/pretendard/main/packages/pretendard/dist/public/static/Pretendard-ExtraBold.otf"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
MAX_TTS_CHARS = 700  # per Short; keeps Google TTS far inside its free tier
# 16:9 source -> 9:16: sharp picture across the middle, blurred zoomed copy behind it
FIT = ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5,"
       "eq=brightness=-0.12[bg];[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,setsar=1")
# wide source in a dub Short: crop around the animal (scene "cx") to 9:8 and show it 1080x960 - over half the screen,
# so the animal reads at feed size - instead of the whole 16:9 frame as a thin 608 px band
ZOOM_W, ZOOM_H, ZOOM_TOP = 1080, 960, 420  # top sits just under the 2-line title

ZOOM_MAX = 2.0  # closer than this gets blurry: a "box" without "zoom" is framed no tighter
BOX_PAD = 0.08  # room kept around "box" on every side, as a share of its size

def window(sw, sh, cx=0.5, cy=0.5, zoom=None, cut=0.0, box=None, aspect=None):
    """The part of the source shown sharp, (x0, y0, w, h) in source pixels: the bottom `cut` share is dropped (subtitles
    burned into the source), then a window 1/zoom of what is left, centred on the animal at cx, cy where it fits.
    Wide sources get a 9:8 window (shown 1080x960), narrow ones keep their own shape.
    box = [x0, y0, x1, y1] (0..1 of the source): everything that must stay in the picture for the whole scene - the
    character's full body, what it is after, other animals. The window always holds all of it (zoom only goes as close
    as that allows; a box wider than 9:8 gets a wider window, shown letterboxed in the same band).
    aspect: the band's own shape instead of 9:8 (the pick style's 1080x810)."""
    uh = sh * (1 - cut)
    band = aspect or ZOOM_W / ZOOM_H
    a = band if sw / uh > band else sw / uh
    w = min(uh * a, sw) / (zoom or (ZOOM_MAX if box else 1.0))
    if box:
        bx0, by0, bx1, by1 = box[0] * sw, box[1] * sh, box[2] * sw, min(box[3] * sh, uh)
        pw, ph = (bx1 - bx0) * BOX_PAD, (by1 - by0) * BOX_PAD
        bx0, by0, bx1, by1 = max(bx0 - pw, 0), max(by0 - ph, 0), min(bx1 + pw, sw), min(by1 + ph, uh)
        cx, cy = (bx0 + bx1) / 2 / sw, (by0 + by1) / 2 / sh
        w = max(w, bx1 - bx0, (by1 - by0) * a)
    w = min(w, sw)
    h = min(w / a, uh)
    return (round(min(max(cx * sw - w / 2, 0), sw - w)), round(min(max(cy * sh - h / 2, 0), uh - h)), round(w), round(h))

def shown(sw, sh, cut, w, h):
    """Where window() lands on the 1080x1920 screen: (top y, height); always 1080 wide."""
    dh = 2 * round(540 * h / w)
    if sw / (sh * (1 - cut)) <= ZOOM_W / ZOOM_H:  # already narrow (phone footage): full width, centred
        return (1920 - dh) // 2, dh
    return ZOOM_TOP + (ZOOM_H - dh) // 2, dh  # 9:8 fills the 960 band; a wider box sits letterboxed in it

def union(*boxes):
    boxes = [b for b in boxes if b]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else None

def fit(sw, sh, cx=0.5, cy=0.5, zoom=None, cut=0.0, box=None):
    x0, y0, w, h = window(sw, sh, cx, cy, zoom, cut, box)
    top, dh = shown(sw, sh, cut, w, h)
    return ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5,"
            f"eq=brightness=-0.12[bg];[b]crop={w}:{h}:{x0}:{y0},scale=1080:{dh}[fg];[bg][fg]overlay=0:{top},fps=30,setsar=1")

# "pick" style: picture in a 1080x810 band on white, header (brand + title) above, comment + credit below
PICK_TOP = 520
PICK_W, PICK_H = 1080, 810

def fit_pick(sw, sh, cut=0.0, box=None, **_):
    """Wide source in the pick style: window() at 4:3 around "box", fitted into the 1080x810 band on white."""
    x0, y0, w, h = window(sw, sh, cut=cut, box=box, aspect=PICK_W / PICK_H, zoom=None if box else 1.0)
    top, dh = pick_shown(w, h)
    return (f"[0:v]crop={w}:{h}:{x0}:{y0},scale=1080:{dh},setsar=1,"
            f"pad=1080:1920:0:{top}:white,fps=30")

def pick_shown(w, h):
    dh = min(PICK_H, 2 * round(540 * h / w))
    return PICK_TOP + (PICK_H - dh) // 2, dh
# vertical (phone-shot) source: full-screen picture, white title band over the top
FIT_PICK_V = f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,drawbox=0:0:1080:{PICK_TOP - 20}:white:t=fill,fps=30"
GREEN = r"&H3CFF5A&"  # pick-style speech captions, like the variety-show subtitles viewers know
CUT = 2.5      # seconds per stock clip; fast cuts read as current
CHUNK = 9      # max chars per caption pop
YELLOW = r"{\c&H00E0FF&}"
READ_CPS, SILENT_MIN = 6, 1.6  # caption-only ("silent") scenes: Korean chars read per second, shortest scene
CAP_TRIM = 0.2  # ...minus this much per caption pop (asked for snappier pacing)
CAP_MAX = 2.2   # a caption that stays longer reads as a stall (retention drops there): not made
SUBJECT_MIN = 0.10  # the main character's body must fill at least this share of the picture (hook: twice that)
MAX_LEN = 25    # seconds; viewers stay ~12 s on average, so 15-20 s Shorts, never over this
HOOK_MAX = 0.8  # "hook": the funniest moment flashed first, before scene 1
MOTION_MIN = 6.0  # mean frame-to-frame change (0-255 grey, 64x36, 5 fps) below this = a still shot: never used

def motion(src, start, dur, box=None):
    """How much the picture moves from start for dur seconds, inside box (x0, y0, w, h: the part the Short shows) or
    the top 80% (burned-in subtitles popping in would count as motion). ~2 = a sleeping walrus on a fixed camera,
    5-9 = slow, 15+ = lively."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{max(dur, 0.6):.2f}", "-i", src, "-an", "-vf",
                          (f"crop={box[2]}:{box[3]}:{box[0]}:{box[1]}" if box else "crop=iw:ih*0.8:0:0") + ",fps=5,scale=64:36,format=gray", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, 36, 64).astype(float)
    return float(np.abs(np.diff(f, axis=0)).mean()) if len(f) > 1 else 0.0
NEXT_DUR = 1.5  # a 2-part story's "다음 화: ..." teaser replaces the outro line, shorter so the loop isn't held up
PREV_DUR = 1.5  # ...and part 2 opens with a "지난 화: ..." line for viewers who meet it first
OUTRO = 2.5    # seconds the "outro" line stays on, over the end of the last scene
OUTRO_FREE = lambda out: os.path.splitext(out)[0] + ".no-outro.mp4"  # same Short without it; upload.py archives this one

def _xf(path, deg=0, k=1.5, norm=True):
    """Rotate an ASS drawing's coordinates (pairs after m/l/b) by deg around 0,0 and scale by k. norm shifts it to start
    at 0,0: libass centres a drawing (\\an5) on its 0,0-based box, so negative coordinates would push it off the spot."""
    import math
    c, n, toks, nums = math.cos(math.radians(deg)), math.sin(math.radians(deg)), [], []
    for tok in path.split():
        if tok.lstrip("-").replace(".", "").isdigit():
            nums.append(float(tok))
            if len(nums) == 2:
                x, y = nums; toks.append(((x * c - y * n) * k, (x * n + y * c) * k)); nums = []
        else:
            toks.append(tok)
    pts = [t for t in toks if isinstance(t, tuple)]
    mx, my = (min(p[0] for p in pts), min(p[1] for p in pts)) if norm else (0, 0)
    return " ".join(t if isinstance(t, str) else f"{t[0] - mx:.0f} {t[1] - my:.0f}" for t in toks)

_VEIN = "m -34 -10 b -14 -10 -10 -14 -10 -34 l -20 -34 b -20 -24 -24 -20 -34 -20"  # one quarter of the anger mark, bent inward
# kind -> (style overrides, drawing or text, animation); colours are ASS &HBBGGRR&
FX = {
    "sweat":    (r"\1c&HFFC864&\3c&HFFFFFF&\bord4", _xf("m 0 -40 b 18 -10 28 5 28 18 b 28 34 15 44 0 44 b -15 44 -28 34 -28 18 b -28 5 -18 -10 0 -40"), "slide"),
    "anger":    (r"\1c&H3C3CFF&\3c&HFFFFFF&\bord3", _xf(" ".join(_xf(_VEIN, d, 1, norm=False) for d in (0, 90, 180, 270))), "pulse"),
    "heart":    (r"\1c&H9E5CFF&\3c&HFFFFFF&\bord4", _xf("m 0 30 b -44 0 -32 -34 0 -14 b 32 -34 44 0 0 30"), "float"),
    "sparkle":  (r"\1c&H40E6FF&\3c&HFFFFFF&\bord3", _xf("m 0 -34 l 9 -9 l 34 0 l 9 9 l 0 34 l -9 9 l -34 0 l -9 -9"), "twinkle"),
    "gloom":    (r"\1c&HC87850&\3c&HFFFFFF&\bord2", _xf("m -30 0 l -22 0 l -22 56 l -30 56 m -4 -6 l 4 -6 l 4 50 l -4 50 m 22 0 l 30 0 l 30 56 l 22 56"), "slide"),
    "surprise": (r"\1c&H00E0FF&\3c&H16131C&\bord8\fs160", "!", "pop"),
    "question": (r"\1c&HFFFFFF&\3c&H16131C&\bord8\fs150", "?", "pop"),
    "zzz":      (r"\1c&HFFFFFF&\3c&H8A5A3B&\bord7\fs96", "Z z z", "float"),
    "dots":     (r"\1c&HFFFFFF&\3c&H16131C&\bord8\fs170", "…", "pop"),
}
FX_DUR = 1.4  # seconds a mark stays
FX_TEXT = {"surprise", "question", "zzz", "dots"}  # drawn as letters in the channel font, the rest as vector shapes

_HEART = "m 0 30 b -44 0 -32 -34 0 -14 b 32 -34 44 0 0 30"  # 88 px wide at scale 1

def cover_lines(t0, t1, x, y, w):
    """A big pink heart hiding part of the picture (e.g. mating) from t0 to t1, w px wide, gently pulsing."""
    k, out, t = w / 88, [], t0
    while t < t1:  # 0.5 s beats: 100% -> 108% -> 100%
        e = min(t + 0.5, t1)
        out.append(rf"Dialogue: 4,{ts(t)},{ts(e)},Arrow,,0,0,0,,{{\an5\pos({x},{y})\1c&H9E5CFF&\3c&HFFFFFF&\bord{max(4, round(w / 40))}"
                   rf"\t(0,250,\fscx108\fscy108)\t(250,500,\fscx100\fscy100)}}{{\p1}}{_xf(_HEART, 0, k)}")
        t = e
    return out

def fx_lines(t0, kind, x, y):
    style, body, anim = FX[kind]
    a, b = ts(t0), ts(t0 + FX_DUR)
    move = {"slide": rf"\move({x},{y - 10},{x},{y + 30})", "float": rf"\move({x},{y},{x},{y - 60})"}.get(anim, rf"\pos({x},{y})")
    grow = {"pulse": r"\t(0,150,\fscx120\fscy120)\t(150,300,\fscx95\fscy95)\t(300,450,\fscx115\fscy115)\t(450,600,\fscx100\fscy100)",
            "twinkle": r"\t(0,200,\fscx130\fscy130\frz20)\t(200,400,\fscx90\fscy90\frz0)\t(400,600,\fscx120\fscy120)",
            "pop": r"\fscx40\fscy40\t(0,120,\fscx115\fscy115)\t(120,220,\fscx100\fscy100)"}.get(anim, r"\fscx60\fscy60\t(0,150,\fscx100\fscy100)")
    draw = body if kind in FX_TEXT else rf"{{\p1}}{body}"
    return [rf"Dialogue: 3,{a},{b},Arrow,,0,0,0,,{{\an5{move}{style}{grow}\fad(80,250)}}{draw}"]
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

TAGS = re.compile(r"<(laugh|breath|sigh)>\s*")  # Supertonic expression tags; read aloud by nothing else, never captioned
_supertonic = None

def tts(text, out, voice=VOICE, rate=1.0):
    """Google Cloud TTS voice name, or "supertonic:<F1..F5|M1..M5>" for Supertone's free local model (pip install supertonic)."""
    text = text.replace("*", "")
    if voice.startswith("supertonic:"):
        global _supertonic
        from supertonic import TTS  # local ONNX model, downloaded from Hugging Face on first use
        _supertonic = _supertonic or TTS(auto_download=True)
        wav, _ = _supertonic.synthesize(text, voice_style=_supertonic.get_voice_style(voice_name=voice.split(":", 1)[1]),
                                        lang="ko", total_steps=16, speed=rate)
        raw = out + ".st.wav"
        _supertonic.save_audio(wav, raw)
        ff("-i", raw, "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", out)
        os.remove(raw)
        return
    body = {"input": {"text": TAGS.sub("", text)}, "voice": {"languageCode": "ko-KR", "name": voice},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 44100, "speakingRate": rate}}  # 1.0 natural; 1.2 sounded rushed
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

def frames(script, outdir):
    """framing check, one image per scene (hook = scene 0 when there is one): source frames at the start, middle and end
    of every cut with the shown window drawn in green - the character's whole body, what it is after and the other
    animals must stay inside it in every frame, or widen "box"."""
    os.makedirs(outdir, exist_ok=True)
    src, cut = script["source"], script.get("cut_bottom", 0.0)
    sw, sh = map(int, subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                               "stream=width,height", "-of", "csv=p=0", src]).decode().split(",")[:2])
    scenes = ([{**script["hook"], "orig": script["hook"]["at"]}] if script.get("hook") else []) + script["scenes"]
    for i, s in enumerate(scenes):
        if s.get("orig"):
            starts, d = [s["orig"][0]], s["orig"][1] - s["orig"][0]
        else:
            starts = s.get("src") or []
            line = TAGS.sub("", s.get("say", "")).replace("*", "")
            d = s.get("dur") or max(SILENT_MIN, len(line) / (READ_CPS if s.get("silent") else 5))  # TTS reads ~5 chars/s
        if not starts:
            continue
        box = union(s.get("box"), s.get("subject"))
        x0, y0, w, h = (window(sw, sh, cut=cut, box=box, aspect=PICK_W / PICK_H, zoom=None if box else 1.0) if script.get("style") == "pick"
                        else window(sw, sh, s.get("cx", 0.5), s.get("cy", 0.5), s.get("zoom"), cut, box))
        with tempfile.TemporaryDirectory() as tmp:
            shots = []
            for st in starts:
                for k, at in enumerate((st + 0.1, st + d / len(starts) / 2, st + d / len(starts) - 0.1)):
                    shot = os.path.join(tmp, f"{len(shots)}.png")
                    ff("-ss", f"{max(at, 0):.2f}", "-i", src, "-frames:v", "1", "-vf",
                       f"drawbox={x0}:{y0}:{w}:{h}:0x00FF00:t=8,drawbox=0:{round(sh * (1 - cut))}:iw:ih:black@0.6:t=fill,scale=480:-2", shot)
                    shots.append(shot)
            ff(*sum([["-i", p] for p in shots], []), "-filter_complex",
               "".join(f"[{j}:v]" for j in range(len(shots))) + f"xstack=inputs={len(shots)}:grid=3x{len(starts)}" if len(shots) > 3 else
               "".join(f"[{j}:v]" for j in range(len(shots))) + f"hstack=inputs={len(shots)}", os.path.join(outdir, f"scene{i}.png"))
    print(f"framing check in {outdir}: green = what the Short shows")

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

def outro(text, end, dur=OUTRO):
    """Pink-boxed line + an arrow bobbing down onto the channel avatar, which the Shorts player shows bottom-left
    to viewers at about y 1700-1790, x 50-140 of the 1080x1920 frame on a phone (the channel owner's own view sits
    higher, with an extra analytics row - don't place by that); both sit above it so the tip lands on the avatar."""
    a = max(end - dur, 0)
    arrow = r"{\p1}m 21 0 l 42 0 l 42 35 l 63 35 l 31 70 l 0 35 l 21 35{\p0}"
    lines = [f"Dialogue: 2,{ts(a)},{ts(end)},Outro,,0,0,0,,{{\\pos(60,1510)\\fad(200,0)}}{text}"]
    k, step, y0, bob = 0, 0.3, 1610, 20
    while a + k * step < end:  # bob down and back every 0.6 s
        y, y1 = (y0 + bob, y0) if k % 2 else (y0, y0 + bob)
        lines.append(f"Dialogue: 2,{ts(a + k * step)},{ts(min(a + (k + 1) * step, end))},Arrow,,0,0,0,,"
                     f"{{\\move(64,{y},64,{y1})}}{arrow}")
        k += 1
    return lines

def ass(title, timeline, cap_y=1180, pick=None, end=0, tail="", extra=(), tail_dur=OUTRO):
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
Style: Outro,Pretendard ExtraBold,58,&H00FFFFFF,&H00FFFFFF,&H007E2EFF,&H00000000,0,0,0,0,100,100,0,0,3,18,0,7,0,0,0,1
Style: Prev,Pretendard ExtraBold,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,3,12,0,7,0,0,0,1
Style: Badge,Pretendard ExtraBold,42,&H00FFFFFF,&H00FFFFFF,&H007E2EFF,&H00000000,0,0,0,0,100,100,0,0,3,12,0,7,0,0,0,1
Style: Arrow,Pretendard ExtraBold,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,5,0,7,0,0,0,1
Style: PCreditV,Pretendard ExtraBold,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,4,0,2,60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    end = end or (timeline[-1][1] if timeline else 0)  # pick scenes may carry no captions at all
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
    lines += list(extra)
    if tail:
        lines += outro(tail, end, tail_dur)
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
        vparts, aparts, timeline, marks = [], [], [], []
        if script.get("source"):
            sw, sh = map(int, subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                                       "stream=width,height", "-of", "csv=p=0", script["source"]]).decode().split(",")[:2])
            cut = script.get("cut_bottom", 0.0)
            ch = sh * (1 - cut)  # source height left once burned-in subtitles are cut off
            # "subject" (the main character's whole body) always stays in the picture, whatever "box" says
            view = lambda s: dict(cx=s.get("cx", 0.5), cy=s.get("cy", 0.5), zoom=s.get("zoom"), cut=cut, box=union(s.get("box"), s.get("subject")))
            def screen(x, y, s):
                """Source-frame fraction -> output pixel, following fit() / FIT_PICK / FIT_PICK_V."""
                if pick and not pick["vertical"]:  # fit_pick's window in the 1080x810 band
                    x0, y0, w, h = window(sw, sh, cut=cut, box=view(s)["box"], aspect=PICK_W / PICK_H, zoom=None if view(s)["box"] else 1.0)
                    top, dh = pick_shown(w, h)
                    return round((x * sw - x0) / w * 1080), round(top + (y * sh - y0) / h * dh)
                if pick:  # cover the whole screen
                    k = max(1080 / sw, 1920 / ch)
                    return round(x * sw * k - (sw * k - 1080) / 2), round(y * sh * k - (ch * k - 1920) / 2)
                x0, y0, w, h = window(sw, sh, **view(s))
                top, dh = shown(sw, sh, cut, w, h)
                return round((x * sw - x0) / w * 1080), round(top + (y * sh - y0) / h * dh)
        scenes, problems = script["scenes"], []
        if script.get("hook"):
            # the funniest moment first, with its own sound and no caption - what the feed shows before anyone swipes
            a, b = script["hook"]["at"]
            scenes = [{**script["hook"], "orig": [a, min(b, a + HOOK_MAX)]}] + scenes
        for i, s in enumerate(scenes):
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
            elif s.get("silent") and s.get("src"):
                # inner thought as caption only: the source's own sound at full volume, long enough to read
                n = len(s["src"])
                line = TAGS.sub("", s["say"])
                d0 = s.get("dur") or max(SILENT_MIN, len(line.replace("*", "")) / READ_CPS + 0.6 - CAP_TRIM * len(chunks(line)))
                beds = []
                for st in s["src"]:
                    beds += ["-ss", f"{st:.2f}", "-t", f"{d0 / n:.3f}", "-i", script["source"]]
                ff(*beds, "-filter_complex", "".join(f"[{j}:a]" for j in range(n)) + f"concat=n={n}:v=0:a=1",
                   "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", wav)
            else:
                tts(s["say"], wav, script.get("voice", VOICE), script.get("rate", 1.0))
                if script.get("dub") and s.get("src"):
                    # animal dub: the barks/meows stay audible under the voice
                    d0, n = duration(wav), len(s["src"])
                    beds = []
                    for j, st in enumerate(s["src"]):
                        beds += ["-ss", f"{st:.2f}", "-t", f"{d0 / n:.3f}", "-i", script["source"]]
                    mixed = os.path.join(tmp, f"{i}_dub.wav")
                    ff("-i", wav, *beds, "-filter_complex",
                       "".join(f"[{j + 1}:a]" for j in range(n)) + f"concat=n={n}:v=0:a=1,volume=0.3[b];"
                       "[0:a][b]amix=inputs=2:duration=first:normalize=0", "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", mixed)
                    os.replace(mixed, wav)
            d = duration(wav)
            aparts.append(wav)
            if script.get("source") and s.get("src"):
                box = None if pick else window(sw, sh, **view(s))
                m = sum(motion(script["source"], st, d / len(s["src"]), box) for st in s["src"]) / len(s["src"])
                if m < MOTION_MIN:
                    problems.append(f"scene {i} at {s['src'][0]:.1f}s is a still shot (motion {m:.1f} < {MOTION_MIN}) - pick a moving moment (--motion)")
                if script.get("badge") and not s.get("subject"):
                    problems.append(f"scene {i} has no \"subject\" (the main character's whole body, or with \"cutaway\" "
                                    "the animal / thing it deals with)")
                elif s.get("subject"):
                    x0, y0, w, h = window(sw, sh, cut=cut, box=view(s)["box"], aspect=PICK_W / PICK_H if pick else None,
                                          zoom=s.get("zoom")) if not (pick and pick["vertical"]) else (0, 0, sw, ch)
                    b = s["subject"]
                    share = (b[2] - b[0]) * sw * (min(b[3] * sh, ch) - b[1] * sh) / (w * h)
                    need = SUBJECT_MIN * (2 if i == 0 and script.get("hook") else 1)
                    if share < need:
                        problems.append(f"scene {i}: the main character fills {share:.0%} of the picture (< {need:.0%}) - "
                                        "too far away: a closer moment, or a tighter \"box\"")
            for a0, a1, x, y, size in s.get("cover", []):
                px, py = screen(x, y, s)
                marks += cover_lines(t + a0, t + min(a1, d), px, py, round(size * 1080))
            for off, kind, x, y in s.get("fx", []):
                px, py = screen(x, y, s)
                marks += fx_lines(t + min(off, max(d - 0.3, 0)), kind, min(max(px, 70), 1010), min(max(py, 80), 1840))
            # captions: spread over the scene by character count
            cs = chunks(TAGS.sub("", s["say"])) if s["say"] else []; total = sum(n for n, _ in cs) or 1; c = t
            for n, text in cs:
                timeline.append((c, c + d * n / total, text)); c += d * n / total
            if cs and d / len(cs) > CAP_MAX:
                problems.append(f"scene {i} holds each caption {d / len(cs):.1f}s (> {CAP_MAX}s) - split the line or the scene")
            if s.get("src"):
                # review mode: cuts of the source video at the given start times, fitted over a blurred copy
                starts = s["src"]
                for j, st in enumerate(starts):
                    seg = os.path.join(tmp, f"{i}_{j}.mp4")
                    ff("-ss", f"{st:.2f}", "-i", script["source"], "-t", f"{d / len(starts):.3f}", "-an",
                       "-filter_complex", (FIT_PICK_V.replace("[0:v]", f"[0:v]crop=iw:ih*{1 - cut:.3f}:0:0,", 1)
                       if pick["vertical"] else fit_pick(sw, sh, **view(s))) if pick else fit(sw, sh, **view(s)), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", seg)
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
        if problems:  # still shots, tiny animals and stalled captions are where viewers swipe away
            sys.exit("not made:\n  " + "\n  ".join(problems))
        lst = lambda name, parts: (open(os.path.join(tmp, name), "w").write("".join(f"file '{p}'\n" for p in parts)), os.path.join(tmp, name))[1]
        ff("-f", "concat", "-safe", "0", "-i", lst("v.txt", vparts), "-c", "copy", os.path.join(tmp, "v.mp4"))
        ff("-f", "concat", "-safe", "0", "-i", lst("a.txt", aparts), "-c", "copy", os.path.join(tmp, "a.wav"))
        cap_y = (1480 if pick["vertical"] else PICK_TOP + 700) if pick else 1440 if script.get("source") else 1180
        # series badge ("샤바니 #12") pinned to the picture's top-left corner the whole time, so feed viewers learn the series
        by = PICK_TOP + 20 if pick else ZOOM_TOP + 20
        badge = [f"Dialogue: 2,{ts(0)},{ts(t)},Badge,,0,0,0,,{{\\pos(36,{by})}}{script['badge']}"] if script.get("badge") else []
        if script.get("prev"):  # part 2 of a 2-part story: one line on what happened in part 1
            badge.append(f"Dialogue: 2,{ts(0)},{ts(PREV_DUR)},Prev,,0,0,0,,{{\\pos(36,{by + 66})\\fad(0,200)}}{script['prev']}")
        # with an outro, also a copy without it (OUTRO_FREE): the weekly 16:9 compilation has no channel avatar to point at
        tail = script.get("next") or script.get("outro", "")
        outs = [(out, tail)] + ([(OUTRO_FREE(out), "")] if tail else [])
        for k, (path, tail) in enumerate(outs):
            sub = os.path.join(tmp, f"s{k}.ass")
            open(sub, "w").write(ass(script.get("title", ""), timeline, cap_y, pick, t, tail, marks + badge,
                                     NEXT_DUR if script.get("next") else OUTRO))
            # no background music: original voices and the narration only
            ff("-i", os.path.join(tmp, "v.mp4"), "-i", os.path.join(tmp, "a.wav"),
               "-vf", f"subtitles={sub}:fontsdir={fontsdir}", "-map", "0:v", "-map", "1:a", "-t", f"{t:.3f}",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", path)
    return out

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("script"); p.add_argument("-o", "--out", default="short.mp4"); p.add_argument("--sheet")
    p.add_argument("--frames", metavar="DIR", help="framing check images per scene (source scripts), then stop")
    p.add_argument("--motion", action="store_true", help="print how much each second of the script (source) moves")
    a = p.parse_args()
    if a.motion:  # script may be just the source video here
        src = a.script if a.script.endswith((".mp4", ".mkv", ".webm", ".mov")) else json.load(open(a.script))["source"]
        n = int(float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src])))
        for k in range(n):
            m = motion(src, k, 1)
            print(f"{k // 60}:{k % 60:02d} {m:5.1f} {'still' if m < MOTION_MIN else '#' * min(40, round(m))}")
        sys.exit()
    script = json.load(open(a.script))
    says = [i for i, s in enumerate(script["scenes"]) if s.get("say")]
    if script.get("style") == "pick" and says: sys.exit("pick style has no narration: use orig scenes only")
    # review style: narration only as the opening hook and the closing line; the middle is the people themselves
    # animal sources ("dub") have no voices of their own, so the inner-voice narration may sit anywhere
    if script.get("source") and not script.get("dub") and set(says) - {0, len(script["scenes"]) - 1}:
        sys.exit("narration only in the first and last scene; middle scenes must be orig")
    if script.get("source") and "cut_bottom" not in script:
        sys.exit('set "cut_bottom" (0 when the source has no subtitles burned in at the bottom; see PLAN.md)')
    if a.frames:
        frames(script, a.frames); sys.exit()
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
    if d > script.get("max_len", MAX_LEN): sys.exit(f"too long: {d:.1f}s > {script.get('max_len', MAX_LEN)}s - cut scenes (aim for 15-20 s) and make it again")
