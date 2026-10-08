"""대기열의 건을 차례로 AI 없이 판정한다: 받기(prep) → 메뉴 구간(tabs, 파트마다) → 판정(auto_judge).
승인 · 거절 버튼은 누르지 않는다(판정 결과만 낸다).

python run_queue.py [rev_id ...] [--queue work/queue.json] [--fetch] [--limit N] [--claim] [--webhook question|review]
  rev_id 를 주지 않으면 대기열에서 아무도 잡지 않은 건을 오래된 순으로 --limit 개(기본 1)
  --fetch    먼저 mod_api.py queue 로 대기열을 새로 받는다
  --claim    판정 전에 「검토 중」 표시(mod_api.py claim)
  --webhook  결과를 디스코드로(question = config 의 question_webhook, review = discord_webhook)
결과: runs/<rev>/auto.json · auto_log.txt, 요약은 work/results.jsonl 에 한 줄씩"""
import os, sys, json, subprocess, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import RUNS, WORK, PY   # noqa: E402

ENV = dict(os.environ, PYTHONIOENCODING='utf8')


def sh(args, **kw):
    return subprocess.run([PY] + args, capture_output=True, text=True, encoding='utf8', errors='replace', env=kw.pop('env', ENV), **kw)


def mmss(t):
    return '?' if t is None else f'{int(t) // 60}:{int(t) % 60:02d}'


GP_NAME = {'revive': 'Castorice', 'firewall': 'Silver Wolf LV.999'}


WARN_BELOW = 90   # 이 밑이면 ⚠️(사용자, 2026-10-08)


def report(rev, a, item, action=None, reason=None):
    """디스코드 보고 글(영어, 링크는 < > 로 감싸 임베드를 끈다).
    맨 앞 표시: :check: 사이트에서 승인함 / ❌ 거절함 / ⚠️ 신뢰도 90% 미만. 판정 · 신뢰도, 신뢰도가 깎인 이유(-# 작은 글),
    문제, 거절 사유(넣은 글), 캐릭터마다 광추 · 중첩 · 성혼 대조(:check: 같음 / ✗ 다름 / ? 못 읽음), 보유 효과, 전투 결과, UID, 링크."""
    from judge import en_key
    p = item['payload']
    side = (p.get('runs') or [p])[0]
    url = side.get('video_url') or ''
    sh_t = a.get('showcase')
    vid = url.split('&t=')[0].split('?t=')[0]
    sep = '&' if '?' in vid else '?'
    sub = ' '.join(str(x) for x in (side.get('boss_name'), side.get('subcategory'), side.get('metric_value')) if x not in (None, ''))
    marks = (':check: ' if action == 'approve' else '❌ ' if action == 'reject' else '') + ('⚠️ ' if a['confidence'] < WARN_BELOW else '')
    did = {'approve': ' — approved on site', 'reject': ' — rejected on site'}.get(action, ' — not decided (human)')
    lines = [f"{marks}**{a['verdict']}** {(item.get('run_ids') or [rev])[0]} ({sub})  Confidence: {a['confidence']}%{did}"]
    lines += [f'-# −{n} {w}' for n, w in a.get('deductions', [])]
    lines += [f'- ⚠ CHECK: {x}' for x in a.get('check_reasons', [])]
    lines += [f'- {x}' for x in a['problems']]
    if reason:
        lines.append(f'Reason sent: {reason}')
    lines.append('Build:')
    for b in a.get('build') or []:
        s = b['submitted']
        lc = en_key(s['lc']) if s.get('lc') else '?'
        if b.get('lc_seen') is None:
            lc_part = f'Light Cone {lc} S{s["s"]} ✗ not shown'
        else:
            name_ok = ':check:' if (b.get('lc_match') or 0) >= 0.7 else '✗'
            if b.get('s_seen') is None:
                sup = f'S{s["s"]} ? unread'
            else:
                sup = f'S{b["s_seen"]} ' + (':check:' if b['s_seen'] == s['s'] else f'✗ (submitted S{s["s"]})')
            if name_ok == ':check:':
                lc_part = f'Light Cone {lc} :check: {sup} ({mmss(b.get("lc_t"))})'
            else:
                lc_part = f"Light Cone ✗ video '{b['lc_seen']}' (submitted {lc}) {sup} ({mmss(b.get('lc_t'))})"
        if b.get('e_t') is None:
            e_part = f'Eidolons E{s["e"]} ✗ not shown'
        elif b.get('e_seen') is None:
            e_part = f'Eidolons E{s["e"]} ? unread ({mmss(b.get("e_t"))})'
        else:
            gray = b.get('e_gray') or 0
            if b['e_seen'] == s['e']:
                mark = f'E{s["e"]} :check:'
            elif b['e_seen'] - gray <= s['e'] <= b['e_seen']:
                mark = f'E{s["e"]} :check: ({gray} uncertain node)'
            else:
                mark = f'E{b["e_seen"]} ✗ (submitted E{s["e"]})'
            e_part = f'Eidolons {mark} ({mmss(b.get("e_t"))})'
        lines.append(f"- {b['char']}: {lc_part} · {e_part}")
    g = a.get('gp')
    if g is not None:
        flags, seen, first = set(g.get('flags') or []), set(g.get('seen') or []), g.get('first') or {}
        parts = []
        for f in ('revive', 'firewall'):
            if f in flags and f in seen:
                parts.append(f'{GP_NAME[f]} submitted, triggered at {mmss(first.get(f))} :check:')
            elif f in flags:
                parts.append(f'{GP_NAME[f]} submitted, trigger not found ' + ('? (human check)' if f == 'revive' else '✗'))
            elif f in seen:
                parts.append(f'{GP_NAME[f]} not submitted, triggered at {mmss(first.get(f))} ✗')
        lines.append('Global Passive: ' + ('; '.join(parts) if parts else 'none submitted, none triggered :check:'))
    lines += [f'- {x}' for x in a['checks']]
    if a.get('uid'):
        lines.append(f"UID: {a['uid']}")
    if sh_t is not None:
        lines.append(f'Showcase: <{vid}{sep}t={int(sh_t)}>')
    lines.append(f'Video: <{url}>')
    lines.append(f'Review: <https://theherta.com/mod?review={rev}>')
    return '\n'.join(lines)


