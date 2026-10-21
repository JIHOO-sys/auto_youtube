#!/usr/bin/env python3
"""brand.py - render 돌뚜뿌꾸 branding: channel/profile.png, channel/banner.png, channel/watermark.png, shorts/intro.mp4.

    python3 channel/brand.py

Needs ffmpeg, numpy and the Playwright headless Chromium in /opt/pw-browsers. Re-run when the branding changes.
"""
import glob, math, os, subprocess, tempfile, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = os.path.join(ROOT, "shorts", ".cache", "Pretendard-ExtraBold.otf")  # make.py downloads it
CHROME = glob.glob("/opt/pw-browsers/chromium_headless_shell-*/*/headless_shell")[0]
PINK, DARK, WHITE = "#FF2E7E", "#16131C", "#FFFFFF"
BROWN, FUR, CREAM = "#8A5A3B", "#5E3B26", "#F6E3C8"  # otter face
MINT = "#CDEEEA"  # profile background: soft water tone, easier on the eyes than PINK
FPS, DUR, SR = 30, 0.7, 44100

def logo(look=1.0, badge=1.0):
    """Otter face peeking at you; look -1..1 moves the pupils, badge scales the play button."""
    px = 14 * look
    return f"""<svg viewBox="0 0 400 380" xmlns="http://www.w3.org/2000/svg" style="overflow:visible">
  <circle cx="86" cy="92" r="40" fill="{BROWN}"/><circle cx="314" cy="92" r="40" fill="{BROWN}"/>
  <circle cx="86" cy="92" r="20" fill="{FUR}"/><circle cx="314" cy="92" r="20" fill="{FUR}"/>
  <ellipse cx="200" cy="190" rx="178" ry="152" fill="{BROWN}"/>
  <ellipse cx="200" cy="258" rx="118" ry="78" fill="{CREAM}"/>
  <ellipse cx="148" cy="248" rx="58" ry="46" fill="{CREAM}"/><ellipse cx="252" cy="248" rx="58" ry="46" fill="{CREAM}"/>
  <circle cx="{136 + px}" cy="168" r="30" fill="{DARK}"/><circle cx="{264 + px}" cy="168" r="30" fill="{DARK}"/>
  <circle cx="{146 + px}" cy="156" r="10" fill="{WHITE}"/><circle cx="{274 + px}" cy="156" r="10" fill="{WHITE}"/>
  <path d="M170 214 Q200 200 230 214 Q228 240 200 246 Q172 240 170 214 Z" fill="{DARK}"/>
  <path d="M200 246 L200 268 M200 268 Q182 288 162 274 M200 268 Q218 288 238 274" stroke="{DARK}" stroke-width="8" fill="none" stroke-linecap="round"/>
  <circle cx="132" cy="258" r="5" fill="{BROWN}"/><circle cx="112" cy="244" r="5" fill="{BROWN}"/><circle cx="114" cy="272" r="5" fill="{BROWN}"/>
  <circle cx="268" cy="258" r="5" fill="{BROWN}"/><circle cx="288" cy="244" r="5" fill="{BROWN}"/><circle cx="286" cy="272" r="5" fill="{BROWN}"/>
  <path d="M96 246 L14 228 M96 264 L12 272 M304 246 L386 228 M304 264 L388 272" stroke="{DARK}" stroke-width="5" stroke-linecap="round" opacity=".55"/>
  <ellipse cx="96" cy="210" rx="22" ry="13" fill="{PINK}" opacity=".45"/><ellipse cx="304" cy="210" rx="22" ry="13" fill="{PINK}" opacity=".45"/>
  <g transform="translate(330 300) scale({badge})">
    <circle r="62" fill="{PINK}" stroke="{DARK}" stroke-width="12"/><path d="M-18 -28 L30 0 L-18 28 Z" fill="{WHITE}"/>
  </g>
</svg>"""

def shot(html, w, h, out, transparent=False):
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(f"<html><head><meta charset=utf-8><style>@font-face{{font-family:P;src:url(file://{FONT})}}"
                f"body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;font-family:P}}</style></head><body>{html}</body></html>")
    subprocess.run([CHROME, "--no-sandbox", "--hide-scrollbars", f"--window-size={w},{h}", f"--screenshot={out}",
                    *(["--default-background-color=00000000"] if transparent else []),
                    f"file://{f.name}"], check=True, capture_output=True)
    os.unlink(f.name)

