"""화면 그림으로 광추 · 캐릭터를 알아보는 도구(글 읽기에 기대지 않는다: 워터마크 · 자막 · 언어 · 흔들림에 강하다).

광추 카드: 게임 자료의 광추 그림(LightConeMaxFigures, 카드 안 그림)과 화면의 카드를 SIFT 특징점으로 맞추고 호모그래피(RANSAC)로 걸러
  맞은 점 수(인라이어)를 센다. 진짜 광추는 150~230, 다른 광추는 10 안쪽이라 차이가 압도적이다(rev_3oxwzm 네 장 시험).
  카드는 기울어져 보이고(원근) 자막 · 워터마크가 가려도 점 몇 개가 가릴 뿐이다.

그림 자료: data/img/<종류>/<아이디>.webp (me-miisi 의 public/img 에서 복사, 원본은 HF 데이터셋 fffffffff1/imageassets · assets 의 spriteoutput)
  lightconemaxfigures  광추 카드 그림(세로 720)
  avatarroundicon      캐릭터 둥근 얼굴 아이콘
python imgrec.py <프레임.jpg> [...]   광추 화면 프레임이면 광추 순위를 찍는다"""
import os, sys, glob, json
import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(HERE, '..', 'data', 'img')
_sift = None
_lc = None


def sift():
    global _sift
    if _sift is None:
        _sift = cv2.SIFT_create(nfeatures=1500)
    return _sift


def lc_library():
    """{광추 아이디: (특징점, 설명자)}"""
    global _lc
    if _lc is None:
        _lc = {}
        for p in glob.glob(os.path.join(IMG, 'lightconemaxfigures', '2*.webp')):
            i = int(os.path.basename(p).split('.')[0])
            im = cv2.imread(p)
            if im is None:
                continue
            s = 360 / im.shape[0]
            im = cv2.resize(im, None, fx=s, fy=s)
            kp, d = sift().detectAndCompute(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), None)
            if d is not None:
                _lc[i] = (kp, d)
    return _lc


def _viewport(f):
    import judge
    return judge.viewport(f)


def card_region(f):
    """광추 화면에서 카드가 있는 곳(게임 화면 가운데). 메뉴 · 패널과 겹쳐도 점 몇 개일 뿐이다."""
    H, W = f.shape[:2]
    l, r = _viewport(f)
    w = r - l
    return f[int(0.12 * H):int(0.88 * H), int(l + 0.25 * w):int(l + 0.72 * w)]


def _inliers(fk, fd, i, bf):
    kp, d = lib[i]
    m = bf.knnMatch(d, fd, k=2)
    good = [a for a, b in (x for x in m if len(x) == 2) if a.distance < 0.75 * b.distance]
    if len(good) < 6:
        return len(good) // 2
    src = np.float32([kp[g.queryIdx].pt for g in good])
    dst = np.float32([fk[g.trainIdx].pt for g in good])
    _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
    return int(mask.sum()) if mask is not None else 0


