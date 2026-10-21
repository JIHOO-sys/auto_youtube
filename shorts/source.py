#!/usr/bin/env python3
"""source.py - long-form animal source videos for 돌뚜뿌꾸 Shorts, from the Drive folder 롱폼원본.

    python3 source.py suggest           # CC candidates to download, per category (read-only)
    python3 source.py list              # videos in 롱폼원본: drive id, YouTube id, shorts already made from it
    python3 source.py clean             # move sources with 3 Shorts made (and their subtitles) to the Drive trash
    python3 source.py fetch DRIVE_ID DIR # DIR/video.*, meta.json (YouTube title/channel/license), transcript.txt, frames.jpg, moves.txt
    python3 source.py moves VIDEO        # motion/loudness per 2 s + liveliest windows (animal sources have little dialogue)

File names should contain the YouTube id in brackets, e.g. "간식 훔쳐먹은 강아지 [N9UJE7TMe1I].mp4" (yt-dlp's default);
otherwise the exact video title is looked up among CC videos.
A subtitle file with the same name (.srt/.vtt) is used as the transcript; otherwise faster-whisper transcribes.
"""
import datetime, difflib, html, json, os, re, subprocess, sys, urllib.parse
import urllib.error
from upload import api, drive_get, drive_ls, drive_trash, recent

FOLDER = "롱폼원본"
YTID = re.compile(r"\[([A-Za-z0-9_-]{11})\]")
SHORTS_PER_SOURCE = 3  # different moments of one long video before moving on

def youtube_meta(vid):
    items = api(f"https://www.googleapis.com/youtube/v3/videos?part=snippet,status,contentDetails&id={vid}")["items"]
    if not items:
        return None
    sn, st = items[0]["snippet"], items[0]["status"]
    return {"id": vid, "url": f"https://youtu.be/{vid}", "title": sn["title"], "channel": sn["channelTitle"],
            "channel_id": sn["channelId"], "license": st["license"], "description": sn["description"][:1500]}

def find_id(name):
    """YouTube id from '[id]' in the file name, else the CC video whose title matches the file name."""
    m = YTID.search(name)
    if m:
        return m.group(1)
    stem = re.sub(r"\.[^.]+$", "", name)
    hits = api("https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(
        {"part": "snippet", "type": "video", "videoLicense": "creativeCommon", "maxResults": 10,
         "q": " ".join(re.findall(r"[0-9A-Za-z가-힣]+", stem))}))["items"]  # emoji/brackets make search return nothing
    norm = lambda t: re.sub(r"[^0-9a-z가-힣]", "", html.unescape(t).lower())
    for h in hits:  # ponytail: exact normalised title match only; widen if downloaders mangle names more
        if norm(h["snippet"]["title"]) == norm(stem):
            return h["id"]["videoId"]
    return ""

# Korean and Japanese channels only: their voices sit naturally under Korean dubbing and subtitles
SEARCHES = [(q, "ko") for q in ["웃긴 강아지", "웃긴 고양이", "강아지 반응", "고양이 반응", "강아지 브이로그", "고양이 브이로그",
                                "강아지 일상", "고양이 집사", "댕댕이", "반려동물 브이로그",
                                "토끼", "햄스터", "고슴도치", "수달", "카피바라", "아기 동물", "동물원"]] + \
           [(q, "ja") for q in ["犬 おもしろ", "猫 おもしろ", "子猫", "犬 日常", "猫 日常", "カワウソ"]]

# character series: channel id -> series name. Their unused CC long videos are listed in every suggest run
# (channel id, title keyword or "" for every upload) -> series name
SERIES = {("UC4hQbfN_ZRy4lSngWxuhHxA", ""): "수달 사쿠라 (ma ko)",
          ("UCz8xxcZ3zrmv1HAL8iZ50JA", "セイウチ"): "바다코끼리 히마와리 (伊勢シーパラダイス)"}

