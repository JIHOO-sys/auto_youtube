---
name: yt-package
description: Write and lint the title and thumbnail for a YouTube video as one pairing, checking truncation, duplication and vagueness before publish. Use for "title ideas", "what should I call this", "thumbnail text", "my CTR is bad", packaging, or any request to rename or repackage an existing video.
---

# yt-package

> **언어 규칙:** 모든 결과(대본, 제목, 설명, 답글, 분석)는 한국어로 쓴다. 한국 시청자와 한국어 유튜브 기준으로 판단한다.

The title and the thumbnail are ONE unit. Writing them separately is why most packaging fails: the
thumbnail repeats the title, and half the click surface says the same thing twice.

```bash
python3 title.py --title "..." --thumb "AI RAN IT"
python3 title.py titles.txt            # one per line, ranked
```

## Before you write

1. Read `~/.claude/youtube/voice.md` if it exists. That is the user's voice profile: how they talk
   on camera, the words they never use, who they are talking to, what they will not claim. If it
   does not exist, ask for **three of their own videos**, read or transcribe them, infer the voice,
   and write the file. A script in the wrong voice is worse than no script, because they have to
   read it out loud.
2. Never invent a number, a result or a source. If a figure would strengthen it and you do not have
   one, ask for it or write the line without it.

## Rules the tool enforces, and why

- 한글은 한 글자가 영문 두 글자 폭이다. 한국어 제목은 PC 약 30자, 모바일 약 20자에서 잘린다.
- **60 characters** is where desktop search truncates, **40** is a mobile home feed. Both are
  reported because they fail differently: a desktop cut loses the tail, a mobile cut can lose the
  subject.
- **The thumbnail must not repeat the title.** Different words, same promise. (`title.py`는 조사를 떼고 비교한다: "유튜브가" = "유튜브")
- **Three words maximum on the thumbnail.** At feed size a fourth word is a grey smear.
- **A number, a name or a date** beats every adjective available to you. "역대급", "꿀팁", "대박", "총정리"는 막연한 표현으로 잡힌다.
- **Two all-caps words is the ceiling** before a title reads as spam.

## Write ten, keep two

Generate ten titles, run them all through `title.py`, show the user the top three with their scores
and the specific issue on each. For the winner, write the thumbnail brief: the expression, the
framing, the three words, and what the background has to do to hold contrast at feed size.

## The gate

Nothing here publishes. This skill writes and you publish. Every output ends in a block the user
copies, and the last line of every run is the question: **ship it, or change it?**
