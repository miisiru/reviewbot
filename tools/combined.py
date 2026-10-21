"""합친 제출(multi · merge) 검토 보조. 계획: work/combined_plan.md (사용자와 정한 규칙)
기록(side)마다 단일 분석을 돌린 결과를 모아, 합친 제출만의 규칙을 얹은 보고서를 만든다. 사이트에는 아무것도 보내지 않는다 —
승인 · 거절은 보고서의 증거 화면을 사람(나)이 직접 보고 확신한 뒤에만 한다.
  B  영상을 보기 전에 정해지는 것: 보스 순서(4.6 시즌), 같은 영상이면 2번째부터 타임스탬프가 있고 점점 커야 한다
  D  전투 직전 오른쪽 가운데 4인 목록의 이름이 그 기록의 팀과 같은가(타임스탬프가 다른 기록의 전투를 가리키는지)
  G  UID 가 모든 기록에서 같은가, 두 기록이 같은 전투를 가리키지 않는가
python combined.py analyze <rev_id> [--queue work/queue_live.json]   기록별 분석 + 보고서(work/combined_<rev>.json)
python combined.py report <rev_id>                                    이미 돌린 분석으로 보고서만"""
import os, sys, re, json, copy, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import WORK, RUNS                              # noqa: E402

CANON = {'pf': ['Flame Reaver', 'King Pom-Pom', 'Argenti'],
         'moc': ['SparxiConOfficial', 'Zandar', 'Murata Graphia, Founding Artist'],
         'aa': ['King Pom-Pom', 'Pollux', 'Harbinger of Death'],
         'as': ['Kafka', 'Ichor Memosprite', 'Hoolay']}
BOSSES_4_6 = {b for v in CANON.values() for b in v}


def tsec(u):
    m = re.search(r'[?&#](?:t|start)=([0-9hms]+)', u or '')
    if not m:
        return None
    v = m.group(1)
    if v.isdigit():
        return int(v)
    return sum(int(n) * {'h': 3600, 'm': 60, 's': 1}[unit] for n, unit in re.findall(r'(\d+)([hms])', v))


def split_item(item):
    """합친 제출 한 건 → 기록 하나짜리 항목들(side 번호 순). 실행 폴더 이름은 <rev>_<번호>."""
    out = []
    for i, r in enumerate(item['payload']['runs'], 1):
        x = copy.deepcopy(item)
        x['id'] = f"{item['id']}_{i}"
        x['kind'] = 'single'
        x['payload'] = copy.deepcopy(r)
        x['payload'].setdefault('flags', item['payload'].get('flags') or '')
        x['run_ids'] = [r.get('submission_id')]
        out.append(x)
    return out


def rule_b(item):
    from video_policy import url_key
    runs = item['payload']['runs']
    out = []
    modes = {r.get('mode') for r in runs}
    if len(modes) == 1:
        order = CANON.get(runs[0].get('mode'))
        bosses = [r.get('boss_name') for r in runs]
        if order and all(b in BOSSES_4_6 for b in bosses) and bosses != order[:len(bosses)]:
            out.append({'rule': 'B1', 'problem': True, 'text': f'boss order {bosses}, expected {order}'})
    groups = collections.defaultdict(list)
    for i, r in enumerate(runs):
        groups[url_key(r['video_url'])].append(i)
    for k, idx in groups.items():
        if len(idx) < 2:
            continue
        ts = [tsec(runs[i]['video_url']) for i in idx]
        bad = [i + 1 for i, t in zip(idx[1:], ts[1:]) if not t]
        if bad:
            out.append({'rule': 'B2', 'problem': True, 'text': f'side {bad} points at the same video as another side without a timestamp'})
        elif any(b <= a for a, b in zip([ts[0] or 0] + ts[1:-1], ts[1:])):
            out.append({'rule': 'B2', 'problem': True, 'text': f'timestamps not increasing {ts}'})
    return out


def load_side(rev, i):
    d = os.path.join(RUNS, f'{rev}_{i}')
    res = {'dir': d}
    for name, key in (('auto.json', 'auto'), ('segment_selection.json', 'selection')):
        p = os.path.join(d, name)
        res[key] = json.load(open(p, encoding='utf8')) if os.path.exists(p) else None
    return res


