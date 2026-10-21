#!/usr/bin/env python3
"""gemini_sample.py - Gemini TTS voice samples for the 속마음 dub, to compare against the Chirp3-HD VOICE.

  python3 shorts/gemini_sample.py [--out DIR] [--model M] [--text "..."] [VOICE ...]

Writes one <voice>.wav per voice (24 kHz mono). Reads GEMINI_API_KEY from the environment.
"""
import argparse, base64, json, os, urllib.request, wave

MODEL = "gemini-3.8-flash-tts"
VOICES = ["Kore", "Aoede", "Zephyr", "Leda", "Puck", "Fenrir"]
TEXT = "간식 봉지가 뜯겼어요. 범인은…? 저요? 저는... 집에 있는데요? 뽀뽀 한 번이면 다 용서돼요. …내일 또 먹어도 되겠죠?"
# Gemini TTS takes a spoken-style instruction in front of the line
STYLE = "능청스럽고 귀여운 강아지가 속마음을 말하듯, 밝고 조금 빠르게, 끊어 읽는 곳에서는 살짝 뜸을 들여서 읽어 주세요:"

def tts(text, out, voice, model=MODEL):
    body = {"contents": [{"parts": [{"text": f"{STYLE}\n{text.replace('*', '')}"}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                 json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    with urllib.request.urlopen(req) as r:
        pcm = base64.b64decode(json.loads(r.read())["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
    with wave.open(out, "wb") as w:  # raw 16-bit 24 kHz mono PCM
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("voices", nargs="*", default=VOICES)
    ap.add_argument("--out", default="samples")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--text", default=TEXT)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for v in a.voices:
        path = os.path.join(a.out, f"{v}.wav")
        tts(a.text, path, v, a.model)
        print(path)
