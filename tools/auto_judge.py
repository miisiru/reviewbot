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
    # 'eidolon_activatable': 감점 없음(사용자, 2026-10-09)
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
    # 캐릭터 화면에서 못 읽으면 전투 화면 왼쪽 아래 작은 「UID:…」에서(전투 중에도 나온다, rev_6quic9).
    # 글자가 작아 두 배로 키워 읽고, 영상 곳곳 12장에서 가장 많이 나온 값
    vids_p = os.path.join(ROOT, rev, 'videos.json')
    if not os.path.exists(vids_p):
        return None
    votes = {}
    for v in json.load(open(vids_p, encoding='utf8')):
        video = os.path.join(ROOT, rev, v['file'])
        if not os.path.exists(video):
            continue
        dur, W, H = tabs.probe(video)
        for t, f in tabs.frames(video, 0, dur, 12 / max(dur, 1), W, H):
            c = cv2.resize(f[int(0.9 * H):H, 0:int(0.3 * W)], None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            txt = ''.join(b[4] for b in ocr(c, 'chinese')).replace(' ', '')
            m = re.search(r'UID\D{0,2}(\d{9,10})', txt, re.I) or re.search(r'(\d{9,10})', txt)
            if m:
                votes[m.group(1)] = votes.get(m.group(1), 0) + 1
    if votes:
        best = max(votes, key=votes.get)
        if votes[best] >= 2:
            return best
    return None


def hud_model(rev, default):
    """전투 HUD 오른쪽 위 라벨이 13개 언어 사전(CYCLES · RAV)과 가장 잘 맞는 OCR 모델. 영상 곳곳 6장."""
    d = os.path.join(ROOT, rev)
    vids = json.load(open(os.path.join(d, 'videos.json'), encoding='utf8'))
    video = os.path.join(d, vids[0]['file'])
    dur, W, H = tabs.probe(video)
    fr = [f for _, f in tabs.frames(video, 0, dur, 6 / max(dur, 1), W, H)][:6]
    scores = {}
    for m in judge.MODELS:
        tot = 0.0
        for f in fr:
            Hh, Ww = f.shape[:2]
            c = f[0:int(0.6 * Hh), int(0.60 * Ww):Ww]
            tot += max([max(hud.label_score(b[4], hud.CYCLES), hud.label_score(b[4], hud.RAV)) for b in ocr(c, m)] or [0])
        scores[m] = tot
    best = max(scores, key=scores.get)
    return best if scores[best] > scores.get(default, 0) + 0.3 else default


def start_seen(rev, vid, t0, model):
    """t0 뒤 62초 안에 전투 HUD(소모 라운드 · 남은 행동값 라벨)가 보이는 첫 시각."""
    d = os.path.join(ROOT, rev)
    vids = json.load(open(os.path.join(d, 'videos.json'), encoding='utf8'))
    video = os.path.join(d, vids[vid]['file'])
    dur, W, H = tabs.probe(video)
    # 고른 모델로 못 찾으면 다른 언어로도: 게임 글과 UI 글의 언어가 다른 영상이 있다(rev_1g39naf: 이름 영어 · UI 태국어)
    for m in [model] + [x for x in judge.MODELS if x != model]:
        for t, f in tabs.frames(video, t0, min(START_WITHIN + 2, dur - t0), 1, W, H):
            Hh, Ww = f.shape[:2]
            c = f[0:int(0.6 * Hh), int(0.60 * Ww):Ww]
            for b in ocr(c, m):
                if hud.label_score(b[4], hud.CYCLES) >= 0.8 or hud.label_score(b[4], hud.RAV) >= 0.8:
                    return round(t, 1)
    return None


_RESULT = None


def result_seen(rev, model):
    """메뉴가 하나도 없는 영상에서 전투 결과 화면(도전 성공 · 도전 종료 · 전투 종료, 13개 언어 TextMap)이 보이는 시각.
    영상이 끝까지 디코드되고(summary.json decoded) 메뉴 구간이 0 일 때만 부른다. 끝 2분을 1초마다, 고른 모델로 못 찾으면 다른 모델로."""
    global _RESULT
    if _RESULT is None:
        _RESULT = {judge.norm(v) for en in ('Challenge Completed', 'Challenge Ended', 'Battle Over')
                   for l in judge.LANGS for v in (judge.localize(en, l) or []) if judge.norm(v)}
    d = os.path.join(ROOT, rev)
    vids = json.load(open(os.path.join(d, 'videos.json'), encoding='utf8'))
    for vi, v in enumerate(vids):
        sj = os.path.join(d, f'tabs{vi}', 'summary.json')
        if not os.path.exists(sj):
            return None
        s = json.load(open(sj))
        if s.get('windows') or s.get('decode_error') or (s.get('decoded') or 0) < 0.99:
            return None
    for vi, v in enumerate(vids):
        video = os.path.join(d, v['file'])
        dur, W, H = tabs.probe(video)
        for m in [model] + [x for x in judge.MODELS if x != model]:
            for t, f in tabs.frames(video, max(0, dur - 120), min(120, dur), 1, W, H):
                c = f[int(0.05 * H):int(0.5 * H), int(0.2 * W):int(0.8 * W)]
                for b in ocr(c, m):
                    n = judge.norm(b[4])
                    if n and any(w in n or judge.sim(n, w) >= 0.8 for w in _RESULT):
                        return round(t, 1)
    return None


def uncertain_eidolons(c):
    """잠김 · 열림이 애매한 성혼 단계를 「E3」 꼴로: 읽은 단계와 다음으로 맞는 단계 사이의 노드(노드 순서 = 성혼 단계)."""
    if c.get('e_alt') is None or c.get('e_seen') is None:
        return '?'
    a, b = sorted((c['e_seen'], c['e_alt']))
    return ', '.join(f'E{i}' for i in range(a + 1, b + 1)) or '?'


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
            out['check_reasons'].append(why if ('not read' in why or 'unreadable' in why) else f'{why} (could not be read)')
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
    if not any(f['tab'] == 'LightCone' for f in b['frames']):
        # 광추 화면이 하나도 없으면(성혼 머리글만으로 고른 언어는 틀리기 쉽다: rev_zmad8t 중국어 영상이 latin 으로) 또는 광추 · 성혼 화면이 하나도 없으면 judge 가 언어를 못 골라 중국어로 남는다(rev_1pjotys: 한국어 영상, 메뉴 없음)
        # → 전투 화면 오른쪽 위 HUD 라벨(소모 라운드 · 남은 행동값)을 모델마다 읽어 가장 잘 맞는 모델
        model = hud_model(rev, model)
    lc_found = sum(1 for c in b['chars'] if c.get('lc_seen') is not None)
    # 메뉴 구간은 찾았는데(디테일 · 유물 · 성혼 등) 광추 탭이 한 번도 안 열렸으면 「못 읽음」이 아니라 「안 보여 줌」이다
    # (rev_s4it7k: 넷 다 광추 탭을 안 염 → 거절이 맞다). 메뉴를 못 찾았거나 광추 화면이 있는데 누구 것인지 못 정한 때만 애매
    segs = []
    vids_p = os.path.join(ROOT, rev, 'videos.json')
    for vi in range(len(json.load(open(vids_p, encoding='utf8'))) if os.path.exists(vids_p) else 1):
        if os.path.exists(os.path.join(ROOT, rev, f'tabs{vi}', 'timeline.txt')):
            segs += judge.segs_of(rev, vi)
    lc_never_opened = bool(segs) and not any(k == 'LightCone' for _, _, k in segs)
    # 메뉴 구간이 하나도 없고 영상이 끝까지 재생되며 결과 화면(도전 성공 · 전투 종료)이 보이면 빌드를 안 보여 준 것이다
    # (사용자, 2026-10-09: rev_6quic9 — 전투 뒤 결과 화면으로 끝나고 캐릭터 화면이 없다 → 거절)
    menu_never_shown = False
    if not segs and not any(w.startswith('video file') for _, w in out['deductions']):
        rt = result_seen(rev, model)
        if rt is not None:
            menu_never_shown = True
            out['checks'].append(f'no character menu anywhere in the video; result screen at {rt} (build not shown)')
    for c in b['chars']:
        name = c['char']
        sub = c['submitted']
        for key in ('lc_how', 'e_how'):
            how = c.get(key) or ''
            if how.startswith('name 1') or how.startswith('details name 1') or how.startswith('name 0.9'):
                continue
            # 광추 제목이 거의 그대로 읽히고 다른 캐릭터 광추와 0.25 넘게 갈리면(judge 가 고를 때 거는 조건) 확실하다
            m = re.match(r'lc title (\d\.\d+)', how)
            if m and float(m[1]) >= 0.95:
                continue
            if re.match(r'eidolon names [3-6]/', how) or ' + ' in how:
                continue          # 성혼 이름 셋 이상이 한 캐릭터와만 맞거나, 따로 된 근거 둘이 같은 캐릭터를 가리키면 확실하다
            if how.startswith('name') or how.startswith('lc title') or how.startswith('details') or how.startswith('eidolon names'):
                ded('id_weak', f'{name}: identified by {how}')
            elif how:
                ded('id_inferred', f'{name}: identified by {how}')
        if c.get('lc_seen') is None:
            prob(f'{name} Light Cone Superimposition not shown', 'lc_not_shown', char=name)
            if lc_found < len(b['chars']) - 1 and not lc_never_opened and not menu_never_shown:
                ded('not_shown_uncertain', f'{name}: Light Cone page not found (other pages also missing)')
        else:
            if c['lc_match'] < 0.7 and not c.get('lc_title_found', True):
                # 광추 제목이 한 줄도 안 읽혔다 → 안 맞는 게 아니라 못 읽은 것(사용자, 2026-10-09: rev_1sqwwaj)
                ded('superimp_unread', f"{name}: Light Cone title unreadable")
            elif c['lc_match'] < 0.7:
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
            if sub['e'] not in (c['e_seen'], c.get('e_alt')):
                prob(f"{name} Eidolons mismatch (submitted E{sub['e']}, video E{c['e_seen']})", 'eidolon_mismatch', char=name,
                     sub=sub['e'], video=c['e_seen'])
            # 두 장이라도 노드 여섯이 모두 뚜렷하면(자물쇠 0.8 이상 · 열림 0.45 미만) 감점하지 않는다
            blurry = any(v is not None and 0.58 <= v < 0.8 for v in (c.get('lock_scores') or [0.6]))
            if (c.get('e_frames') or 0) < 2 or ((c.get('e_frames') or 0) < 3 and blurry):
                ded('eidolon_few_frames', f"{name}: Eidolons read from {c.get('e_frames')} frame(s)")
            if c.get('e_alt') is not None:
                ded('eidolon_gray', f"{name}: {uncertain_eidolons(c)} uncertain (locked or not)", abs(c['e_seen'] - c['e_alt']))
            # 빨간 「!」(활성화 가능, 아직 안 켬)는 활성화 안 한 것으로 세고 감점하지 않는다(사용자, 2026-10-09: 정상 상태)
    out['build'] = [{k: c.get(k) for k in ('char', 'submitted', 'lc_seen', 'lc_match', 's_seen', 'e_seen', 'e_gray', 'e_alt', 'lock_scores', 'lc_t', 'e_t')}
                    for c in b['chars']]
    tm('build')
    # 2) UID
    uid = read_uid(rev, b['frames'])
    out['uid'] = uid
    if not uid and not menu_never_shown:     # UID 는 캐릭터 화면에 나온다 — 화면이 아예 없으면 못 읽은 게 아니다
        ded('uid_missing', 'UID not readable')
    tm('uid')
    # 3) 전투 HUD
    mode = s0.get('mode')
    plight = 'Plight' in (s0.get('boss_name') or '')
    run_vid = next((k for k, v in enumerate(vids) if v.get('run_part')), 0)
    cyc_mode = mode in ('moc', 'pf')      # 혼돈의 기억 · 허구 이야기: 오른쪽 위 「소모 라운드」가 없고 행동 순서의 모래시계 칸으로 센다
    if 'hud' not in cache:
        cache['hud'] = {} if cyc_mode else hud.scan(rev, run_vid, model=model, plight=plight)['final']
        if not cyc_mode and not plight and not cache['hud'].get('rav') and not (cache['hud'].get('cycles') or {}).get('frames'):
            # 광추 이름은 영어인데 UI 는 태국어인 영상 등: 고른 모델로 HUD 라벨이 안 읽히면 HUD 글로 모델을 다시 골라 한 번 더(rev_jwrt4a)
            m2 = hud_model(rev, model)
            if m2 != model:
                cache['hud'] = hud.scan(rev, run_vid, model=m2, plight=plight)['final']
    fin = cache['hud']
    out['hud'] = fin
    # 모드 불일치(사용자, 2026-10-09): 전투 HUD 오른쪽 위가 이상 중재면 「소모 라운드」, 종말의 환영이면 「남은 행동값」.
    # 한쪽 라벨만 또렷하게 여러 번 읽혔는데 제출 모드와 반대면 모드가 다르다(rev_zmad8t: AA 로 냈는데 AS 영상)
    if not cyc_mode and not plight:
        got_rav = (fin.get('rav') or {}).get('of', 0) >= 3
        got_cyc = (fin.get('cycles') or {}).get('frames', 0) >= 3
        if mode == 'aa' and got_rav and not got_cyc:
            prob('Mode mismatch (submitted Anomaly Arbitration, video is Apocalyptic Shadow)', 'mode_mismatch', sub='aa', video='as')
        elif mode == 'as' and got_cyc and not got_rav:
            prob('Mode mismatch (submitted Apocalyptic Shadow, video is Anomaly Arbitration)', 'mode_mismatch', sub='as', video='aa')

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
            if not any(i.get('kind') == 'mode_mismatch' for i in out['problem_items']):
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
        pf_ambiguous = False
        if cyc_mode:
            if 'cycles_hg' not in cache:
                r = hud.scan_cycles(rev, run_vid, mode=mode, start=float(tstart(s0.get('video_url'))))
                cache['cycles_hg'] = {k: r.get(k) for k in ('value', 'first', 'last', 'counter', 'note', 'lost_after', 'battle_until', 'banner')} | {'n': len(r['reads'])}
            ch = cache['cycles_hg']
            cyc = ch.get('value')
            # 「Remaining Cycles: 0」 띠를 봤으면 모래시계 칸을 끝까지 못 읽었어도 4 사이클
            if cyc is not None and ch.get('lost_after') is not None and ch.get('banner') is None:
                ded('hud_unread', f"hourglass cell last read {ch['last'][1]} at {ch['lost_after']}, battle continued to {ch['battle_until']} (counter at the end unknown)")
                cyc, pf_ambiguous = None, 'checked'
            if cyc is not None:
                if mode == 'pf':
                    how = (f"\"Remaining Cycles: 0\" banner at {ch['banner']}" if ch.get('banner') is not None
                           else f"hourglass counter {ch.get('counter')} at the end"
                           + (', no "Remaining Cycles: 0" banner' if ch.get('counter') == 0 else ''))
                else:
                    how = f"remaining-cycle counter {ch['first'][1]} -> {ch['last'][1]}"
                out['checks'].append(f'Cycles (action order): {cyc} ({how})')
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
            if not plight and pf_ambiguous != 'checked' and not any(k == 'mode_mismatch' for k in [i.get('kind') for i in out['problem_items']]):
                ded('hud_unread', 'Cycles Used at Battle Over not read' if not cyc_mode else 'action-order hourglass counter not read')
        else:
            if not cyc_mode:
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
            cache['start'] = (hud.first_cell_time(rev, run_vid, t0, START_WITHIN + 2, model) if mode in ('moc', 'pf')
                              else start_seen(rev, run_vid, t0, model))
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
