"""한 파트를 높은 화질(기본 1080p, 영상만)로 다시 받는다 → runs/<rev>/video<i>_<h>p.mp4
720p 에서 13px 남짓인 작은 표시(카스토리스 나비 등)를 다시 볼 때 쓴다.
python hires.py <rev> [vid=0] [height=1080]"""
import os, sys, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RUNS, YT, FF   # noqa: E402


def get(rev, vid=0, height=1080):
    d = os.path.join(RUNS, rev)
    vids = json.load(open(os.path.join(d, 'videos.json'), encoding='utf8'))
    out = os.path.join(d, f'video{vid}_{height}p.mp4')
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    fmt = f'bv*[vcodec^=avc1][height<={height}]/bv*[height<={height}]'
    subprocess.run([YT, '-q', '--no-progress', '--js-runtimes', 'node', '--retries', '50', '--fragment-retries', '50',
                    '--http-chunk-size', '10M', '-N', '4', '--ffmpeg-location', FF, '--no-playlist',
                    '-f', fmt, '-o', out, vids[vid]['url']], capture_output=True)
    return out if os.path.exists(out) else None


if __name__ == '__main__':
    a = sys.argv[1:]
    print(get(a[0], int(a[1]) if len(a) > 1 else 0, int(a[2]) if len(a) > 2 else 1080))
