"""전역 패시브 띠 자리(오른쪽 가운데)를 1초마다 잘라 10x8 시트로. python gp_strip.py <video> <outdir> [start] [dur]"""
import sys, subprocess, os
from paths import FF   # noqa: E402
v, out = sys.argv[1], sys.argv[2]; ss = sys.argv[3] if len(sys.argv) > 3 else "0"; dur = sys.argv[4] if len(sys.argv) > 4 else None
os.makedirs(out, exist_ok=True)
vf = ("fps=1,crop=iw*0.32:ih*0.42:iw*0.68:ih*0.32,scale=200:-1,"
      f"drawtext=text='%{{pts\:hms\:{ss}}}':x=2:y=2:fontsize=14:fontcolor=yellow:box=1:boxcolor=black,tile=12x10")
subprocess.run([FF, "-loglevel", "error", "-ss", ss] + (["-t", dur] if dur else []) + ["-i", v, "-vf", vf, "-q:v", "4", "-y", os.path.join(out, "%02d.jpg")], stderr=subprocess.DEVNULL)
print(sorted(os.listdir(out)))
