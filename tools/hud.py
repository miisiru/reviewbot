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
    c = f[0:int(0.45 * H), int(0.60 * W):W]
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


if __name__ == '__main__':
    rev = sys.argv[1]
    p = json.load(open(os.path.join(ROOT, rev, 'review.json'), encoding='utf8'))['payload']
    s = (p.get('runs') or [p])[0]
    pl = 'Plight' in (s.get('boss_name') or '')
    r = scan(rev, int(sys.argv[2]) if len(sys.argv) > 2 else 0, plight=pl)
    print(rev, r['window'], 'final', r['final'], 'reads', len(r['reads']))
    for t, x in r['reads'][-6:]:
        print('  ', t, x)
