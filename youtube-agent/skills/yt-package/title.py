#!/usr/bin/env python3
"""title.py - lint a YouTube title and thumbnail pairing before you publish it.

    python3 title.py --title "..." --thumb "AI RAN IT"
    python3 title.py titles.txt            # one per line, ranked
    python3 title.py --title "..." --json

The pairing is the unit, not the title. A title that repeats the thumbnail text wastes half the
click surface, and that is the single most common mistake this checks for.

Length: YouTube truncates around 60 characters on desktop search and around 40 on a mobile home
feed. Both limits are reported because they are different failures - a desktop truncation loses the
tail, a mobile one can lose the subject.

KOREAN. Length is measured in display width: a Hangul syllable is as wide as two Latin letters, so
a Korean title hits the desktop cut near 30 syllables and the mobile one near 20. Duplicates are
compared after the particles are stripped ("유튜브가", "유튜브를" and "유튜브" are one word), and the
vague-word check knows "역대급", "꿀팁", "대박" and friends. The 100-character hard limit is
YouTube's own and counts characters, not width.
"""
import json, re, sys, os, unicodedata

DESKTOP, MOBILE, HARD = 60, 40, 100
VAGUE = {"amazing","incredible","insane","crazy","huge","massive","ultimate","best","powerful",
         "secret","revolutionary","mindblowing","epic","perfect","complete","everything"}
STOP = {"the","a","an","of","for","to","in","on","and","or","is","are","with","your","you","my","i",
        "this","that","it","how","what","why"}

KO_VAGUE = ["역대급", "꿀팁", "대박", "미친", "레전드", "충격", "완벽", "끝판왕", "소름", "최고", "최강",
            "꿀템", "인생템", "필수", "무조건", "총정리", "모든 것", "놀라운", "어마어마", "핵꿀"]
KO_STOP = {"이", "그", "저", "이거", "그거", "저거", "이것", "제", "내", "나", "저는", "나는", "너", "수",
           "것", "거", "왜", "어떻게", "뭐", "무엇", "진짜", "정말", "하는", "하기", "한", "할", "했다",
           "하면", "있는", "없는", "더", "다", "꼭", "좀", "여러분", "모든", "법", "방법"}
# longest first, so "에서" is stripped before "서" would be
PARTICLES = sorted("은 는 이 가 을 를 에 의 도 만 와 과 로 으로 에서 에게 한테 께 랑 이랑 하고 까지 부터 "
                   "보다 처럼 마다 이나 나 이란 란 이라 라 으론 로는 에는 에선 이다 입니다 이에요 예요 "
                   "이요 요 들".split(), key=len, reverse=True)
HANGUL = re.compile(r"[가-힣]")
NUM = re.compile(r"\d[\d,.]*\s?(%|만\s?원|만|억|천|원|명|개월|개|배|일|주|달|년|분|초|시간|회|위|번|살|뷰)?"
                 r"|(백|천|만|억|천만|백만)\s?(원|명|뷰)")

def words(t): return re.findall(r"[a-z0-9']+", t.lower())

def is_korean(t):
    letters = re.findall(r"[a-zA-Z가-힣]", t)
    return bool(letters) and len(HANGUL.findall(t)) / len(letters) >= 0.5

