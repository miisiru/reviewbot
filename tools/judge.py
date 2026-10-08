"""AI 없이 판정 재료를 읽는다(1단계: 빌드). tabs.py 가 남긴 광추 · 성혼 프레임에서
  - 누구 화면인지: 머리글 「길 / 이름」 칸 OCR → 제출된 캐릭터들의 모든 언어 이름 중 가장 가까운 것
  - 광추 이름: 패널 제목 칸 OCR → 제출 광추의 모든 언어 이름과 비교
  - 중첩: 「중첩 N / Superimposition N / 叠影N阶 …」 줄의 숫자
  - 성혼: 자물쇠 아이콘 개수(틀 맞추기, 언어 무관). 왼쪽 메뉴 성혼 줄의 빨간 「!」 = 활성화 가능
OCR 은 프레임 전체가 아니라 위치를 아는 작은 칸만, 읽은 글은 해석하지 않고 후보 이름과 맞춘다.
python judge.py <rev>   → runs/<rev>/judge.json + 요약 출력"""
import os, sys, json, re, glob, difflib, unicodedata
import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'auto'))
from ocr import OCR            # noqa: E402  (RapidOCR + 언어별 PP-OCRv5 인식 모델)
from names import localize     # noqa: E402

sys.path.insert(0, HERE)
from paths import RUNS as ROOT   # noqa: E402
PATH_WORDS = set()      # 길 이름(모든 언어) — 디테일 이름 줄에서 뺀다
LANGS = ['EN', 'KR', 'CHS', 'CHT', 'JP', 'VI', 'TH', 'RU', 'ES', 'PT', 'FR', 'DE', 'ID']
SUPERIMP = ['superimposition', '중첩단계', '叠影阶', '疊影階', '重畳ランク', 'tichtangbac', 'วางซอนlv', 'наложениеур',
            'superposicionniv', 'sobreposicao', 'superposition', 'bundelungsst', 'superimpositionlv']
MODELS = ['chinese', 'korean', 'latin', 'eslav', 'thai']
_ocr = {}


def ocr(img, model):
    key = (model, sys.modules['ocr'].USE_GPU)      # GPU 엔진과 CPU 엔진을 따로 둔다(auto_judge 가 단계마다 바꾼다)
    if key not in _ocr:
        _ocr[key] = OCR(model)
    scale = 2.0 if img.shape[1] < 500 else 1.0
    return _ocr[key](img, scale=scale)


def norm(s):
    # 라틴 글자의 성조 · 악센트만 지운다. 분해한 뒤 다시 합쳐야 한글 음절이 자모로 쪼개진 채 남지 않는다
    s = unicodedata.normalize('NFKD', str(s)).lower()
    s = unicodedata.normalize('NFC', ''.join(c for c in s if not unicodedata.combining(c)))
    s = s.replace('đ', 'd')
    return re.sub(r'[^0-9a-z\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u0e00-\u0e7f\u0400-\u04ff]+', '', s)


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if len(a) >= 2 and len(b) >= 2 and (a in b or b in a):
        return 0.6 + 0.4 * min(len(a), len(b)) / max(len(a), len(b))
    return difflib.SequenceMatcher(None, a, b).ratio()


_alias = {}


_en_index = None


def en_key(en):
    """제출 이름의 게임 EN 표기. 제출 쪽이 문장부호를 빼고 적는 일이 있어(「Dance Dance Dance」 = 「Dance! Dance! Dance!」)
    글자만 같으면 같은 이름으로 본다."""
    global _en_index
    if localize(en, 'KR'):
        return en
    if _en_index is None:
        import names
        _en_index = {}
        for v in names._load('EN').values():
            if isinstance(v, str) and len(v) < 60:
                _en_index.setdefault(norm(v), names.clean(v))
    return _en_index.get(norm(en), en)


def aliases(en):
    if en not in _alias:
        k = en_key(en)
        out = {en, k}
        for l in LANGS:
            out.update(localize(k, l) or [])
        _alias[en] = sorted(out)
    return _alias[en]


def best(text, en):
    return max((sim(text, a), a) for a in aliases(en))


# ---------- 배치 · 칸 ----------
def layout_of(rev, vid):
    lay = []
    for line in open(os.path.join(ROOT, rev, f'tabs{vid}', 'timeline.txt'), encoding='utf8'):
        m = re.search(r'window ([\d.]+)-([\d.]+) layout x=(\d+) y0=(\d+) sp=([\d.]+)', line)
        if m:
            lay.append((float(m[1]), float(m[2]), (float(m[3]), float(m[4]), float(m[5]))))
    return lay


def segs_of(rev, vid):
    out = []
    for line in open(os.path.join(ROOT, rev, f'tabs{vid}', 'timeline.txt'), encoding='utf8'):
        m = re.match(r'\s*([\d.]+)\s+([\d.]+)\s+(\w+)', line)
        if m:
            out.append((float(m[1]), float(m[2]), m[3]))
    return out


def seg_at(segs, t, tab):
    for a, b, k in segs:
        if k == tab and a - 0.05 <= t <= b + 0.05:
            return (a, b)
    return (t - 0.3, t + 0.3)


def lay_at(lays, t):
    for a, b, l in lays:
        if a - 1 <= t <= b + 1:
            return l
    return lays[0][2] if lays else None


def header_crop(f, lay):
    x, y0, sp = lay
    H, W = f.shape[:2]
    return f[int(max(0, y0 - 1.05 * sp)):int(max(1, y0 - 0.5 * sp)), int(max(0, x - 1.6 * sp)):int(min(W, x + 4.2 * sp))]


def panel_crop(f):
    H, W = f.shape[:2]
    return f[int(0.04 * H):int(0.80 * H), int(0.70 * W):int(0.99 * W)]


# ---------- 성혼: 노드 6개 찾고 자물쇠 판정 ----------
# 노드 6개의 상대 위치(실제 화면에서 잰 값). 캐릭터 줄이 위인 배치와 왼쪽인 배치(종말 열람 모드 · 일부 기기)는
# 노드 모양이 달라 기준을 둘 둔다. 축마다 따로 배율을 맞추므로 화면비 차이는 흡수된다
NODE_REFS = [np.array([(442, 155), (709, 145), (1025, 284), (879, 604), (561, 582), (260, 525)], float),
             np.array([(432, 95), (695, 75), (926, 250), (880, 516), (605, 522), (396, 465)], float),
             # 4:3 에 가까운 태블릿 화면(1030×720, rev_brnfnl): 16:9 와 노드 간격 비율 자체가 다르다
             np.array([(266, 178), (564, 148), (800, 326), (728, 604), (438, 630), (178, 578)], float)]
ANCHORS = [(0, 3), (1, 4), (2, 5)]
_lock = None


def lock_tpl():
    global _lock
    if _lock is None:
        _lock = cv2.cvtColor(cv2.imread(os.path.join(HERE, 'lock_tpl.png')), cv2.COLOR_BGR2GRAY)
    return _lock


