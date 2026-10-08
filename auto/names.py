"""영어 게임 이름 → 언어별 TextMap 이름. 캐시: names_cache.json
from names import localize; localize('Sparkle', 'KR') -> ['스파클']"""
import json, glob, re, os

HERE = os.path.dirname(os.path.abspath(__file__))
# 게임 TextMap 폴더(Dimbreath TurnBasedGameData 의 TextMap). 환경 변수 HSR_TEXTMAP 으로 바꿀 수 있다
D = os.path.join(os.environ.get('HSR_TEXTMAP') or os.path.join(HERE, '..', 'data', 'TextMap'), '')
CACHE = os.path.join(HERE, 'names_cache.json')
_cache = json.load(open(CACHE, encoding='utf8')) if os.path.exists(CACHE) else {}
_maps = {}
clean = lambda s: re.sub(r'<[^>]+>|\{RUBY_[BE]#[^}]*\}', '', str(s or '')).replace('\u00a0', ' ').strip()


def _load(l):
    if l not in _maps:
        d = {}
        for f in glob.glob(D + 'TextMap*.json'):
            if re.match(r'^TextMap(Main)?' + l + r'(_\d)?\.json$', os.path.basename(f)):
                d.update(json.load(open(f, encoding='utf8')))
        _maps[l] = d
    return _maps[l]


def localize(name, lang):
    """같은 EN 글을 가진 모든 해시의 그 언어 글(중복 없이). 못 찾으면 []."""
    key = f'{lang}|{name}'
    if key in _cache:
        return _cache[key]
    alt = {'Trailblazer (Elation)': 'Trailblazer', 'Trailblazer (Remembrance)': 'Trailblazer', 'Trailblazer (Harmony)': 'Trailblazer',
           'Trailblazer (Destruction)': 'Trailblazer', 'Trailblazer (Preservation)': 'Trailblazer'}
    en = _load('EN')
    T = _load(lang)
    want = alt.get(name, name)
    keys = [k for k, v in en.items() if isinstance(v, str) and clean(v) == want]
    if not keys:
        # 사이트는 같은 이름의 다른 갈래를 「March 7th (Hunt)」처럼 괄호로 가른다. 게임 이름은 괄호 없이 「March 7th」
        m = re.match(r'^(.*\S)\s*\([^()]*\)$', want)
        if m:
            keys = [k for k, v in en.items() if isinstance(v, str) and clean(v) == m.group(1)]
    out = sorted({clean(T[k]) for k in keys if T.get(k)})
    _cache[key] = out
    json.dump(_cache, open(CACHE, 'w', encoding='utf8'), ensure_ascii=False)
    return out


# ---------- 게임 글인지 ----------
# 영상 화면의 큰 글자가 게임이 띄운 글(스킬 이름 · 배너)인지, 업로더가 넣은 자막 · 편집 글인지 가른다.
# 짧은 TextMap 글(30자 이하)을 3글자 조각으로 색인해 두고, OCR 글과 조각이 많이 겹치는 것만 비교한다.
_idx = {}
IDX_DIR = os.path.join(HERE, '..', 'data', 'cache')


def _n(s):
    import unicodedata
    s = unicodedata.normalize('NFKD', str(s))
    s = unicodedata.normalize('NFC', ''.join(c for c in s if not unicodedata.combining(c)))
    return re.sub(r'[\W_]+', '', s.lower())


def _tris(s):
    return {s[i:i + 3] for i in range(len(s) - 2)}


def text_index(lang):
    if lang in _idx:
        return _idx[lang]
    import pickle
    p = os.path.join(IDX_DIR, f'textidx_{lang}.pkl')
    if os.path.exists(p):
        _idx[lang] = pickle.load(open(p, 'rb'))
        return _idx[lang]
    strs = sorted({n for n in (_n(clean(v)) for v in _load(lang).values() if isinstance(v, str) and len(v) <= 60)
                   if 2 <= len(n) <= 30})
    tri = {}
    for i, s in enumerate(strs):
        for t in _tris(s):
            tri.setdefault(t, []).append(i)
    _idx[lang] = (strs, set(strs), tri)
    os.makedirs(IDX_DIR, exist_ok=True)
    pickle.dump(_idx[lang], open(p, 'wb'))
    return _idx[lang]


def is_game_text(text, langs, ratio=0.75):
    """OCR 글이 그 언어들의 게임 글(또는 그 일부)과 맞으면 True. 3글자보다 짧으면 가를 수 없어 True."""
    import difflib
    n = _n(text)
    if len(n) < 3:
        return True
    q = _tris(n)
    for lang in langs:
        strs, full, tri = text_index(lang)
        if n in full:
            return True
        cnt = {}
        for t in q:
            for i in tri.get(t, ()):
                cnt[i] = cnt.get(i, 0) + 1
        need = max(1, int(0.5 * len(q)))
        for i, c in sorted(cnt.items(), key=lambda z: -z[1])[:40]:
            if c < need:
                break
            s = strs[i]
            if (len(n) >= 4 and n in s) or difflib.SequenceMatcher(None, n, s).ratio() >= ratio:
                return True
    return False


# OCR 모델 → 그 모델로 읽는 게임 언어들
MODEL_LANGS = {'chinese': ['CHS', 'CHT', 'JP', 'EN'], 'korean': ['KR', 'EN'], 'latin': ['EN', 'FR', 'DE', 'ES', 'PT', 'VI', 'ID'],
               'eslav': ['RU', 'EN'], 'thai': ['TH', 'EN']}
