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


def report(rev, a, item):
    """디스코드 보고 글(영어, 링크는 < > 로 감싸 임베드를 끈다)."""
    p = item['payload']
    side = (p.get('runs') or [p])[0]
    url = side.get('video_url') or ''
    sh_t = a.get('showcase')
    vid = url.split('&t=')[0].split('?t=')[0]
    sep = '&' if '?' in vid else '?'
    lines = [f"**{a['verdict']}** {(item.get('run_ids') or [rev])[0]}  Confidence: {a['confidence']}%"
             + ('  ⚠ LOW CONFIDENCE' if a['confidence'] <= 80 else '')]
    lines += [f'- {x}' for x in a['problems']]
    lines += [f'- {x}' for x in a['checks']]
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
