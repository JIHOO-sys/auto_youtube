#!/usr/bin/env python3
"""deadair.py - an edit decision list from a timestamped transcript.

    python3 deadair.py transcript.srt            # or .vtt, or whisper .json
    python3 deadair.py transcript.srt --floor 0.35 --json

Finds three things and prints the cuts as a list you can act on, newest problem first:
  DEAD    gaps between spoken cues longer than the floor
  FILLER  cues that are only filler ("um", "so yeah", "basically")
  REPEAT  a sentence restarted - the second take of the same opening

WHAT IT DOES NOT DO. It does not cut the file. It prints an EDL, the total it would remove, and the
runtime you would land on, and you apply it in whatever editor you use. Nothing here touches media.

KOREAN. Korean fillers ("음", "어", "그니까", "뭐", "이제", "약간", "있잖아요") count as FILLER when a
cue is nothing but them. Restarts are compared on spoken syllables, not words, because Korean puts
few spaces in a sentence: two cues that open on the same six syllables, or a cue that is a cut-off
start of the next one, is a REPEAT. Fillers buried inside a real sentence cannot be cut from cue
timing alone, so they are counted and listed as TIC notes, not added to the cut total.
"""
import json, os, re, sys

FILLER_ONLY = re.compile(r"^[\s,.-]*((um+|uh+|er+|ah+|so|okay|ok|right|yeah|like|anyway|basically|"
                         r"actually|you know|i mean|let me see|hold on)[\s,.-]*)+$", re.I)
KO_FILLERS = (r"음+|으+음*|어+|엄+|아+|에+|그+|저+|그니까|그러니까|그니깐|뭐+|뭐랄까|뭐지|이제|약간|막|자|네+|"
              r"아무튼|좀|그게|그거|있잖아요?|그죠|그쵸|그래서|어쨌든|일단|진짜|그러면|흠+")
KO_FILLER_ONLY = re.compile(r"^[\s,.~…!?-]*((" + KO_FILLERS + r")[\s,.~…!?-]*)+$")
# a filler standing on its own inside a real sentence ("그니까 이게 음 중요한데")
KO_TIC = re.compile(r"(?<![\uac00-\ud7a3])(음+|어+|엄+|그니까|그러니까|뭐랄까|뭐+|약간|있잖아요?)(?![\uac00-\ud7a3])")
HANGUL = re.compile(r"[\uac00-\ud7a3]")

def is_filler(t): return bool(FILLER_ONLY.match(t) or KO_FILLER_ONLY.match(t))

def is_korean(t):
    letters = re.findall(r"[a-zA-Z\uac00-\ud7a3]", t)
    return bool(letters) and len(HANGUL.findall(t)) / len(letters) >= 0.5

def ko_syl(t):
    """Spoken syllables with the leading fillers peeled off, so "음 오늘은" and "오늘은" restart alike."""
    t = re.sub(r"^[\s,.~…!?-]*((" + KO_FILLERS + r")[\s,.~…!?-]+)+", "", t.strip())
    return "".join(re.findall(r"[\uac00-\ud7a30-9]", t))

def restart(prev, cur):
    """The words both attempts share, if cur is a second take of prev, else None."""
    if is_korean(prev) and is_korean(cur):
        a, b = ko_syl(prev), ko_syl(cur)
        if (len(a) >= 6 and len(b) >= 6 and a[:6] == b[:6]) or \
           (len(a) >= 4 and len(b) > len(a) and b.startswith(a)):         # abandoned first attempt
            return prev.strip()[:24]
        return None
    a1, b1 = norm(prev)[:5], norm(cur)[:5]
    return " ".join(a1) if len(a1) >= 3 and a1 == b1 else None

def parse_ts(s):
    s = s.strip().replace(",", ".")
    p = s.split(":")
    return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2]) if len(p) == 3 else int(p[0]) * 60 + float(p[1])