def circles(g, lay):
    x, y0, sp = lay
    H, W = g.shape
    ox, oy = int(x + 1.3 * sp), int(max(0, y0 - 0.8 * sp))
    reg = cv2.medianBlur(g[oy:H, ox:int(W - 0.3 * sp)], 3)
    cs = cv2.HoughCircles(reg, cv2.HOUGH_GRADIENT, dp=1, minDist=int(1.1 * sp), param1=120, param2=18,
                          minRadius=int(0.28 * sp), maxRadius=int(0.5 * sp))
    return [] if cs is None else [(float(cx + ox), float(cy + oy)) for cx, cy, _ in cs[0]]


def fit_nodes(cs, sp):
    """원 후보들 중 노드 6개 모양에 가장 잘 맞는 배치 → 6개 예상 위치(맞은 수가 5 미만이면 None)."""
    best = (0, 1e9, None)
    tol = 0.4 * sp
    for ref in NODE_REFS:
        for ai, aj in ANCHORS:
            rdx, rdy = ref[aj, 0] - ref[ai, 0], ref[aj, 1] - ref[ai, 1]
            for i, a in enumerate(cs):
                for j, b in enumerate(cs):
                    if i == j:
                        continue
                    kx, ky = (b[0] - a[0]) / rdx, (b[1] - a[1]) / rdy
                    if kx <= 0 or ky <= 0 or not (0.6 < kx / ky < 1.6) or not (0.3 * sp / 62.8 < kx < 3 * sp / 62.8):
                        continue
                    pred = np.c_[a[0] + (ref[:, 0] - ref[ai, 0]) * kx, a[1] + (ref[:, 1] - ref[ai, 1]) * ky]
                    hit, err = 0, 0.0
                    for p in pred:
                        dd = min((np.hypot(p[0] - c[0], p[1] - c[1]) for c in cs), default=1e9)
                        if dd < tol:
                            hit += 1
                            err += dd
                    if hit > best[0] or (hit == best[0] and err < best[1]):
                        best = (hit, err, pred)
    return best[2] if best[0] >= 5 else None


def hp(g):
    """고주파 영상(밝기에서 흐린 밝기를 뺀 것). 노드 뒤 배경이 밝든 어둡든 자물쇠 글리프 모양만 남는다."""
    g = g.astype(np.float32)
    return g - cv2.GaussianBlur(g, (0, 0), 3)


_glyph = None


def glyph_tpl():
    """자물쇠 글리프(노드 가운데 흰 자물쇠)만의 고주파 틀, 줄 간격 62.8 기준."""
    global _glyph
    if _glyph is None:
        t = lock_tpl()
        c = t.shape[0] // 2
        _glyph = hp(t)[c - 11:c + 11, c - 10:c + 10]
    return _glyph


def node_names(f, pred, sp):
    """노드마다 오른쪽 성혼 이름 줄의 흰 글자 픽셀(192×24). 캐릭터마다 이름이 달라 누구 화면인지 가르는 데 쓴다."""
    H, W = f.shape[:2]
    out = []
    for px, py in pred:
        c = f[int(max(0, py)):int(min(H, py + 0.5 * sp)), int(max(0, px + 0.55 * sp)):int(min(W, px + 4.0 * sp))]
        if c.size == 0 or c.shape[0] < 3 or c.shape[1] < 3:
            out.append(np.zeros((24, 192), bool))
            continue
        hsv = cv2.cvtColor(cv2.resize(c, (192, 24)), cv2.COLOR_BGR2HSV)
        v = hsv[..., 2]
        out.append((v > max(110, 0.7 * float(np.percentile(v, 99.5)))) & (hsv[..., 1] < 60))
    return out


def names_changed(a, b):
    """두 프레임의 노드 이름 여섯 중 바뀐 것 수(둘 다 글자가 보이는 노드만). 캐릭터가 바뀌면 거의 다 바뀌고,
    자막 상자가 생기거나 걷히면 가린 노드만 바뀐다(rev_zrakw 11.5초)."""
    # 글자 획이 한두 픽셀 밀리는 것(압축 · 확대)은 같은 것으로: 서로 상대를 3px 불린 것 밖으로 나간 픽셀만 센다
    k = np.ones((3, 3), np.uint8)
    n = 0
    for p, q in zip(a, b):
        if p.sum() < 40 or q.sum() < 40:
            continue
        dp = cv2.dilate(p.astype(np.uint8), k, iterations=1).astype(bool)
        dq = cv2.dilate(q.astype(np.uint8), k, iterations=1).astype(bool)
        if ((p & ~dq).sum() + (q & ~dp).sum()) / max(1, p.sum() + q.sum()) > 0.35:
            n += 1
    return n


def lock_states(f, lay, want_pred=False):
    """노드 6개마다 자물쇠 점수. 노드를 못 찾으면 None. 노드 둘레 원이 안 잡힌 노드(영상에 박힌 자막 상자 등이
    가렸다: rev_zrakw 4 · 5번)는 그 칸만 None — 자물쇠가 안 보인다고 열림으로 세지 않는다.
    want_pred 면 (점수, 노드 자리)."""
    x, y0, sp = lay
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    cs = circles(g, lay)
    pred = fit_nodes(cs, sp)
    if pred is None:
        return (None, None) if want_pred else None
    H, W = g.shape
    t0 = glyph_tpl()
    out = []
    for px, py in pred:
        if min((np.hypot(px - cx, py - cy) for cx, cy in cs), default=1e9) >= 0.4 * sp:
            out.append(None)
            continue
        r = hp(g[int(max(0, py - 0.5 * sp)):int(min(H, py + 0.5 * sp)), int(max(0, px - 0.5 * sp)):int(min(W, px + 0.5 * sp))])
        sc = -1.0
        for m in (0.85, 1.0, 1.15):
            t = cv2.resize(t0, None, fx=sp / 62.8 * m, fy=sp / 62.8 * m, interpolation=cv2.INTER_AREA)
            if r.shape[0] > t.shape[0] and r.shape[1] > t.shape[1]:
                sc = max(sc, float(cv2.matchTemplate(r, t, cv2.TM_CCOEFF_NORMED).max()))
        out.append(round(sc, 2))
    return (out, pred) if want_pred else out


LOCK_MIN = 0.6     # 자물쇠로 볼 점수(잠김 0.65~1.0, 열림 0.3~0.5 로 잰 값)
LOCK_GRAY = (0.5, 0.65)   # 이 사이면 애매(신뢰도 감점)
# 성혼은 차례로만 열린다: 앞 k 개 열림, 뒤는 잠김. 노드마다 따로 가르지 않고 여섯 점수에 가장 잘 맞는 k 를 고른다.
# 잰 값(판 66편): 열림 0.25~0.57, 잠김 대부분 0.8~0.96(드물게 0.67) → 가운데 0.7
LOCK_MID = 0.7
FIT_SURE = 0.1     # 가장 잘 맞는 k 와 다음 k 의 어긋남 차이가 이보다 작으면 애매


