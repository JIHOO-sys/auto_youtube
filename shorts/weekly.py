#!/usr/bin/env python3
"""weekly.py - character recaps: 10 consecutive episodes of ONE series in one 16:9 video ("수달 사쿠라 #9~#18 몰아보기").

    python3 weekly.py [--n 10] [--max 1] [--dry]   # --dry: render the first ready recap to weekly.mp4, don't upload

For each series with at least --n archived public episodes (the copies upload.py --episode keeps in Drive 쇼츠보관),
takes the --n lowest-numbered ones, crops each to its picture + captions on a blurred 1920x1080 canvas after the 0.7 s
channel intro, and uploads it public with chapters and the sources in the description, into "<series> 몰아보기".
Those copies are then trashed; the rest wait for the next run. Characters are never mixed. --max recaps per run
(default 1, the series waiting longest first) so the day stays inside YouTube's ~10 uploads.
"""
import argparse, datetime, os, re, subprocess, sys, tempfile, urllib.error
from upload import ARCHIVE, SERIES_NAMES, api, drive_get, drive_ls, drive_trash, localizations, playlist_add, upload
from make import font

SERIES = ["수달 사쿠라", "바다코끼리 히마와리", "고릴라 샤바니"]
EMOJI = {"수달 사쿠라": "🦦", "바다코끼리 히마와리": "🦭", "고릴라 샤바니": "🦍"}
TAGS = {"수달 사쿠라": "#수달사쿠라 #수달", "바다코끼리 히마와리": "#바다코끼리히마와리 #바다코끼리", "고릴라 샤바니": "#고릴라샤바니 #고릴라"}
INTRO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "intro.mp4")
MINT = "0xCDEEEA"
CROP_TOP, CROP_H = 420, 1140  # make.py ZOOM_TOP, then the 960 px picture and the caption lines centred at y 1440