def rule_d(item, sides, models=('chinese', 'latin')):
    """각 기록의 전투 직전 4인 목록 이름이 그 기록의 팀과 같은지. 다른 기록의 팀이 보이면 그 기록을 가리킨다고 적는다."""
    import prebattle_team as P
    runs = item['payload']['runs']
    teams = [[r[f'p{k}_char'] for k in (1, 2, 3, 4)] for r in runs]
    out = []
    for i, (s, r) in enumerate(zip(sides, runs), 1):
        sel = s['selection']
        video = os.path.join(s['dir'], 'video0.mp4')
        if not sel or not os.path.exists(video):
            out.append({'rule': 'D', 'side': i, 'status': 'unknown', 'text': 'battle not located'})
            continue
        start = sel['battle'][0]
        frames = P.read_texts(video, start - 14, start - 0.3, models)
        mine = P.match_team(frames, teams[i - 1])
        others = [(j + 1, P.match_team(frames, t)) for j, t in enumerate(teams) if j != i - 1]
        entry = {'rule': 'D', 'side': i, 'battle_start': start, 'frames': len(frames), 'need': mine['need'],
                 'seen': mine['best'][2], 'at': mine['best'][1],
                 'other_side_seen': {j: m['best'][2] for j, m in others if m['best'][0]}}
        if mine['best'][0] >= mine['need'] or (mine['need'] >= 4 and mine['best'][0] >= mine['need'] - 1):
            entry['status'] = 'match'
        elif entry['other_side_seen']:
            entry['status'] = 'other-team'
        elif not frames or mine['best'][0] == 0:
            entry['status'] = 'unseen'        # 목록이 안 보임(녹화가 전투부터 시작 등): 사람이 직접 대조
        else:
            entry['status'] = 'partial'
        out.append(entry)
    return out


def rule_g(sides):
    out = []
    uids = {i: (s['auto'] or {}).get('uid') for i, s in enumerate(sides, 1)}
    known = {u for u in uids.values() if u}
    if len(known) > 1:
        out.append({'rule': 'G1', 'problem': True, 'text': f'UID differs between sides {uids}'})
    starts = [(s['selection'] or {}).get('battle') for s in sides]
    if len({tuple(b) for b in starts if b}) < len([b for b in starts if b]):
        out.append({'rule': 'G2', 'problem': True, 'text': f'two sides point at the same battle {starts}'})
    return out


def report(item, run_d=True):
    sides = [load_side(item['id'], i) for i in range(1, len(item['payload']['runs']) + 1)]
    rep = {'rev': item['id'], 'kind': item.get('kind'), 'author': item.get('author_name'), 'B': rule_b(item)}
    rep['sides'] = []
    for i, s in enumerate(sides, 1):
        a = s['auto']
        # 합친 제출에서는 캐릭터가 기록 사이에 겹치지 않으므로(사용자) 「공유 쇼케이스가 이 전투 것인지」 확인 사유는 필요 없다 —
        # 쇼케이스 쪽은 머리글 이름으로 캐릭터에 바로 연결된다. 그 밖의 확인 사유와 문제는 그대로 둔다.
        reasons = [c for c in ((a or {}).get('check_reasons') or []) if not c.startswith('Shared showcase')]
        eff = None
        if a:
            eff = ('REJECT' if a.get('problems') else 'CHECK' if reasons or a.get('confidence', 0) < 90 else 'APPROVE')
        rep['sides'].append({'side': i, 'boss': item['payload']['runs'][i - 1].get('boss_name'),
                             'verdict': eff, 'tool_verdict': a and a.get('verdict'), 'confidence': a and a.get('confidence'),
                             'problems': a and a.get('problems'), 'check_reasons': reasons,
                             'battle': (s['selection'] or {}).get('battle'), 'uid': a and a.get('uid')})
    rep['D'] = rule_d(item, sides) if run_d else []
    rep['G'] = rule_g(sides)
    blockers = []
    if any(not s['auto'] for s in sides):
        blockers.append('a side has no analysis')
    if any(d['status'] in ('unknown', 'unseen', 'partial') for d in rep['D']):
        blockers.append('pre-battle team list not confirmed on some side (look yourself)')
    if any(s['verdict'] != 'APPROVE' for s in rep['sides']):
        blockers.append('a side is not APPROVE')
    rep['suggestion'] = ('REJECT-CANDIDATE' if any(x.get('problem') for x in rep['B'] + rep['G'])
                         or any(d['status'] == 'other-team' for d in rep['D']) else ('CHECK' if blockers else 'APPROVE-CANDIDATE'))
    rep['blockers'] = blockers
    p = os.path.join(WORK, f"combined_{item['id']}.json")
    json.dump(rep, open(p, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    return rep


def analyze(item, queue_path):
    import subprocess
    split = split_item(item)
    qp = os.path.join(WORK, f"queue_split_{item['id']}.json")
    json.dump(split, open(qp, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    for x in split:
        subprocess.run([sys.executable, '-u', os.path.join(HERE, 'run_queue.py'), '--worker', x['id'], '--queue', qp],
                       env=dict(os.environ, PYTHONIOENCODING='utf8'))


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) < 2 or a[0] not in ('analyze', 'report'):
        print(__doc__)
        sys.exit(1)
    qf = a[a.index('--queue') + 1] if '--queue' in a else os.path.join(WORK, 'queue_live.json')
    item = next(x for x in json.load(open(qf, encoding='utf8')) if x['id'] == a[1])
    if a[0] == 'analyze':
        analyze(item, qf)
    r = report(item)
    print(json.dumps({k: v for k, v in r.items() if k != 'sides'}, ensure_ascii=False, indent=1))
    for s in r['sides']:
        print(s)
