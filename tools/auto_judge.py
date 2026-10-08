"""AI 없이 한 건을 판정한다: 빌드(judge.py) + UID + 전투 HUD(hud.py) + 보유 효과(gp.py) + 시작 시각.
결과 화면은 쓰지 않는다(최고 기록을 보여 줄 수 있어서). 신뢰도는 아래 고정 공식(측정값으로 감점)이라 같은 영상이면 늘 같다.
판정: REJECT(확실한 문제) / CHECK(못 읽은 항목이 있거나 신뢰도 80 이하) / APPROVE
python auto_judge.py <rev>   → runs/<rev>/auto.json + 요약(영어 디스코드 글 꼴)"""
import os, sys, re, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import judge, hud, gp, tabs      # noqa: E402
from judge import ROOT, ocr      # noqa: E402
import cv2                       # noqa: E402

# ---------------- 신뢰도 공식 (감점) ----------------
CONF = {
    'decode_error': 100,          # 영상 파일이 깨짐 → 판정 불가
    'id_weak': 2,                 # 누구 화면인지 이름(0.6~0.9) · 광추 제목으로 정함
    'id_inferred': 4,             # 소거 · 바로 앞 화면 · 같은 머리글 · 개척자 추정으로 정함
    'lc_name_fuzzy': 3,           # 광추 이름 맞춤 0.7~0.9
    'superimp_unread': 20,        # 중첩 숫자를 못 읽음
    'eidolon_unread': 20,         # 성혼을 못 읽음(노드를 못 찾음 · 흐린 프레임뿐)
    'eidolon_few_frames': 5,      # 성혼을 1~2 프레임으로만 읽음
    'eidolon_gray': 5,            # 자물쇠인지 애매한 노드 하나당
    'eidolon_activatable': 5,     # 빨간 「!」(활성화 가능) — 하나로 셈
    'hud_unread': 30,             # 전투 끝 HUD 값을 못 읽음
    'hud_weak': 5,                # HUD 값 읽기 일치율 50~80%
    'hud_poor': 15,               # HUD 값 읽기 일치율 50% 미만
    'uid_missing': 10,            # UID 를 못 읽음
    'start_unseen': 10,           # 재생 시작 1분 안에 전투 HUD 를 못 봄
    'not_shown_uncertain': 15,    # 「미표시」인데 다른 캐릭터 화면도 덜 잡힘(도구가 놓쳤을 수 있음)
}
CHECK_BELOW = 79   # 80% 는 CHECK 가 아니다(사용자, 2026-10-08: 80% 이상이면 누른다)
START_WITHIN = 60   # 재생 시작 뒤 이 초 안에 전투가 보여야 한다(사용자, 2026-10-08: 30초 → 1분)
UNREAD = {'decode_error', 'superimp_unread', 'eidolon_unread', 'hud_unread', 'uid_missing', 'start_unseen'}
STOP_LOOP = {'superimp_unread', 'eidolon_unread'}


def read_uid(rev, frames):
    for fr in frames[:4]:
        p = os.path.join(ROOT, rev, f"tabs{fr['vid']}", f"{fr['t']:07.2f}_{fr['tab']}.jpg")
        if not os.path.exists(p):
            continue
        f = cv2.imread(p)
        H, W = f.shape[:2]
        txt = ''.join(b[4] for b in ocr(f[int(0.88 * H):H, 0:int(0.25 * W)], 'chinese')).replace(' ', '')
        m = re.search(r'(\d{9,10})', txt)
        if m:
            return m.group(1)
    return None


def start_seen(rev, vid, t0, model):
    """t0 뒤 62초 안에 전투 HUD(소모 라운드 · 남은 행동값 라벨)가 보이는 첫 시각."""
    d = os.path.join(ROOT, rev)
    vids = json.load(open(os.path.join(d, 'videos.json'), encoding='utf8'))
    video = os.path.join(d, vids[vid]['file'])
    dur, W, H = tabs.probe(video)
    for t, f in tabs.frames(video, t0, min(START_WITHIN + 2, dur - t0), 1, W, H):
        Hh, Ww = f.shape[:2]
        c = f[0:int(0.45 * Hh), int(0.60 * Ww):Ww]
        for b in ocr(c, model):
            if hud.label_score(b[4], hud.CYCLES) >= 0.8 or hud.label_score(b[4], hud.RAV) >= 0.8:
                return round(t, 1)
    return None


def uncertain_eidolons(c):
    """잠김 · 열림 점수가 애매한 성혼 노드를 「E3」 꼴로(노드 순서 = 성혼 단계)."""
    sc = c.get('lock_scores') or []
    lo, hi = judge.LOCK_GRAY
    return ', '.join(f'E{i + 1}' for i, v in enumerate(sc) if lo <= v < judge.LOCK_MIN) or '?'