def eidolon_fit(sc):
    """노드 점수 여섯 → (열린 수 k, 다음으로 맞는 k, 두 어긋남의 차)."""
    # None(가려진 노드)은 어느 쪽이든 어긋남 0 — 앞뒤 노드가 정한다
    cost = [sum(max(0.0, v - LOCK_MID) for v in sc[:k] if v is not None)
            + sum(max(0.0, LOCK_MID - v) for v in sc[k:] if v is not None) for k in range(len(sc) + 1)]
    order = sorted(range(len(cost)), key=lambda k: cost[k])
    return order[0], order[1], round(cost[order[1]] - cost[order[0]], 3)


def read_eidolon(video, t_ref, lay, W, H, since=None, until=None, ref_img=None):
    """성혼 화면을 t_ref 앞 1초 ~ 뒤 1.5초(앞뒤로 남겨 둔 다른 프레임은 넘지 않음) 10fps 로 다시 읽는다.
    머리글 이름 모양이 t_ref 프레임과 같은 프레임만 쓰고, 이름이 막 바뀐 첫 프레임은 뺀다 — 성혼 탭을 연 채 캐릭터를
    넘기면 머리글이 먼저 바뀌고 노드 그림은 한 프레임 늦게 바뀐다.
    노드마다 최댓값으로 잠김을 정한다(화면이 열리는 연출 동안 자물쇠가 차례로 또렷해지므로).
    → (잠김 수, 노드별 최댓값, 쓴 프레임 수)"""
    import tabs
    a = t_ref - 1.0 if since is None else max(t_ref - 1.0, since + 0.05)
    b = t_ref + 1.5 if until is None else min(t_ref + 1.5, until - 0.05)
    # 영상 원래 프레임(최대 30fps)으로 읽는다: 성혼 탭을 0.3~0.4초만 여는 영상이 있어 10fps 로는 한두 장뿐이다
    fr = list(tabs.frames(video, max(0, a), max(0.15, b - a), 30, W, H))
    if not fr:
        return None, None, 0
    # 기준 프레임: t_ref 와 같거나 바로 뒤(같은 거리면 앞 캐릭터 화면일 수 있는 앞쪽을 피한다)
    ref = min(fr, key=lambda z: (abs(z[0] - t_ref) + (0.03 if z[0] < t_ref - 0.02 else 0)))[1]
    # 누구 화면인지 정한 저장 프레임이 있으면 그것을 기준으로(다시 디코드한 같은 시각 프레임은 한두 장 어긋나
    # 이름이 바뀌기 직전 화면일 수 있다: rev_16nnmps 317.7초)
    if ref_img is not None and ref_img.shape[:2] == ref.shape[:2]:
        ref = ref_img
    ref_nm = tabs.name_mask(ref, lay)
    mx, n = _eidolon_pass(fr, lay, t_ref, ref_nm)
    fit = eidolon_fit(mx) if mx else None
    if mx is None or n < 3 or fit[2] < FIT_SURE:
        # 애매하거나 프레임이 적으면 둘레를 더 본다(사용자, 2026-10-09): 앞뒤 2초, 머리글 조건 없이 —
        # 머리글은 화면이 열리는 연출 동안 「다름」으로 읽혀 또렷한 프레임을 버리는 일이 있다(rev_ss0gr5 361.1~361.23초).
        # 다른 캐릭터 화면은 노드 옆 성혼 이름 그림으로 나눠 뺀다
        fr2 = list(tabs.frames(video, max(0, t_ref - 2.0), 4.0, 30, W, H))
        mx2, n2 = _eidolon_pass(fr2, lay, t_ref, None)
        fit2 = eidolon_fit(mx2) if mx2 else None
        if mx2 is not None and (mx is None or fit2[2] > fit[2] or (fit2[2] >= fit[2] and n2 > n)):
            mx, n = mx2, n2
    if mx is None:
        return None, None, 0
    return sum(1 for v in mx if v is not None and v >= LOCK_MIN), mx, n


def _eidolon_pass(fr, lay, t_ref, ref_nm):
    """read_eidolon 의 한 번 읽기. ref_nm 이 있으면 머리글 이름이 같은 프레임만(이름이 같아진 뒤 0.1초 빼고).
    → (노드별 최댓값, 쓴 프레임 수) 또는 (None, 0)"""
    import tabs
    # 이름이 같아진 뒤 0.1초는 쓰지 않는다 — 성혼 탭을 연 채 캐릭터를 넘기면 머리글이 먼저 바뀌고 노드 그림은 0.1초쯤 늦게 바뀐다
    # (30fps 로는 서너 장. 한 장만 빼면 앞 캐릭터 노드가 섞인다: rev_16nnmps 317.7초)
    t_ref_used = t_ref
    sts, same_since = [], None
    for t, f in fr:
        if ref_nm is not None:
            same = tabs.same_name(tabs.name_mask(f, lay), ref_nm) is not False
            if not same:
                same_since = None
                continue
            if same_since is None:
                same_since = t
            if t - same_since < 0.095:
                continue
        # 메뉴에서 켜진 탭이 성혼이 아니면 쓰지 않는다 — 행적 화면의 노드 둘레가 성혼 노드 배치에 들어맞아
        # 「자물쇠 없음」으로 섞이는 일이 있다(rev_1fntqfx 303.4초)
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
        tab = tabs.which_tab(tabs.pale_gold(hsv, lay), tabs.gold_rows(hsv, lay))
        if tab is not None and tab != 'Eidolon':
            continue
        st, pred = lock_states(f, lay, want_pred=True)
        if st is None:
            continue
        sts.append((t, st, node_names(f, pred, lay[2])))
    if not sts:
        return None, 0
    # 머리글이 워터마크에 덮이면 이름 비교로 캐릭터가 바뀐 것을 못 가른다(rev_122c7wk 233.0초 앞 캐릭터,
    # rev_1alwmmn 943.63초 다음 캐릭터) → 노드 옆 성혼 이름이 셋 넘게 한꺼번에 바뀐 자리로 나눠 기준 시각이 든 구간만 쓴다.
    # 자물쇠 점수가 튀는 것으로 가르면 안 된다: 영상에 박힌 자막 상자가 걷히면 가렸던 노드 점수가 0.4 → 0.9 로 튄다(rev_zrakw)
    segs = [[sts[0]]]
    for prev, cur in zip(sts, sts[1:]):
        if names_changed(prev[2], cur[2]) >= 3:
            segs.append([])
        segs[-1].append(cur)
    seg = next((s for s in segs if s[0][0] - 0.02 <= t_ref_used <= s[-1][0] + 0.02), None) \
        or min(segs, key=lambda s: min(abs(z[0] - t_ref_used) for z in s))
    seg = [(t, st) for t, st, _ in seg]
    mx = seg[0][1]
    for _, st in seg[1:]:
        mx = [q if p is None else p if q is None else max(p, q) for p, q in zip(mx, st)]
    return mx, len(seg)


