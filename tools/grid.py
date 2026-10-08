"""지정 시각들의 프레임을 2열 격자로. python grid.py <video> <out.jpg> t1 t2 ... (초)"""
import sys, subprocess, os, tempfile
from paths import FF   # noqa: E402
v, out, ts = sys.argv[1], sys.argv[2], sys.argv[3:]
d = tempfile.mkdtemp(); files = []
for i, t in enumerate(ts):
    f = os.path.join(d, f"{i:02d}.jpg")
    subprocess.run([FF, "-loglevel", "error", "-ss", t, "-i", v, "-frames:v", "1", "-vf", "scale=960:540", "-q:v", "3", "-y", f])
    files.append(f)
if len(files) % 2: files.append(files[-1])
args = []; [args.extend(["-i", f]) for f in files]
n = len(files); lay = "|".join(f"{(i%2)*960}_{(i//2)*540}" for i in range(n))
subprocess.run([FF, "-loglevel", "error"] + args + ["-filter_complex", f"xstack=inputs={n}:layout={lay}", "-q:v", "3", "-y", out])
