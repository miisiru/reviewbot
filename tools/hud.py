"""전투 중 HUD 값을 읽는다(AI 없음). 결과 화면은 쓰지 않는다 — 최고 기록을 보여 줄 수 있어서.
  - 소모 라운드(이상 중재 · 혼돈): 오른쪽 위 「Cycles Used / 消耗轮次 …」 라벨 아래 숫자
  - 남은 행동값(종말의 환영): 오른쪽 위 「Remaining Action Value / 剩余行动值 …」 라벨 아래 숫자
  - 절망(행동 수치): 왼쪽 행동 순서 칸 「⧗N | x」
쇼케이스(또는 영상 끝) 앞 구간을 1fps 로 훑어, HUD 가 마지막으로 보인 순간들의 값을 쓴다(= 전투 종료 순간).
python hud.py <rev> [vid]"""
import os, sys, re, json, difflib
import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tabs               # noqa: E402
from judge import ocr, norm, ROOT   # noqa: E402

CYCLES = ['cyclesused', '소모라운드', '消耗轮次', '消耗轮', '消耗輪', '消耗輪數', '消費ラウンド', 'vongtieuhao', 'จำนวนรอบที่ใช้',
          'использованоциклов', 'ciclosutilizados', 'cicloscosumidos', 'ciclosconsumidos', 'cyclesutilises', 'verbrauchterd',
          'benotigterd', 'putaranterkonsumsi']
RAV = ['remainingactionvalue', '남은행동수치', '剩余行动值', '剩餘行動值', '残り行動値', 'diemhanhdongcon', 'คาแอกชนทเหลอ',
       'оставшийсяиндексдействия', 'valordeaccionrestante', 'valordeacaorestante', 'valeurdactionrestante',
       'verbleibenderaktionswert', 'sisanilaiaksi']


def label_score(t, words):
    n = norm(t)
    if not n:
        return 0.0
    if any(w in n or (len(n) >= 3 and n in w) for w in words):
        return 1.0
    return max(difflib.SequenceMatcher(None, n, w).ratio() for w in words)


def number_near(lines, ly, lx, lh, W):
    """라벨 아래(또는 옆) 가장 가까운 숫자 덩어리."""
    best = None
    for y, x, h, t in lines:
        t2 = t.replace('O', '0').replace('o', '0').replace(' ', '')
        if not re.fullmatch(r'\d{1,5}', t2):
            continue
        dy = y - ly
        if -0.5 * lh <= dy <= 4.0 * lh and abs(x - lx) < 0.25 * W:
            d = abs(dy) + 0.3 * abs(x - lx)
            if best is None or d < best[0]:
                best = (d, int(t2))
    return None if best is None else best[1]


_rec = None


def rec_digit(img):
    """작은 칸 하나를 글자 찾기 없이 바로 인식. 숫자 하나면 그 숫자, 아니면 None."""
    global _rec
    if _rec is None:
        from ocr import OCR
        _rec = OCR('chinese').engine.text_recognizer
    out = _rec([img])[0]
    t = (out[0][0] if out else '').replace('O', '0').replace('o', '0').strip()
    return int(t) if re.fullmatch(r'\d{1,2}', t) else None


def _badge_read(c, wy0, wy1, cx, h):
    d = c[wy0:wy1, int(max(0, cx - 1.9 * h)):int(cx + 1.9 * h)]
    if d.size == 0:
        return []
    big = cv2.resize(d, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    g = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    mid = big[:, int(0.15 * W):int(0.85 * W)]
    gm = g[:, int(0.15 * W):int(0.85 * W)]
    variants = [mid, cv2.cvtColor(255 - gm, cv2.COLOR_GRAY2BGR),
                cv2.cvtColor(cv2.equalizeHist(gm), cv2.COLOR_GRAY2BGR)]
    out = []
    for v in variants:
        n = rec_digit(v)
        if n is not None:
            out.append(n)
    return out


def badge_votes(c, lab):
    """소모 라운드 라벨 아래 배지 안 숫자를 전처리 세 가지로 읽어 나온 숫자들(배지 안 큰 숫자는 글자 찾기 단계에서 빠진다)."""
    x, y, w, h = lab
    cx = x + w / 2
    wy0, wy1 = int(y + 1.6 * h), int(y + 5.0 * h)
    out = _badge_read(c, wy0, wy1, cx, h)
    if out:
        return out
    # 라벨이 두 줄로 갈리면(러시아어 「Использовано / циклов:」) 읽힌 줄의 가운데가 배지 가운데와 어긋난다 →
    # 라벨 아래 넓게 보고 큰 흰 글자(배지 숫자)가 있으면 그 가운데로 다시 읽는다
    wx0, wx1 = int(max(0, x - 2 * h)), int(min(c.shape[1], x + w + 4 * h))
    wide = c[wy0:wy1, wx0:wx1]
    if wide.size == 0:
        return out
    hsv = cv2.cvtColor(wide, cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 2] > 200) & (hsv[..., 1] < 70)).astype(np.uint8)
    n, _, st, cen = cv2.connectedComponentsWithStats(m, 8)
    big = [(abs(cen[i][0] + wx0 - cx), cen[i][0] + wx0) for i in range(1, n) if 1.3 * h <= st[i][3] <= 3.5 * h]
    return _badge_read(c, wy0, wy1, min(big)[1], h) if big else out


