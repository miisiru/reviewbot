"""캐릭터 화면에서 지금 켜진 탭(왼쪽 메뉴의 금색 아이콘)을 프레임마다 읽어, 광추 · 성혼 탭이 열린 구간과
그 구간에서 가장 또렷한 프레임(글자가 자리 잡은 화면)만 뽑는다. AI · OCR 없음.

python tabs.py <rev> [vid=0] [start dur]
  영상 전체를 1fps 로 훑어 메뉴가 보이는 구간을 먼저 찾는다. start/dur 를 주면 그 안의 구간만 본다.
결과: runs/<rev>/tabs<vid>/
  timeline.txt  구간마다 「시작 끝 탭」(# 줄은 구간 · 메뉴 배치)
  NNNN.NN_<탭>.jpg  광추 · 성혼 구간(캐릭터마다)의 가장 또렷한 프레임
  sheet.jpg  위 프레임들을 한 장에(왼쪽 위에 시각 · 탭)
  summary.json  탭마다 서로 다른 캐릭터 수"""
import os, sys, subprocess, re, json
import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import FF, RUNS as ROOT   # noqa: E402
TABS = ['Details', 'LightCone', 'Trace', 'Relics', 'Eidolon', 'Info']
# 메뉴 배치는 영상의 화면비 · 기기(PC 16:9, 휴대폰 와이드, 좌우 검은 띠 등)에 따라 위치 · 간격이 다르다.
# 고정 비율을 쓰지 않고, 아이콘 6개를 여러 크기로 찾아 배치(아이콘 열 가운데 x, 첫 줄 가운데 y, 줄 간격 sp)를 정한 뒤
# 탭 판정 · 이름 줄 · 또렷함 영역을 모두 그 배치에서 잰다.
ICON_PER_SP = 32 / 60          # 아이콘 틀 한 변 / 줄 간격(기준 화면에서 잰 값)
PASS1_W = 640                  # 1단계(메뉴 구간 찾기) 해상도
MATCH = 0.6                    # 아이콘 모양 일치 문턱(진짜 메뉴 0.77 이상, 전투 화면 0.6 미만)
LAYOUT_MIN = 0.8               # 메뉴 배치로 받아들일 평균 일치 점수(아이콘 6개 중 가장 낮은 것 빼고)


def probe(video):
    out = subprocess.run([FF, '-i', video], capture_output=True, text=True, errors='replace').stderr
    m = re.search(r'Duration: (\d+):(\d+):([\d.]+)', out)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r'Video:.*?, (\d{3,5})x(\d{3,5})', out)
    return dur, int(m.group(1)), int(m.group(2))