def main():
    a = sys.argv[1:]
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d
    qf = opt('--queue', os.path.join(WORK, 'queue.json'))
    if '--fetch' in a:
        print(sh([os.path.join(HERE, 'mod_api.py'), 'queue', '--out', qf]).stdout.strip())
    q = json.load(open(qf, encoding='utf8'))
    skip = {opt('--queue'), opt('--limit'), opt('--webhook')}
    revs = [x for x in a if not x.startswith('--') and x not in skip]
    if not revs:
        revs = [x['id'] for x in q if not x.get('claimed_by_name')][:int(opt('--limit', '1'))]
    byid = {x['id']: x for x in q}
    os.makedirs(WORK, exist_ok=True)
    for rev in revs:
        t0 = time.time()
        item = byid[rev]
        if '--claim' in a:
            sh([os.path.join(HERE, 'mod_api.py'), 'claim', rev])
        one = os.path.join(WORK, f'q_{rev}.json')
        json.dump([item], open(one, 'w', encoding='utf8'), ensure_ascii=False)
        env = dict(ENV, HQ_QUEUE=one)
        print(sh([os.path.join(HERE, 'prep.py'), rev], env=env).stdout.strip())
        d = os.path.join(RUNS, rev)
        vids = json.load(open(os.path.join(d, 'videos.json'), encoding='utf8'))
        for i in range(len(vids)):
            sh([os.path.join(HERE, 'tabs.py'), rev, str(i)])
        r = sh([os.path.join(HERE, 'auto_judge.py'), rev])
        open(os.path.join(d, 'auto_log.txt'), 'w', encoding='utf8').write(r.stdout + r.stderr[-3000:])
        res = json.load(open(os.path.join(d, 'auto.json'), encoding='utf8'))
        msg = report(rev, res, item)
        print(msg, f'\n({time.time() - t0:.0f}s)\n')
        with open(os.path.join(WORK, 'results.jsonl'), 'a', encoding='utf8') as f:
            f.write(json.dumps({'rev': rev, 'verdict': res['verdict'], 'confidence': res['confidence'],
                                'problems': res['problems'], 'seconds': round(time.time() - t0)}, ensure_ascii=False) + '\n')
        wh = opt('--webhook')
        if wh:
            sh([os.path.join(HERE, 'ask.py' if wh == 'question' else 'notify.py'), msg])


if __name__ == '__main__':
    main()
