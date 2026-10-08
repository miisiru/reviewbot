"""구간 프레임 시트. python frames.py <video> <out.jpg> <start> <dur> [fps=1] [cols=5] [width=480]"""
import sys, subprocess
from paths import FF   # noqa: E402
v, out, ss, dur = sys.argv[1:5]; fps = sys.argv[5] if len(sys.argv) > 5 else "1"; cols = int(sys.argv[6]) if len(sys.argv) > 6 else 5; w = sys.argv[7] if len(sys.argv) > 7 else "480"
n = max(1, int(float(dur) * float(fps))); rows = (n + cols - 1) // cols
vf = f"fps={fps},scale={w}:-1,drawtext=text='%{{pts\:hms\:{ss}}}':x=4:y=4:fontsize=18:fontcolor=yellow:box=1:boxcolor=black,tile={cols}x{rows}"
subprocess.run([FF, "-loglevel", "error", "-ss", ss, "-t", dur, "-i", v, "-vf", vf, "-frames:v", "1", "-q:v", "3", "-y", out], stderr=subprocess.DEVNULL)
