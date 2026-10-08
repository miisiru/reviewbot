"""화면 왼쪽 위 머리글(Eidolon Resonance / 길 / 이름) 띠를 fps 간격으로 잘라 세로로 쌓는다. 캐릭터 화면 구간을 빨리 읽는 용도.
python header_strip.py <video> <out.jpg> [start] [dur] [fps=2]"""
import sys, subprocess
from paths import FF   # noqa: E402
v, out = sys.argv[1], sys.argv[2]; ss = sys.argv[3] if len(sys.argv) > 3 else "0"; dur = sys.argv[4] if len(sys.argv) > 4 else None; fps = sys.argv[5] if len(sys.argv) > 5 else "2"
vf = (f"fps={fps},crop=iw*0.2:ih*0.075:0:0,scale=360:-1,"
      f"drawtext=text='%{{pts\:hms\:{ss}}}':x=w-90:y=2:fontsize=12:fontcolor=yellow:box=1:boxcolor=black,tile=4x60")
subprocess.run([FF, "-loglevel", "error", "-ss", ss] + (["-t", dur] if dur else []) + ["-i", v, "-vf", vf, "-q:v", "3", "-y", out.replace(".jpg", "_%02d.jpg")])