def profile():
    shot(f"""<div style="width:800px;height:800px;background:{MINT};display:flex;flex-direction:column;align-items:center;justify-content:center">
      <div style="width:400px;height:380px;margin-top:-10px">{logo(0.6)}</div>
      <div style="font-size:104px;color:{DARK};letter-spacing:-4px;margin-top:8px">돌뚜뿌꾸</div></div>""",
         800, 800, os.path.join(ROOT, "channel", "profile.png"))

def watermark():
    """YouTube video watermark (bottom-right corner, desktop players): the otter face on a transparent square."""
    shot(f"""<div style="width:300px;height:300px;display:flex;align-items:center;justify-content:center">
      <div style="width:270px;height:257px">{logo(0)}</div></div>""",
         300, 300, os.path.join(ROOT, "channel", "watermark.png"), transparent=True)

def banner():
    # YouTube shows only the centre 1546x423 on phones; everything that matters lives there
    shot(f"""<div style="width:2560px;height:1440px;background:{DARK};position:relative">
      <div style="position:absolute;left:180px;top:120px;width:300px;height:300px;border-radius:50%;background:{PINK};opacity:.12"></div>
      <div style="position:absolute;right:160px;bottom:110px;width:420px;height:420px;border-radius:50%;background:{PINK};opacity:.10"></div>
      <div style="position:absolute;left:507px;top:508px;width:1546px;height:423px;display:flex;align-items:center;justify-content:center;gap:70px">
        <div style="width:330px;height:314px;flex:none">{logo(0.6)}</div>
        <div><div style="font-size:108px;color:{WHITE};letter-spacing:-3px;line-height:1.1"><span style="color:{PINK}">돌뚜뿌꾸</span><br>귀여운 친구들</div>
          <div style="margin-top:22px;font-size:42px;color:#B9B4C6">수달 사쿠라 · 바다코끼리 히마와리<br>속마음 더빙 · 하루한픽 웃긴 순간</div>
          <div style="display:inline-block;margin-top:28px;background:{PINK};color:{WHITE};font-size:40px;padding:12px 34px;border-radius:999px">매일 1분 동물</div></div>
      </div></div>""", 2560, 1440, os.path.join(ROOT, "channel", "banner.png"))

def ease_back(x):
    x = min(max(x, 0), 1); c = 1.9
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2

def intro():
    """DUR seconds: face pops in, eyes glance left then right, play badge pops with a "뿅", name rises.
    The beats are laid out on a 0..1 timeline and squeezed into DUR."""
    out = os.path.join(ROOT, "shorts", "intro.mp4")
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(int(FPS * DUR)):
            t = i / FPS / DUR  # 0..1
            look = -1 + 2 * min(max((t - 0.25) / 0.25, 0), 1)
            txt = min(max((t - 0.45) / 0.25, 0), 1)
            shot(f"""<div style="width:1080px;height:1920px;background:{MINT};position:relative">
              <div style="position:absolute;left:260px;top:600px;width:560px;height:532px;transform:scale({ease_back(t / 0.3):.3f});transform-origin:50% 60%">
                {logo(look, ease_back((t - 0.35) / 0.2))}</div>
              <div style="position:absolute;width:100%;top:{1200 + 40 * (1 - txt):.1f}px;text-align:center;font-size:140px;letter-spacing:-5px;color:{DARK};opacity:{txt:.2f}">돌뚜뿌꾸</div>
            </div>""", 1080, 1920, f"{tmp}/{i:03d}.png")
        tt = np.arange(int(SR * DUR)) / SR
        a = np.zeros_like(tt); m = tt >= 0.35 * DUR; s = tt[m] - 0.35 * DUR
        a[m] = np.sin(2 * np.pi * (500 * s + 2500 * s * s)) * np.exp(-s * 18) * 0.5  # rising "뿅"
        with wave.open(f"{tmp}/a.wav", "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes((np.stack([a, a], 1) * 32767).astype(np.int16).tobytes())
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", f"{tmp}/%03d.png", "-i", f"{tmp}/a.wav",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-ar", "44100", "-ac", "2",
                        "-shortest", out], check=True)

if __name__ == "__main__":
    profile(); banner(); watermark(); intro()
    print("channel/profile.png channel/banner.png channel/watermark.png shorts/intro.mp4")