def red_badge(f, lay, row=4):
    """왼쪽 메뉴 row 번째 줄 아이콘 둘레의 빨간 「!」 배지."""
    x, y0, sp = lay
    H, W = f.shape[:2]
    cy = y0 + row * sp
    r = f[int(max(0, cy - 0.6 * sp)):int(min(H, cy + 0.2 * sp)), int(max(0, x - 0.6 * sp)):int(min(W, x + 0.6 * sp))]
    hsv = cv2.cvtColor(r, cv2.COLOR_BGR2HSV)
    red = ((hsv[..., 0] < 8) | (hsv[..., 0] > 172)) & (hsv[..., 1] > 120) & (hsv[..., 2] > 120)
    return int(red.sum()) >= max(12, int(0.004 * sp * sp))


# ---------- 읽기 ----------
def read_lines(img, models):
    """여러 모델로 읽어 (모델, 줄 목록). 줄 = (y, x, text)."""
    out = {}
    for m in models:
        res = ocr(img, m)
        out[m] = sorted([(b[1], b[0], b[4]) for b in res], key=lambda z: (z[0], z[1]))
    return out


def header_name(lines):
    """머리글 줄들 중 「길 / 이름」에서 이름 쪽(없으면 전체)."""
    texts = [t for _, _, t in lines]
    for t in texts:
        if '/' in t or '／' in t:
            return re.split(r'[/／]', t, maxsplit=1)[1]
    return ' '.join(texts)


def superimp_from(lines):
    """중첩 줄: 숫자 하나(1~5)로 끝나는 짧은 줄 중 12개 언어 「중첩 #1」 표기와 가장 비슷한 것.
    OCR 이 글자 하나쯤 빠뜨리거나 틀려도(「影1阶」, 「重長ランク1」) 잡히게 정확 일치가 아니라 비슷함으로 고른다."""
    bestc = (0.0, None, None)
    for i, (y, x, t) in enumerate(lines):
        joined = t
        # 숫자 하나(앞의 로마 숫자 배지 「I」가 「1」로 읽혀 둘이 되기도 한다)
        if not (1 <= len(re.findall(r'\d', t)) <= 2) or not re.search(r'[1-5]\D*$', t):
            # 숫자가 같은 높이의 다음 조각으로 떨어진 경우
            nxt = [t2 for y2, x2, t2 in lines[i + 1:i + 3] if abs(y2 - y) < 12 and re.fullmatch(r'\D{0,4}[1-5]\D{0,4}', t2)]
            if not nxt:
                continue
            joined = t + nxt[0]
        if re.search(r'[%+/]|lv|\d{2}', joined.lower()) or ':' in joined.rstrip(' :：'):
            continue
        word = norm(re.sub(r'[0-9]', '', joined))
        if not word or len(word) > 24:
            continue
        sc = max(difflib.SequenceMatcher(None, word, k).ratio() for k in SUPERIMP)
        if any(k in word or (len(word) >= 2 and word in k) for k in SUPERIMP):
            sc = max(sc, 0.9)
        if sc > bestc[0]:
            bestc = (sc, int(re.findall(r'[1-5]', joined)[-1]), joined)
    return (bestc[1], bestc[2]) if bestc[0] >= 0.45 else (None, None)


_no_lc = None


def no_lc_words():
    """「광추 없음」 낱말(Not Equipped / Unequipped / 미장착 / 未装备 …, 13개 언어). 제출에서 광추가 빈 칸이면 화면이 이 낱말을 보여야 한다."""
    global _no_lc
    if _no_lc is None:
        _no_lc = set()
        for en in ('Not Equipped', 'Unequipped'):
            for l in LANGS:
                _no_lc.update(norm(v) for v in (localize(en, l) or []) if norm(v))
    return _no_lc


_guide = None


def guide_words():
    """광추 제목과 한 줄로 읽히는 오른쪽 위 「캐릭터 공략」 단추 글(13개 언어, TextMap)."""
    global _guide
    if _guide is None:
        _guide = sorted({norm(v) for l in LANGS for v in (localize('Character Guide', l) or [])} - {''}, key=len, reverse=True)
    return _guide


def title_sim(t, a):
    """OCR 줄 t 가 광추 이름 a 인 정도. 줄에 「캐릭터 공략」 단추 글 · 길 이름 · 레벨이 붙어 읽혀도(「Character Guide
    Mushy Shroomy's Adventures」) 이름 부분만 본다: 단추 글을 떼고, 그래도 길면 줄 안에서 이름 길이만큼의 가장 잘 맞는 자리."""
    n, an = norm(t), (a if isinstance(a, list) else norm(a))
    if not n or not an:
        return 0.0
    for g in guide_words():
        if g in n:
            n = n.replace(g, '')
    n = n.translate(_SMALL_KANA)
    if re.search('[Ѐ-ӿ]', n):
        n = n.translate(_LAT_CYR)       # 러시아어 줄에 섞여 읽힌 라틴 닮은꼴(zаnаvеs → занавес)
    L = len(an)
    if len(n) <= 1.15 * L:
        wins = [n]
    else:
        # OCR 이 한두 글자를 빼거나 더 읽어도(燃ゆる影 → 燃ゆ影) 맞게 길이 L-2 ~ L+2 창
        wins = [n[i:i + m] for m in range(max(1, L - 2), L + 3) for i in range(0, max(1, len(n) - m + 1))]
    return max(_charset_ratio(w, an) if isinstance(an, list) else difflib.SequenceMatcher(None, w, an.translate(_SMALL_KANA)).ratio()
               for w in wins)


_LAT_CYR = str.maketrans('aeopcxykmthbnzvsiu', 'аеорсхукмтнвпзвсии')
# 일본어 작은 글자는 OCR 이 큰 글자로 읽는 일이 잦다(めくって → めくつて)
_SMALL_KANA = str.maketrans('ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮ', 'あいうえおつやゆよわアイウエオツヤユヨワ')


def _charset_ratio(w, sets):
    """글자 자리마다 허용 글자 모음(간체 · 번체 같은 자리 글자)과 맞춘 비율."""
    if len(w) != len(sets):
        return difflib.SequenceMatcher(None, w, ''.join(min(s) for s in sets)).ratio()
    return sum(1 for ch, s in zip(w, sets) if ch in s) / len(sets)


def lc_aliases(en):
    """aliases 에 간체 · 번체를 한 자리씩 합친 것을 더한다: 영상 글이 「當一颗星」처럼 두 글자 체계가 섞여 읽혀도 맞게."""
    al = list(aliases(en))
    k = en_key(en)
    chs, cht = [norm(x) for x in localize(k, 'CHS') or []], [norm(x) for x in localize(k, 'CHT') or []]
    for a in chs:
        for b in cht:
            if len(a) == len(b) and a != b:
                al.append([{p, q} for p, q in zip(a, b)])
    return al