def width(t):
    """Display width: Hangul and other wide characters count as two Latin letters."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in t)

def cut(t, w):
    """The longest prefix of t that fits in display width w, broken at a space when there is one."""
    out, n = "", 0
    for c in t:
        n += width(c)
        if n > w: break
        out += c
    return out.rsplit(" ", 1)[0] if " " in out and len(out) < len(t) else out

def stem(tok):
    for p in PARTICLES:
        if len(tok) > len(p) and tok.endswith(p):
            return tok[: -len(p)]
    return tok

def ko_words(t):
    """Tokens with particles stripped: Hangul runs, Latin words and numbers."""
    toks = re.findall(r"[가-힣]+|[a-z0-9']+", t.lower())
    return [stem(x) if HANGUL.match(x) else x for x in toks]

def content(t):
    if is_korean(t): return {w for w in ko_words(t) if w not in KO_STOP and w not in STOP}
    return set(words(t)) - STOP

def check(title, thumb=None):
    t = title.strip()
    ko = is_korean(t) or bool(thumb and is_korean(thumb))
    n, w = len(t), width(t)
    issues, good = [], []
    if ko:
        if n > HARD: issues.append(("length", f"{n}자 - 유튜브 제목 최대 길이는 {HARD}자입니다"))
        elif w > DESKTOP: issues.append(("length", f"폭 {w} (한글 1자 = 영문 2자) - PC 검색에서 폭 {DESKTOP}, 한글 약 {DESKTOP // 2}자 근처에서 잘립니다"))
        else: good.append(f"폭 {w}, PC 검색 잘림선({DESKTOP}) 안쪽")
        if w > MOBILE:
            issues.append(("mobile", f'모바일 피드에는 "{cut(t, MOBILE)}..." 까지만 보입니다 - 핵심 단어가 살아남는지 확인하세요'))
    else:
        if n > HARD: issues.append(("length", f"{n} characters - YouTube's hard limit is {HARD}"))
        elif n > DESKTOP: issues.append(("length", f"{n} characters - desktop search cuts near {DESKTOP}"))
        else: good.append(f"{n} characters, inside the {DESKTOP}-character desktop cut")
        if n > MOBILE:
            head = t[:MOBILE].rsplit(" ", 1)[0]
            issues.append(("mobile", f'a mobile feed shows about "{head}..." - check the subject survives'))
    caps = [x for x in t.split() if len(x) > 2 and x.isupper() and x.isascii()]
    if len(caps) > 2: issues.append(("shouting", f"대문자 단어 {len(caps)}개 - 두 개를 넘으면 스팸처럼 보입니다" if ko else
                                     f"{len(caps)} all-caps words - two is the ceiling before it reads as spam"))
    elif caps: good.append(f"강조용 대문자 단어 {len(caps)}개" if ko else f"{len(caps)} all-caps word for emphasis")
    v = sorted(set(x for x in words(t) if x in VAGUE) | {k for k in KO_VAGUE if k in t})
    if v: issues.append(("vague", f"{', '.join(v)} - 숫자, 이름, 날짜로 바꾸세요 (예: '꿀팁' 대신 '3분 만에 끝내는')" if ko else
                         f"{', '.join(v)} - swap for a number, a name or a date"))
    nums = [m.group(0).strip() for m in NUM.finditer(t) if m.group(0).strip()]
    if nums: good.append(f"구체적인 숫자 포함 ({', '.join(nums[:3])})" if ko else f"carries a concrete figure ({', '.join(nums[:3])})")
    else: issues.append(("no-number", "숫자, 날짜, 이름이 없습니다 - 가장 확실한 한 가지 개선입니다" if ko else
                         "no number, date or name - the most reliable single fix"))
    if t.endswith("?") or (ko and re.search(r"(까요|나요|일까|을까)\??$", t)):
        good.append("제목에 열린 질문" if ko else "open question in the title")
    if ko:
        front = [x for x in ko_words(t)[:3] if x not in KO_STOP and x not in STOP]
        if not front: issues.append(("front-load", "앞 세 단어가 모두 군더더기입니다 - 주제를 앞으로 당기세요"))
    else:
        front = [x for x in words(t)[:3] if x not in STOP]
        if not front: issues.append(("front-load", "the first three words are all filler - move the subject forward"))
    if thumb:
        tw, hw = content(t), content(thumb)
        shared = tw & hw
        if ko:
            # compounds: "수익" on the thumbnail inside "유튜브수익" in the title is still a repeat
            shared |= {h for h in hw if len(h) >= 2 and HANGUL.match(h) and any(h in x and h != x for x in tw)}
        if shared:
            issues.append(("duplicate", f"제목과 썸네일에 같은 단어가 반복됩니다: {', '.join(sorted(shared))} - 썸네일은 제목이 말하지 않는 것을 말해야 합니다" if ko else
                                        f"thumbnail repeats the title on {', '.join(sorted(shared))} - "
                                        "the thumbnail should say what the title does not"))
        else:
            good.append("썸네일과 제목이 서로 다른 단어를 씁니다" if ko else "thumbnail and title carry different words")
        if ko and is_korean(thumb):
            syl = len(HANGUL.findall(thumb))
            if len(thumb.split()) > 4 or syl > 12:
                issues.append(("thumb-length", f"썸네일 문구 {syl}음절, {len(thumb.split())}어절 - 피드 크기에서는 3어절, 10음절 안팎이 한계입니다"))
        elif len(words(thumb)) > 4:
            issues.append(("thumb-length", f"{len(words(thumb))} words on the thumbnail - three is the ceiling at feed size"))
    score = max(0, min(100, 100 - 14 * len(issues) + 4 * len(good)))
    return {"title": t, "lang": "ko" if ko else "en", "chars": n, "width": w, "score": score,
            "issues": issues, "good": good}

def show(r):
    print(f'\n  "{r["title"]}"')
    if r["lang"] == "ko":
        print(f"  {r['chars']}자 (폭 {r['width']})   점수 {r['score']}/100")
    else:
        print(f"  {r['chars']} chars   score {r['score']}/100")
    for k, m in r["issues"]: print(f"    x  {k:<12} {m}")
    for m in r["good"]:      print(f"    ok              {m}")

def main():
    a = sys.argv[1:]
    as_json = "--json" in a; a = [x for x in a if x != "--json"]
    thumb = a[a.index("--thumb") + 1] if "--thumb" in a else None
    if "--title" in a:
        rows = [check(a[a.index("--title") + 1], thumb)]
    elif a and os.path.exists(a[0]):
        with open(a[0], encoding="utf-8") as f:
            rows = [check(l, thumb) for l in f.read().splitlines() if l.strip()]
    else:
        print(__doc__); sys.exit(1)
    rows.sort(key=lambda r: -r["score"])
    if as_json: print(json.dumps(rows, indent=1, ensure_ascii=False)); return
    for r in rows: show(r)
    print()

if __name__ == "__main__":
    main()
