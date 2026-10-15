#!/usr/bin/env python3
"""upload.py - upload one video to YouTube with only the stdlib.

    python3 upload.py video.mp4 --title "..." [--desc "..."] [--privacy private|unlisted|public]
    python3 upload.py video.mp4 --title "..." --desc "..." --publish-at 2026-10-15T07:30:00+09:00   # scheduled
    python3 upload.py --recent          # last 50 uploads: title <TAB> source YouTube id, to avoid repeats

Reads YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN from the environment
(optional DRIVE_REFRESH_TOKEN: a different Google account for Drive, e.g. when the channel is a Brand Account).
A vertical video under 3 minutes is treated as a Short by YouTube automatically.
"""
import argparse, datetime, json, os, re, shutil, sys, urllib.parse, urllib.request

def access_token(drive=False):
    # A Brand Account channel has no Drive of its own, so Drive may use a separate token (DRIVE_REFRESH_TOKEN)
    token = (drive and os.environ.get("DRIVE_REFRESH_TOKEN")) or os.environ["YT_REFRESH_TOKEN"]
    body = urllib.parse.urlencode({
        "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": token, "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", body) as r:
        return json.load(r)["access_token"]

def upload(path, title, desc, privacy, publish_at=None):
    tok = access_token()
    tags = [w.lstrip("#") for w in desc.split() if w.startswith("#")]
    meta = {"snippet": {"title": title[:100], "description": desc, "tags": tags, "categoryId": "26",
                        "defaultLanguage": "ko", "defaultAudioLanguage": "ko"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
    if publish_at:  # YouTube flips a scheduled video from private to public at this moment
        when = datetime.datetime.fromisoformat(publish_at).astimezone(datetime.timezone.utc)
        if when > datetime.datetime.now(datetime.timezone.utc):
            meta["status"].update(privacyStatus="private", publishAt=when.strftime("%Y-%m-%dT%H:%M:%SZ"))
        else:
            meta["status"]["privacyStatus"] = "public"  # slot already passed: publish now
    req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        data=json.dumps(meta).encode(), method="POST",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/*", "X-Upload-Content-Length": str(os.path.getsize(path))})
    with urllib.request.urlopen(req) as r:
        loc = r.headers["Location"]
    # ponytail: single PUT, no chunk resume - fine for Shorts (<100MB); add chunking if uploads time out
    with open(path, "rb") as f:
        put = urllib.request.Request(loc, data=f.read(), method="PUT",
                                     headers={"Authorization": f"Bearer {tok}", "Content-Type": "video/*"})
        with urllib.request.urlopen(put) as r:
            return json.load(r)["id"]

def api(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token('/drive/' in url)}"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)

def drive_ls(folder, mime=""):
    """Files (id, name, size) in the channel account's Drive folder with this name."""
    ls = lambda q: api("https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode(
        {"q": q + " and trashed=false", "pageSize": 1000, "fields": "files(id,name,size,mimeType)"}))["files"]
    found = ls(f"name='{folder}' and mimeType='application/vnd.google-apps.folder'")
    if not found:
        return []
    return [f for f in ls(f"'{found[0]['id']}' in parents") if f["mimeType"].startswith(mime)]

def drive_get(file_id, path):
    req = urllib.request.Request(f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
                                 headers={"Authorization": f"Bearer {access_token(drive=True)}"})
    with urllib.request.urlopen(req) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f)  # source videos can be GBs; stream, don't buffer
    return path

def recent():
    """(title, source YouTube id or "") of the last 50 uploads; the id comes from the 원본 link in the description."""
    pl = api("https://www.googleapis.com/youtube/v3/channels?part=contentDetails&mine=true")["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    items = api(f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=50&playlistId={pl}")["items"]
    out = []
    for i in items:
        m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", i["snippet"]["description"])
        out.append((i["snippet"]["title"], m.group(1) if m else ""))
    return out

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("video", nargs="?"); p.add_argument("--title"); p.add_argument("--recent", action="store_true")
    p.add_argument("--desc", default=""); p.add_argument("--privacy", default="private")
    p.add_argument("--publish-at", help="ISO time with offset, e.g. 2026-10-15T07:30:00+09:00")
    a = p.parse_args()
    missing = [k for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN") if not os.environ.get(k)]
    if missing: sys.exit(f"missing env: {', '.join(missing)}")
    if a.recent:
        print("\n".join(f"{t}\t{src}" for t, src in recent())); sys.exit()
    if not (a.video and a.title): p.error("video and --title are required")
    if a.desc.count("#") < 3: p.error("--desc needs a content summary and at least 3 #hashtags")
    vid = upload(a.video, a.title, a.desc, a.privacy, a.publish_at)
    print(f"https://youtube.com/shorts/{vid}")
