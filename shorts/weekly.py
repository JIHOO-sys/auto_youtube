#!/usr/bin/env python3
"""weekly.py - the weekly long-form: this week's best character-series Shorts in one 16:9 video.

    python3 weekly.py [--days 7] [--n 10] [--dry]   # --dry: pick and render to weekly.mp4, don't upload

Picks the most-viewed public "<series> #n | ..." episodes of the last --days days (half per series when possible),
using the 720p copies upload.py --episode keeps in Drive 쇼츠보관, and lays them out on a blurred 1920x1080 canvas
after the 0.7 s channel intro. Uploads public with chapters and the sources in the description, adds it to the
"주간 몰아보기" playlist, then trashes the used week's copies from 쇼츠보관.
"""
import argparse, datetime, os, re, subprocess, sys, tempfile, urllib.error
from upload import ARCHIVE, api, drive_get, drive_ls, drive_trash, localizations, playlist_add, upload
from make import font

SERIES = ["수달 사쿠라", "바다코끼리 히마와리", "고릴라 샤바니"]
PLAYLIST = "주간 몰아보기"
INTRO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "intro.mp4")
MINT = "0xCDEEEA"

def episodes(days):
    """Public series episodes published in the last `days` days: dicts with id, title, series, views, published, desc."""
    pl = api("https://www.googleapis.com/youtube/v3/channels?part=contentDetails&mine=true")["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    ids, tok = [], ""
    for _ in range(5):  # newest first; a week is ~63 uploads
        r = api(f"https://www.googleapis.com/youtube/v3/playlistItems?part=contentDetails&maxResults=50&playlistId={pl}" + (f"&pageToken={tok}" if tok else ""))
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        tok = r.get("nextPageToken")
        if not tok:
            break
    out = []
    for k in range(0, len(ids), 50):
        for v in api("https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics,status&id=" + ",".join(ids[k:k + 50]))["items"]:
            sn = v["snippet"]
            ser = next((s for s in SERIES if re.match(re.escape(s) + r" #\d+ \|", sn["title"])), None)
            when = datetime.datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
            if ser and v["status"]["privacyStatus"] == "public" and when >= since:
                out.append({"id": v["id"], "title": sn["title"], "series": ser, "views": int(v["statistics"].get("viewCount", 0)),
                            "published": when, "desc": sn["description"]})
    return out

def pick(eps, n):
    """Top n by views, n//2 per series when both have enough, in publishing order."""
    by = {s: sorted([e for e in eps if e["series"] == s], key=lambda e: -e["views"]) for s in SERIES}
    chosen = [e for s in SERIES for e in by[s][:n // len(SERIES)]]
    rest = sorted([e for e in eps if e not in chosen], key=lambda e: -e["views"])
    chosen += rest[:n - len(chosen)]
    return sorted(chosen, key=lambda e: e["published"])

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
           f"[b]scale=-2:1080[fg];[bg][fg]overlay=(W-w)/2:0,setsar=1,"
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

def description(chosen, starts):
    # YouTube chapters: the first must be 0:00 and each at least 10 s, so the 0.7 s intro goes into the first one
    chap = [f"{mmss(s) if k else '0:00'} {e['title']}" for k, (e, s) in enumerate(zip(chosen, starts))]
    src = []
    for e in chosen:
        m = re.search(r"📺 원본: (.+)\n.*?youtu\.be/([A-Za-z0-9_-]{11})", e["desc"])
        if m:
            # watch?v= form on purpose: upload.recent() counts youtu.be links as source uses for the 3-Shorts limit
            line = f"· {m.group(1)}\n  https://www.youtube.com/watch?v={m.group(2)}"
            if line not in src:
                src.append(line)
    names = " & ".join(s.split()[-1] for s in SERIES)
    return (f"이번 주 {names} 쇼츠 중 가장 많이 본 {len(chosen)}편을 한 번에 몰아봐요 🦦🦭🦍\n\n" + "\n".join(chap) +
            "\n\n📺 원본 (크리에이티브 커먼즈 저작자 표시 CC BY)\n" + "\n".join(src) +
            "\n\n#돌뚜뿌꾸 #수달사쿠라 #바다코끼리히마와리 #고릴라샤바니 #수달 #바다코끼리 #고릴라 #동물 #귀여운동물 #동물더빙 #몰아보기")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7); p.add_argument("--n", type=int, default=10); p.add_argument("--dry", action="store_true")
    a = p.parse_args()
    files = {os.path.splitext(f["name"])[0]: f["id"] for f in drive_ls(ARCHIVE, "video/")}
    eps = [e for e in episodes(a.days) if e["id"] in files]
    if len(eps) < 3:
        sys.exit(f"only {len(eps)} archived episodes this week - skip the compilation")
    chosen = pick(eps, a.n)
    with tempfile.TemporaryDirectory() as tmp:
        clips = [(drive_get(files[e["id"]], os.path.join(tmp, f"src_{e['id']}.mp4")), e["title"].split(" | ")[0]) for e in chosen]
        out = "weekly.mp4" if a.dry else os.path.join(tmp, "weekly.mp4")
        starts = render(clips, out, tmp)
        kst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        title = f"이번 주 사쿠라 & 히마와리 & 샤바니 몰아보기 | {kst.month}월 {kst.day}일"
        desc = description(chosen, starts)
        if a.dry:
            print(title, desc, sep="\n\n"); sys.exit()
        ja = f"今週のさくら＆ヒマワリ＆シャバーニまとめ | {kst.month}月{kst.day}日"
        en = f"This Week with Sakura, Himawari & Shabani | {kst.strftime('%b')} {kst.day}"
        loc = localizations(desc, (ja, f"今週いちばん見られたカワウソさくら・セイウチのヒマワリ・ゴリラのシャバーニのショート{len(chosen)}本をまとめました🦦🦭🦍"),
                            (en, f"This week's {len(chosen)} most-watched Shorts of Sakura the otter, Himawari the walrus and Shabani the gorilla, back to back 🦦🦭🦍"))
        vid = upload(out, title, desc, "public", loc=loc)
    print(f"https://youtu.be/{vid}\t{title}")
    try:
        playlist_add(PLAYLIST, vid)
    except urllib.error.HTTPError as e:
        print(f"warning: playlist {PLAYLIST!r} not updated ({e.code})", file=sys.stderr)
    # this week's copies are done; newer (still scheduled) ones stay for next week
    for e in episodes(a.days):
        if e["id"] in files:
            drive_trash(files[e["id"]])