def load(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    if path.endswith(".json"):
        d = json.loads(raw)
        segs = d.get("segments", d if isinstance(d, list) else [])
        return [(float(s["start"]), float(s["end"]), (s.get("text") or "").strip()) for s in segs]
    cues, cur = [], None
    for line in raw.splitlines():
        m = re.match(r"\s*(\d[\d:.,]+)\s*-->\s*(\d[\d:.,]+)", line)
        if m:
            cur = [parse_ts(m.group(1)), parse_ts(m.group(2)), []]
            cues.append(cur)
        elif cur is not None and line.strip() and not line.strip().isdigit():
            cur[2].append(line.strip())
    return [(a, b, " ".join(t)) for a, b, t in cues if t]

def norm(t): return re.sub(r"[^a-z\uac00-\ud7a3 ]", "", t.lower()).split()

def main():
    a = sys.argv[1:]
    as_json = "--json" in a; a = [x for x in a if x != "--json"]
    floor = float(a[a.index("--floor") + 1]) if "--floor" in a else 0.45
    a = [x for x in a if not x.startswith("--") and not re.match(r"^[\d.]+$", x)]
    if not a or not os.path.exists(a[0]): print(__doc__); sys.exit(1)
    cues = load(a[0])
    if not cues: print("no cues found - is this an srt, vtt or whisper json?"); sys.exit(1)
    dur = cues[-1][1]
    cuts, tics = [], []
    for i, (s, e, t) in enumerate(cues):
        if is_filler(t):
            cuts.append({"kind": "FILLER", "start": s, "end": e, "why": t.strip()[:48]})
        else:
            found = KO_TIC.findall(t)
            if found:
                tics.append({"kind": "TIC", "start": s, "end": e,
                             "why": f'{len(found)} in-line: {", ".join(found)}  "{t.strip()[:40]}"'})
        if i:
            gap = s - cues[i - 1][1]
            if gap > floor:
                keep = floor / 2
                cuts.append({"kind": "DEAD", "start": round(cues[i - 1][1] + keep, 3),
                             "end": round(s - keep, 3), "why": f"{gap:.2f}s gap"})
        # A restart is compared against the last cue that was actually SPEECH. Comparing against
        # the literal previous cue misses every retake with an "um" between the two attempts, which
        # is most of them.
        if t.strip() and not is_filler(t):
            j = i - 1
            while j >= 0 and (is_filler(cues[j][2]) or not cues[j][2].strip()): j -= 1
            if j >= 0:
                shared = restart(cues[j][2], t)
                if shared:
                    cuts.append({"kind": "REPEAT", "start": cues[j][0], "end": cues[j][1],
                                 "why": f'restart of "{shared}"'})
    cuts = [c for c in cuts if c["end"] > c["start"]]
    cuts.sort(key=lambda c: c["start"])
    removed = sum(c["end"] - c["start"] for c in cuts)
    if as_json:
        print(json.dumps({"source": a[0], "duration": dur, "cuts": cuts, "tics": tics,
                          "removed": round(removed, 3), "out": round(dur - removed, 3)},
                         indent=1, ensure_ascii=False)); return
    print(f"\n  {a[0]}   {dur:.2f}s in, {len(cues)} cues, dead-air floor {floor}s\n")
    for c in cuts:
        print(f"    {c['kind']:<7} {c['start']:8.2f} -> {c['end']:8.2f}   {c['end']-c['start']:5.2f}s   {c['why']}")
    print(f"\n  {len(cuts)} cuts, {removed:.2f}s removed, {dur - removed:.2f}s out "
          f"({removed / dur * 100:.1f}% shorter)\n")
    if tics:
        print(f"  {len(tics)} cues carry in-line fillers - not cut, trim them by ear:\n")
        for c in tics:
            print(f"    {c['kind']:<7} {c['start']:8.2f} -> {c['end']:8.2f}   {c['why']}")
        print()

if __name__ == "__main__":
    main()