def read_topright(f, model):
    H, W = f.shape[:2]
    # 가로로 넓은 화면(1280×584, rev_fjaqx)은 배지가 0.38~0.47 높이까지 내려온다 → 0.6 까지 본다
    c = f[0:int(0.6 * H), int(0.60 * W):W]
    res = ocr(c, model)
    lines = [(b[1], b[0], b[3], b[4]) for b in res]
    out = {}
    for key, words in (('cycles', CYCLES), ('rav', RAV)):
        cand = [(label_score(t, words), y, x, h, b) for (y, x, h, t), b in zip(lines, res)]
        cand = [z for z in cand if z[0] >= 0.75]
        if cand:
            _, y, x, h, b = max(cand, key=lambda z: z[0])
            v = number_near(lines, y, x, h, c.shape[1])
            if key == 'cycles':
                votes = badge_votes(c, b[:4])
                if v is not None:
                    votes.append(v)
                out[key] = votes or None
            else:
                out[key] = v
    return out


def rec_text(img):
    """글자 찾기 없이 바로 인식한 글(빈칸 없이)."""
    global _rec
    if _rec is None:
        from ocr import OCR
        _rec = OCR('chinese').engine.text_recognizer
    out = _rec([img])[0]
    return (out[0][0] if out else '').replace('O', '0').replace('o', '0').replace(' ', '')


def plight_col(f):
    """왼쪽 행동 순서 줄(모바일은 절망 칸이 화면 가운데 아래까지 내려온다), 2배."""
    H, W = f.shape[:2]
    c = f[int(0.03 * H):int(0.80 * H), 0:int(0.18 * W)]
    return cv2.resize(c, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)


