"""팀 순서 CHECK 만 모은 HTML 보고서(사람이 한꺼번에 볼 것). 한 건 요약 카드는 summary_html 과 같은 모양.
대상: 지금 사이트 대기열에 있고, auto.json 이 CHECK 이며 「First position …」 사유가 있고 확실한 문제(problems)는 없는 건.
합친 제출(combined)은 side 별 폴더(rev_<id>_<n>)가 팀 순서 사유를 가지면 그 건 전체를 올린다(카드는 그 side 의 것).
python team_order_report.py [--loop 300]   → work/team_order_check.html (사이트에서 처리된 건은 다음 갱신 때 빠진다)"""
import os, sys, json, time, re
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import RUNS, WORK        # noqa: E402
import summary_html, mod_api        # noqa: E402

OUT = os.path.join(WORK, 'team_order_check.html')


def pending_ids():
    try:
        items, _ = mod_api.queue(os.path.join(WORK, 'queue_team.json'))
    except BaseException:
        items = json.load(open(os.path.join(WORK, 'queue_team.json'), encoding='utf8'))
    return {x['id']: x for x in items}


def team_order_revs(pending):
    out = []
    for rev in pending:
        cands = [rev] + [d for d in (f'{rev}_{i}' for i in (1, 2, 3)) if os.path.isdir(os.path.join(RUNS, d))]
        for c in cands:
            p = os.path.join(RUNS, c, 'auto.json')
            if not os.path.exists(p):
                continue
            a = json.load(open(p, encoding='utf8'))
            if a.get('verdict') == 'CHECK' and not a.get('problems') and any(str(r).startswith('First position') for r in a.get('check_reasons') or []):
                out.append(c)
    return out


def build():
    pending = pending_ids()
    revs = team_order_revs(pending)
    entries = [e for e in (summary_html.load(r) for r in revs) if e]
    # 카드에는 팀 순서 사유가 맨 앞에 보이도록 정렬: 제출 시각 오래된 순
    entries.sort(key=lambda e: (pending.get(e['rev'].split('_')[0] + '_' + e['rev'].split('_')[1], {}).get('created_at') or '') if e['rev'].count('_') >= 2 else (pending.get(e['rev'], {}).get('created_at') or ''))
    text = summary_html.page(entries, title='Team order CHECK')
    os.makedirs(WORK, exist_ok=True)
    open(OUT, 'w', encoding='utf8').write(text)
    return len(entries), [e['rev'] for e in entries]


if __name__ == '__main__':
    if '--loop' in sys.argv:
        gap = int(sys.argv[sys.argv.index('--loop') + 1])
        while True:
            try:
                n, r = build()
                print(time.strftime('%H:%M:%S'), n, 'records', flush=True)
            except Exception as ex:
                print('error', repr(ex)[:200], flush=True)
            time.sleep(gap)
    else:
        n, r = build()
        print(n, r)
