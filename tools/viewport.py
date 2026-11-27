"""게임 화면이 영상 일부에만 있는 영상(세로 휴대폰 녹화 rev_11nrgkl: 360x640 안에 약 300x168, 장식 띠 · 낙서 배경 틀 rev_segsk7)을
게임 화면만 잘라 1280x720 으로 다시 만든다. 분할 · HUD · 쇼케이스 판독이 모두 화면 전체가 게임이라고 보고 있어서다.

게임 화면은 시간에 따라 계속 바뀌고 틀 · 배경은 거의 그대로다 → 영상 곳곳에서 뽑은 프레임의 화소별 표준편차가 큰 곳의
가로 · 세로 범위를 찾는다. 범위가 16:9 에 가깝고 화면보다 뚜렷이 작을 때만 자른다(이미 게임 화면 전체면 아무것도 안 함 —
두 번 돌려도 같다).

python viewport.py <video> [--fix]    찾은 범위를 보이고, --fix 면 잘라서 바꾼다(원본은 <video>.orig.mp4 로 두지 않는다)"""
import os
import subprocess
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = 48
MOVE = 10.0          # 회색조 표준편차 문턱
FRAC = 0.25          # 한 줄에서 움직이는 화소 몫
ASPECT = (1.6, 2.4)       # 16:9 · 휴대폰 가로(20:9 ≈ 2.2)
FULL = 0.93          # 가로 · 세로 모두 이만큼 넘으면 이미 화면 전체


def _longest(mask):
    best, cur, start = (0, 0), 0, 0
    for i, v in enumerate(list(mask) + [False]):
        if v:
            if cur == 0:
                start = i
            cur += 1
        else:
            if cur > best[1] - best[0]:
                best = (start, start + cur)
            cur = 0
    return best


def detect(video):
    """(x, y, w, h) 원본 화소 기준, 자를 필요가 없거나 못 찾으면 None."""
    cap = cv2.VideoCapture(video)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if n < SAMPLES or not W or not H:
        cap.release()
        return None
    scale = 320.0 / max(W, H)
    grays = []
    for k in range(SAMPLES):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (0.05 + 0.9 * k / (SAMPLES - 1))))
        ok, f = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(cv2.resize(f, (max(1, int(W * scale)), max(1, int(H * scale)))), cv2.COLOR_BGR2GRAY)
        grays.append(g.astype(np.float32))
    cap.release()
    if len(grays) < SAMPLES // 2:
        return None
    sd = np.std(np.stack(grays), axis=0)
    mask = sd > MOVE
    # 세로 영상은 게임 띠가 화면 높이의 1/4 뿐이라 열마다 움직이는 몫이 작다 → 줄 범위를 먼저 잡고 그 안에서 열을, 다시 그 열 안에서 줄을
    r0, r1 = _longest(mask.mean(axis=1) > FRAC)
    c0, c1 = _longest(mask[r0:r1].mean(axis=0) > FRAC) if r1 > r0 else (0, 0)
    if c1 > c0:
        r0, r1 = _longest(mask[:, c0:c1].mean(axis=1) > FRAC)
    h, w = mask.shape
    if c1 - c0 < 0.2 * w or r1 - r0 < 0.15 * h:
        return None
    if (c1 - c0) >= FULL * w and (r1 - r0) >= FULL * h:
        return None
    # 가로 영상에서 가로가 꽉 찬 것(휴대폰 녹화를 위아래 검은 띠와 함께 16:9 로 올린 영상)은 지금 판독이 되므로 건드리지 않는다.
    # 세로 영상이거나 좌우에도 틀이 있을 때만 자른다
    if W > H and (c1 - c0) >= FULL * w:
        # 다만 위아래 띠가 비대칭이면(위에 제목 글 띠, 아래 검은 띠: rev_15u6ojs 21:9 게임이 1280x536) 대칭 띠 감지가 실패해
        # HUD · 배너 좌표가 어긋난다 → 게임 줄만 남기고 위아래 같은 높이의 검은 띠로 다시 채운다(fix 가 pad)
        top, bottom = r0, h - r1
        # 위아래 띠가 검지 않아도(흰 낙서 장식 띠, rev_segsk7) 검은 띠 감지가 못 하니 같은 처리
        mean = np.mean(np.stack(grays), axis=0)
        bands = np.concatenate([mean[:r0].ravel(), mean[r1:].ravel()]) if (r0 or r1 < h) else np.array([0.0])
        not_black = bands.size > 0 and float(np.median(bands)) > 30
        if (r1 - r0) < 0.9 * h and (abs(top - bottom) > 0.03 * h or not_black):
            y, bh = int(r0 / scale), int((r1 - r0) / scale)
            return 0, y - y % 2, W - W % 2, bh - bh % 2
        return None
    x, y = int(c0 / scale), int(r0 / scale)
    bw, bh = int((c1 - c0) / scale), int((r1 - r0) / scale)
    if not ASPECT[0] <= bw / max(1, bh) <= ASPECT[1]:
        return None
    # 16:9 근처면 16:9 로 맞춘다(가장자리 화소가 문턱에 걸쳐 한두 줄 덜 잡히므로 작은 쪽을 늘린다). 휴대폰 가로 비율(2 넘음)은 그대로
    if bw / bh < 16 / 9:
        nw = int(round(bh * 16 / 9))
        x, bw = max(0, x - (nw - bw) // 2), min(W, nw)
    elif bw / bh < 1.95:
        nh = int(round(bw * 9 / 16))
        y, bh = max(0, y - (nh - bh) // 2), min(H, nh)
    x, y = min(x, W - bw), min(y, H - bh)
    return x - x % 2, y - y % 2, bw - bw % 2, bh - bh % 2


def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return 'ffmpeg'


def fix(video):
    """잘라야 하면 잘라서 바꾸고 (x, y, w, h) 를, 아니면 None."""
    box = detect(video)
    if box is None:
        return None
    x, y, w, h = box
    cap = cv2.VideoCapture(video)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    oh = int(round(1280 * h / w / 2)) * 2          # 16:9 면 720, 휴대폰 비율이면 그 비율대로
    vf = f'crop={w}:{h}:{x}:{y},scale=1280:{oh}:flags=lanczos'
    if w >= W - 1 and W > H:
        # 가로가 꽉 찬 비대칭 띠 영상: 게임 줄을 가운데 두고 위아래를 같은 검은 띠로(원래 비율 그대로)
        th = int(round(1280 * H / W / 2)) * 2
        vf += f',pad=1280:{th}:0:{(th - oh) // 2}:black'
    tmp = video + '.crop.mp4'
    r = subprocess.run([ffmpeg(), '-y', '-loglevel', 'error', '-i', video,
                        '-vf', vf,
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-c:a', 'copy', tmp],
                       capture_output=True, text=True, errors='replace')
    if r.returncode or not os.path.exists(tmp):
        if os.path.exists(tmp):
            os.remove(tmp)
        raise RuntimeError('viewport crop failed: ' + r.stderr[-500:])
    os.replace(tmp, video)
    return box


if __name__ == '__main__':
    v = sys.argv[1]
    if '--fix' in sys.argv:
        print(fix(v))
    else:
        print(detect(v))