def lc_score(texts, c):
    """광추 제목 칸 글들이 이 캐릭터의 제출 광추와 얼마나 맞는지. 제출 광추가 빈 칸이면 「광추 없음」 낱말과 맞는 정도."""
    if c['lc']:
        # 긴 제목은 두 줄로 읽힌다(「Mushy Shroomy's」 / 「Adventures」) → 이웃 줄을 이은 것과 모두 이은 것도 본다
        tt = list(texts) + [a + ' ' + b for a, b in zip(texts, texts[1:])] + ([' '.join(texts)] if len(texts) > 2 else [])
        return max(title_sim(t, a) for t in tt for a in lc_aliases(c['lc']))
    ws = no_lc_words()
    return max((1.0 if norm(t) in ws or any(len(w) >= 3 and w in norm(t) for w in ws) else
                max((sim(t, w) for w in ws), default=0.0)) for t in texts)


def path_words():
    if not PATH_WORDS:
        for en in ['Elation', 'Remembrance', 'Harmony', 'Destruction', 'Preservation', 'Nihility', 'Abundance', 'The Hunt', 'Erudition']:
            for l in LANGS:
                for v in localize(en, l) or []:
                    PATH_WORDS.add(norm(v))
    return PATH_WORDS


_ei_names = None


def ei_names(en):
    """그 캐릭터의 성혼 이름 6개 × 13개 언어(정규화). tools/eidolon_names.json(build_eidolon_names.mjs 로 만든다)."""
    global _ei_names
    if _ei_names is None:
        raw = json.load(open(os.path.join(HERE, 'eidolon_names.json'), encoding='utf8'))
        _ei_names = {}
        for key, per in raw.items():
            name = key.rsplit('#', 1)[0]
            s = _ei_names.setdefault(norm(name), set())
            for vs in per.values():
                s.update(norm(v.replace('\\n', '')) for v in vs if v)
    base = re.sub(r'\s*\([^()]*\)$', '', en)      # 「March 7th (Hunt)」 → 게임 이름 「March 7th」(두 갈래의 이름이 합쳐진다)
    return (_ei_names.get(norm(en_key(en)), set()) or _ei_names.get(norm(en), set())
            or _ei_names.get(norm(base), set()))


def ei_who(f, lay, chars, model):
    """성혼 화면에 보이는 성혼 이름 줄이 누구 것인지. 머리글이 워터마크에 덮여도 성혼 이름은 캐릭터마다 다르다.
    [(맞은 줄 수, k)] 큰 것부터."""
    H, W = f.shape[:2]
    x0 = int(lay[0] + 3 * lay[2]) if lay else int(0.2 * W)
    lines = [norm(t) for _, _, t in read_lines(f[:, min(x0, W - 1):], [model])[model]]
    lines = [t for t in lines if len(t) >= 4]
    out = []
    for k, c in enumerate(chars):
        names = ei_names(c['char'])
        hit = sum(1 for t in lines if any(t == n or (len(t) >= 5 and (t in n or n in t)) or
                                          difflib.SequenceMatcher(None, t, n).ratio() >= 0.75 for n in names))
        out.append((hit, k))
    return sorted(out, reverse=True)


