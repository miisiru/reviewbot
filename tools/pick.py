"""여러 시각 프레임을 3열로. pick.py <video> <out> <width> t1 t2 ..."""
import sys, subprocess, os
from PIL import Image
from paths import FF   # noqa: E402
v, out, w = sys.argv[1], sys.argv[2], int(sys.argv[3]); ts = sys.argv[4:]
ims = []
for i, t in enumerate(ts):
    f = f"_pick{i}.png"
    subprocess.run([FF, "-v", "error", "-ss", t, "-i", v, "-frames:v", "1", "-vf", f"scale={w}:-1,drawtext=text='{t}':x=w-80:y=2:fontsize=16:fontcolor=yellow:box=1:boxcolor=black", "-y", f], stderr=subprocess.DEVNULL)
    if os.path.exists(f): ims.append(Image.open(f).copy()); os.remove(f)
cols = 3 if len(ims) > 4 else 2
W, H = ims[0].size; o = Image.new("RGB", (W * cols, H * ((len(ims) + cols - 1) // cols)))
for i, im in enumerate(ims): o.paste(im, ((i % cols) * W, (i // cols) * H))
o.save(out)
