#!/usr/bin/env python3
"""source.py - long-form source videos for 대신봐드림 review Shorts, from the Drive folder 롱폼원본.

    python3 source.py suggest           # CC candidates to download, per category (read-only)
    python3 source.py list              # videos in 롱폼원본: drive id, YouTube id, shorts already made from it
    python3 source.py fetch DRIVE_ID DIR # DIR/video.*, meta.json (YouTube title/channel/license), transcript.txt, frames.jpg

File names should contain the YouTube id in brackets, e.g. "세븐틴 브이로그 [md5zNFKvfvE].mp4" (yt-dlp's default);
otherwise the exact video title is looked up among CC videos.
A subtitle file with the same name (.srt/.vtt) is used as the transcript; otherwise faster-whisper transcribes.
"""
import datetime, html, json, os, re, subprocess, sys, urllib.parse
from upload import api, drive_get, drive_ls, recent

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

SEARCHES = ["아이돌 브이로그", "아이돌 비하인드", "kpop behind", "jpop", "pop music behind", "연예인 비하인드",
            "브이로그", "해외 생활", "외국 이야기", "로블록스", "생활꿀팁",
            "예능", "예능 레전드", "코미디빅리그", "1박2일", "개그", "몰래카메라", "웃긴 영상"]

def cmd_suggest():
    """CC candidates per category (read-only): already used/downloaded ids removed, best first by views."""
    seen = {src for _, src in recent()} | {find_id(f["name"]) for f in drive_ls(FOLDER, "video/")}
    after = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for q in SEARCHES:
        ids = [h["id"]["videoId"] for h in api("https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(
            {"part": "snippet", "type": "video", "videoLicense": "creativeCommon", "q": q, "maxResults": 15,
             "order": "viewCount", "publishedAfter": after, "relevanceLanguage": "ko"}))["items"]]
        ids = [i for i in ids if i not in seen]
        if not ids:
            continue
        vids = api("https://www.googleapis.com/youtube/v3/videos?part=snippet,status,statistics,contentDetails&id=" + ",".join(ids))["items"]
        print(f"== {q}")
        for v in sorted(vids, key=lambda v: -int(v["statistics"].get("viewCount", 0))):
            if v["status"]["license"] != "creativeCommon":
                continue
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
    print(f"video={video} duration={dur:.0f}s license={meta['license']} transcript_lines={len(lines)}")
    if meta["license"] != "creativeCommon":
        print("WARNING: not Creative Commons on YouTube - do not use this source", file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "suggest":
        cmd_suggest()
    elif len(sys.argv) >= 2 and sys.argv[1] == "list":
        cmd_list()
    elif len(sys.argv) == 4 and sys.argv[1] == "fetch":
        cmd_fetch(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
