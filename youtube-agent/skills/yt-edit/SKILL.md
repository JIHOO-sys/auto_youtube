---
name: yt-edit
description: Turn a raw recording's transcript into an edit decision list - dead air, filler cues and retakes, with timecodes. Use for "edit this", "cut the dead space", "tighten this video", "I rambled", or any request to shorten footage from a transcript.
---

# yt-edit

> **언어 규칙:** 모든 결과(대본, 제목, 설명, 답글, 분석)는 한국어로 쓴다. 한국 시청자와 한국어 유튜브 기준으로 판단한다.

An edit decision list from a timestamped transcript. It prints the cuts. You apply them.

```bash
python3 deadair.py transcript.srt              # srt, vtt or whisper json
python3 deadair.py transcript.srt --floor 0.35 --json
```

No transcript yet? Ask for one, or produce one first - `whisper`, `faster-whisper`, or the caption
track YouTube generates on an unlisted upload all work. Do not guess at timings.

## What it finds

- **DEAD** - gaps longer than the floor, trimmed from the MIDDLE so both sides keep a breath.
  Cutting flush against speech is what makes a tightened take sound gasping.
- **FILLER** - cues that are nothing but "um", "so yeah", "basically" - or "음", "어", "그니까", "뭐", "이제".
- **TIC** - 문장 중간에 섞인 한국어 추임새. 자막 타이밍만으로는 잘라낼 수 없어서 컷 합계에 넣지 않고 위치만 알려준다.
- **REPEAT** - a sentence restarted. Compared against the last cue that was actually speech, not
  the literal previous cue, because most retakes have an "um" between the two attempts.
  한국어는 띄어쓰기 대신 음절로 비교한다: 앞 6음절이 같거나, 앞 문장이 다음 문장의 앞부분에서 끊긴 경우.

## What it will not do

It does not touch media. It has no opinion about your B-roll. A 40% cut on the report is a 40% cut
of SPEECH, and if the video has a long silent demo in it that number is wrong - check the report
against the footage before you trust the runtime at the bottom.

## The gate

Nothing here publishes. This skill writes and you publish. Every output ends in a block the user
copies, and the last line of every run is the question: **ship it, or change it?**
