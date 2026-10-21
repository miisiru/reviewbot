"""빌리빌리가 이 PC 의 스크립트 요청(영상 정보 API · yt-dlp)에는 412 를 돌려주는데 진짜 브라우저로는 열릴 때의 우회 도구.
브라우저(Chrome)에서 영상 페이지를 열면 페이지 안에 영상 주소(window.__playinfo__)와 길이(__INITIAL_STATE__)가 들어 있다.
그 주소(.m4s)를 이 도구에 넘기면 bili_dl 로 받아 runs/<rev>/video0.mp4 로 두고, 그다음은 보통 분석(run_queue.py --worker)이 이어 받는다.
python bili_browser_dl.py <rev_id> <m4s 주소> [길이 초]"""
import os, sys, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import RUNS, FF       # noqa: E402
import bili_dl                   # noqa: E402

if __name__ == '__main__':
    rev, url = sys.argv[1], sys.argv[2]
    d = os.path.join(RUNS, rev)
    os.makedirs(d, exist_ok=True)
    v = os.path.join(d, 'video0.mp4')
    tmp = v + '.m4s'
    for p in (v, tmp):
        if os.path.exists(p):
            os.remove(p)
    ok = bili_dl.download(url, tmp)
    if not ok:
        print('download failed')
        sys.exit(2)
    subprocess.run([FF, '-loglevel', 'error', '-y', '-i', tmp, '-c', 'copy', v])
    os.remove(tmp)
    print('saved', v, os.path.getsize(v) if os.path.exists(v) else 0)