def episodes():
    """Public series episodes: dicts with id, title, series, n, published, desc."""
    pl = api("https://www.googleapis.com/youtube/v3/channels?part=contentDetails&mine=true")["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, tok = [], ""
    for _ in range(10):  # newest first
        r = api(f"https://www.googleapis.com/youtube/v3/playlistItems?part=contentDetails&maxResults=50&playlistId={pl}" + (f"&pageToken={tok}" if tok else ""))
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        tok = r.get("nextPageToken")
        if not tok:
            break
    ids = list(dict.fromkeys(ids))
    out = []
    for k in range(0, len(ids), 50):
        for v in api("https://www.googleapis.com/youtube/v3/videos?part=snippet,status&id=" + ",".join(ids[k:k + 50]))["items"]:
            sn = v["snippet"]
            m = next((m for s in SERIES for m in [re.match(re.escape(s) + r" #(\d+) \|", sn["title"])] if m), None)
            if m and v["status"]["privacyStatus"] == "public":
                out.append({"id": v["id"], "title": sn["title"], "series": sn["title"][:m.start(1) - 2], "n": int(m.group(1)),
                            "published": sn["publishedAt"], "desc": sn["description"]})
    return out

def ready(eps, files, n, most):
    """{series: its n lowest-numbered archived episodes} for up to `most` series that have n of them, longest-waiting first."""
    out = {}
    for s in SERIES:
        mine = sorted([e for e in eps if e["series"] == s and e["id"] in files], key=lambda e: (e["n"], e["published"]))
        if len(mine) >= n:
            out[s] = mine[:n]
    return dict(sorted(out.items(), key=lambda kv: kv[1][0]["published"])[:most])

def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

def render(clips, out, tmp):
    """clips: [(path, label)] -> out (1920x1080, intro first). Returns each clip's start second (after the intro)."""
    fontfile = os.path.join(font(), "Pretendard-ExtraBold.otf")
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
           "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "192k"]
    parts = [os.path.join(tmp, "intro.mp4")]
    ff("-i", INTRO, "-filter_complex", f"[0:v]scale=-2:1080,pad=1920:1080:(ow-iw)/2:0:color={MINT},setsar=1[v]",
       "-map", "[v]", "-map", "0:a", *enc, parts[0])
    for k, (path, label) in enumerate(clips):
        txt = os.path.join(tmp, f"{k}.txt")
        open(txt, "w").write(label)
        seg = os.path.join(tmp, f"{k}.mp4")
        ff("-i", path, "-filter_complex",
           "[0:v]split[a][b];[a]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=30:5,eq=brightness=-0.15[bg];"
           # only the Short's picture + caption band (y 420-1560 of 1080x1920): the title strip on top and the empty
           # bottom are dropped, so the animal is ~1.7x bigger than the whole 9:16 frame would be
           f"[b]crop=iw:ih*{CROP_H}/1920:0:ih*{CROP_TOP}/1920,scale=-2:1080[fg];[bg][fg]overlay=(W-w)/2:0,setsar=1,"
           f"drawtext=fontfile={fontfile}:textfile={txt}:x=60:y=60:fontsize=54:fontcolor=white:box=1:boxcolor=0xFF2E7E:boxborderw=18[v]",
           "-map", "[v]", "-map", "0:a", *enc, seg)
        parts.append(seg)
    starts, t = [], 0.0
    for p in parts:
        starts.append(t)
        t += float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]))
    lst = os.path.join(tmp, "list.txt")
    open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
    ff("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out)
    return starts[1:]

def mmss(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"

def description(series, chosen, starts):
    # YouTube chapters: the first must be 0:00 and each at least 10 s, so the 0.7 s intro goes into the first one
    chap = [f"{mmss(s) if k else '0:00'} {e['title'][len(series) + 1:]}" for k, (e, s) in enumerate(zip(chosen, starts))]
    src = []
    for e in chosen:
        m = re.search(r"📺 원본: (.+)\n.*?youtu\.be/([A-Za-z0-9_-]{11})", e["desc"])
        if m:
            # watch?v= form on purpose: upload.recent() counts youtu.be links as source uses for the per-source limit
            line = f"· {m.group(1)}\n  https://www.youtube.com/watch?v={m.group(2)}"
            if line not in src:
                src.append(line)
    return (f"{series} #{chosen[0]['n']}부터 #{chosen[-1]['n']}까지 {len(chosen)}편을 순서대로 한 번에 몰아봐요 {EMOJI[series]}\n\n" + "\n".join(chap) +
            "\n\n📺 원본 (크리에이티브 커먼즈 저작자 표시 CC BY)\n" + "\n".join(src) +
            f"\n\n#돌뚜뿌꾸 {TAGS[series]} #동물 #귀여운동물 #동물더빙 #몰아보기")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=10); p.add_argument("--dry", action="store_true")
    p.add_argument("--max", type=int, default=1)  # recaps per run: each is one more upload on top of the day's 9 Shorts
    a = p.parse_args()
    files = {os.path.splitext(f["name"])[0]: f["id"] for f in drive_ls(ARCHIVE, "video/")}
    todo = ready(episodes(), files, a.n, a.max)
    if not todo:
        sys.exit(f"no series has {a.n} archived episodes yet - skip")
    for series, chosen in todo.items():
        rng = f"#{chosen[0]['n']}~#{chosen[-1]['n']}"
        with tempfile.TemporaryDirectory() as tmp:
            clips = [(drive_get(files[e["id"]], os.path.join(tmp, f"src_{e['id']}.mp4")), e["title"].split(" | ")[0]) for e in chosen]
            out = "weekly.mp4" if a.dry else os.path.join(tmp, "weekly.mp4")
            starts = render(clips, out, tmp)
            title = f"{series} {rng} 몰아보기 | {len(chosen)}편 한 번에"
            desc = description(series, chosen, starts)
            if a.dry:
                print(title, desc, sep="\n\n"); sys.exit()
            ja, en = SERIES_NAMES[series]["ja"], SERIES_NAMES[series]["en"]
            loc = localizations(desc, (f"{ja} {rng} まとめ | {len(chosen)}本イッキ見", f"{ja}のショート{rng}を{len(chosen)}本、順番にまとめました{EMOJI[series]}"),
                                (f"{en} {rng} Compilation | {len(chosen)} Shorts in a Row", f"{en} Shorts {rng}, all {len(chosen)} back to back in order {EMOJI[series]}"))
            vid = upload(out, title, desc, "public", loc=loc)
        print(f"https://youtu.be/{vid}\t{title}")
        try:
            playlist_add(f"{series} 몰아보기", vid)
        except urllib.error.HTTPError as e:
            print(f"warning: playlist not updated ({e.code})", file=sys.stderr)
        for e in chosen:  # used; the newer copies wait for the next recap
            drive_trash(files[e["id"]])
