"""은랑 999 전역 패시브 띠(McAwolfee 999, 노란 평행사변형)를 영상에서 찾는다.
화면 오른쪽 가운데 띠 자리를 잘라 2fps로 훑고, 띠 노란색 픽셀 비율이 높은 시각을 낸다.
python scan_gp.py <video> [start_sec] [dur_sec]"""
import sys, subprocess, numpy as np
from paths import FF   # noqa: E402
video = sys.argv[1]; ss = sys.argv[2] if len(sys.argv) > 2 else "0"; dur = sys.argv[3] if len(sys.argv) > 3 else None
W, H = 160, 60; FPS = 2
vf = f"fps={FPS},crop=iw*0.26:ih*0.16:iw*0.73:ih*0.55,scale={W}:{H}"
cmd = [FF, "-loglevel", "error", "-ss", ss] + (["-t", dur] if dur else []) + ["-i", video, "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
i = 0; hits = []
while True:
    buf = p.stdout.read(W * H * 3)
    if len(buf) < W * H * 3: break
    a = np.frombuffer(buf, np.uint8).reshape(H, W, 3).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    yellow = (r > 160) & (g > 130) & (b < 100) & (r - b > 90)
    ratio = yellow.mean()
    t = float(ss) + i / FPS
    if ratio > 0.07: hits.append((t, ratio))
    i += 1
for t, r in hits: print(f"{int(t//60)}:{t%60:05.2f}  {r:.2f}")
print(f"frames={i} hits={len(hits)}")
