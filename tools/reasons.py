"""거절 사유를 영상 속 게임 언어로(reject_templates.md 의 꼴). 한 · 영 · 중 · 일, 그 밖의 언어는 영어.
auto_judge.py 가 남긴 problem_items(문제 종류 · 캐릭터 · 제출 값 · 영상 값)를 한 줄로 잇는다(「 / 」).
캐릭터 · 광추 이름은 그 언어의 게임 이름(ExcelOutput 이름 해시 → TextMap).
python reasons.py <rev>   → 언어와 사유를 찍는다"""
import os, sys, re, json, difflib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'auto'))
from paths import ROOT, RUNS   # noqa: E402
import names   # noqa: E402

TM_LANG = {'KR': 'KR', 'EN': 'EN', 'CN': 'CHS', 'JP': 'JP'}
EXCEL = os.environ.get('HSR_EXCEL') or os.path.join(ROOT, 'data', 'ExcelOutput')
_tables = {}


def _excel(name):
    s = open(os.path.join(EXCEL, name), encoding='utf8').read()
    return json.loads(re.sub(r'"Hash": *(-?\d+)', lambda m: f'"Hash": "{m.group(1)}"', s))


def _names(kind):
    """kind = 'char' | 'lc' → {EN 이름: {언어: 이름}}"""
    if kind in _tables:
        return _tables[kind]
    en = names._load('EN')
    rows = _excel('AvatarConfig.json') if kind == 'char' else _excel('EquipmentConfig.json')
    out = {}
    for r in rows:
        h = str((r.get('AvatarName') if kind == 'char' else r.get('EquipmentName') or {}).get('Hash'))
        e = names.clean(en.get(h, ''))
        if not e or (kind == 'char' and r.get('AvatarID', 0) >= 8000):
            continue
        out.setdefault(e, {l: names.clean(names._load(t).get(h, '')) for l, t in TM_LANG.items()})
    _tables[kind] = out
    return out


def char_name(en, lang):
    if lang == 'EN':
        return en
    if en.startswith('Trailblazer'):
        v = names.localize('Trailblazer', TM_LANG[lang])
        return (v or ['Trailblazer'])[0]
    t = _names('char')
    base = re.sub(r'\s*\([^()]*\)$', '', en)          # 「March 7th (Hunt)」 → 「March 7th」
    for k in (en, base):
        if k in t and t[k].get(lang):
            return t[k][lang]
    v = [x for x in names.localize(en, TM_LANG[lang]) if '?' not in x and '？' not in x]
    return v[0] if v else en


def lc_name(en, lang):
    if not en:      # 광추를 안 낀 제출
        v = names.localize('Not Equipped', TM_LANG[lang])
        return v[0] if v else 'Not Equipped'
    t = _names('lc')
    from judge import en_key
    k = en_key(en)
    return (t.get(k) or {}).get(lang) or k


def lc_from_screen(text, lang):
    """광추 화면 OCR 글에서 그 언어의 광추 이름을 찾는다. 못 찾으면 None."""
    from judge import norm
    n = norm(text)
    best = (0.0, None)
    for e, per in _names('lc').items():
        v = per.get(lang) or e
        nv = norm(v)
        if len(nv) >= 3 and nv in n:
            sc = 0.9 + len(nv) / 1000
        else:
            sc = difflib.SequenceMatcher(None, n, nv).ratio()
        if sc > best[0]:
            best = (sc, v)
    return best[1] if best[0] >= 0.6 else None


def detect_lang(rev):
    """영상 화면 글(광추 패널 · 머리글 · 디테일)의 글자 종류로 게임 언어를 정한다. 가나 → JP, 한글 → KR, 한자 → CN, 그 밖 → EN."""
    j = json.load(open(os.path.join(RUNS, rev, 'judge.json'), encoding='utf8'))
    txt = ' '.join([f.get('panel_title') or '' for f in j['frames']] + [f.get('header') or '' for f in j['frames']]
                   + [d.get('text') or '' for d in j.get('details', [])])
    kana = len(re.findall(r'[぀-ヿ]', txt))
    hangul = len(re.findall(r'[가-힣]', txt))
    han = len(re.findall(r'[一-鿿]', txt))
    latin = len(re.findall(r'[A-Za-z]', txt))
    if hangul >= max(5, 0.3 * (han + kana + latin)):
        return 'KR'
    if kana >= 3:
        return 'JP'
    if han >= max(5, 0.3 * latin):
        return 'CN'
    return 'EN'


GP = {'revive': {'KR': '카스토리스', 'EN': 'Castorice', 'CN': '遐蝶', 'JP': 'キャストリス'},
      'firewall': {'KR': '은랑 LV.999', 'EN': 'Silver Wolf LV.999', 'CN': '银狼LV.999', 'JP': '銀狼LV.999'}}
CAT = {'CN': {'0-Cycle': '0T', 'full stars': '满星', 'Clear': '通关', '0 AV': '0行动值'},
       'JP': {'0-Cycle': '0ラウンド', 'full stars': '星3', 'Clear': 'クリア', '0 AV': '0行動値'}}
SEP = {'KR': ', ', 'EN': ', ', 'CN': '、', 'JP': '、'}


