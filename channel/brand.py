#!/usr/bin/env python3
"""brand.py - render 대신봐드림 branding: channel/profile.png, channel/banner.png, shorts/intro.mp4.

    python3 channel/brand.py

Needs ffmpeg, numpy and the Playwright headless Chromium in /opt/pw-browsers. Re-run when the branding changes.
"""
import glob, math, os, subprocess, tempfile, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = os.path.join(ROOT, "shorts", ".cache", "Pretendard-ExtraBold.otf")  # make.py downloads it
CHROME = glob.glob("/opt/pw-browsers/chromium_headless_shell-*/*/headless_shell")[0]
PINK, DARK, WHITE = "#FF2E7E", "#16131C", "#FFFFFF"
FPS, DUR, SR = 30, 1.0, 44100

def logo(look=1.0, badge=1.0):
    """TV screen with two eyes watching for you; look -1..1 moves the pupils, badge scales the play button."""
    px = 20 * look
    return f"""<svg viewBox="0 0 400 380" xmlns="http://www.w3.org/2000/svg" style="overflow:visible">
  <path d="M150 40 L120 8 M250 40 L280 8" stroke="{DARK}" stroke-width="16" stroke-linecap="round"/>
  <rect x="20" y="40" width="360" height="270" rx="56" fill="{DARK}"/>
  <circle cx="140" cy="175" r="62" fill="{WHITE}"/><circle cx="260" cy="175" r="62" fill="{WHITE}"/>
  <circle cx="{140 + px}" cy="182" r="28" fill="{DARK}"/><circle cx="{260 + px}" cy="182" r="28" fill="{DARK}"/>
  <circle cx="{150 + px}" cy="170" r="9" fill="{WHITE}"/><circle cx="{270 + px}" cy="170" r="9" fill="{WHITE}"/>
  <g transform="translate(330 300) scale({badge})">
    <circle r="62" fill="{PINK}" stroke="{DARK}" stroke-width="12"/><path d="M-18 -28 L30 0 L-18 28 Z" fill="{WHITE}"/>
  </g>
</svg>"""

def shot(html, w, h, out):
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(f"<html><head><style>@font-face{{font-family:P;src:url(file://{FONT})}}"
                f"body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;font-family:P}}</style></head><body>{html}</body></html>")
    subprocess.run([CHROME, "--no-sandbox", "--hide-scrollbars", f"--window-size={w},{h}", f"--screenshot={out}",
                    f"file://{f.name}"], check=True, capture_output=True)
    os.unlink(f.name)

def profile():
    shot(f"""<div style="width:800px;height:800px;background:{PINK};display:flex;flex-direction:column;align-items:center;justify-content:center">
      <div style="width:400px;height:380px;margin-top:-10px">{logo(0.6)}</div>
      <div style="font-size:104px;color:{DARK};letter-spacing:-4px;margin-top:8px">대신봐드림</div></div>""",
         800, 800, os.path.join(ROOT, "channel", "profile.png"))

def banner():
    # YouTube shows only the centre 1546x423 on phones; everything that matters lives there
    shot(f"""<div style="width:2560px;height:1440px;background:{DARK};position:relative">
      <div style="position:absolute;left:180px;top:120px;width:300px;height:300px;border-radius:50%;background:{PINK};opacity:.12"></div>
      <div style="position:absolute;right:160px;bottom:110px;width:420px;height:420px;border-radius:50%;background:{PINK};opacity:.10"></div>
      <div style="position:absolute;left:507px;top:508px;width:1546px;height:423px;display:flex;align-items:center;justify-content:center;gap:70px">
        <div style="width:330px;height:314px;flex:none">{logo(0.6).replace(f'stroke="{DARK}" stroke-width="16"', 'stroke="#3A3346" stroke-width="16"').replace(f'rx="56" fill="{DARK}"', 'rx="56" fill="#3A3346"')}</div>
        <div><div style="font-size:108px;color:{WHITE};letter-spacing:-3px;line-height:1.1">긴 영상,<br><span style="color:{PINK}">대신 봐드림</span></div>
          <div style="margin-top:22px;font-size:42px;color:#B9B4C6">K-POP · 연예계 · 브이로그 · 외국 이야기 · 로블록스 · 생활꿀팁</div>
          <div style="display:inline-block;margin-top:28px;background:{PINK};color:{WHITE};font-size:40px;padding:12px 34px;border-radius:999px">매일 1분 요약</div></div>
      </div></div>""", 2560, 1440, os.path.join(ROOT, "channel", "banner.png"))

def ease_back(x):
    x = min(max(x, 0), 1); c = 1.9
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2

def intro():
    """1s: screen pops in, eyes glance left then right, play badge pops with a "뿅", name rises."""
    out = os.path.join(ROOT, "shorts", "intro.mp4")
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(int(FPS * DUR)):
            t = i / FPS
            look = -1 + 2 * min(max((t - 0.25) / 0.25, 0), 1)
            txt = min(max((t - 0.45) / 0.25, 0), 1)
            shot(f"""<div style="width:1080px;height:1920px;background:{PINK};position:relative">
              <div style="position:absolute;left:260px;top:600px;width:560px;height:532px;transform:scale({ease_back(t / 0.3):.3f});transform-origin:50% 60%">
                {logo(look, ease_back((t - 0.35) / 0.2))}</div>
              <div style="position:absolute;width:100%;top:{1200 + 40 * (1 - txt):.1f}px;text-align:center;font-size:140px;letter-spacing:-5px;color:{DARK};opacity:{txt:.2f}">대신봐드림</div>
            </div>""", 1080, 1920, f"{tmp}/{i:03d}.png")
        tt = np.arange(int(SR * DUR)) / SR
        a = np.zeros_like(tt); m = tt >= 0.35; s = tt[m] - 0.35
        a[m] = np.sin(2 * np.pi * (500 * s + 2500 * s * s)) * np.exp(-s * 18) * 0.5  # rising "뿅"
        with wave.open(f"{tmp}/a.wav", "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes((np.stack([a, a], 1) * 32767).astype(np.int16).tobytes())
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", f"{tmp}/%03d.png", "-i", f"{tmp}/a.wav",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-ar", "44100", "-ac", "2",
                        "-shortest", out], check=True)

if __name__ == "__main__":
    profile(); banner(); intro()
    print("channel/profile.png channel/banner.png shorts/intro.mp4")
