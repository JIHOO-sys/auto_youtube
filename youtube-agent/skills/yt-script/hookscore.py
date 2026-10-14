#!/usr/bin/env python3
"""hookscore.py - score a YouTube hook before you waste a take on it.

Five properties, 0-100 each, and a verdict that is 60% the mean and 40% the weakest one. The
weakest-link weighting is deliberate: a hook with four strong properties and one dead one is a hook
that leaks at the dead one, and averaging hides that.

    python3 hookscore.py hooks.txt            # one hook per line, ranked
    python3 hookscore.py --hook "one line"    # score a single hook
    python3 hookscore.py --json hooks.txt     # machine-readable

WHAT THIS CAN AND CANNOT TELL YOU. Measured against 74 real short-form hooks (first 15 seconds of
auto-captions, top-8 and bottom-8 by views across five channels): it separates deliberately bad
hooks from real ones well, and it separates a creator's own hits from their own misses barely at
all. Treat a low score as a reason to look again, never a high score as a promise.

KOREAN. A hook that is mostly Hangul is scored with Korean rules: length is counted in spoken
syllables (18-55 is the band), and address, stakes, curiosity and vagueness are read from Korean
expressions ("여러분", "만원", "왜", "날리다", "역대급"). Korean has no spaces before particles, so
the Korean patterns never end in a word boundary - "채널이" still matches "채널".
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
FORMULAS = json.load(open(os.path.join(HERE, "hooks.json"), encoding="utf-8"))["hooks"]

FILLER = {"basically","actually","literally","just","really","very","so","kind","sort","like",
          "guys","hey","welcome","today","video","subscribe","channel"}
VAGUE = {"amazing","incredible","insane","crazy","huge","massive","game","changer","secret",
         "powerful","ultimate","best","revolutionary","mind","blowing","unbelievable"}
CONCRETE = re.compile(r"\b(\d[\d,.]*\s?(%|k|m|x|s|m|h)?|\$\d|\d+\s?(second|minute|hour|day|week|month|year)s?)\b", re.I)
YOU = re.compile(r"\b(you|your|you're|youre|yourself)\b", re.I)
STAKE = re.compile(r"\b(lose|lost|wasting|waste|quit|fail|broke|cost|risk|before|stop|never|die|dying|dead)\b", re.I)
CURIOSITY = re.compile(r"\b(why|how|what|which|until|before|but|nobody|almost|except|reason|actually)\b", re.I)

def words(t): return re.findall(r"[a-z0-9'%$.]+", t.lower())

# --- Korean --------------------------------------------------------------------------------------
HANGUL = re.compile(r"[\uac00-\ud7a3]")

def is_korean(t):
    letters = re.findall(r"[a-zA-Z\uac00-\ud7a3]", t)
    return bool(letters) and len(HANGUL.findall(t)) / len(letters) >= 0.5

def syllables(t):
    """Spoken length: one per Hangul syllable, one per digit, two per Latin word ("AI", "GPT")."""
    return len(HANGUL.findall(t)) + len(re.findall(r"\d", t)) + 2 * len(re.findall(r"[A-Za-z]+", t))

KO_CONCRETE = re.compile(r"\d[\d,.]*\s?(%|퍼센트|프로|만\s?원|억|천|만|원|명|개월|개|배|일|주|달|년|분|초|시간|회|위|번|살|뷰)?"
                         r"|(백|천|만|억|천만|백만)\s?(원|명|뷰)|(두|세|네|열)\s?배")
KO_VAGUE = ["역대급", "대박", "미친", "엄청", "레전드", "충격", "꿀팁", "완벽", "끝판왕", "소름", "핵꿀",
            "놀라운", "어마어마", r"장난\s?아닌", "인생템", "최강", "무조건"]
# short fillers only count when they stand alone - "뭐" is filler, "뭐가" is a question
KO_FILLER = ["그냥", "약간", "그니까", "아무튼", "솔직히", "안녕하세요", "구독", "좋아요", "오늘은",
             "영상에서는", r"(?<![가-힣])(이제|뭐|좀|음+|어+|진짜)(?![가-힣])"]
KO_YOU = re.compile(r"여러분|당신|너희|님들|시(는|면|죠|나요|고|게|던)|셔(도|서|야)|세요|십시오")
KO_STAKE = re.compile(r"날리|날려|날린|잃|손해|망하|망한|망했|버리|버린|낭비|놓치|놓친|그만두|포기|실패|후회|"
                      r"위험|막히|막힌|떨어지|떨어진|돈|전에|절대|끝장|사라지|날아가")
KO_CURIOSITY = re.compile(r"왜|어떻게|무엇|뭐가|뭘|어떤|사실은?|진짜\s?이유|이유|아무도|근데|그런데|하지만|"
                          r"딱\s?하나|비밀|까지|전에|빼고|말고|거의|단\s?하나|숨겨진")
# "기 때문에" explains the result and closes the gap; "이 설정 하나 때문에" names a cause and keeps it open
KO_CLOSED = re.compile(r"기\s?때문에|그래서|그러니까|덕분에|이라서|이니까|하니까")
KO_LABEL = {"SPECIFICITY": "구체성", "ADDRESS": "말걸기", "STAKES": "손실감", "CURIOSITY": "궁금증",
            "BREVITY": "길이"}

def _count(pats, t): return sum(len(re.findall(p, t)) for p in pats)

def ko_specificity(t):
    nums = sum(1 for m in KO_CONCRETE.finditer(t) if m.group(0).strip())
    s = 34 + nums * 22 - _count(KO_VAGUE, t) * 16 - _count(KO_FILLER, t) * 5
    # Latin brand or product names inside a Korean line ("ChatGPT", "캡컷" aside) read as named things
    s += min(18, 6 * len(re.findall(r"\b[A-Z][A-Za-z0-9]+", t)))
    return max(0, min(100, s))

def ko_address(t):
    n = len(KO_YOU.findall(t))
    # "여러분" inside the first twelve spoken syllables, the Korean version of "you" in the first six words
    pos = [m.start() for m in HANGUL.finditer(t)]
    head = t[:pos[11] + 1] if len(pos) > 12 else t
    first = 30 if re.search(r"여러분|당신|너희|님들", head) else 0
    return max(0, min(100, 26 + n * 20 + first))

def ko_stakes(t):
    n = len(KO_STAKE.findall(t))
    return max(0, min(100, 22 + n * 26 + (14 if KO_CONCRETE.search(t) and re.search(r"\d|백|천|만|억", t) else 0)))

def ko_curiosity(t):
    n = len(KO_CURIOSITY.findall(t))
    q = 18 if re.search(r"(\?|까요|나요|ㄹ까|을까|일까)\s*$", t.strip()) else 0
    closed = -18 if KO_CLOSED.search(t) else 0
    return max(0, min(100, 24 + n * 17 + q + closed))

def ko_brevity(t):
    n = syllables(t)
    if n == 0: return 0
    # 18-55 syllables is what a Korean speaker gets through in about 10 seconds without rushing
    if 18 <= n <= 55: return 100
    if n < 18: return max(30, 100 - (18 - n) * 5)
    return max(10, 100 - (n - 55) * 3)

def specificity(t):
    w = words(t)
    if not w: return 0
    nums = len(CONCRETE.findall(t))
    vague = sum(1 for x in w if x in VAGUE)
    filler = sum(1 for x in w if x in FILLER)
    s = 34 + nums * 22 - vague * 16 - filler * 5
    # proper nouns that are not sentence-initial read as named things
    s += min(18, 6 * sum(1 for x in t.split()[1:] if x[:1].isupper()))
    return max(0, min(100, s))

def address(t):
    n = len(YOU.findall(t))
    first = 30 if YOU.search(" ".join(t.split()[:6])) else 0
    return max(0, min(100, 26 + n * 20 + first))

def stakes(t):
    n = len(STAKE.findall(t))
    return max(0, min(100, 22 + n * 26 + (14 if CONCRETE.search(t) else 0)))

def curiosity(t):
    n = len(CURIOSITY.findall(t))
    q = 18 if t.strip().endswith("?") else 0
    # a hook that resolves itself has no gap left
    closed = -18 if re.search(r"\b(because|so that|which means)\b", t, re.I) else 0
    return max(0, min(100, 24 + n * 17 + q + closed))

def brevity(t):
    n = len(words(t))
    if n == 0: return 0
    # 9-24 words is the band a spoken hook lands in at ~150wpm inside 10 seconds
    if 9 <= n <= 24: return 100
    if n < 9:  return max(30, 100 - (9 - n) * 11)
    return max(10, 100 - (n - 24) * 7)

PROPS = [("SPECIFICITY", specificity), ("ADDRESS", address), ("STAKES", stakes),
         ("CURIOSITY", curiosity), ("BREVITY", brevity)]
KO_PROPS = [("SPECIFICITY", ko_specificity), ("ADDRESS", ko_address), ("STAKES", ko_stakes),
            ("CURIOSITY", ko_curiosity), ("BREVITY", ko_brevity)]

def classify(t):
    best, hits = None, 0
    for f in FORMULAS:
        n = sum(1 for p in f["match"] if re.search(p, t, re.I))
        if n > hits: best, hits = f, n
    return (best["name"] if best else "Unclassified"), hits

def score(t):
    parts = {n: fn(t) for n, fn in (KO_PROPS if is_korean(t) else PROPS)}
    vals = list(parts.values())
    verdict = round(0.6 * (sum(vals) / len(vals)) + 0.4 * min(vals))
    name, hits = classify(t)
    return parts, verdict, name, hits

def band(v): return "STRONG" if v >= 72 else "WORKABLE" if v >= 55 else "WEAK"

def report(t, parts, verdict, name, hits):
    if is_korean(t): return report_ko(t, parts, verdict, name, hits)
    print(f"\n  {t.strip()}")
    print(f"  {'-' * min(72, max(20, len(t.strip())))}")
    for k, v in parts.items():
        print(f"    {k:<12} {v:3d}  {'#' * (v // 5)}")
    print(f"    {'VERDICT':<12} {verdict:3d}  {band(verdict)}")
    print(f"    formula      {name}" + (f"  ({hits} pattern{'s' if hits != 1 else ''} matched)" if hits else "  (no formula matched - that is usually a summary, not a hook)"))
    low = min(parts, key=parts.get)
    print(f"    weakest      {low} - {FIX[low]}")

BAND_KO = {"STRONG": "강함", "WORKABLE": "쓸만함", "WEAK": "약함"}

def report_ko(t, parts, verdict, name, hits):
    print(f"\n  {t.strip()}   ({syllables(t)}음절)")
    print(f"  {'-' * min(72, max(20, len(t.strip()) * 2))}")
    for k, v in parts.items():
        print(f"    {KO_LABEL[k]:<6} {k:<12} {v:3d}  {'#' * (v // 5)}")
    print(f"    {'종합':<6} {'VERDICT':<12} {verdict:3d}  {band(verdict)} ({BAND_KO[band(verdict)]})")
    ko = next((f.get("example_ko") for f in FORMULAS if f["name"] == name), None)
    print(f"    공식         {name}" + (f"  (패턴 {hits}개 일치)" if hits else "  (일치하는 공식 없음 - 훅이 아니라 요약일 가능성이 큽니다)"))
    if ko: print(f"    공식 예시    {ko}")
    low = min(parts, key=parts.get)
    print(f"    가장 약한 곳 {KO_LABEL[low]} - {FIX_KO[low]}")

FIX_KO = {
 "SPECIFICITY": "'역대급', '대박' 같은 말 대신 숫자, 이름, 날짜를 하나 넣으세요 (예: 3일, 50만원, 구독자 1만)",
 "ADDRESS": "첫 마디 안에 '여러분'을 넣거나 시청자에게 직접 말을 거세요",
 "STAKES": "지금 방식대로 하면 무엇을 잃는지 말하세요 (돈을 날린다, 시간을 버린다)",
 "CURIOSITY": "스스로 답해버리는 뒷부분('~기 때문에', '그래서')을 잘라내고 '왜'를 남기세요",
 "BREVITY": "18~55음절. 소리 내어 읽고 숨이 찰 때 끊으세요",
}

FIX = {
 "SPECIFICITY": "swap one adjective for a number, a name or a date",
 "ADDRESS": "say 'you' in the first six words",
 "STAKES": "name what it costs them to keep doing it the current way",
 "CURIOSITY": "cut the half of the sentence that answers itself",
 "BREVITY": "9 to 24 words. Read it out loud and stop where you run out of breath",
}

def main():
    a = sys.argv[1:]
    as_json = "--json" in a
    a = [x for x in a if x != "--json"]
    if "--hook" in a:
        lines = [a[a.index("--hook") + 1]]
    elif a and os.path.exists(a[0]):
        lines = [l for l in open(a[0], encoding="utf-8").read().splitlines() if l.strip()]
    else:
        print(__doc__); sys.exit(1 if not a else 0)
    out = []
    for t in lines:
        parts, verdict, name, hits = score(t)
        out.append({"hook": t.strip(), "lang": "ko" if is_korean(t) else "en",
                    "properties": parts, "verdict": verdict,
                    "band": band(verdict), "formula": name, "matched": hits})
    out.sort(key=lambda r: -r["verdict"])
    if as_json:
        print(json.dumps([{k: v for k, v in r.items() if k != "matched"} for r in out], indent=1, ensure_ascii=False)); return
    for r in out:
        report(r["hook"], r["properties"], r["verdict"], r["formula"], r["matched"])
    if len(out) > 1:
        print(f"\n  winner: {out[0]['hook'].strip()}  ({out[0]['verdict']}, {out[0]['band']})\n")

if __name__ == "__main__":
    main()