def iso_secs(d):
    m = re.match(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d)
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s

def series_candidates(ch, seen, n=10, kw=""):
    """Most-viewed unused CC uploads of 3-15 min from a series channel (no search quota: playlist + videos calls)."""
    ids, tok = [], ""
    while True:
        r = api(f"https://www.googleapis.com/youtube/v3/playlistItems?part=contentDetails&maxResults=50&playlistId=UU{ch[2:]}" + (f"&pageToken={tok}" if tok else ""))
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        tok = r.get("nextPageToken")
        if not tok:
            break
    vids = []
    for k in range(0, len(ids), 50):
        vids += api("https://www.googleapis.com/youtube/v3/videos?part=snippet,status,statistics,contentDetails&id=" + ",".join(ids[k:k + 50]))["items"]
    vids = [v for v in vids if v["id"] not in seen and v["status"]["license"] == "creativeCommon" and kw in v["snippet"]["title"]
            and 180 <= iso_secs(v["contentDetails"]["duration"]) <= 900]
    return sorted(vids, key=lambda v: -int(v["statistics"].get("viewCount", 0)))[:n]

SIMILAR = 0.7  # same channel and titles this alike = the same moment filmed twice (e.g. 아기 고양이 / 고양이들 반응)

def norm_title(t):
    return re.sub(r"[^0-9a-z가-힣ぁ-んァ-ン一-龥]", "", html.unescape(t).lower())

def cmd_suggest():
    """CC candidates per category (read-only): already used/downloaded ids and near-copies of them removed, best first by views."""
    seen = {src for _, src in recent()} | {find_id(f["name"]) for f in drive_ls(FOLDER, "video/")}
    seen.discard("")
    # channel + title of everything already used or downloaded, to drop look-alike videos from the same channel
    known, ids = [], sorted(seen)
    for k in range(0, len(ids), 50):
        known += [(v["snippet"]["channelId"], norm_title(v["snippet"]["title"])) for v in
                  api("https://www.googleapis.com/youtube/v3/videos?part=snippet&id=" + ",".join(ids[k:k + 50]))["items"]]
    alike = lambda v: any(ch == v["snippet"]["channelId"] and difflib.SequenceMatcher(None, t, norm_title(v["snippet"]["title"])).ratio() >= SIMILAR
                          for ch, t in known)
    after = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=365 * 5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for (ch, kw), name in SERIES.items():
        print(f"== 시리즈: {name}")
        for v in series_candidates(ch, seen, kw=kw):
            seen.add(v["id"])
            dur = v["contentDetails"]["duration"].replace("PT", "").lower()
            print(f"{v['id']}\t{int(v['statistics'].get('viewCount', 0)):>9}\t{dur}\t{v['snippet']['channelTitle']}\t{v['snippet']['title']}")
    for q, lang in SEARCHES:
        ids = [h["id"]["videoId"] for h in api("https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(
            {"part": "snippet", "type": "video", "videoLicense": "creativeCommon", "q": q, "maxResults": 15,
             "order": "viewCount", "publishedAfter": after, "relevanceLanguage": lang, "videoDuration": "medium"}))["items"]]
        ids = [i for i in ids if i not in seen]
        if not ids:
            continue
        vids = api("https://www.googleapis.com/youtube/v3/videos?part=snippet,status,statistics,contentDetails&id=" + ",".join(ids))["items"]
        print(f"== {q}")
        for v in sorted(vids, key=lambda v: -int(v["statistics"].get("viewCount", 0))):
            if v["status"]["license"] != "creativeCommon" or alike(v):
                continue
            seen.add(v["id"])  # print each video once even when several search terms find it
            dur = v["contentDetails"]["duration"].replace("PT", "").lower()
            print(f"{v['id']}\t{int(v['statistics'].get('viewCount', 0)):>9}\t{dur}\t{v['snippet']['channelTitle']}\t{v['snippet']['title']}")