def frames(video, start, dur, fps, w, h):
    """연속 디코드(구간 시작만 키프레임 탐색). (시각, BGR) 를 낸다."""
    p = subprocess.Popen([FF, '-v', 'quiet', '-ss', str(start), '-t', str(dur), '-i', video,
                          '-vf', f'fps={fps},scale={w}:{h}', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                         stdout=subprocess.PIPE)
    n = w * h * 3
    i = 0
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield start + i / fps, np.frombuffer(b, np.uint8).reshape(h, w, 3)
        i += 1
    p.wait()


_ICONS = None
_SIZED = {}


def icons():
    """메뉴 아이콘 틀(디테일 · 광추 · 특성 · 유물 · 성혼 · 정보). menu_icons*.png 마다 32px 6장을 세로로 쌓은 것."""
    global _ICONS
    if _ICONS is None:
        _ICONS = [[] for _ in range(6)]
        for fn in sorted(os.listdir(HERE)):
            if fn.startswith('menu_icons') and fn.endswith('.png'):
                im = cv2.imread(os.path.join(HERE, fn), cv2.IMREAD_GRAYSCALE)
                for k in range(6):
                    _ICONS[k].append(im[k * 32:(k + 1) * 32])
    return _ICONS


def sized(size):
    if size not in _SIZED:
        _SIZED[size] = [[cv2.resize(t, (size, size), interpolation=cv2.INTER_AREA) for t in ts] for ts in icons()]
    return _SIZED[size]


def best_match(region, tpls):
    """틀 여러 장 중 가장 잘 맞는 (점수, 가운데 x, 가운데 y)."""
    best = (-1.0, 0.0, 0.0)
    for t in tpls:
        if region.shape[0] < t.shape[0] or region.shape[1] < t.shape[1]:
            continue
        r = cv2.matchTemplate(region, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(r)
        if mx > best[0]:
            best = (float(mx), loc[0] + t.shape[1] / 2, loc[1] + t.shape[0] / 2)
    return best


def fit_layout(found, size):
    """아이콘 k 의 (점수, x, y) 들 → 배치 (x, y0, sp) 또는 None. 5개 이상이 한 열에 고른 간격으로 있어야 한다."""
    good = [(k, x, y) for k, (s, x, y) in enumerate(found) if s > MATCH]
    if len(good) < 5:
        return None
    xs = np.array([g[1] for g in good])
    if np.abs(xs - np.median(xs)).max() > 0.35 * size:
        return None
    ks = np.array([g[0] for g in good], float)
    ys = np.array([g[2] for g in good])
    sp, y0 = np.polyfit(ks, ys, 1)
    if not (1.4 * size < sp < 2.6 * size):
        return None
    if np.abs(ys - (y0 + ks * sp)).max() > 0.25 * size:
        return None
    return float(np.median(xs)), float(y0), float(sp)


def layout_score(found):
    return float(np.mean(sorted(f[0] for f in found)[1:]))


def find_layout(g):
    """회색 프레임에서 메뉴 배치 (점수, x, y0, sp) 를 찾는다. 없으면 None.
    먼저 맨 위 디테일 아이콘과 아래쪽 기준 아이콘만 여러 크기로 찾아 후보를 고르고, 그 크기에서 6개를 다 본다.
    아래쪽 기준은 정보(5줄 아래). 종말의 환영 도전 화면의 「캐릭터 상세」(열람 모드)는 정보 줄이 없는 5줄 메뉴라
    성혼(4줄 아래)으로도 찾는다."""
    H, W = g.shape
    region = g[:, :int(W * 0.45)]
    best = None
    size = max(8, int(W / 90))
    while size <= W / 14:
        tp = sized(size)
        a = best_match(region, tp[0])
        if a[0] > MATCH - 0.05:
            for k_end in (5, 4):
                b = best_match(region, tp[k_end])
                # 맨 위 · 기준 아이콘이 한 열에, k_end 줄 간격만큼 떨어져 있어야 한다
                if not (b[0] > MATCH - 0.05 and abs(a[1] - b[1]) < 0.4 * size
                        and 1.4 * size * k_end < b[2] - a[2] < 2.6 * size * k_end):
                    continue
                sp = (b[2] - a[2]) / k_end
                found = []
                for k in range(6):
                    cy = a[2] + k * sp
                    y0, y1 = int(max(0, cy - 0.5 * sp)), int(min(H, cy + 0.5 * sp))
                    x0, x1 = int(max(0, a[1] - 0.5 * sp)), int(a[1] + 0.5 * sp)
                    if y1 - y0 < 4:
                        found.append((-1.0, 0.0, 0.0))
                        continue
                    s, x, y = best_match(g[y0:y1, x0:x1], tp[k])
                    found.append((s, x + x0, y + y0))
                lay = fit_layout(found, size)
                score = layout_score(found) if lay else 0.0
                # 진짜 메뉴 0.90 이상, 전투 화면 왼쪽 행동 순서 줄을 잘못 맞춘 것 0.68~0.73 (잰 값)
                if lay and score >= LAYOUT_MIN:
                    if best is None or score > best[0]:
                        best = (score,) + lay
                    break
        size = int(size * 1.08) + 1
    return best


def find_layout_near(g, lay):
    """대략의 배치를 알 때, 그 둘레 · 그 근처 크기만으로 정확한 배치를 찾는다."""
    x, y0, sp = lay
    H, W = g.shape
    ox, oy = int(max(0, x - 1.5 * sp)), int(max(0, y0 - 1.2 * sp))
    sub = g[oy:int(min(H, y0 + 6.2 * sp)), ox:int(min(W, x + 1.5 * sp))]
    best = None
    for m in (0.9, 0.95, 1.0, 1.05, 1.1):
        size = max(8, int(round(sp * m * ICON_PER_SP)))
        tp = sized(size)
        found = []
        for k in range(6):
            cy = y0 - oy + k * sp
            r0, r1 = int(max(0, cy - 0.6 * sp)), int(min(sub.shape[0], cy + 0.6 * sp))
            s, fx, fy = best_match(sub[r0:r1], tp[k])
            found.append((s, fx + ox, fy + r0 + oy))
        got = fit_layout(found, size)
        if got:
            score = layout_score(found)
            if best is None or score > best[0]:
                best = (score,) + got
    return best


def layout_ok(g, lay, need=5):
    """정해 둔 배치 자리에 아이콘 6개 중 need 개 이상이 있는지(캐릭터 화면인지)."""
    x, y0, sp = lay
    tp = sized(max(8, int(round(sp * ICON_PER_SP))))
    H, W = g.shape
    ok = 0
    for k in range(6):
        cy = y0 + k * sp
        r = g[int(max(0, cy - 0.45 * sp)):int(min(H, cy + 0.45 * sp)), int(max(0, x - 0.45 * sp)):int(min(W, x + 0.45 * sp))]
        if best_match(r, tp[k])[0] > MATCH:
            ok += 1
            if ok >= need:
                return True
        elif k - ok >= 6 - need:
            return False
    return ok >= need


def gold_rows(hsv, lay):
    """줄마다 금색 픽셀 비율. 켜진 탭은 아이콘과 글자가 금색(색상 10~35, 채도 40 이상)."""
    x, y0, sp = lay
    H, W = hsv.shape[:2]
    out = []
    for k in range(6):
        cy = y0 + k * sp
        r = hsv[int(max(0, cy - 0.3 * sp)):int(min(H, cy + 0.3 * sp)), int(max(0, x - 0.35 * sp)):int(min(W, x + 2.5 * sp))]
        out.append(float(((r[..., 0] >= 10) & (r[..., 0] <= 35) & (r[..., 1] > 40) & (r[..., 2] > 140)).mean()))
    return out


def pale_gold(hsv, lay):
    """줄마다 아이콘의 밝은 픽셀 중 옅은 금색(색상 10~40, 채도 12 이상)인 몫(밝은 픽셀이 30개 안 되면 None).
    켜진 탭 아이콘은 옅은 금색이 된다. 금색 하이라이트가 덜 뜬 빠른 클릭에서도, 수정 조각(연보라 · 흰색)이 덮어도 갈린다.
    잰 값: 켜진 줄 0.33~0.97, 다른 줄 0.22 이하(막 꺼진 줄의 남은 빛)."""
    x, y0, sp = lay
    H, W = hsv.shape[:2]
    out = []
    for k in range(6):
        cy = y0 + k * sp
        r = hsv[int(max(0, cy - 0.25 * sp)):int(min(H, cy + 0.25 * sp)), int(max(0, x - 0.25 * sp)):int(min(W, x + 0.25 * sp))].reshape(-1, 3)
        br = r[r[:, 2] > 140]
        out.append(float(((br[:, 0] >= 10) & (br[:, 0] <= 40) & (br[:, 1] >= 12)).mean()) if len(br) >= 30 else None)
    return out


def which_tab(pale, gold):
    """켜진 탭. 옅은 금색 몫이 가장 큰 줄(0.3 이상, 둘째보다 0.2 이상). 결정이 안 나면 금색 하이라이트(아이콘+글자)가 뚜렷한 줄."""
    v = [p if p is not None else 0.0 for p in pale]
    k = int(np.argmax(v))
    if v[k] >= 0.3 and v[k] - sorted(v)[-2] >= 0.2:
        return TABS[k]
    k = int(np.argmax(gold))
    if gold[k] >= 0.008 and gold[k] >= 3 * sorted(gold)[-2] + 0.003:
        return TABS[k]
    return None


def name_mask(f, lay, static=None):
    """머리글 둘째 줄(길 / 캐릭터 이름)의 흰 글자 픽셀.
    첫 줄 아이콘 위로 0.62~0.93 줄 간격, 아이콘 열 왼쪽 0.8 ~ 오른쪽 2.9 줄 간격(16:9 · 휴대폰 화면에서 잰 값).
    static 은 영상 내내 그 자리에 있는 글자(제작자 워터마크 등) — 빼고 본다."""
    x, y0, sp = lay
    H, W = f.shape[:2]
    c = f[int(max(0, y0 - 0.93 * sp)):int(max(1, y0 - 0.62 * sp)), int(max(0, x - 0.8 * sp)):int(min(W, x + 2.9 * sp))]
    if c.size == 0:
        return np.zeros((32, 320), bool)
    hsv = cv2.cvtColor(cv2.resize(c, (320, 32)), cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    # 흰 글자만(채도 낮음). 문턱은 글자 밝기에 맞춰 — 페이드로 어두워져도 글자 모양이 같게
    m = (v > max(90, 0.6 * float(np.percentile(v, 99.5)))) & (hsv[..., 1] < 70)
    return m & ~static if static is not None else m


def name_diff(a, b):
    """두 이름 줄이 얼마나 다른가. 64px 창을 8px씩 밀며 (겹치지 않는 글자 픽셀 / 합친 글자 픽셀)이 가장 큰 곳.
    「Elation / Sparxie」와 「Elation / Pearl」, 「欢愉／火花」와 「欢愉／爻光」처럼 앞부분이 같아도 이름 자리에서 갈린다.
    잰 값: 같은 캐릭터(페이드 · 워터마크 포함) 0.38 이하, 다른 캐릭터 0.68 이상."""
    best = 0.0
    W = a.shape[1]
    for x in range(0, W - 64 + 1, 8):
        sa, sb = a[:, x:x + 64], b[:, x:x + 64]
        u = (sa | sb).sum()
        if u >= 25:
            best = max(best, float((sa ^ sb).sum() / u))
    return best


def detail_name(f, lay):
    """디테일 화면 오른쪽 위 큰 캐릭터 이름의 흰 글자 픽셀(첫 메뉴 줄 높이, 화면 가로 70~97%).
    이름이 시작하는 자리는 배치마다 다르다(캐릭터 줄이 위: 약 76%, 캐릭터 줄이 왼쪽: 약 73%) — 넓게 잡고,
    캐릭터가 바뀌어도 같은 자리에 있는 UI(버튼 · 아이콘)는 scan 에서 빼고 비교한다.
    머리글 둘째 줄이 워터마크 · 연출에 가릴 때 누구 화면인지 정하는 데 쓴다."""
    x, y0, sp = lay
    H, W = f.shape[:2]
    c = f[int(max(0, y0 - 0.45 * sp)):int(min(H, y0 + 0.12 * sp)), int(0.70 * W):int(0.97 * W)]
    if c.size == 0:
        return np.zeros((32, 320), bool)
    hsv = cv2.cvtColor(cv2.resize(c, (320, 32)), cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    return (v > max(120, 0.7 * float(np.percentile(v, 99.5)))) & (hsv[..., 1] < 60)


def static_text(video, a, b, W, H, lay):
    """메뉴 구간 앞뒤(전투 화면 등)에서 이름 줄 자리에 늘 켜져 있는 글자 픽셀 = 워터마크."""
    ms = [name_mask(f, lay) for _, f in frames(video, max(0, a - 60), min(60, a), 1, W, H)]
    ms += [name_mask(f, lay) for _, f in frames(video, b, 30, 1, W, H)]
    if len(ms) < 10:
        return None
    return np.mean(ms, axis=0) > 0.6


def sharpness(f, lay):
    """메뉴 오른쪽 화면의 또렷함. 글자가 자리 잡은 프레임이 크고, 들어오고 나가는 연출 · 빈 화면은 작다."""
    x, y0, sp = lay
    g = cv2.cvtColor(f[:, int(min(f.shape[1] - 10, x + 3 * sp)):], cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (480, max(1, int(480 * g.shape[0] / g.shape[1]))))
    return float(cv2.Laplacian(g, cv2.CV_32F).var())


def _pass1_chunk(args):
    """find_windows 의 한 토막(일꾼 프로세스 하나). 전투 프레임마다 여러 크기 아이콘 맞추기를 다 해야 해서 느리므로
    영상을 시간 토막으로 나눠 동시에 돈다."""
    video, a, b, w, h = args
    cv2.setNumThreads(1)
    hits, last, n = [], None, 0
    for t, f in frames(video, a, b - a, 1, w, h):
        n += 1
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        if last is not None and layout_ok(g, last):
            hits.append((t, last))
            continue
        lay = find_layout(g)
        if lay:
            last = lay[1:]
            hits.append((t, last))
    return hits, n


def find_windows(video, dur, W, H):
    """1fps 저해상도로 메뉴가 보이는 시각을 찾아 구간(앞뒤 3초 여유)마다 배치(원래 크기 기준)를 낸다."""
    w = PASS1_W
    h = int(round(H * w / W / 2) * 2)
    k = max(1, min(6, int(dur // 60)))
    cuts = [int(dur * i / k) for i in range(k)] + [dur]
    jobs = [(video, cuts[i], cuts[i + 1], w, h) for i in range(k)]
    if k == 1:
        res = [_pass1_chunk(jobs[0])]
    else:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(k) as ex:
            res = list(ex.map(_pass1_chunk, jobs))
    hits = sorted((h_ for r in res for h_ in r[0]), key=lambda z: z[0])
    n = sum(r[1] for r in res)
    wins = []
    for t, lay in hits:
        if wins and t - wins[-1][1] <= 6:
            wins[-1][1] = t
            wins[-1][2].append(lay)
        else:
            wins.append([t, t, [lay]])
    k = W / w
    out = []
    for a, b, lays in wins:
        lay = tuple(float(np.median([l[i] for l in lays])) * k for i in range(3))
        out.append((max(0, a - 3), b + 3, lay))
    return out, n / max(1.0, dur)


def refine(video, a, b, W, H, lay):
    """원래 해상도에서 구간 안 몇 프레임으로 배치를 다시 잰다(저해상도에서 잰 값의 오차를 없앤다)."""
    found = []
    for t, f in frames(video, a, b - a, min(2.0, 10.0 / max(b - a, 1)), W, H):
        got = find_layout_near(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), lay)
        if got:
            found.append(got)
    if not found:
        return lay
    found.sort(reverse=True)
    top = found[:max(1, (len(found) + 1) // 2)]
    return tuple(float(np.median([f[i] for f in top])) for i in (1, 2, 3))


NAME_PX = 150     # 이름 줄 글자 픽셀이 이보다 적으면(연출 중 흐림) 이름으로 판단하지 않는다(실제 이름 300~2000)
STILL = 0.25      # 앞 프레임과 이만큼 안 다르면 이름이 멈춘 것
OTHER = 0.53      # 멈춘 이름끼리 이보다 다르면 다른 캐릭터(같은 캐릭터 0.38 이하, 다른 캐릭터 0.68 이상)


def same_name(a, b):
    """두 이름 줄이 같은 캐릭터인지. 어느 한쪽 글자가 거의 없으면(연출 중) 판단하지 않는다(None)."""
    if a.sum() < NAME_PX or b.sum() < NAME_PX:
        return None
    return name_diff(a, b) < OTHER


def same_char(a, b):
    """두 프레임(머리글 이름, 디테일 이름)이 같은 캐릭터인지. 머리글 이름을 둘 다 읽을 수 있으면 그것으로,
    아니면 둘 다 앞서 본 디테일 화면 큰 이름이 있으면 그것으로. 판단할 수 없으면 None."""
    dn = None
    if a[1] is not None and b[1] is not None:
        dn = name_diff(a[1], b[1]) < OTHER
    if a[0].sum() >= NAME_PX and b[0].sum() >= NAME_PX:
        h = name_diff(a[0], b[0])
        # 머리글이 애매한 구간(같은 캐릭터 0.38 이하 · 다른 캐릭터 0.68 이상 사이)이면 디테일 이름을 따른다.
        # 480p 에서 「记忆／昔涟 · 记忆／风堇」 처럼 짧은 이름이 0.48 로 붙는 일이 있다
        if 0.38 < h < 0.62 and dn is not None:
            return dn
        return h < OTHER
    return dn


def scan(video, start, dur, W, H, lay, fps=10, static=None):
    """구간마다 (시작, 끝, 탭). 광추 · 성혼 구간은 캐릭터마다 가장 또렷한 프레임을 남긴다.
    성혼 탭을 연 채 캐릭터 줄로 넘기는 경우가 있어, 머리글 이름이 바뀌면 구간을 나눈다.
    이름이 바뀐 것은 새 이름이 멈춘 뒤(한 프레임 늦게) 알게 되므로, 구간의 대표 프레임은
    그 구간의 이름과 같은 이름인 프레임에서만 고르고, 다른 이름 프레임은 다음 구간 몫으로 남겨 둔다."""
    segs = []           # [시작, 끝, 탭, 대표(또렷함, 시각, 프레임, 이름) | None, 구간 이름 | None]
    prev_hdr, settled, pending, run = None, None, [], 0
    prev_dn, dcur = None, None      # 디테일 화면 큰 이름: 앞 프레임, 지금 캐릭터로 확인된 것
    dsamples = []                   # 확인된 디테일 이름들(캐릭터마다 늘 같은 자리의 UI 를 찾는 데)
    for t, f in frames(video, start, dur, fps, W, H):
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        tab = None
        if layout_ok(g, lay):
            hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
            tab = which_tab(pale_gold(hsv, lay), gold_rows(hsv, lay))
        hd = name_mask(f, lay, static)
        # 이름 줄이 멈춘(앞 프레임과 같은) 상태끼리만 비교한다. 들어오고 나가는 연출 중의 흔들림은 빼고,
        # 멈춘 이름이 앞서 멈췄던 이름과 다르면 캐릭터가 바뀐 것
        # 이름이 3프레임(0.3초) 이어 같아야 멈춘 것으로 본다 — 페이드 중 흐린 이름 두 장이 우연히 닮는 것을 거른다
        new_char = False
        if prev_hdr is not None and name_diff(hd, prev_hdr) < STILL and hd.sum() >= NAME_PX:
            run += 1
        else:
            run = 0
        if run >= 2:
            if settled is not None and name_diff(hd, settled) > OTHER:
                new_char = True
            settled = hd
        # 디테일 화면 오른쪽 위 큰 이름(머리글이 워터마크 · 연출에 가려도 읽힌다). 두 프레임 같으면 확인된 것
        if tab == 'Details':
            dn = detail_name(f, lay)
            if dn.sum() >= NAME_PX and prev_dn is not None and name_diff(dn, prev_dn) < STILL:
                if dcur is None or name_diff(dn, dcur) >= STILL:
                    dsamples.append(dn)
                dcur = dn
            prev_dn = dn
        else:
            prev_dn = None
            if new_char:
                dcur = None             # 디테일 화면을 거치지 않고 캐릭터가 바뀌었다 — 앞 디테일 이름은 이제 다른 사람
        if not segs or segs[-1][2] != tab or (new_char and tab in ('LightCone', 'Eidolon')):
            # 앞 구간이 대표 없이 끝나고 보류한 프레임만 있으면(들어오는 연출 중 이름 줄이 미끄러져 다르게 보인 것),
            # 다른 캐릭터 구간이 그것을 가져가지 않는 한 앞 구간의 대표로 쓴다
            if segs and segs[-1][3] is None and pending and not (new_char and segs[-1][2] == tab):
                segs[-1][3] = max(pending, key=lambda c: c[0])
            # 탭만 바뀐 것이면 캐릭터는 그대로 — 직전에 멈춰 있던 이름을 이 구간의 이름으로 물려받는다
            # (연출 중이라 이름을 못 읽는 동안 뒤따라 온 다른 캐릭터 프레임이 이 구간 대표가 되지 않게)
            segs.append([t, t, tab, None, settled if not new_char else hd])
            # 앞 구간에서 이름이 달라 보류한 프레임 중 이 구간 이름과 같은 것은 이 구간 몫
            if new_char and segs[-2][2] == tab:
                segs[-1][0] = pending[0][1] if pending else t
                for c in pending:
                    if same_name(c[3], hd) and (segs[-1][3] is None or c[0] > segs[-1][3][0]):
                        segs[-1][3] = c
            pending = []
        seg = segs[-1]
        seg[1] = t
        if settled is not None and seg[4] is None and tab in ('LightCone', 'Eidolon') and name_diff(hd, settled) < STILL:
            seg[4] = settled
        if tab in ('LightCone', 'Eidolon'):
            c = (sharpness(f, lay), t, f.copy(), hd, dcur)
            if seg[4] is not None and same_name(hd, seg[4]) is False:
                pending.append(c)            # 이름이 다르다: 곧 다음 캐릭터 구간이 될 수 있다
                pending = pending[-5:]
            elif seg[3] is None or c[0] > seg[3][0]:
                seg[3] = c
        prev_hdr = hd
    if segs and segs[-1][3] is None and pending:
        segs[-1][3] = max(pending, key=lambda c: c[0])
    # 같은 탭이 0.3초 안 되게 끊겨 나온 조각 중 흐릿한 것(패널이 사라지며 머리글이 흔들린 것)은 앞 구간에 합친다.
    # 또렷한 조각은 짧게 넘긴 다른 캐릭터일 수 있으니 남긴다
    merged = []
    for s in segs:
        m = merged[-1] if merged else None
        if (m and m[2] == s[2] and s[1] - s[0] < 0.3 and s[0] - m[1] <= 0.25
                and (s[3] is None or m[3] is None or s[3][0] < 0.6 * m[3][0])
                and not (s[3] is not None and m[3] is not None and same_name(s[3][3], m[3][3]) is False)):
            m[1] = s[1]
            if s[3] is not None and (m[3] is None or s[3][0] > m[3][0]):
                m[3] = s[3]
        else:
            merged.append(s)
    # 디테일 이름에서 캐릭터가 바뀌어도 늘 켜진 픽셀(UI)은 뺀다. 그 뒤 글자가 거의 안 남으면 이름으로 쓰지 않는다
    dstatic = (np.mean(dsamples, axis=0) > 0.7) if len(dsamples) >= 3 else None
    def clean(dn):
        if dn is None:
            return None
        if dstatic is not None:
            dn = dn & ~dstatic
        return dn if dn.sum() >= 60 else None
    for sg in merged:
        if sg[3] is not None and len(sg[3]) > 4:
            sg[3] = sg[3][:4] + (clean(sg[3][4]),)
    # 같은 캐릭터 · 같은 탭이 잇따라 두 번 잡히면(연출 중 이름 줄 흔들림 등) 더 또렷한 한 장만.
    # 이름을 확인할 수 없는 프레임은 지우지 않는다
    keep = []
    for s in merged:
        if s[3] is None:
            continue
        sc, t, f, nm, dn = s[3]
        # 누구인지 확인할 수 없는 프레임(워터마크에 가림, 연출 중)은 지우지 않는다 — 짧게 스친 다른 캐릭터일 수 있다
        if keep and keep[-1][1] == s[2] and t - keep[-1][0] < 6 and same_char((nm, dn), (keep[-1][3], keep[-1][5])):
            if sc > keep[-1][4]:
                keep[-1] = (t, s[2], f, nm, sc, dn)
            continue
        keep.append((t, s[2], f, nm, sc, dn))
    return [s[:3] for s in merged if s[2]], keep


def main():
    rev = sys.argv[1]
    vid = sys.argv[2] if len(sys.argv) > 2 else '0'
    d = os.path.join(ROOT, rev)
    video = os.path.join(d, f'video{vid}.mp4')
    dur, W, H = probe(video)
    outdir = os.path.join(d, f'tabs{vid}')
    os.makedirs(outdir, exist_ok=True)
    for fn in os.listdir(outdir):
        os.remove(os.path.join(outdir, fn))
    wins, decoded = find_windows(video, dur, W, H)
    if len(sys.argv) > 4:
        a, b = float(sys.argv[3]), float(sys.argv[3]) + float(sys.argv[4])
        wins = [(max(a, wa), min(b, wb), lay) for wa, wb, lay in wins if wa < b and wb > a]
    lines, kept = [], []
    for a, b, lay in wins:
        lay = refine(video, a, b, W, H, lay)
        static = static_text(video, a, b, W, H, lay)
        lines.append(f'# window {a:.1f}-{b:.1f} layout x={lay[0]:.0f} y0={lay[1]:.0f} sp={lay[2]:.1f}'
                     f' watermark_px={0 if static is None else int(static.sum())}')
        segs, keep = scan(video, a, b - a, W, H, lay, static=static)
        for s in segs:
            lines.append(f'{s[0]:8.2f} {s[1]:8.2f} {s[2]}')
        kept += keep
    open(os.path.join(outdir, 'timeline.txt'), 'w', encoding='utf8').write('\n'.join(lines) + '\n')
    # 탭마다 서로 다른 캐릭터 수(이름 줄 모양으로 묶음)
    # unnamed: 이름 줄을 읽을 수 없는 프레임 수(사람이 시트에서 누구인지 본다)
    distinct, unnamed = {}, {}
    for tab in ('LightCone', 'Eidolon'):
        ids = []
        unnamed[tab] = 0
        for k in kept:
            if k[1] != tab:
                continue
            me = (k[3], k[5])
            if k[3].sum() < NAME_PX and k[5] is None:
                unnamed[tab] += 1
            elif not any(same_char(me, o) for o in ids):  # noqa
                ids.append(me)
        distinct[tab] = len(ids)
    # 영상의 90% 미만만 디코드되면 파일이 깨진 것 — 「메뉴 없음」이 아니라 다시 받아야 한다
    bad = decoded < 0.9
    json.dump({'windows': len(wins), 'kept': len(kept), 'distinct': distinct, 'unnamed': unnamed,
               'decoded': round(decoded, 3), 'decode_error': bad},
              open(os.path.join(outdir, 'summary.json'), 'w'))
    tiles = []
    for t, tab, f, nm, _, dn in kept:
        cv2.imwrite(os.path.join(outdir, f'{t:07.2f}_{tab}.jpg'), f, [cv2.IMWRITE_JPEG_QUALITY, 92])
        s = cv2.resize(f, (960, int(960 * f.shape[0] / f.shape[1])))
        label = f'{int(t // 60)}:{t % 60:05.2f} {tab}' + ('' if nm.sum() >= NAME_PX else (' (Details name)' if dn is not None else ' name?'))
        cv2.rectangle(s, (0, 0), (470, 34), (0, 0, 0), -1)
        cv2.putText(s, label, (6, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        tiles.append(s)
    if tiles:
        cols = 2
        th = max(s.shape[0] for s in tiles)
        tw = 960
        sheet = np.zeros((th * ((len(tiles) + cols - 1) // cols), tw * cols, 3), np.uint8)
        for i, s in enumerate(tiles):
            sheet[(i // cols) * th:(i // cols) * th + s.shape[0], (i % cols) * tw:(i % cols + 1) * tw] = s
        cv2.imwrite(os.path.join(outdir, 'sheet.jpg'), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])
    print('\n'.join(lines))
    if bad:
        print(f'!!! DECODE ERROR: only {decoded:.0%} of the video decoded - re-download (python prep.py), result is not usable')
    print(len(kept), 'frames kept ->', outdir, distinct, 'unnamed', unnamed)


if __name__ == '__main__':
    main()