def judge(rev):
    path_words()
    d = os.path.join(ROOT, rev)
    rj = json.load(open(os.path.join(d, 'review.json'), encoding='utf8'))
    p = rj['payload']
    sides = p.get('runs') or [p]
    vids = json.load(open(os.path.join(d, 'videos.json'), encoding='utf8')) if os.path.exists(os.path.join(d, 'videos.json')) else [{'file': 'video0.mp4'}]
    chars = []
    for s in sides:
        for i in range(1, 5):
            c = s.get(f'p{i}_char')
            if c:
                chars.append({'char': c, 'lc': s.get(f'p{i}_lc'), 'e': s.get(f'p{i}_eidolon'), 's': s.get(f'p{i}_superimp')})
    frames = []
    for vi in range(len(vids)):
        lays = layout_of(rev, vi) if os.path.exists(os.path.join(d, f'tabs{vi}', 'timeline.txt')) else []
        # 파일 이름은 「0359.10_LightCone」 꼴인데 1000초부터는 앞 0 이 없다(「1250.90_…」, rev_1dq2ylk) → 숫자로 시작하는 것 모두
        for fp in sorted(glob.glob(os.path.join(d, f'tabs{vi}', '[0-9]*_*.jpg')), key=lambda p: float(os.path.basename(p).split('_')[0])):
            m = re.match(r'(\d+\.\d+)_(LightCone|Eidolon)', os.path.basename(fp))
            if not m:
                continue
            frames.append({'vid': vi, 't': float(m[1]), 'tab': m[2], 'path': fp, 'lay': lay_at(lays, float(m[1]))})
    # 언어(모델) 고르기: 광추 패널 제목이 제출 광추 이름과 가장 잘 맞는 모델
    # 언어(모델) 고르기: 광추 화면 두 장의 제목 · 머리글이 제출 이름들과 가장 잘 맞는 모델.
    # 한국어 글은 중국어 모델로 못 읽고, 중국어 모델이 한국어 영상에서도 숫자 · 라틴 글자로 그럴듯하게 맞는 일이 있어
    # 첫 모델에서 멈추지 않고 다섯을 다 견준다
    model = 'chinese'
    lcs = [f for f in frames if f['tab'] == 'LightCone'][:2]
    # 광추 탭을 아예 안 연 영상(rev_s4it7k: 태국어, 넷 다 성혼 · 유물만 봄)은 lcs 가 비어 제목으로 언어를 못 고른다
    # → 성혼 탭 머리글로 대신 고른다(머리글은 어느 탭에나 있다). 그래도 없으면 중국어로 남고, 아래 HUD · 시작 찾기가
    # 엉뚱한 언어로 돌아 못 읽는다(사용자, 2026-10-09)
    cand = lcs or [f for f in frames if f['tab'] == 'Eidolon' and f['lay']][:3]
    if cand:
        scores = {}
        for m in ('chinese', 'korean', 'latin', 'eslav', 'thai'):     # 러시아어 · 태국어 영상도 있다(eslav · thai 모델)
            tot = 0.0
            for fr in cand:
                f = cv2.imread(fr['path'])
                if fr['tab'] == 'LightCone':
                    pl = read_lines(panel_crop(f), [m])[m]
                    tot += max((best(t, c['lc'])[0] for _, _, t in pl[:6] for c in chars if c['lc']), default=0)
                if fr['lay']:
                    hl = read_lines(header_crop(f, fr['lay']), [m])[m]
                    tot += max((best(header_name(hl), c['char'])[0] for c in chars), default=0)
            scores[m] = tot
        model = max(scores, key=scores.get)
    for fr in frames:
        f = cv2.imread(fr['path'])
        lay = fr['lay']
        hl = read_lines(header_crop(f, lay), [model])[model] if lay else []
        fr['header'] = header_name(hl)
        fr['who'] = sorted(((best(fr['header'], c['char'])[0], k) for k, c in enumerate(chars)), reverse=True)
        if fr['tab'] == 'LightCone':
            pl = read_lines(panel_crop(f), [model])[model]
            # 일본어 제목 위의 후리가나(「ながよる」 「かがや」 「ほし」)는 줄로 따로 잡혀 제목을 밀어낸다 → 짧은 히라가나만의 줄은 뺀다(rev_13uh4f6)
            furi = lambda t: bool(re.fullmatch(r'[぀-ゟ\s・]{1,8}', t))
            pl_t = [z for z in pl if not furi(z[2])]
            fr['panel_title'] = ' '.join(t for _, _, t in pl_t[:3])
            # 길 이름 줄(「记忆」 「환락」)은 그 낱말이 든 광추 이름(「记忆永不落幕」)과 부분 일치해 0.7 남짓이 나오므로 뺀다
            tl = [t for _, _, t in pl_t[:4] if norm(t) not in PATH_WORDS] or ['']
            fr['lc_scores'] = sorted(((lc_score(tl, c), k) for k, c in enumerate(chars)), reverse=True)
            fr['superimp'], fr['superimp_line'] = superimp_from(pl)
            if fr['superimp'] is None:
                # 「중첩 N」 줄은 광추 효과 칸 안에 있고 그 칸은 저절로 내려간다 — 고른 프레임에서 줄이 위로 사라졌으면
                # 같은 광추 구간의 다른 프레임(앞 1초 ~ 뒤 0.8초, 이웃 프레임은 넘지 않음)에서 읽는다(rev_3eq9x1)
                import tabs
                video = os.path.join(d, vids[fr['vid']].get('file', f"video{fr['vid']}.mp4"))
                _, W, H = tabs.probe(video)
                ts = sorted(g['t'] for g in frames if g['vid'] == fr['vid'] and g is not fr)
                a = max([fr['t'] - 1.0] + [t + 0.05 for t in ts if t < fr['t']])
                b = min([fr['t'] + 0.8] + [t - 0.05 for t in ts if t > fr['t']])
                votes = []
                for _, g in tabs.frames(video, max(0, a), max(0.1, b - a), 10, W, H):
                    sp, line = superimp_from(read_lines(panel_crop(g), [model])[model])
                    if sp is not None:
                        votes.append((sp, line))
                if votes:
                    sp = max({v for v, _ in votes}, key=lambda v: sum(1 for x, _ in votes if x == v))
                    fr['superimp'], fr['superimp_line'] = sp, next(l for v, l in votes if v == sp) + f' (nearby frames {len(votes)})'
        else:
            import tabs
            video = os.path.join(d, vids[fr['vid']].get('file', f"video{fr['vid']}.mp4"))
            _, W, H = tabs.probe(video)
            # 읽는 범위: 이 프레임 앞 1초 ~ 뒤 0.8초, 단 앞뒤로 남겨 둔 다른 프레임(다른 캐릭터일 수 있다)을 넘지 않는다
            ts = sorted(g['t'] for g in frames if g['vid'] == fr['vid'] and g is not fr)
            prv = max((t for t in ts if t < fr['t']), default=None)
            nxt = min((t for t in ts if t > fr['t']), default=None)
            n, mx, nfr = read_eidolon(video, fr['t'], lay, W, H, since=prv, until=nxt, ref_img=f) if lay else (None, None, 0)
            fr['locks'], fr['lock_scores'], fr['lock_frames'] = n, mx, nfr
            fr['activatable'] = red_badge(f, lay) if lay else False
            fr['ei_who'] = ei_who(f, lay, chars, model)
    tb = [k for k, c in enumerate(chars) if c['char'].startswith('Trailblazer')]
    # 디테일 화면 큰 이름(오른쪽 위). 머리글이 워터마크에 덮여도 읽힌다. 구간마다 한 장 읽어 둔다
    import tabs
    dets = []
    for vi in range(len(vids)):
        p_tl = os.path.join(d, f'tabs{vi}', 'timeline.txt')
        if not os.path.exists(p_tl):
            continue
        video = os.path.join(d, vids[vi].get('file', f'video{vi}.mp4'))
        _, W, H = tabs.probe(video)
        raw = []
        for a, b, k in segs_of(rev, vi):
            if k != 'Details' or b - a < 0.2:
                continue
            # 구간 끝 무렵 한 장: 디테일 탭에 머문 채 캐릭터를 넘기면 구간 앞쪽은 앞 캐릭터다. 뒤따르는 탭은 끝 쪽 캐릭터 것
            fdet = next(tabs.frames(video, max(a, b - 0.15), 0.1, 10, W, H), (None, None))[1]
            if fdet is None:
                continue
            Hh, Ww = fdet.shape[:2]
            crop = fdet[int(0.03 * Hh):int(0.22 * Hh), int(0.66 * Ww):int(0.99 * Ww)]
            raw.append((a, b, [t for _, _, t in read_lines(crop, [model])[model][:4]]))
        # 디테일 화면마다 같이 찍히는 글(「캐릭터 공략」 같은 버튼 글)은 이름이 아니다 — 화면 셋 이상에서 절반 넘게 나오면 뺀다
        cnt = {}
        for _, _, ls in raw:
            for n_ in {norm(t) for t in ls}:
                cnt[n_] = cnt.get(n_, 0) + 1
        static = {n_ for n_, c_ in cnt.items() if len(raw) >= 3 and c_ > 0.5 * len(raw)}
        for a, b, ls in raw:
            # 길 이름(「Elation」 등)이 개척자 별칭 「Trailblazer (Elation)」과 맞아 점수가 오르지 않게, 길 이름 줄은 빼고 본다
            names_only = [t for t in ls if norm(t) not in PATH_WORDS and norm(t) not in static and norm(t)]
            sc = sorted(((max((best(t, c['char'])[0] for t in names_only), default=0), k2) for k2, c in enumerate(chars)), reverse=True)
            if tb and sc and sc[0][0] < 0.7 and names_only:
                sc = [(0.7, tb[0])] + [z for z in sc if z[1] != tb[0]]     # 어느 이름과도 안 맞는 이름 줄 = 플레이어 이름 = 개척자
            dets.append({'vid': vi, 't0': a, 't1': b, 'text': ' '.join(ls), 'who': sc})
    # 디테일 화면 뒤에 처음 나오는 광추 한 장 · 성혼 한 장만 그 캐릭터 것으로 본다. 같은 탭이 디테일 없이 또 나오면
    # 그 사이 캐릭터 줄로 넘긴 것이라 이어받지 않는다(종말 열람 화면 등에서 광추 · 성혼을 먼저 넘겨 보고 디테일을 나중에 보는 경우)
    for fr in frames:
        prev = [x for x in dets if x['vid'] == fr['vid'] and x['t0'] < fr['t']]
        dt = prev[-1] if prev else None
        if dt is not None:
            between = [g for g in frames if g is not fr and g['vid'] == fr['vid'] and g['tab'] == fr['tab'] and dt['t0'] < g['t'] < fr['t']]
            if between:
                dt = None
        fr['details'] = dt

    # 누구 화면인지 정하기
    # 광추: 머리글 이름이 뚜렷하면 그것, 아니면 광추 제목(그 광추를 낸 캐릭터가 하나뿐일 때), 그래도 아니면
    #       개척자(이름이 플레이어 이름) 또는 남은 하나(소거)
    # 성혼: 머리글 이름이 뚜렷하면 그것, 아니면 머리글 글자가 같은 광추 화면, 아니면 바로 앞 광추 화면의 캐릭터
    tb = [k for k, c in enumerate(chars) if c['char'].startswith('Trailblazer')]
    lcf = sorted([f for f in frames if f['tab'] == 'LightCone'], key=lambda f: (f['vid'], f['t']))
    used = set()
    for fr in lcf:
        s0, k0 = fr['who'][0]
        s1 = fr['who'][1][0] if len(fr['who']) > 1 else 0.0
        ls = fr['lc_scores']
        dt = fr.get('details')
        if s0 >= 0.7 or (s0 >= 0.6 and s0 - s1 >= 0.3):
            fr['char_k'], fr['how'] = k0, f'name {s0:.2f}'
        elif ls and ls[0][0] >= 0.9 and (len(ls) < 2 or ls[1][0] < ls[0][0] - 0.25):
            # 광추 제목이 한 캐릭터의 제출 광추와만 뚜렷이 맞으면 디테일 화면보다 앞선다
            # (광추 탭에 머문 채 캐릭터 줄로 넘기면 「디테일 뒤 첫 광추」가 다음 캐릭터 것이 된다)
            fr['char_k'], fr['how'] = ls[0][1], f'lc title {ls[0][0]:.2f}'
        elif dt and dt['who'] and dt['who'][0][0] >= 0.7 and (len(dt['who']) < 2 or dt['who'][1][0] < dt['who'][0][0] - 0.2):
            fr['char_k'], fr['how'] = dt['who'][0][1], f"details name {dt['who'][0][0]:.2f} at {dt['t0']}"
        elif ls and ls[0][0] >= 0.8 and (len(ls) < 2 or ls[1][0] < ls[0][0] - 0.1):
            # 다른 캐릭터 광추와 덜 갈린다(차 0.1~0.25) — 「lc title close」로 적어 확실한 경우와 구별(감점)
            fr['char_k'], fr['how'] = ls[0][1], f'lc title close {ls[0][0]:.2f}'
        else:
            fr['char_k'], fr['how'] = None, 'unknown'
        if fr['char_k'] is not None:
            used.add(fr['char_k'])
    rest = [k for k in range(len(chars)) if k not in used]
    # 광추 제목이 어떤 제출 광추와도 안 맞는 프레임(광추 화면이 아니거나 패널이 덜 뜬 것)은 누구 것으로도 정하지 않는다
    unk = [f for f in lcf if f['char_k'] is None and f['lc_scores'] and f['lc_scores'][0][0] >= 0.5]
    unk.sort(key=lambda f: -sum(1 for sc, k in f['lc_scores'] if sc >= 0.8 and k in rest))
    for fr in unk:
        # 광추 제목이 남은 캐릭터 중 하나와만 맞으면 그 캐릭터
        cand = [k for sc, k in fr['lc_scores'] if sc >= 0.8 and k in rest]
        if len(cand) == 1:
            fr['char_k'], fr['how'] = cand[0], 'lc title among remaining'
        elif tb and tb[0] in rest and len([f for f in unk if f['char_k'] is None]) >= 1 and (len(rest) == 1 or fr['who'][0][0] < 0.35):
            fr['char_k'], fr['how'] = tb[0], 'player-named (Trailblazer)'
        elif len(rest) == 1:
            fr['char_k'], fr['how'] = rest[0], 'only one left'
        if fr['char_k'] is not None and fr['char_k'] in rest:
            rest.remove(fr['char_k'])
    for fr in sorted([f for f in frames if f['tab'] == 'Eidolon'], key=lambda f: (f['vid'], f['t'])):
        s0, k0 = fr['who'][0]
        s1 = fr['who'][1][0] if len(fr['who']) > 1 else 0.0
        if s0 >= 0.7 or (s0 >= 0.6 and s0 - s1 >= 0.3):
            fr['char_k'], fr['how'] = k0, f'name {s0:.2f}'
            continue
        ew = fr.get('ei_who') or []
        # 둘째 캐릭터가 한두 줄 걸리는 일이 있다(설명문 낱말) → 첫째의 1/3 이하면 첫째로
        if ew and ew[0][0] >= 2 and (len(ew) < 2 or ew[1][0] <= ew[0][0] // 3):
            fr['char_k'], fr['how'] = ew[0][1], f'eidolon names {min(ew[0][0], 6)}/6'
            continue
        dt = fr.get('details')
        if dt and dt['who'] and dt['who'][0][0] >= 0.7 and (len(dt['who']) < 2 or dt['who'][1][0] < dt['who'][0][0] - 0.2):
            fr['char_k'], fr['how'] = dt['who'][0][1], f"details name {dt['who'][0][0]:.2f} at {dt['t0']}"
            continue
        same = [l for l in lcf if l['vid'] == fr['vid'] and l['char_k'] is not None and sim(l['header'], fr['header']) >= 0.75]
        # 워터마크가 이름을 덮어 모든 머리글이 비슷하게 읽히면(다른 캐릭터 머리글과도 비슷하면) 머리글로 잇지 않는다
        if same and len({l['char_k'] for l in lcf if l['vid'] == fr['vid'] and l['char_k'] is not None and sim(l['header'], fr['header']) >= 0.6}) > 1:
            same = []
        prev = [l for l in lcf if l['vid'] == fr['vid'] and l['t'] < fr['t'] and l['char_k'] is not None]
        if same:
            l = min(same, key=lambda l: abs(l['t'] - fr['t']))
            fr['char_k'], fr['how'] = l['char_k'], f"same header as LC {l['t']}"
        elif prev:
            fr['char_k'], fr['how'] = prev[-1]['char_k'], f"after LC {prev[-1]['t']}"
        else:
            fr['char_k'], fr['how'] = None, 'unknown'
    # 성혼 화면 둘이 같은 캐릭터로 붙었는데 자물쇠 결과가 다르면 다른 캐릭터다 — 뒤의 것을 아직 성혼이 없는 캐릭터에게
    # (남은 캐릭터가 하나이거나, 남은 것 중 개척자가 있으면 개척자)
    eis = sorted([f for f in frames if f['tab'] == 'Eidolon' and f.get('char_k') is not None], key=lambda f: (f['vid'], f['t']))
    for i, f2 in enumerate(eis):
        firsts = [f1 for f1 in eis[:i] if f1['char_k'] == f2['char_k']]
        if not firsts or f2['locks'] is None or firsts[0]['locks'] is None or f2['locks'] == firsts[0]['locks']:
            continue
        have = {f['char_k'] for f in eis if f is not f2}
        rest = [k for k in range(len(chars)) if k not in have]
        pick = rest[0] if len(rest) == 1 else (tb[0] if tb and tb[0] in rest else None)
        if pick is not None:
            f2['char_k'], f2['how'] = pick, f2['how'] + ' -> different locks from earlier frame, given to ' + ('the only one left' if len(rest) == 1 else 'Trailblazer')
    # 정한 근거와 따로 맞는 다른 근거가 있으면 적어 둔다(머리글 · 광추 제목 · 성혼 이름). 둘이 맞으면 확실하다
    for fr in frames:
        k = fr.get('char_k')
        if k is None:
            continue
        how = fr.get('how') or ''
        also = []
        if not how.startswith('name') and fr['who'] and fr['who'][0][1] == k and fr['who'][0][0] >= 0.5 and \
                (len(fr['who']) < 2 or fr['who'][1][0] <= fr['who'][0][0] - 0.3):
            also.append('name')
        ls = fr.get('lc_scores') or []
        if fr['tab'] == 'LightCone' and not how.startswith('lc title') and ls and ls[0][1] == k and ls[0][0] >= 0.9 and \
                (len(ls) < 2 or ls[1][0] < ls[0][0] - 0.25):
            also.append('lc title')
        ew = fr.get('ei_who') or []
        if fr['tab'] == 'Eidolon' and not how.startswith('eidolon names') and ew and ew[0][1] == k and ew[0][0] >= 2 and \
                (len(ew) < 2 or ew[1][0] <= ew[0][0] // 3):
            also.append('eidolon names')
        if also:
            fr['how'] = how + ' + ' + ' + '.join(also)
    # 캐릭터별 결과
    out = []
    for k, c in enumerate(chars):
        lcf = [f for f in frames if f['tab'] == 'LightCone' and f.get('char_k') == k]
        eif = [f for f in frames if f['tab'] == 'Eidolon' and f.get('char_k') == k]
        r = {'char': c['char'], 'submitted': {'lc': c['lc'], 's': c['s'], 'e': c['e']}}
        if lcf:
            f0 = max(lcf, key=lambda f: f['lc_scores'][0][0] if f['lc_scores'] else 0)
            lcs_k = dict((kk, s) for s, kk in f0['lc_scores'])
            r['lc_seen'] = f0['panel_title']
            r['lc_match'] = round(lcs_k.get(k, 0), 2)
            r['s_seen'] = f0['superimp']
            r['lc_t'] = f0['t']
            r['lc_how'] = f0['how']
        if eif:
            f0 = max(eif, key=lambda f: f.get('lock_frames') or 0)
            act = 1 if f0['activatable'] else 0
            sc = f0.get('lock_scores')
            fit = eidolon_fit(sc) if sc and len(sc) == 6 else None
            if fit:
                f0['locks'] = 6 - fit[0]
            r['locks'] = f0['locks']
            r['activatable'] = bool(f0['activatable'])
            r['e_seen'] = None if f0['locks'] is None else max(0, 6 - f0['locks'] - act)
            names_read = max((h for h, kk in (f0.get('ei_who') or []) if kk == k), default=0)
            # 성혼 이름이 다섯 줄 넘게 읽혔으면 화면이 다 그려진 것이다(여는 연출 중이면 이름도 자물쇠도 아직 없다)
            # 노드 원 여섯이 배치대로 잡힌 프레임이면 자물쇠 그림도 노드와 함께 그려져 있다. 성혼 탭이 켜진 프레임만 쓰므로
            # (행적 화면 섞임 없음) 두 장이면 믿는다
            if f0['locks'] == 0 and (f0.get('lock_frames') or 0) < 2 and names_read < 5:
                r['e_seen'] = None        # 자물쇠 0개를 흐린 프레임 한두 장으로 단정하지 않는다(연출 중이면 자물쇠가 안 보인다)
            # 애매한 범위: 가장 잘 맞는 k 와 다음 k 가 거의 같으면 둘 사이 어느 쪽일 수도 있다
            r['e_alt'] = None
            if fit and r['e_seen'] is not None and fit[2] < FIT_SURE:
                r['e_alt'] = max(0, fit[1] - act)
            r['e_gray'] = (r['e_seen'] - r['e_alt']) if r['e_alt'] is not None and r['e_alt'] < r['e_seen'] else 0
            r['e_frames'] = f0.get('lock_frames')
            r['lock_scores'] = f0.get('lock_scores')
            r['e_t'] = f0['t']
            r['e_how'] = f0['how']
        probs = []
        if not lcf:
            probs.append('Light Cone not shown')
        else:
            if r['lc_match'] < 0.7:
                probs.append(f"Light Cone name? (seen '{r['lc_seen']}')")
            if not c['lc']:
                pass          # 광추를 안 낀 제출: 중첩은 뜻이 없다
            elif r['s_seen'] is None:
                probs.append('Superimposition unreadable')
            elif r['s_seen'] != c['s']:
                probs.append(f"Superimposition {c['s']} submitted, {r['s_seen']} seen")
        if not eif:
            probs.append('Eidolons not shown')
        elif r['e_seen'] is None:
            probs.append('Eidolons unreadable')
        elif r['e_seen'] != c['e'] and c['e'] != r.get('e_alt'):
            probs.append(f"Eidolon E{c['e']} submitted, E{r['e_seen']} seen (locks {r['locks']}{', activatable' if r['activatable'] else ''})")
        r['problems'] = probs
        out.append(r)
    res = {'rev': rev, 'ocr_model': model, 'chars': out, 'details': [{k: v for k, v in x.items()} for x in dets],
           'frames': [{k: v for k, v in f.items() if k not in ('path', 'lay', 'details')} for f in frames]}
    json.dump(res, open(os.path.join(d, 'judge.json'), 'w', encoding='utf8'), ensure_ascii=False, indent=1, default=str)
    return res


if __name__ == '__main__':
    r = judge(sys.argv[1])
    print(r['rev'], 'model', r['ocr_model'])
    for c in r['chars']:
        print(f"  {c['char']:28s} LC {c.get('lc_match')} S{c.get('s_seen')} E{c.get('e_seen')} "
              f"({c.get('lc_how')}; {c.get('e_how')})  {'; '.join(c['problems']) or 'OK'}")
