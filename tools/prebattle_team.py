"""전투 HUD 가 나오기 전, 화면 오른쪽 가운데에 그 전투에 쓰는 캐릭터 4명이 이름 글자와 번호 1~4 로 나열된다.
그 이름을 OCR 로 읽어 제출한 팀과 맞춘다(합친 제출에서 「이 타임스탬프의 전투가 이 기록인가」를 확인하는 용도, 얼굴 인식 없음).
python prebattle_team.py <영상> <전투 시작 초> <캐릭터 영문 이름 ...> [--model chinese]"""
import os, sys, re, json, difflib, unicodedata
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'auto'))
import cv2                                    # noqa: E402
import tabs                                   # noqa: E402
from judge import ocr                         # noqa: E402
from names import localize                    # noqa: E402
import scan_battle_boundaries as S            # noqa: E402

LANGS = ('EN', 'KR', 'CHS', 'CHT', 'JP', 'VI', 'TH', 'RU', 'ES', 'PT', 'FR', 'DE', 'ID')


def _n(s):
    s = unicodedata.normalize('NFKD', str(s))
    s = unicodedata.normalize('NFC', ''.join(c for c in s if not unicodedata.combining(c)))
    return re.sub(r'[\W_]+', '', s.lower())


def name_forms(english):
    """게임 안 이름 표기 모음(13개 언어). 개척자는 이름을 사용자가 짓기 때문에 비교하지 않는다."""
    if english.startswith('Trailblazer'):
        return []
    forms = set()
    for lang in LANGS:
        for t in localize(english, lang) or []:
            n = _n(t)
            if n:
                forms.add(n)
    # 이름이 길어 줄바꿈 · 말줄임으로 잘리는 이름(「Robin • Summeretto」)은 앞부분만 보여도 인정
    return sorted(forms)


def matches(text, forms):
    t = _n(text)
    if not t:
        return False
    for f in forms:
        if len(f) <= 3:                       # 짧은 한자 이름은 글 안에 그대로 있을 때만
            if f in t:
                return True
            continue
        if f in t or (len(t) >= 4 and t in f and len(t) >= 0.6 * len(f)):
            return True
        if difflib.SequenceMatcher(None, t, f).ratio() >= 0.8:
            return True
    return False


def read_texts(video, a, z, models=('chinese', 'latin'), step=1.0):
    """[a, z] 구간을 step 초마다 보며 오른쪽 가운데 띠의 글을 읽는다 → [(시각, [글 …])]. 한 번 읽어 두고 여러 팀과 맞춰 볼 수 있다."""
    dur, W, H = tabs.probe(video)
    a, z = max(0.0, a), min(dur, z)
    out = []
    if z <= a:
        return out
    for t, f in tabs.frames(video, a, z - a, 1.0 / step, W, H):
        p = S.active_picture(f)
        h, w = p.shape[:2]
        crop = p[int(.12 * h):int(.72 * h), int(.76 * w):w]
        if crop.size == 0:
            continue
        big = cv2.resize(crop, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)
        texts = []
        for model in models:
            texts += [b[4] for b in ocr(big, model)]
        out.append((round(t, 2), texts))
    return out


def match_team(frames, chars):
    """읽어 둔 글에서 제출한 캐릭터(개척자 제외)가 몇 명 보이는지 → {'frames', 'best': (수, 시각, [캐릭터]), 'need': 비교 대상 수}"""
    forms = {c: name_forms(c) for c in chars}
    need = sum(1 for c in chars if forms[c])
    best = (0, None, [])
    per = []
    for t, texts in frames:
        seen = [c for c in chars if forms[c] and any(matches(x, forms[c]) for x in texts)]
        per.append((t, seen))
        if len(seen) > best[0]:
            best = (len(seen), t, seen)
    return {'frames': len(frames), 'best': best, 'need': need, 'per_frame': per}


def read_names(video, start, chars, models=('chinese', 'latin'), span=14.0, step=1.0, after=0.0):
    """전투 시작 앞 span 초(+ after 초)를 읽고 제출한 팀과 맞춘다."""
    frames = read_texts(video, start - span, start - 0.3 + after, models, step)
    return match_team(frames, chars)


if __name__ == '__main__':
    a = sys.argv[1:]
    model = a[a.index('--model') + 1] if '--model' in a else None
    rest = [x for i, x in enumerate(a) if not x.startswith('--') and (i == 0 or a[i - 1] != '--model')]
    video, start, chars = rest[0], float(rest[1]), rest[2:]
    r = read_names(video, start, chars, models=(model,) if model else ('chinese', 'latin'))
    print(json.dumps({k: v for k, v in r.items() if k != 'per_frame'}, ensure_ascii=False))
    for t, s in r['per_frame']:
        print(t, s)