def identify_lc(frame, only=None):
    """광추 화면 프레임 → [(맞은 점 수, 광추 아이디)] 많은 순. only 가 있으면 그 아이디들만."""
    global lib
    lib = lc_library()
    c = card_region(frame)
    if c.shape[0] < 540:                     # 작은 영상은 키워 점을 더 얻는다(라이브러리는 높이 360 기준)
        s = 540 / c.shape[0]
        c = cv2.resize(c, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    fk, fd = sift().detectAndCompute(cv2.cvtColor(c, cv2.COLOR_BGR2GRAY), None)
    if fd is None or len(fd) < 8:
        return []
    bf = cv2.BFMatcher()
    ids = [i for i in lib if only is None or i in only]
    return sorted(((_inliers(fk, fd, i, bf), i) for i in ids), reverse=True)




_ids = None


def lc_ids():
    """({영어 이름: 광추 아이디}, {광추 아이디: 영어 이름}) — ExcelOutput 의 EquipmentConfig + TextMap"""
    global _ids
    if _ids is None:
        import reasons, names
        en = names._load('EN')
        a, b = {}, {}
        for r in reasons._excel('EquipmentConfig.json'):
            e = names.clean(en.get(str((r.get('EquipmentName') or {}).get('Hash')), ''))
            if e:
                a.setdefault(e, r['EquipmentID'])
                b[r['EquipmentID']] = e
        _ids = (a, b)
    return _ids


CONFIDENT_MIN = 25          # 이 점 수 이상이면서
CONFIDENT_RATIO = 2.5       # 둘째의 이 배 이상이면 그림으로 광추를 확정한다(평가: 맞은 656장은 모두 1등)


def confident_lc(ranked):
    """identify_lc 결과에서 그림으로 확정할 수 있으면 (아이디, 점 수, 둘째 점 수), 아니면 None"""
    if not ranked:
        return None
    top = ranked[0]
    second = ranked[1][0] if len(ranked) > 1 else 0
    if top[0] >= CONFIDENT_MIN and top[0] >= CONFIDENT_RATIO * max(second, 4):
        return top[1], top[0], second
    return None


# ---------- 캐릭터 얼굴(위쪽 줄 · 왼쪽 세로 줄) ----------
_av = None
_skin_av = None
D0 = 44                      # 720p 에서 보통 얼굴 지름(고른 얼굴은 더 크다)


SKIN_KEY = 10_000_000       # 스킨 얼굴은 키 = SKIN_KEY + 스킨 아이디. 캐릭터 아이디는 avatar_of(키)


def avatar_of(key):
    """얼굴 라이브러리 키 → 캐릭터 아이디(스킨이면 AvatarSkin.json 의 AvatarID)"""
    if key < SKIN_KEY:
        return key
    global _skin_av
    if _skin_av is None:
        import reasons
        _skin_av = {r['ID']: r['AvatarID'] for r in reasons._excel('AvatarSkin.json')}
    return _skin_av.get(key - SKIN_KEY, key)


def avatar_library():
    """{키: 둥근 얼굴 그림(정사각)} 기본 얼굴은 캐릭터 아이디, 스킨 얼굴(data/avatarroundicon_skin)은 SKIN_KEY + 스킨 아이디.
    목록에 스킨은 스킨 얼굴로 나온다(Castorice · Evanescia 가 맞지 않던 까닭). 둥근 얼굴 그림이 없는 스킨은 `<아이디>_icon.png`(머리 아이콘)로 대신한다."""
    global _av
    if _av is None:
        _av = {}
        paths = glob.glob(os.path.join(IMG, 'avatarroundicon', '*.webp')) + glob.glob(os.path.join(HERE, '..', 'data', 'avatarroundicon', '*.webp'))
        paths += glob.glob(os.path.join(HERE, '..', 'data', 'avatarroundicon_skin', '*.png'))
        for p in paths:
            n = os.path.basename(p).split('.')[0]
            skin = os.path.basename(os.path.dirname(p)) == 'avatarroundicon_skin'
            n = n.replace('_icon', '')
            if not n.isdigit():
                continue
            key = int(n) + (SKIN_KEY if skin else 0)
            if key in _av:
                continue
            im = cv2.imread(p, cv2.IMREAD_UNCHANGED)
            if im is None:
                continue
            if im.shape[2] == 4:
                im = (im[..., :3] * (im[..., 3:4] / 255.0)).astype(np.uint8)
            h, w = im.shape[:2]
            s = min(h, w)
            _av[key] = im[(h - s) // 2:(h + s) // 2, (w - s) // 2:(w + s) // 2]
    return _av


def _mask(d):
    yy, xx = np.mgrid[0:d, 0:d]
    return (((yy - d / 2) ** 2 + (xx - d / 2) ** 2) <= (0.40 * d) ** 2).astype(np.uint8)


def _tm(strip, im, d, gray, half):
    t = cv2.resize(im, (d, d), interpolation=cv2.INTER_AREA)
    m = _mask(d)
    if gray:
        t = cv2.cvtColor(t, cv2.COLOR_BGR2GRAY)
    else:
        m = cv2.merge([m] * 3)
    if strip.shape[0] < d or strip.shape[1] < d:
        return 0.0, (0, 0)
    r = cv2.matchTemplate(strip, t, cv2.TM_CCOEFF_NORMED, mask=m)
    r = np.where((r >= -1.0) & (r <= 1.0), np.nan_to_num(r), 0).astype(np.float32)
    _, mx, _, loc = cv2.minMaxLoc(r)
    return float(mx), loc


def faces(f, region, scale0=1.0):
    """region(x0, y0, x1, y1) 안에서 보이는 둥근 얼굴들을 찾는다. → [{id, score, x, y, d}] (고른 얼굴은 d 가 더 크다)
    1) 반 해상도 회색으로 모든 얼굴 아이콘을 보통 크기에서 맞춰 자리를 찾고(자리마다 가장 맞는 아이콘)
    2) 찾은 자리마다 컬러로 여러 크기를 시험해 가장 맞는 크기를 낸다."""
    x0, y0, x1, y1 = region
    H = f.shape[0]
    k = H / 720.0
    d0 = max(16, int(round(D0 * k)))
    strip = f[y0:y1, x0:x1]
    small = cv2.cvtColor(cv2.resize(strip, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    lib = avatar_library()
    d_half = max(8, d0 // 2)
    cand = []
    # 자리를 찾는 것은 아이콘 하나하나의 최고점이 아니라 「자리마다 가장 맞는 아이콘」: 아이콘별 결과 지도를 모아 자리별로 고른다
    best_map = None
    for i, im in lib.items():
        t = cv2.cvtColor(cv2.resize(im, (d_half, d_half), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        if small.shape[0] < d_half or small.shape[1] < d_half:
            continue
        r = cv2.matchTemplate(small, t, cv2.TM_CCOEFF_NORMED, mask=_mask(d_half))
        r = np.where((r >= -1.0) & (r <= 1.0), np.nan_to_num(r), 0).astype(np.float32)     # 평평한 곳에서 터지는 값(수백억)을 버린다
        if best_map is None:
            best_map = r.copy()
            best_id = np.full(r.shape, i, np.int32)
        else:
            up = r > best_map
            best_map[up] = r[up]
            best_id[up] = i
    if best_map is None:
        return []
    out = []
    bm = best_map.copy()
    for _ in range(14):
        _, mx, _, loc = cv2.minMaxLoc(bm)
        if mx < 0.55:
            break
        cx, cy = loc
        out.append((mx, int(best_id[cy, cx]), cx * 2 + x0, cy * 2 + y0))
        bm[max(0, cy - d_half // 2 - 2):cy + d_half // 2 + 3, max(0, cx - d_half // 2 - 2):cx + d_half // 2 + 3] = -1
    res = []
    for mx, i, x, y in out:
        # 크기 시험(컬러): 이 자리 둘레에서 지름을 키워 가며
        bestd = (-1, d0, x, y, i)
        for dd in (int(d0 * r_) for r_ in (0.9, 1.0, 1.12, 1.25, 1.4)):
            pad = int(0.12 * dd)
            ax0, ay0 = max(0, x - pad - x0), max(0, y - pad - y0)
            win = f[y0 + ay0:y0 + ay0 + dd + 2 * pad + 4, x0 + ax0:x0 + ax0 + dd + 2 * pad + 4]
            sc, loc = _tm(win, lib[i], dd, False, False)
            if sc > bestd[0]:
                bestd = (sc, dd, x0 + ax0 + loc[0], y0 + ay0 + loc[1], i)
        res.append({'id': avatar_of(bestd[4]), 'score': round(bestd[0], 3), 'x': bestd[2], 'y': bestd[3], 'd': bestd[1], 'coarse': round(mx, 3)})
    return res


def locate(f, ids):
    """주어진 캐릭터들(제출한 편성)의 얼굴이 얼굴 줄(위쪽 가로 · 왼쪽 세로)의 어디에 어떤 크기로 보이는지 찾는다.
    보통 얼굴 지름은 화면 높이의 약 0.061, 고른 얼굴은 약 0.076 이다(세 배치 모두 같은 비율).
    → {캐릭터 아이디: {score, x, y, d}} (점수 0.7 미만은 못 찾은 것)"""
    H, W = f.shape[:2]
    lib = avatar_library()
    regions = [(int(0.12 * W), 0, int(0.92 * W), int(0.17 * H)), (0, int(0.08 * H), int(0.2 * W), int(0.98 * H))]
    out = {}
    for i in ids:
        if i not in lib:
            continue
        best = None
        for (x0, y0, x1, y1) in regions:
            strip = f[y0:y1, x0:x1]
            for dd in range(int(0.042 * H), int(0.092 * H) + 1, 2):
                sc, loc = _tm(strip, lib[i], dd, False, False)
                if best is None or sc > best['score']:
                    best = {'score': round(sc, 3), 'x': x0 + loc[0], 'y': y0 + loc[1], 'd': dd, 'h': H}
        if best and best['score'] >= 0.7:
            out[i] = best
    return out


def selected_among(f, ids):
    """제출한 캐릭터들 가운데 지금 고른(큰) 얼굴. → (아이디 또는 None, locate 결과). 크기 0.069*H 이상이면서 점수가 가장 높은 것."""
    loc = locate(f, ids)
    H = f.shape[0]
    big = {i: v for i, v in loc.items() if v['d'] >= 0.069 * H}
    if not big:
        return None, loc
    return max(big, key=lambda i: big[i]['score']), loc


# ---------- 선택된 초상화 ----------
# 게임 UI 프리팹(ui/avatar/widget/avatarheadiconsmall · avatartoplistpanel): 고른 얼굴에만 선택 링 「HeadLine」(흰 가는 원,
# 82.667 칸에 얼굴 56 → 링 지름은 얼굴의 1.476배, 얼굴 중심에서 오른쪽으로 3칸)이 켜진다. 얼굴 크기는 그대로다.
# 링 그림(data/ui/HeadLine.png, HF fffffffff1/assets ui/atlas/atlasroot/common/outline/HeadLine.png)을 가는 밝은 선만 남긴 화면에
# 크기를 바꿔 맞춰 링 자리를 찾고, 링 속 얼굴을 제출한 캐릭터들(또는 모든 캐릭터) 얼굴 그림과 대 본다.
RING_MIN = 0.40            # 링 상관이 이 이상이어야 링으로 본다(잰 값: 링 있음 0.43~0.70, 없음 0.26 이하). 약한 상관(0.3 대)은 가려진 화면의 가짜였다
RING_WEAK = 0.30           # 자막 · 워터마크가 링 일부를 가린 프레임: 링은 이만큼이라도, 대신 얼굴이 더 또렷해야 한다(confident 참고)
SEL_TOP_MIN, SEL_MARGIN_MIN = 0.60, 0.20   # 링 속 얼굴을 확정하는 문턱(상관, 둘째와의 차)
_hl = None


def _headline():
    global _hl
    if _hl is None:
        _hl = cv2.imread(os.path.join(IMG, '..', 'ui', 'HeadLine.png'), cv2.IMREAD_UNCHANGED)[..., 3]
    return _hl


def find_ring(f, regions=None, min_score=None):
    """고른 얼굴의 링. → (상관, 지름, 중심 x, 중심 y) 또는 None. 영역은 기본 위쪽 가로 줄과 왼쪽 세로 줄."""
    H, W = f.shape[:2]
    if regions is None:
        regions = [(int(0.12 * W), 0, int(0.92 * W), int(0.17 * H)), (0, int(0.08 * H), int(0.2 * W), int(0.98 * H))]
    He = max(H, W * 9 / 16)       # 화면이 16:9 보다 넓으면(위아래가 잘린 녹화) UI 크기는 가로 기준: 1280x576 에서도 링은 66px
    g = f.min(axis=2)
    th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))).astype(np.float32)
    hl = _headline()
    best = None
    for (x0, y0, x1, y1) in regions:
        sub = th[y0:y1, x0:x1]
        for D in range(int(0.075 * He), int(0.112 * He) + 1, 2):
            if sub.shape[0] < D or sub.shape[1] < D:
                continue
            r = cv2.matchTemplate(sub, cv2.resize(hl, (D, D), interpolation=cv2.INTER_AREA).astype(np.float32), cv2.TM_CCOEFF_NORMED)
            r = np.where((r >= -1) & (r <= 1), np.nan_to_num(r), 0)
            _, mx, _, loc = cv2.minMaxLoc(r)
            if best is None or mx > best[0]:
                best = (float(mx), D, x0 + loc[0] + D / 2, y0 + loc[1] + D / 2)
    return best if best and best[0] >= (RING_MIN if min_score is None else min_score) else None


def identify_face_at(f, cx, cy, D, ids=None, dfs=(0.6, 0.65, 0.7, 0.75), padf=0.12, mask_r=0.30):
    """링 중심 (cx, cy) · 링 지름 D 안의 둥근 얼굴이 누구인지. → [(상관, 캐릭터 아이디)] 높은 순.
    얼굴 지름은 링의 0.6~0.75배(화면 비율마다 조금 다르다)에서 시험하고, 얼굴 가운데 원(0.3d)만 본다 — 가장자리에는
    금빛 초승달 · 팀 번호 배지가 겹친다. 마스크를 0.4d 로 잡으면 Evanescia · Castorice 가 0.5 로 떨어진다(0.3d 면 0.84~0.87)."""
    lib = avatar_library()
    best = {}
    for df in dfs:
        d = int(round(D * df))
        pad = int(padf * d)
        yy, xx = np.mgrid[0:d, 0:d]
        m = cv2.merge([(((yy - d / 2) ** 2 + (xx - d / 2) ** 2) <= (mask_r * d) ** 2).astype(np.uint8)] * 3)
        x0, y0 = int(cx - d / 2 - pad), int(cy - d / 2 - pad)
        win = f[max(0, y0):y0 + d + 2 * pad, max(0, x0):x0 + d + 2 * pad]
        if win.shape[0] < d or win.shape[1] < d:
            continue
        for i, im in lib.items():
            a = avatar_of(i)
            if ids is not None and a not in ids:
                continue
            r = cv2.matchTemplate(win, cv2.resize(im, (d, d), interpolation=cv2.INTER_AREA), cv2.TM_CCOEFF_NORMED, mask=m)
            r = np.where((r >= -1) & (r <= 1), np.nan_to_num(r), 0)
            v = round(float(r.max()), 3)
            if v > best.get(a, -1):
                best[a] = v
    return sorted(((v, a) for a, v in best.items()), reverse=True)


def selected_portrait(f, ids=None):
    """지금 고른 얼굴. → {'ring': 링 상관, 'x','y','d': 링 자리, 'ranked': [(상관, 아이디)...]} 또는 None(링이 안 보임).
    ids 가 있으면 그 캐릭터들 가운데서만 고른다(제출한 편성). dict {캐릭터 아이디: 묶음} 이면 묶음 단위로 합쳐 낸다. 얼굴 지름은 링의 56/82.667 * (124/110) 배 — 720p 에서 약 44."""
    ring = find_ring(f, min_score=RING_WEAK)
    if ring is None:
        return None
    sc, D, rx, ry = ring
    ranked = identify_face_at(f, rx, ry, D, ids)
    if isinstance(ids, dict):
        # 같은 캐릭터의 여러 아이디(개척자 여덟 · 3월 7일 둘)는 한 묶음으로 — 둘째와의 차가 같은 캐릭터 끼리가 되지 않게
        g = {}
        for v, a in ranked:
            g[ids[a]] = max(g.get(ids[a], -1), v)
        ranked = sorted(((v, k) for k, v in g.items()), reverse=True)
    return {'ring': round(sc, 3), 'x': rx, 'y': ry, 'd': D, 'ranked': ranked}


# ---------- 헤더의 운명의 길 아이콘 ----------
# 모든 탭의 머리글(왼쪽 위) 「길 이름 / 캐릭터 이름」 앞에 길 아이콘(ProfessionIconSmall, 720p 에서 약 14px)이 붙는다. 글자가 워터마크에
# 덮여도 아이콘은 읽히고, 머리글 이름과 같이 바뀌므로 어긋나면 이름을 잘못 읽은 것이다(캐릭터를 넘긴 직후의 늦음이 없다).
PATH_EN = {'Warrior': 'Destruction', 'Knight': 'Preservation', 'Rogue': 'The Hunt', 'Mage': 'Erudition', 'Shaman': 'Harmony',
           'Warlock': 'Nihility', 'Pirest': 'Abundance', 'Memory': 'Remembrance', 'Joy': 'Elation'}
PATH_OF_BASETYPE = {'Warrior': 'Warrior', 'Knight': 'Knight', 'Rogue': 'Rogue', 'Mage': 'Mage', 'Shaman': 'Shaman', 'Warlock': 'Warlock',
                    'Priest': 'Pirest', 'Memory': 'Memory', 'Elation': 'Joy'}          # AvatarBaseType.ID → 파일 이름 조각
PATH_MIN, PATH_MARGIN = 0.58, 0.08
_pathlib = None


def path_library():
    """{길(파일 조각): 회색 그림(알파 곱함)}"""
    global _pathlib
    if _pathlib is None:
        _pathlib = {}
        for p in glob.glob(os.path.join(IMG, '..', 'ui', 'path', '*_small.png')):
            im = cv2.imread(p, cv2.IMREAD_UNCHANGED)
            _pathlib[os.path.basename(p).split('_')[0]] = cv2.cvtColor((im[..., :3] * (im[..., 3:4] / 255.0)).astype(np.uint8), cv2.COLOR_BGR2GRAY)
    return _pathlib


def read_path_icon(f, crop=None, unit=None):
    """머리글의 길 아이콘. → (길 조각, 상관, 둘째와의 차, (x, y, d)) 또는 None. 크기를 바꿔 가며 9종과 대 본다.
    crop 이 없으면 화면 왼쪽 위. judge 는 메뉴 줄 간격 unit(lay[2], 720p 에서 약 62)으로 잡은 머리글 영역을 넘긴다 — 위아래가
    잘렸거나 테두리 안에 든 영상에서도 맞는다. 아이콘 지름은 unit 의 0.22배 안팎."""
    H, W = f.shape[:2]
    He = max(H, W * 9 / 16)
    g = cv2.cvtColor(crop if crop is not None else f[:int(0.13 * H), :int(0.32 * W)], cv2.COLOR_BGR2GRAY)
    u = unit if unit else 62.0 * He / 720
    dmin, dmax = int(0.17 * u), int(0.29 * u)
    scores = {}
    where = {}
    for name, t in path_library().items():
        for d in range(dmin, dmax + 1):
            if d < 8 or g.shape[0] < d or g.shape[1] < d:
                continue
            r = cv2.matchTemplate(g, cv2.resize(t, (d, d), interpolation=cv2.INTER_AREA), cv2.TM_CCOEFF_NORMED)
            r = np.where((r >= -1) & (r <= 1), np.nan_to_num(r), 0)
            _, mx, _, loc = cv2.minMaxLoc(r)
            if mx > scores.get(name, -1):
                scores[name], where[name] = float(mx), (loc[0], loc[1], d)
    if not scores:
        return None
    rk = sorted(scores.items(), key=lambda kv: -kv[1])
    top = rk[0]
    # 아이콘 자리는 하나다 — 둘째는 같은 자리에서 다른 길로 읽힌 점수만
    pos = where[top[0]]
    same = [v for n, v in rk[1:] if abs(where[n][0] - pos[0]) <= 3 and abs(where[n][1] - pos[1]) <= 3]
    sec = max(same) if same else (rk[1][1] if len(rk) > 1 else 0)
    return top[0], round(top[1], 3), round(top[1] - sec, 3), pos


def _path_in_name(en_name):
    """이름 끝 괄호가 길 이름이면 그 길(파일 조각). 「Trailblazer (Elation)」 · 「March 7th (Hunt)」"""
    import re
    m = re.search(r'\(([^()]*)\)$', en_name)
    if not m:
        return None
    word = m.group(1).strip()
    word = {'Hunt': 'The Hunt'}.get(word, word)
    inv = {v: k for k, v in PATH_EN.items()}
    return inv.get(word)


def path_of_char(en_name):
    """제출 캐릭터의 길(파일 조각). 이름 끝 괄호가 길이면 그 길, 아니면 아이디들의 길(하나로 정해질 때만)."""
    p = _path_in_name(en_name)
    if p or en_name.startswith('Trailblazer'):
        return p
    import reasons
    rows = {r['AvatarID']: r for r in reasons._excel('AvatarConfig.json')}
    out = {PATH_OF_BASETYPE.get(rows[i].get('AvatarBaseType')) for i in char_ids(en_name) if i in rows}
    out.discard(None)
    return out.pop() if len(out) == 1 else None


# ---------- 상세 화면의 속성 아이콘 ----------
# 상세(Details) 탭 오른쪽 위, 캐릭터 이름 줄 끝에 속성 아이콘(IconNatureColor, 720p 에서 약 40px 정사각형)이 있다. 글과 무관한 근거.
ELEMENTS = ('Fire', 'Ice', 'Imaginary', 'Physical', 'Quantum', 'Thunder', 'Wind')
ELEM_MIN, ELEM_MARGIN = 0.75, 0.08
_elem = None


def element_library():
    """{속성: 회색 그림(알파 곱함)} — 색 · 마스크로 맞추면 어두운 불꽃(Fire)이 낮게 나오고 엉뚱한 자리가 붙었다. 회색이 낫다"""
    global _elem
    if _elem is None:
        _elem = {}
        for n in ELEMENTS:
            for kind in ('color', 'dtype'):          # 물리는 IconNatureColor 가 없어 IconDamageType 로
                p = os.path.join(IMG, '..', 'ui', 'element', f'{n}_{kind}.png')
                if os.path.exists(p):
                    im = cv2.imread(p, cv2.IMREAD_UNCHANGED)
                    _elem[n] = cv2.cvtColor((im[..., :3] * (im[..., 3:4] / 255.0)).astype(np.uint8), cv2.COLOR_BGR2GRAY)
                    break
    return _elem


def read_element_icon(f):
    """상세 화면 오른쪽 위의 속성 아이콘. → (속성, 상관, 둘째와의 차, (x, y, d)) 또는 None. 가장 잘 맞은 자리에서 다른 속성과 견준다."""
    H, W = f.shape[:2]
    He = max(H, W * 9 / 16)
    x0 = int(0.88 * W)        # 이름 줄 끝(오른쪽 12% 안)에만 있다 — 더 넓게 보면 다른 그림이 속성으로 읽힌다(rev_1gocivt 290초)
    g = cv2.cvtColor(f[:int(0.2 * H), x0:], cv2.COLOR_BGR2GRAY)
    hits = []
    for name, t in element_library().items():
        for d in range(int(0.045 * He), int(0.066 * He) + 1, 2):
            if g.shape[0] < d or g.shape[1] < d:
                continue
            r = cv2.matchTemplate(g, cv2.resize(t, (d, d), interpolation=cv2.INTER_AREA), cv2.TM_CCOEFF_NORMED)
            r = np.where((r >= -1) & (r <= 1), np.nan_to_num(r), 0)
            _, mx, _, loc = cv2.minMaxLoc(r)
            hits.append((float(mx), name, d, loc[0] + x0, loc[1], r))
    if not hits:
        return None
    best = max(hits, key=lambda h: h[0])
    # 같은 자리(±4px)에서 다른 속성이 얻은 최고 점수
    sec = 0.0
    for sc, name, d, x, y, r in hits:
        if name == best[1]:
            continue
        lx, ly = best[3] - x0, best[4]
        win = r[max(0, ly - 4):ly + 5, max(0, lx - 4):lx + 5]
        if win.size:
            sec = max(sec, float(win.max()))
    return best[1], round(best[0], 3), round(best[0] - sec, 3), (best[3], best[4], best[2])


def element_of_char(en_name):
    """제출 캐릭터의 속성(Fire …). 이름 끝 괄호가 길이면(개척자 · 3월 7일) 그 길의 아이디로 좁힌다."""
    import reasons
    rows = {r['AvatarID']: r for r in reasons._excel('AvatarConfig.json')}
    ids = char_ids(en_name)
    want = _path_in_name(en_name)
    if want:
        ids = [i for i in ids if PATH_OF_BASETYPE.get(rows.get(i, {}).get('AvatarBaseType')) == want]
    out = {rows[i].get('DamageType') for i in ids if i in rows}
    out.discard(None)
    return out.pop() if len(out) == 1 else None


# ---------- 성혼 노드 아이콘 ----------
# 켜진 성혼 노드는 그 캐릭터의 성혼 아이콘(AvatarRankConfig.IconPath)을 보여 주고, 잠긴 노드는 자물쇠 + 거의 안 보이는 아이콘(알파 0.157)이다
# (UI 프리팹 ui/avatar/rank/avatarrankpanel: Activated · UnActivated · Locked). 아이콘 상관이 켜진 노드 0.64~0.83, 잠긴 노드 0.31~0.51,
# 다른 캐릭터 아이콘은 0.59 이하 — 노드 상태와 누구인지를 한꺼번에 알려 준다.
_rank = None
_avid = None
ICON_ON = 0.60          # 이 이상이면 그 캐릭터의 켜진 노드 아이콘으로 본다


def rank_icons():
    """{(캐릭터 아이디, 성혼 번호 1~6): 그림(알파 포함)}"""
    global _rank
    if _rank is None:
        _rank = {}
        fp = os.path.join(HERE, '..', 'data', 'ExcelOutput', 'AvatarRankConfig.json')
        for r in json.load(open(fp, encoding='utf8')):
            cid, rk = r['RankID'] // 100, r['Rank']
            fn = os.path.basename(r.get('IconPath') or '').rsplit('.', 1)[0]
            p = os.path.join(IMG, 'skillicons', str(cid), fn + '.webp')
            if os.path.exists(p):
                im = cv2.imread(p, cv2.IMREAD_UNCHANGED)
                if im is not None:
                    _rank[(cid, rk)] = im
    return _rank


def avatar_ids():
    """{영어 이름: [캐릭터 아이디...]} 개척자는 여덟 아이디 모두(성별 · 운명의 길)"""
    global _avid
    if _avid is None:
        import reasons, names
        en = names._load('EN')
        _avid = {}
        for r in reasons._excel('AvatarConfig.json'):
            e = names.clean(en.get(str((r.get('AvatarName') or {}).get('Hash')), ''))
            if e:
                _avid.setdefault(e, []).append(r['AvatarID'])
        tb = sorted({i for v in _avid.values() for i in v if 8001 <= i <= 8020})
        for k in ('Trailblazer', 'Trailblazer (Elation)', 'Trailblazer (Remembrance)', 'Trailblazer (Harmony)',
                  'Trailblazer (Destruction)', 'Trailblazer (Preservation)'):
            _avid[k] = tb
    return _avid


def char_ids(en_name):
    import re
    a = avatar_ids()
    return a.get(en_name) or a.get(re.sub(r'\s*\([^()]*\)$', '', en_name)) or []


def _icon_score(g, cx, cy, sp, im):
    bgr, a = (im[..., :3], (im[..., 3] > 40).astype(np.uint8)) if im.shape[2] == 4 else (im, np.ones(im.shape[:2], np.uint8))
    if im.shape[2] == 4:
        al = im[..., 3:4] / 255.0
        bgr = (im[..., :3] * al).astype(np.uint8)
    best = 0.0
    for k in (0.50, 0.58, 0.66, 0.74):
        d = max(10, int(round(k * sp)))
        t = cv2.cvtColor(cv2.resize(bgr, (d, d), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        m = cv2.resize(a, (d, d), interpolation=cv2.INTER_NEAREST) * 255
        yy, xx = np.mgrid[0:d, 0:d]
        m = (m * (((yy - d / 2) ** 2 + (xx - d / 2) ** 2) <= (0.46 * d) ** 2)).astype(np.uint8)
        pad = int(0.25 * sp)
        x0, y0 = int(cx - d / 2 - pad), int(cy - d / 2 - pad)
        win = g[max(0, y0):y0 + d + 2 * pad, max(0, x0):x0 + d + 2 * pad]
        if win.shape[0] < d or win.shape[1] < d or m.sum() < 50:
            continue
        r = cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED, mask=m)
        r = np.where((r >= -1) & (r <= 1), np.nan_to_num(r), 0)
        best = max(best, float(r.max()))
    return best


def node_icon_scores(frame, pred, sp, cids):
    """성혼 화면의 노드 여섯 자리(pred)에서 이 캐릭터(아이디 여럿이면 가장 맞는 것)의 성혼 아이콘과의 상관. → [6개, 못 보면 None]"""
    lib = rank_icons()
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    out = []
    for n in range(6):
        best = None
        for c in cids:
            im = lib.get((c, n + 1))
            if im is None:
                continue
            v = _icon_score(g, pred[n][0], pred[n][1], sp, im)
            best = v if best is None or v > best else best
        out.append(None if best is None else round(best, 2))
    return out


if __name__ == '__main__':
    for p in sys.argv[1:]:
        f = cv2.imread(p)
        if '--faces' in sys.argv:
            continue
        print(p, identify_lc(f)[:4])


def selected_confident(sp):
    """selected_portrait 결과가 확정인가: 얼굴 상관 · 둘째와의 차 문턱, 링이 약하면(RING_MIN 미만) 더 또렷해야 한다."""
    if not sp or not sp['ranked']:
        return False
    top = sp['ranked'][0][0]
    sec = sp['ranked'][1][0] if len(sp['ranked']) > 1 else 0
    if top < SEL_TOP_MIN or top - sec < SEL_MARGIN_MIN:
        return False
    return sp['ring'] >= RING_MIN or (top >= 0.70 and top - sec >= 0.30)