def tstart(url):
    m = re.search(r'[?&#]t=(\d+)', url or '') or re.search(r'[?&]start=(\d+)', url or '')
    return int(m.group(1)) if m else 0


def run(rev, do_gp=True, reuse=False):
    d = os.path.join(ROOT, rev)
    # 느린 HUD · 보유 효과 · 시작 시각 읽기 결과는 auto_cache.json 에 남긴다. --reuse 면 그것을 다시 쓴다(빌드만 고쳤을 때)
    cache_p = os.path.join(d, 'auto_cache.json')
    cache = json.load(open(cache_p, encoding='utf8')) if reuse and os.path.exists(cache_p) else {}
    rj = json.load(open(os.path.join(d, 'review.json'), encoding='utf8'))
    p = rj['payload']
    sides = p.get('runs') or [p]
    s0 = sides[0]
    vids = json.load(open(os.path.join(d, 'videos.json'), encoding='utf8'))
    out = {'rev': rev, 'run': (rj.get('run_ids') or [None])[0], 'problems': [], 'checks': [], 'deductions': [], 'notes': [],
           'check_reasons': []}   # 문제는 아니지만 사람이 꼭 봐야 하는 것(있으면 CHECK)

    out['problem_items'] = []   # 거절 사유를 영상 언어로 쓰기 위한 구조(reasons.py)

    def prob(text, kind, **kw):
        out['problems'].append(text)
        out['problem_items'].append(dict(kind=kind, **kw))

    def ded(key, why, n=1):
        out['deductions'].append((CONF[key] * n, why))
        # 실전(사용자, 2026-10-08): 「못 읽음」이 하나라도 있으면 신뢰도와 상관없이 CHECK.
        # 성혼 · 광추 중첩을 못 읽은 것은 도구 문제라 루프도 멈춘다
        if key in UNREAD:
            out['check_reasons'].append(f'{why} (could not be read)')
            if key in STOP_LOOP:
                out['stop_loop'] = True

    import time
    T = [time.time()]
    out['timing'] = {}

    def tm(name):          # 단계별 걸린 초
        now = time.time()
        out['timing'][name] = round(now - T[0], 1)
        T[0] = now

    # 0) 영상 파일
    for k, v in enumerate(vids):
        sj = os.path.join(d, f'tabs{k}', 'summary.json')
        if os.path.exists(sj) and json.load(open(sj)).get('decode_error'):
            ded('decode_error', f"video file {v['file']} decodes only partly")
    # 1) 빌드
    import ocr as ocr_mod
    ocr_mod.set_gpu(os.environ.get('OCR_GPU', '1') != '0')     # 빌드(큰 화면)만 GPU, 나머지는 CPU
    b = judge.judge(rev)
    ocr_mod.set_gpu(False)
    model = b['ocr_model']
    lc_found = sum(1 for c in b['chars'] if c.get('lc_seen') is not None)
    for c in b['chars']:
        name = c['char']
        sub = c['submitted']
        for key in ('lc_how', 'e_how'):
            how = c.get(key) or ''
            if how.startswith('name 1') or how.startswith('details name 1') or how.startswith('name 0.9'):
                continue
            if re.match(r'eidolon names [3-6]/', how) or ' + ' in how:
                continue          # 성혼 이름 셋 이상이 한 캐릭터와만 맞거나, 따로 된 근거 둘이 같은 캐릭터를 가리키면 확실하다
            if how.startswith('name') or how.startswith('lc title') or how.startswith('details') or how.startswith('eidolon names'):
                ded('id_weak', f'{name}: identified by {how}')
            elif how:
                ded('id_inferred', f'{name}: identified by {how}')
        if c.get('lc_seen') is None:
            prob(f'{name} Light Cone Superimposition not shown', 'lc_not_shown', char=name)
            if lc_found < len(b['chars']) - 1:
                ded('not_shown_uncertain', f'{name}: Light Cone page not found (other pages also missing)')
        else:
            if c['lc_match'] < 0.7:
                # 제출 쪽 표기(「Dance Dance Dance」) 대신 게임 영어 이름(「Dance! Dance! Dance!」)으로 적는다
                shown = judge.en_key(sub['lc']) if sub['lc'] else 'Not Equipped'
                prob(f"{name} Light Cone mismatch (submitted '{shown}', video '{c['lc_seen']}')", 'lc_mismatch', char=name,
                     sub=shown if sub['lc'] else '', sub_s=sub['s'], seen_text=c['lc_seen'], seen_s=c.get('s_seen'))
            elif c['lc_match'] < 0.9:
                ded('lc_name_fuzzy', f"{name}: Light Cone name match {c['lc_match']}")
            if not sub['lc']:
                pass          # 광추를 안 낀 제출(영상도 「미장착」): 중첩은 뜻이 없어 보지 않는다
            elif c.get('s_seen') is None:
                ded('superimp_unread', f'{name}: Superimposition unreadable')
            elif c['s_seen'] != sub['s']:
                prob(f"{name} Superimposition mismatch (submitted S{sub['s']}, video S{c['s_seen']})", 'superimp_mismatch', char=name,
                     sub=sub['s'], video=c['s_seen'])
        if c.get('e_t') is None:
            prob(f'{name} Eidolons not shown', 'eidolon_not_shown', char=name)
        elif c.get('e_seen') is None:
            ded('eidolon_unread', f'{name}: Eidolons unreadable')
        else:
            lo = c['e_seen'] - (c.get('e_gray') or 0)
            if not (lo <= sub['e'] <= c['e_seen']):
                prob(f"{name} Eidolons mismatch (submitted E{sub['e']}, video E{c['e_seen']})", 'eidolon_mismatch', char=name,
                     sub=sub['e'], video=c['e_seen'])
            # 두 장이라도 노드 여섯이 모두 뚜렷하면(자물쇠 0.8 이상 · 열림 0.45 미만) 감점하지 않는다
            blurry = any(0.45 <= v < 0.8 for v in (c.get('lock_scores') or [0.6]))
            if (c.get('e_frames') or 0) < 2 or ((c.get('e_frames') or 0) < 3 and blurry):
                ded('eidolon_few_frames', f"{name}: Eidolons read from {c.get('e_frames')} frame(s)")
            if c.get('e_gray'):
                ded('eidolon_gray', f"{name}: {uncertain_eidolons(c)} uncertain (locked or not)", c['e_gray'])
            if c.get('activatable'):
                ded('eidolon_activatable', f'{name}: activatable Eidolon (red !) counted as not activated')
    out['build'] = [{k: c.get(k) for k in ('char', 'submitted', 'lc_seen', 'lc_match', 's_seen', 'e_seen', 'e_gray', 'lock_scores', 'lc_t', 'e_t')}
                    for c in b['chars']]
    tm('build')
    # 2) UID
    uid = read_uid(rev, b['frames'])
    out['uid'] = uid
    if not uid:
        ded('uid_missing', 'UID not read')
    tm('uid')
    # 3) 전투 HUD
    mode = s0.get('mode')
    plight = 'Plight' in (s0.get('boss_name') or '')
    run_vid = next((k for k, v in enumerate(vids) if v.get('run_part')), 0)
    if 'hud' not in cache:
        cache['hud'] = hud.scan(rev, run_vid, model=model, plight=plight)['final']
    fin = cache['hud']
    out['hud'] = fin

    def hv(key):
        x = fin.get(key)
        if not x or x.get('value') is None:
            return None
        r = x['agree'] / max(1, x['of'])
        if r < 0.5:
            ded('hud_poor', f"HUD {key} read agreement {x['agree']}/{x['of']}")
        elif r < 0.8:
            ded('hud_weak', f"HUD {key} read agreement {x['agree']}/{x['of']}")
        return x['value']
    sub_cat = s0.get('subcategory')
    if mode == 'as':
        rav = hv('rav')
        if rav is None:
            ded('hud_unread', 'Remaining Action Value at Battle Over not read')
        else:
            score = 2000 + rav
            out['checks'].append(f'Score (HUD): Remaining Action Value {rav} at Battle Over, boss killed -> 2000 + {rav} = {score}')
            if s0.get('metric_value') is not None and int(s0['metric_value']) != score:
                prob(f"Score mismatch (submitted {s0['metric_value']}, video {score})", 'score_mismatch', sub=s0['metric_value'], video=score)
            if (sub_cat == '0 AV') != (rav == 2000):
                prob(f"Category mismatch (submitted {sub_cat}, should be {'0 AV' if rav == 2000 else 'Clear'})", 'category_mismatch',
                     sub=sub_cat, should='0 AV' if rav == 2000 else 'Clear')
    else:
        cyc = hv('cycles')
        if plight:
            pl = hv('plight')
            if pl is None:
                ded('hud_unread', 'Plight action-order cell at Battle Over not read')
            else:
                used = 500 - (pl[0] * 100 + pl[1])
                out['checks'].append(f'Action Value (HUD): last cell {pl[0]} | {pl[1]} -> 500 - ({pl[0]}x100 + {pl[1]}) = {used}')
                if s0.get('action_value') and int(s0['action_value']) != used:
                    prob(f"Action Value mismatch (submitted {s0['action_value']}, video {used})", 'av_mismatch', sub=s0['action_value'], video=used)
        if cyc is None:
            if not plight:
                ded('hud_unread', 'Cycles Used at Battle Over not read')
        else:
            out['checks'].append(f'Cycles (HUD): {cyc} at Battle Over')
            if sub_cat == '0-Cycle' and cyc != 0:
                prob(f'Consumed Cycles mismatch (submitted 0 Cycles, video {cyc} Cycles)', 'cycles_mismatch', sub=0, video=cyc)
            elif sub_cat != '0-Cycle' and cyc == 0:
                prob(f'Category mismatch (submitted {sub_cat}, should be 0-Cycle)', 'category_mismatch', sub=sub_cat, should='0-Cycle')
            elif sub_cat in ('full stars', 'Clear') and not plight and s0.get('metric_value') is not None and int(s0['metric_value']) != cyc:
                prob(f"Consumed Cycles mismatch (submitted {s0['metric_value']} Cycles, video {cyc} Cycles)", 'cycles_mismatch',
                     sub=s0['metric_value'], video=cyc)
    tm('hud')
    # 4) 보유 효과
    flags = {f for f in (s0.get('flags') or '').split(',') if f}
    if do_gp:
        if 'gp' not in cache:
            g0 = gp.scan(rev, run_vid, model=model)
            cache['gp'] = {'seen': g0['seen'], 'hits': g0['hits']}
        g = cache['gp']
        seen = set(g['seen'])
        out['gp'] = {'flags': sorted(flags), 'seen': sorted(seen), 'first': {h['flag']: h['t'] for h in reversed(g['hits'])}}
        for f in sorted(flags - seen):
            if f == 'revive':
                # 카스토리스: 제출에 있는데 배너를 못 찾으면, 실제로 안 썼든 도구가 놓쳤든 사람이 본다(사용자, 2026-10-08)
                out['check_reasons'].append('Castorice Global Passive submitted, but its trigger banner was not found in the video')
            else:
                prob("Global Passive not triggered: Silver Wolf LV.999", 'gp_not_triggered', who='firewall')
        for f in sorted(seen - flags):
            prob(f"Global Passive missing: {'Castorice' if f == 'revive' else 'Silver Wolf LV.999'}", 'gp_missing', who=f)
    tm('gp')
    # 5) 시작 시각(한 런 · 한 영상)
    url = s0.get('video_url')
    t0 = tstart(url)
    if len(sides) == 1:
        if 'start' not in cache:
            cache['start'] = start_seen(rev, run_vid, t0, model)
        st = cache['start']
        out['start'] = st
        if st is None:
            ded('start_unseen', f'battle HUD not seen within {START_WITHIN}s after {t0}s (may still be a lineup screen)')
    tm('start')
    # 쇼케이스 시작
    first = min((fr['t'] for fr in b['frames'] if fr['vid'] == run_vid), default=None)
    sh = None
    tl = os.path.join(d, f'tabs{run_vid}', 'timeline.txt')
    if os.path.exists(tl):
        m = re.search(r'\n\s*([\d.]+)\s+[\d.]+\s+Details', open(tl, encoding='utf8').read())
        sh = float(m.group(1)) if m else first
    out['showcase'] = sh
    # 판정
    conf = max(0, 100 - sum(x for x, _ in out['deductions']))
    out['confidence'] = conf
    if out['check_reasons']:
        out['verdict'] = 'CHECK'          # 다른 문제가 있어도 사람에게(문제 목록은 그대로 남긴다)
    elif out['problems']:
        out['verdict'] = 'REJECT'
    elif conf <= CHECK_BELOW or any(w.endswith('unreadable') or 'not read' in w for _, w in out['deductions']):
        out['verdict'] = 'CHECK'
    else:
        out['verdict'] = 'APPROVE'
    json.dump(out, open(os.path.join(d, 'auto.json'), 'w', encoding='utf8'), ensure_ascii=False, indent=1, default=str)
    json.dump(cache, open(cache_p, 'w', encoding='utf8'), ensure_ascii=False, default=str)
    return out


if __name__ == '__main__':
    r = run(sys.argv[1], do_gp='--nogp' not in sys.argv, reuse='--reuse' in sys.argv)
    print(r['rev'], r['run'], r['verdict'], f"{r['confidence']}%", 'UID', r['uid'], 'showcase', r['showcase'], 'start', r.get('start'))
    for x in r.get('check_reasons', []):
        print('  CHECK', x)
    for x in r['problems']:
        print('  PROBLEM', x)
    for x in r['checks']:
        print('  check', x)
    for n, w in r['deductions']:
        print(f'  -{n} {w}')
    if 'gp' in r:
        print('  GP', r['gp'])
    print('  time', r['timing'], 'total', round(sum(r['timing'].values()), 1))