def render(items, lang):
    lang = lang if lang in TM_LANG else 'EN'
    C = lambda en: char_name(en, lang)
    out = []
    groups = {}
    for it in items:
        if it['kind'] in ('lc_not_shown', 'eidolon_not_shown', 'gp_missing', 'gp_not_triggered'):
            groups.setdefault(it['kind'], []).append(it)
    done = set()
    for it in items:
        k = it['kind']
        if k in groups:
            if k in done:
                continue
            done.add(k)
            g = groups[k]
            if k in ('gp_missing', 'gp_not_triggered'):
                who = SEP[lang].join(GP[x.get('who', 'firewall')][lang] for x in g)
                out.append({'gp_missing': {'KR': f'보유 효과 누락: {who}', 'EN': f'Global Passive missing: {who}',
                                           'CN': f'仓库技缺失：{who}', 'JP': f'パッシブ未申請：{who}'},
                            'gp_not_triggered': {'KR': f'보유 효과 미발동: {who}', 'EN': f'Global Passive not triggered: {who}',
                                                 'CN': f'仓库技未触发：{who}', 'JP': f'パッシブ未発動：{who}'}}[k][lang])
                continue
            cs = SEP[lang].join(C(x['char']) for x in g)
            if k == 'lc_not_shown':
                out.append({'KR': f'{cs} 광추 중첩 미표시', 'EN': f'{cs} Light Cone Superimposition not shown',
                            'CN': f'视频中未展示{cs}光锥叠影', 'JP': f'{cs}の光円錐の重畳未表示'}[lang])
            else:
                out.append({'KR': f'{cs} 성혼 미표시', 'EN': f'{cs} Eidolons not shown',
                            'CN': f'视频中未展示{cs}星魂', 'JP': f'{cs}の星魂未表示'}[lang])
            continue
        if k == 'lc_mismatch':
            c, sub = C(it['char']), lc_name(it['sub'], lang)
            vid = lc_from_screen(it.get('seen_text') or '', lang) or '?'
            ss, vs = it.get('sub_s'), it.get('seen_s')
            if lang == 'KR':
                out.append(f'{c} 광추 불일치 (제출 {sub} {ss}중첩, 영상 {vid}' + (f' {vs}중첩)' if vs else ')'))
            elif lang == 'CN':
                out.append(f'{c}光锥与提交不符（提交为{sub}叠{ss}，视频中为{vid}' + (f'叠{vs}）' if vs else '）'))
            elif lang == 'JP':
                out.append(f'{c}の光円錐が申請と不一致（申請{sub} 重畳{ss}、動画{vid}' + (f' 重畳{vs}）' if vs else '）'))
            else:
                out.append(f'{c} Light Cone mismatch (submitted {sub} S{ss}, video {vid}' + (f' S{vs})' if vs else ')'))
        elif k == 'superimp_mismatch':
            if any(x['kind'] == 'lc_mismatch' and x.get('char') == it['char'] for x in items):
                continue          # 광추가 다르면 그 줄에 중첩도 함께 적었다
            c, a, b = C(it['char']), it['sub'], it['video']
            out.append({'KR': f'{c} 광추 중첩 불일치 (제출 S{a}, 영상 S{b})', 'EN': f'{c} Superimposition mismatch (submitted S{a}, video S{b})',
                        'CN': f'{c}光锥叠影与提交不符（提交为叠{a}，视频中为叠{b}）', 'JP': f'{c}の光円錐の重畳が申請と不一致（申請{a}、動画{b}）'}[lang])
        elif k == 'eidolon_mismatch':
            c, a, b = C(it['char']), it['sub'], it['video']
            out.append({'KR': f'{c} 성혼 불일치 (제출 E{a}, 영상 E{b})', 'EN': f'{c} Eidolons mismatch (submitted E{a}, video E{b})',
                        'CN': f'{c}星魂与提交不符（提交为{a}魂，视频中为{b}魂）', 'JP': f'{c}の星魂が申請と不一致（申請{a}、動画{b}）'}[lang])
        elif k == 'score_mismatch':
            a, b = it['sub'], it['video']
            out.append({'KR': f'점수 불일치 (제출 {a}, 영상 {b})', 'EN': f'Score mismatch (submitted {a}, video {b})',
                        'CN': f'积分与提交不符（提交为{a}，视频中为{b}）', 'JP': f'ポイントが申請と不一致（申請{a}、動画{b}）'}[lang])
        elif k == 'av_mismatch':
            a, b = it['sub'], it['video']
            out.append({'KR': f'소모 행동 수치 불일치 (제출 {a}, 영상 {b})', 'EN': f'Action Value mismatch (submitted {a}, video {b})',
                        'CN': f'消耗行动值与提交不符（提交为{a}，视频中为{b}）', 'JP': f'消費行動値が申請と不一致（申請{a}、動画{b}）'}[lang])
        elif k == 'cycles_mismatch':
            a, b = it['sub'], it['video']
            out.append({'KR': f'소모 라운드 불일치 (제출 {a}라운드, 영상 {b}라운드)', 'EN': f'Consumed Cycles mismatch (submitted {a} Cycles, video {b} Cycles)',
                        'CN': f'消耗轮次与提交不符（提交为{a}轮，视频中为{b}轮）', 'JP': f'消費ラウンドが申請と不一致（申請{a}ラウンド、動画{b}ラウンド）'}[lang])
        elif k == 'category_mismatch':
            m = CAT.get(lang, {})
            a, b = m.get(it['sub'], it['sub']), m.get(it['should'], it['should'])
            out.append({'KR': f'분류 불일치 (제출 {a}, 맞는 분류 {b})', 'EN': f'Category mismatch (submitted {a}, should be {b})',
                        'CN': f'分类与提交不符（提交为{a}，应为{b}）', 'JP': f'カテゴリーが申請と不一致（申請{a}、正しくは{b}）'}[lang])
    return ' / '.join(out)


if __name__ == '__main__':
    rev = sys.argv[1]
    a = json.load(open(os.path.join(RUNS, rev, 'auto.json'), encoding='utf8'))
    lang = detect_lang(rev)
    print(lang, '|', render(a.get('problem_items', []), lang))
