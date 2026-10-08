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