def _binar(cell):
    g = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
    k = max(3, int(cell.shape[0] * 0.8)) | 1
    th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    _, m = cv2.threshold(th, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
    return ((m > 0) & (hsv[..., 1] < 110) & (g > 110)).astype(np.uint8)


def parse_plight(c, box):
    """box(x, y, w, h) 둘레에서 「⧗ N | x」 꼴을 찾는다. 흰 글자 덩어리를 왼쪽부터 늘어놓고
    가는 세로줄(구분선) 왼쪽에 숫자 하나(N), 그 왼쪽에 모래시계, 오른쪽에 숫자 1~3개(x)가 있어야 한다.
    OCR 은 모래시계를 「2」로, 구분선을 「1」로 읽어서 글만으로는 「20116」(⧗0|16)처럼 가를 수 없다 —
    N 과 x 는 따로 잘라 인식한다. 캐릭터 칸의 행동값(「15」)은 구분선이 없어서 걸리지 않는다. 찾으면 (N, x)."""
    x, y, w, h = [int(v) for v in box[:4]]
    y0, y1 = max(0, int(y - 0.3 * h)), min(c.shape[0], int(y + 1.3 * h))
    x0, x1 = max(0, int(x - 3.5 * h)), min(c.shape[1], int(x + w + 0.4 * h))
    cell = c[y0:y1, x0:x1]
    if cell.size == 0:
        return None
    m = _binar(cell)
    n, _, st, _ = cv2.connectedComponentsWithStats(m, 8)
    cs = sorted(tuple(int(v) for v in st[i][:4]) for i in range(1, n) if st[i][3] >= 0.45 * h and st[i][4] >= 4)
    if len(cs) < 3:
        return None
    dh = float(np.median([q[3] for q in cs]))
    cs = [q for q in cs if 0.7 * dh <= q[3] <= 1.4 * dh]
    for i in range(1, len(cs) - 1):
        sx, sy, sw, sh = cs[i]
        nn = cs[i - 1]
        if sw > 0.26 * sh or nn[2] < 0.3 * sh or sx - (nn[0] + nn[2]) > 1.2 * sh:
            continue
        if cs[i + 1][0] - (sx + sw) > 1.6 * sh:
            continue
        right = [cs[i + 1]]
        for q in cs[i + 2:]:
            if q[0] - (right[-1][0] + right[-1][2]) > 0.8 * sh:
                break
            right.append(q)
        if len(right) > 3:
            continue
        hg = m[nn[1]:nn[1] + nn[3], max(0, int(nn[0] - 1.3 * sh)):nn[0]]     # 모래시계 자리
        if hg.size == 0 or hg.mean() < 0.12:
            continue
        pad = max(2, int(0.25 * sh))

        def crop(a, z):
            ya, yb = min(a[1], z[1]), max(a[1] + a[3], z[1] + z[3])
            r = cell[max(0, ya - pad):yb + pad, max(0, a[0] - pad):z[0] + z[2] + pad]
            s = 48 / max(1, r.shape[0])
            return cv2.resize(r, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
        tn, tx = rec_text(crop(nn, nn)), rec_text(crop(right[0], right[-1]))
        if not (re.fullmatch(r'\d', tn) and re.fullmatch(r'\d{1,3}', tx)):
            continue
        N, X = int(tn), int(tx)
        if N > 2 or X > (300 if N == 2 else 100):      # 0라운드 300, 그 뒤 100씩
            continue
        return N, X
    return None


def read_plight(f, model):
    """OCR 이 찾은 숫자 상자마다 절망 칸 꼴인지 본다. 찾으면 ((N, x), 상자)."""
    c = plight_col(f)
    for b in sorted(ocr(c, model), key=lambda b: b[1]):
        if re.search(r'\d', b[4]):
            p = parse_plight(c, b)
            if p:
                return p, b[:4]
    return None


def read_plight_slide(f, geom):
    """칸 자리를 아는 뒤에는 OCR 상자 없이 같은 크기 창을 줄 위아래로 밀어 본다(글자 찾기가 칸을 자주 놓친다)."""
    c = plight_col(f)
    x, w, h = geom
    for y in range(0, max(1, c.shape[0] - h), max(1, h // 3)):
        p = parse_plight(c, (x, y, w, h))
        if p:
            return p
    return None


def scan(rev, vid=0, model='chinese', mode='aa', plight=False):
    d = os.path.join(ROOT, rev)
    vids = json.load(open(os.path.join(d, 'videos.json'), encoding='utf8')) if os.path.exists(os.path.join(d, 'videos.json')) else [{'file': 'video0.mp4'}]
    video = os.path.join(d, vids[vid].get('file', f'video{vid}.mp4'))
    dur, W, H = tabs.probe(video)
    end = dur
    tl = os.path.join(d, f'tabs{vid}', 'timeline.txt')
    if os.path.exists(tl):
        ws = [float(m.group(1)) for m in re.finditer(r'window ([\d.]+)-', open(tl, encoding='utf8').read())]
        late = [w for w in ws if w > 0.3 * dur]
        if late:
            end = min(late)
    start = max(0.0, end - 200)
    st = {'geom': None, 'last_pl': None}

    def pass_a(a, b):
        out = []
        for t, f in tabs.frames(video, a, b - a, 1, W, H):
            r = read_topright(f, model)
            if plight:
                pl = read_plight(f, model)
                if pl:
                    r['plight'] = list(pl[0])
                    if st['last_pl'] is None or t > st['last_pl']:
                        st['geom'], st['last_pl'] = (int(pl[1][0]), int(pl[1][2]), int(pl[1][3])), t
            if r:
                out.append((round(t, 1), r))
        return out

    def enough(rs):
        fin = final_value(rs)
        hud_ok = (fin.get('rav', {}).get('of', 0) >= 3) or \
                 (fin.get('cycles', {}).get('frames', 0) >= 5 and fin['cycles'].get('of', 0) > 0)
        return hud_ok and (not plight or st['geom'] is not None)
    # 끝 값만 쓰므로 마지막 40초부터 읽고, 모자랄 때만(전투 끝과 쇼케이스 사이가 길 때 등) 200초까지 넓힌다
    mid = max(start, end - 40)
    reads = pass_a(mid, end)
    if not enough(reads) and mid > start:
        reads = pass_a(start, mid) + reads
    geom, last_pl = st['geom'], st['last_pl']
    if plight and geom:
        # 끝 무렵은 4fps 로 다시: 마지막 칸 값은 몇 초만 보이기도 한다(궁 연출 사이)
        for t, r in reads:
            if t >= last_pl - 2:
                r.pop('plight', None)
        for t, f in tabs.frames(video, max(start, last_pl - 2), end - max(start, last_pl - 2), 4, W, H):
            pl = read_plight_slide(f, geom)
            if pl:
                reads.append((round(t, 2), {'plight': list(pl)}))
        reads.sort(key=lambda z: z[0])
    return {'video': video, 'window': (round(start, 1), round(end, 1)), 'reads': reads, 'final': final_value(reads)}


def final_value(reads):
    """HUD 가 마지막으로 보인 값들. 남은 행동값 · 절망 칸은 마지막 3번 읽은 값의 다수결.
    소모 라운드는 라벨이 보인 마지막 10번의 배지 숫자 표(프레임마다 전처리 셋)를 모두 모아 다수결."""
    out = {}
    for key in ('rav', 'plight'):
        vals = [(t, r[key]) for t, r in reads if r.get(key) is not None]
        if not vals:
            continue
        last = vals[-3:]
        vs = [v for _, v in last]
        v = max(vs, key=vs.count)
        out[key] = {'value': v, 't': last[-1][0], 'agree': vs.count(v), 'of': len(vs)}
    cyc = [(t, r['cycles']) for t, r in reads if 'cycles' in r]
    if cyc:
        last = cyc[-10:]
        votes = [n for _, vs in last for n in (vs or [])]
        if votes:
            v = max(set(votes), key=votes.count)
            out['cycles'] = {'value': v, 't': last[-1][0], 'agree': votes.count(v), 'of': len(votes), 'frames': len(last)}
        else:
            out['cycles'] = {'value': None, 't': last[-1][0], 'agree': 0, 'of': 0, 'frames': len(last)}
    return out


# ---------- 혼돈의 기억(MoC) · 허구 이야기(PF): 행동 순서 줄의 모래시계 칸 ----------
# MoC 「⧗ | 29」 = 남은 사이클 수. 사이클이 하나 지날 때마다 1 씩 준다 → 쓴 사이클 = 처음 값 − 끝 값(두 전반 · 후반 합쳐서)
# PF  「⧗ | 3」  = 사이클 카운터. 끝나는 순간 남은 카운터 N 으로 3 − N(⧗3 → 0, ⧗0 → 3, ⧗0 까지 지나 행동값 소진 → 4)
_HG = None


def _hg_binar(img):
    """밝은 글자를 둘레보다 밝은 곳(top-hat)으로 가른다. 칸 바탕이 빨갛든 어둡든 같은 기준."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    k = max(15, int(img.shape[0] * 0.035)) | 1
    th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    return ((th > 45) & (g > 110) & (hsv[..., 1] < 120)).astype(np.uint8)


def _is_hourglass(m):
    """글리프 마스크가 모래시계(실제 영상에서 자른 틀, tools/hourglass_tpl.png)와 닮았는지."""
    global _HG
    h, w = m.shape
    if h < 6 or w < 3 or not (0.5 <= w / h <= 0.9):
        return False
    if _HG is None:
        _HG = cv2.imread(os.path.join(HERE, 'hourglass_tpl.png'), 0).astype(np.float32) / 255
    r = cv2.resize(m.astype(np.float32), (_HG.shape[1], _HG.shape[0]), interpolation=cv2.INTER_AREA)
    a, b = r - r.mean(), _HG - _HG.mean()
    return float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-6)) >= 0.65


def hourglass_cells(f):
    """행동 순서 줄의 모래시계 칸들 [(y, 오른쪽 숫자 글)] 위에서부터. 모래시계는 모양(틀)으로 찾고 오른쪽 숫자는 따로 읽는다."""
    H, W = f.shape[:2]
    c = f[int(0.03 * H):int(0.85 * H), 0:int(0.20 * W)]
    c = cv2.resize(c, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    m = _hg_binar(c)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if not (0.024 * H <= h <= 0.07 * H):
            continue
        if not _is_hourglass((lab[y:y + h, x:x + w] == i).astype(np.uint8)):
            continue
        x0, x1 = x + w + 1, min(c.shape[1], x + w + int(4.5 * h))
        band = np.ascontiguousarray(m[max(0, y - h // 4):y + h + h // 4, x0:x1])
        if band.shape[0] < 3 or band.shape[1] < 3:
            continue
        k, _, s2, _ = cv2.connectedComponentsWithStats(band, 8)
        comps = sorted(tuple(int(v) for v in s2[j][:4]) for j in range(1, k) if s2[j][3] >= 0.6 * h)
        digits = [q for q in comps if q[2] > 0.26 * q[3]]
        if not digits:
            continue
        grp = [digits[0]]
        for q in digits[1:]:
            if q[0] - (grp[-1][0] + grp[-1][2]) > 0.6 * h:
                break
            grp.append(q)
        gx1 = grp[-1][0] + grp[-1][2] + int(0.6 * h)
        # 왼쪽은 구분선(「|」) 바로 뒤부터(구분선이 「1」로 읽혀 「|29」가 「129」가 되는 것을 막는다), 오른쪽은 여백까지
        seps = [q for q in comps if q[2] <= 0.26 * q[3] and q[0] < grp[0][0]]
        left = (seps[-1][0] + seps[-1][2] + 2) if seps else 0
        crop = c[max(0, y - h // 3):y + h + h // 3, x0 + left:x0 + gx1]
        if crop.size == 0:
            continue
        s = 48 / crop.shape[0]
        txt = rec_text(cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC))
        d = re.sub(r'\D', '', txt)
        if d:
            out.append((int(y / 2), d))
    return sorted(out)


def scan_cycles(rev, vid=0, mode='moc', start=0.0):
    """MoC · PF 의 쓴 사이클 수. 영상 처음(start)부터 쇼케이스 전까지 1초에 한 장씩 모래시계 칸을 읽는다.
    → {'value': 쓴 사이클, 'reads': [(t, 값)], 'first', 'last', 'note'}"""
    d = os.path.join(ROOT, rev)
    vids = json.load(open(os.path.join(d, 'videos.json'), encoding='utf8')) if os.path.exists(os.path.join(d, 'videos.json')) else [{'file': 'video0.mp4'}]
    video = os.path.join(d, vids[vid].get('file', f'video{vid}.mp4'))
    dur, W, H = tabs.probe(video)
    end = dur
    tl = os.path.join(d, f'tabs{vid}', 'timeline.txt')
    if os.path.exists(tl):
        ws = [float(m.group(1)) for m in re.finditer(r'window ([\d.]+)-', open(tl, encoding='utf8').read())]
        late = [w for w in ws if w > 0.3 * dur]
        if late:
            end = min(late)
    reads = []
    for t, f in tabs.frames(video, start, end - start, 1, W, H):
        cs = hourglass_cells(f)
        if not cs:
            continue
        v = cs[0][1]               # 가장 앞(위) 칸
        if mode == 'pf':
            v = int(v[-1])         # 카운터는 한 자리(「13」 = 구분선 + 3)
            if v > 3:
                continue
        else:
            if len(v) == 3 and v[0] == '1':
                v = v[1:]          # 구분선이 「1」로 붙은 것
            v = int(v)
            if v > 99:
                continue
        reads.append((round(t, 1), v))
    out = {'reads': reads, 'value': None, 'note': ''}
    if not reads:
        return out
    # 한 번만 나온 값은 잘못 읽은 것으로 보고 뺀다(연속 두 번 이상 · 모두 세 번 이상 나온 값만)
    cnt = {}
    for _, v in reads:
        cnt[v] = cnt.get(v, 0) + 1
    stable = [(t, v) for i, (t, v) in enumerate(reads)
              if cnt[v] >= 3 or (i + 1 < len(reads) and reads[i + 1][1] == v) or (i and reads[i - 1][1] == v)]
    if not stable:
        return out
    out['first'], out['last'] = stable[0], stable[-1]
    # 마지막으로 읽은 뒤에도 전투가 이어졌는지(왼쪽 위 웨이브 표시). 소환물로 행동 순서가 길어지면 모래시계 칸이
    # 화면 아래로 밀려 끝까지 안 보인다(rev_7dqskh 646초에 「⧗1」로 끊기고 전투는 820초까지) → 끝 값을 모르는 것
    last_t = reads[-1][0]
    seen = None
    for t, f in tabs.frames(video, last_t + 5, max(1, end - last_t - 5), 0.2, W, H):
        c = f[0:int(0.2 * H), 0:int(0.16 * W)]
        if any(re.search(r'\b[1-5]\s*/\s*[1-5]\b', b[4]) for b in ocr(c, 'chinese')):
            seen = round(t, 1)
    if seen is not None and seen - last_t > 15:
        out['lost_after'], out['battle_until'] = last_t, seen
    if mode == 'pf':
        tail = [v for _, v in stable[-5:]]
        n = max(set(tail), key=tail.count)
        # 카운터는 줄기만 한다. 전투가 끝나기 직전 마지막 칸은 한 번만 보이기도 한다(rev_n52sr9 392초 「⧗1」) →
        # 마지막 안정 값보다 꼭 1 작은 값이 그 뒤에 읽혔으면 받는다
        later = [v for t, v in reads if t > stable[-1][0]]
        if later and later[-1] == n - 1:
            n = later[-1]
        out['value'] = 3 - n
        out['counter'] = n
        if n == 0:
            # ⧗0 까지 지나 행동값을 다 쓰면 끝에 「Remaining Cycles: 0」 띠 → 4 사이클
            bt = cycles_out_banner(video, last_t - 2, min(end, last_t + 240), W, H)
            if bt is not None:
                out['value'], out['banner'] = 4, bt
                out['note'] = f'"Remaining Cycles: 0" banner at {bt}: Action Value ran out'
            else:
                out['note'] = 'counter 0 at the end, no "Remaining Cycles: 0" banner'
    else:
        out['value'] = max(0, stable[0][1] - stable[-1][1])
    return out


def cycles_out_banner(video, a, b, W, H, model='chinese'):
    """PF 에서 행동값을 다 써 끝날 때 화면 위쪽 가운데에 1초쯤 뜨는 빨간 띠 「Remaining Cycles: 0」(剩余轮次：0 …).
    이것이 보이면 4 사이클, 없으면 ⧗0 으로 끝난 3 사이클(사용자, 2026-10-09). 5fps 로 빨간 띠가 있는 프레임만 읽는다
    → 처음 본 시각(못 보면 None)"""
    for t, f in tabs.frames(video, max(0, a), max(1, b - a), 5, W, H):
        c = f[int(0.2 * H):int(0.38 * H), int(0.25 * W):int(0.75 * W)]
        hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV)
        red = ((hsv[..., 0] < 8) | (hsv[..., 0] > 172)) & (hsv[..., 1] > 110) & (hsv[..., 2] > 120)
        rows = red.mean(axis=1) > 0.35           # 띠는 가로로 넓다(화면 폭의 30% 남짓)
        if rows.sum() < 0.03 * H:
            continue
        for bx in ocr(c, model):
            if re.search(r'[:：]\s*0\s*$', bx[4].strip()):
                return round(t, 1)
    return None


def first_cell_time(rev, vid, t0, within, model='chinese'):
    """t0 뒤 within 초 안에 MoC · PF 전투 화면이 처음 보이는 시각: 왼쪽 위 웨이브 표시(「⚑ 1/3」 「1/2」).
    모래시계 칸은 전투 초반에 행동 순서 아래로 밀려 안 보이기도 해서(rev_121hwl6 84초에야 보임) 쓰지 않는다."""
    d = os.path.join(ROOT, rev)
    vids = json.load(open(os.path.join(d, 'videos.json'), encoding='utf8'))
    video = os.path.join(d, vids[vid]['file'])
    dur, W, H = tabs.probe(video)
    for t, f in tabs.frames(video, t0, min(within, dur - t0), 1, W, H):
        c = f[0:int(0.2 * H), 0:int(0.16 * W)]   # 위아래 검은 띠가 있는 영상(rev_13uh4f6)은 표시가 아래로 밀린다
        if any(re.search(r'\b[1-5]\s*/\s*[1-5]\b', b[4]) for b in ocr(c, model)):
            return round(t, 1)
    return None


if __name__ == '__main__':
    rev = sys.argv[1]
    p = json.load(open(os.path.join(ROOT, rev, 'review.json'), encoding='utf8'))['payload']
    s = (p.get('runs') or [p])[0]
    pl = 'Plight' in (s.get('boss_name') or '')
    r = scan(rev, int(sys.argv[2]) if len(sys.argv) > 2 else 0, plight=pl)
    print(rev, r['window'], 'final', r['final'], 'reads', len(r['reads']))
    for t, x in r['reads'][-6:]:
        print('  ', t, x)