def cmd_list():
    used = {}
    for _, src in recent():
        used[src] = used.get(src, 0) + 1
    for f in drive_ls(FOLDER, "video/"):
        vid = find_id(f["name"])
        n = used.get(vid, 0)
        status = "youtube id not found - skip" if not vid else ("done" if n >= SHORTS_PER_SOURCE else f"{n}/{SHORTS_PER_SOURCE} made")
        print(f"{f['id']}\t{vid}\t{status}\t{f['name']}")

def cmd_clean():
    """Trash 롱폼원본 videos that already have SHORTS_PER_SOURCE Shorts, plus their same-name subtitle files."""
    used = {}
    for _, src in recent():
        used[src] = used.get(src, 0) + 1
    files = drive_ls(FOLDER)
    for f in [x for x in files if x["mimeType"].startswith("video/")]:
        vid = find_id(f["name"])
        if not vid or used.get(vid, 0) < SHORTS_PER_SOURCE:
            continue
        base = os.path.splitext(f["name"])[0]
        subs = [x for x in files if x is not f and x["name"].startswith(base) and x["name"].endswith((".srt", ".vtt"))]
        try:
            for x in [f, *subs]:
                drive_trash(x["id"])
        except urllib.error.HTTPError as e:
            if e.code == 403:  # token only has drive.readonly: leave the files, the user removes them by hand
                print("skip: Drive token is read-only (drive.readonly) - re-issue it with the drive scope to auto-clean", file=sys.stderr)
                return
            raise
        print(f"trashed\t{vid}\t{f['name']}" + (f" (+{len(subs)} subtitle)" if subs else ""))

def srt_to_lines(text):
    """VTT/SRT -> '12.3 text' lines (start seconds)."""
    out, start = [], None
    for line in text.splitlines():
        m = re.match(r"(\d+):(\d+):(\d+)[.,](\d+)\s*-->", line) or re.match(r"(\d+):(\d+)[.,](\d+)\s*-->", line)
        if m:
            g = [int(x) for x in m.groups()]
            h, mi, sec, ms = g if len(g) == 4 else [0, *g]
            start = h * 3600 + mi * 60 + sec + ms / 1000
        elif line.strip() and start is not None and not line.strip().isdigit() and "WEBVTT" not in line:
            out.append(f"{start:.1f} {re.sub('<[^>]+>', '', line.strip())}")
    return out

def transcribe(video):
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    from faster_whisper import WhisperModel
    import numpy as np  # decode with ffmpeg ourselves: faster-whisper's PyAV path breaks on newer av releases
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         check=True, capture_output=True).stdout
    audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
    segs, _ = WhisperModel("small", device="cpu", compute_type="int8").transcribe(audio, vad_filter=True)
    return [f"{s.start:.1f} {s.text.strip()}" for s in segs]

def frames(video, out):
    """24 evenly spaced frames, timestamped, on one sheet - lets Claude see what happens where."""
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video]))
    step = max(dur / 24, 1)
    font = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "Pretendard-ExtraBold.otf")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vf",
                    f"fps=1/{step:.3f},scale=320:-2,drawtext=fontfile={font}:text='%{{pts\\:hms}}':x=6:y=6:"
                    "fontsize=22:fontcolor=yellow:borderw=2,tile=6x4", "-frames:v", "1", out], check=True)
    return dur

def series(args, key):
    """Per-frame values of one ffmpeg metadata key, as [(seconds, value)]."""
    out = subprocess.run(["ffmpeg", "-v", "error", *args, "-f", "null", "-"], capture_output=True, text=True, check=True).stdout
    vals, t = [], None
    for line in out.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
        elif line.startswith(key + "=") and t is not None:
            v = line.split("=", 1)[1]
            vals.append((t, float(v) if v not in ("-inf", "inf", "nan") else -90.0))
    return vals

def moves(video, window=20):
    """Animal sources have little dialogue to pick moments by: score each 2 s by on-screen motion and loudness."""
    motion = series(["-i", video, "-an", "-vf", "fps=4,scale=160:-2,format=gray,tblend=all_mode=difference,"
                     "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=/dev/stdout"], "lavfi.signalstats.YAVG")
    loud = series(["-i", video, "-vn", "-af", "aresample=8000,asetnsamples=n=4000,astats=metadata=1:reset=1,"
                   "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=/dev/stdout"], "lavfi.astats.Overall.RMS_level")
    bins = {}
    for t, v in motion:
        bins.setdefault(int(t // 2) * 2, [[], []])[0].append(v)
    for t, v in loud:
        bins.setdefault(int(t // 2) * 2, [[], []])[1].append(v)
    avg = lambda xs, d: sum(xs) / len(xs) if xs else d
    rows = [(t, avg(m, 0), avg(l, -90)) for t, (m, l) in sorted(bins.items())]
    top = max((m for _, m, _ in rows), default=0) or 1
    lines = [f"{t}\t{round(100 * m / top)}\t{l:.0f}dB" for t, m, l in rows]
    # liveliest non-overlapping windows by motion; loud seconds (barks, reactions) add a bonus
    score = {t: m * (1.5 if l > -25 else 1) for t, m, l in rows}
    wins = sorted(((sum(score.get(t + k, 0) for k in range(0, window, 2)), t) for t in score), reverse=True)
    best = []
    for sc, t in wins:
        if all(abs(t - b) >= window for b in best) and t + window <= rows[-1][0] + 2:
            best.append(t)
        if len(best) == 3:
            break
    return ["# start_sec  motion(0-100)  loudness", *lines,
            "# liveliest %ds windows: " % window + ", ".join(f"{t}-{t + window}" for t in best)]

def cmd_fetch(file_id, outdir):
    os.makedirs(outdir, exist_ok=True)
    files = drive_ls(FOLDER)
    f = next(x for x in files if x["id"] == file_id)
    base, ext = os.path.splitext(f["name"])
    video = drive_get(f["id"], os.path.join(outdir, "video" + ext))
    vid = find_id(f["name"])
    meta = youtube_meta(vid) or {"id": vid, "license": "unknown"}
    json.dump(meta, open(os.path.join(outdir, "meta.json"), "w"), ensure_ascii=False, indent=1)
    sub = next((x for x in files if x["name"].startswith(base) and x["name"].endswith((".srt", ".vtt"))), None)
    if sub:
        lines = srt_to_lines(open(drive_get(sub["id"], os.path.join(outdir, "sub" + sub["name"][-4:])), encoding="utf-8").read())
    else:
        try:
            lines = transcribe(video)
        except Exception as e:  # no transcript is survivable: the frame sheet still shows the content
            print(f"warning: transcription failed ({e}); use frames.jpg only", file=sys.stderr)
            lines = []
    open(os.path.join(outdir, "transcript.txt"), "w").write("\n".join(lines))
    dur = frames(video, os.path.join(outdir, "frames.jpg"))
    try:
        open(os.path.join(outdir, "moves.txt"), "w").write("\n".join(moves(video)))
    except Exception as e:  # only a helper for low-dialogue sources
        print(f"warning: moves.txt failed ({e})", file=sys.stderr)
    print(f"video={video} duration={dur:.0f}s license={meta['license']} transcript_lines={len(lines)}")
    if meta["license"] != "creativeCommon":
        print("WARNING: not Creative Commons on YouTube - do not use this source", file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "suggest":
        cmd_suggest()
    elif len(sys.argv) >= 2 and sys.argv[1] == "list":
        cmd_list()
    elif len(sys.argv) >= 2 and sys.argv[1] == "clean":
        cmd_clean()
    elif len(sys.argv) == 3 and sys.argv[1] == "moves":
        print("\n".join(moves(sys.argv[2])))
    elif len(sys.argv) == 4 and sys.argv[1] == "fetch":
        cmd_fetch(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
