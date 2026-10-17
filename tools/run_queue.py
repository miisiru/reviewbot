"""대기열의 건을 차례로 AI 없이 판정한다: 받기(prep) → 영상 구간 나누기 · 건의 전투 · 쇼케이스 고르기(segment_pipeline)
→ 고른 쇼케이스의 메뉴 구간(tabs) → 판정(auto_judge). 승인 · 거절 버튼은 누르지 않는다(판정 결과만 낸다).

python run_queue.py [rev_id ...] [--queue work/queue.json] [--fetch] [--limit N] [--claim] [--webhook question|review]
  rev_id 를 주지 않으면 대기열에서 아무도 잡지 않은 건을 오래된 순으로 --limit 개(기본 1)
  --fetch    먼저 mod_api.py queue 로 대기열을 새로 받는다
  --claim    판정 전에 「검토 중」 표시(mod_api.py claim)
  --webhook  결과를 디스코드로(question = config 의 question_webhook, review = discord_webhook)
  --jobs N        한꺼번에 분석할 건 수(건마다 따로 프로세스, 기본 1)
  --downloads M   분석 자리를 기다리는 건들의 영상을 미리 받는 수(기본 0 = 분석하면서 받는다). 병렬 예: --jobs 3 --downloads 3
결과: runs/<rev>/auto.json · auto_log.txt, 요약은 work/results.jsonl 에 한 줄씩

곧바로 CHECK 로 보내는 건(분석하지 않는다): 합친 제출(런 여럿), 같은 영상이 다른 건에도 있는데 이 건 링크에 타임스탬프가 없는 것
(어느 전투인지 알 수 없다), 20분 넘는 영상(두 건 이상이 같은 영상을 가리키면 한 시간까지 분석), 못 받은 영상.
타임스탬프 링크는 그 시각이 든 전투를 골라 분석한다(segment_pipeline.select_battle).
config.json 에 "legacy_gates": true 를 두면 옛 규칙(타임스탬프 링크 · 한 영상에 건이 여럿이면 무조건 CHECK)으로 돌아간다."""
import os, sys, re, json, subprocess, time
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import RUNS, WORK, PY, config   # noqa: E402
from webhook import post   # noqa: E402
from report import report, as_text, video_key, check_result, attach_sheets   # noqa: E402
import video_policy   # noqa: E402

ENV = dict(os.environ, PYTHONIOENCODING='utf8')


def sh(args, **kw):
    return subprocess.run([PY] + args, capture_output=True, text=True, encoding='utf8', errors='replace', env=kw.pop('env', ENV), **kw)


def save(path, value):
    json.dump(value, open(path, 'w', encoding='utf8'), ensure_ascii=False, indent=1)


def gate_reason(rev, item, q, legacy):
    """분석하지 않고 곧바로 CHECK 로 보낼 까닭. 없으면 None."""
    pl = item.get('payload') or {}
    n_runs = len(pl.get('runs') or [1])
    if item.get('kind') == 'multi' or n_runs > 1:
        # 합친 제출(한 건에 런 여럿)은 런마다 나누는 방침(검토 결과를 어떻게 합칠지)이 정해지기 전까지 검토하지 않는다(사용자, 2026-10-09)
        return f'combined submission ({n_runs} runs in one item): not reviewed by the tool'
    run0 = (pl.get('runs') or [pl])[0]
    u0 = run0.get('video_url') or ''
    tm = re.search(r'[?&#](?:t|start)=(\d+)', u0)
    stamped = bool(tm and int(tm.group(1)) > 0)
    if stamped and legacy:
        return f'video link has a timestamp (t={tm.group(1)}): the video holds several runs, not reviewed by the tool'
    k0 = video_key(u0)
    same = [x['id'] for x in q if x['id'] != rev and k0 and any(video_key(r2.get('video_url') or '') == k0
            for r2 in ((x.get('payload') or {}).get('runs') or [x.get('payload') or {}]))]
    if same and (legacy or not stamped):
        # 타임스탬프가 없으면 한 영상의 여러 기록 중 어느 전투인지 알 수 없다(타임스탬프가 있으면 그 전투를 고른다)
        return f'the same video is on other queue items ({", ".join(same[:3])}): several runs in one video and no timestamp on this link, not reviewed by the tool'
    return None


def write_check(d, rev, item, reason, **extra):
    os.makedirs(d, exist_ok=True)
    save(os.path.join(d, 'review.json'), item)
    res = dict(check_result(reason), **extra)
    save(os.path.join(d, 'auto.json'), res)
    return res


def download_error(d):
    why = ''
    vids = json.load(open(os.path.join(d, 'videos.json'), encoding='utf8'))
    for i in range(len(vids)):
        ip = os.path.join(d, f'video{i}.info')
        if os.path.exists(ip):
            m = re.findall(r'ERROR: (.*)', open(ip, encoding='utf8', errors='replace').read())
            why = (m[-1] if m else '')[:160]
    return why


def analyze(rev, item, d, env):
    """받기 → 구간 나누기 → 판정. 판정 결과(dict)를 auto.json 에도 쓴다. 분석이 막히면 CHECK(까닭)."""
    pl = item.get('payload') or {}
    run0 = (pl.get('runs') or [pl])[0]
    out = sh([os.path.join(HERE, 'prep.py'), rev], env=env)
    print(out.stdout.strip())
    tl_p = os.path.join(d, 'too_long.json')
    if os.path.exists(tl_p):
        # 20분 넘는 영상: 받지 않고 곧바로 사람 확인. 두 건 이상이 같은 영상을 가리키면 한 시간까지는 분석한다(video_policy)
        blocked = json.load(open(tl_p, encoding='utf8'))
        reasons = '; '.join(dict.fromkeys(x.get('reason') or f"video longer than 20 minutes ({x['seconds'] / 60:.0f} min), not downloaded" for x in blocked))
        extra = {'long_video_waiting': [x['key'] for x in blocked]} if all(x.get('deferred') for x in blocked) else {}
        return write_check(d, rev, item, reasons, **extra)
    vids = json.load(open(os.path.join(d, 'videos.json'), encoding='utf8'))
    if any(not os.path.exists(os.path.join(d, v['file'])) or os.path.getsize(os.path.join(d, v['file'])) == 0 for v in vids):
        # 영상을 못 받았다(비공개 · 삭제 · 지역 제한 등): 판정하지 않고 사람 확인으로(rev_1e5ddxv)
        why = download_error(d)
        return write_check(d, rev, item, 'video could not be downloaded' + (f' ({why})' if why else ''))
    from segment_pipeline import prepare, extract_build
    from battle_sheets import generate
    side = {k: v for k, v in pl.items() if k != 'runs'}
    side.update(run0)
    try:
        selection = prepare(Path(d), side, vids)
        try:
            generate(Path(d), vids, selection)
        except (OSError, ValueError, RuntimeError) as exc:
            print(f'{rev}: battle sheets unavailable: {exc}; continuing analysis', flush=True)
        extract_build(Path(d), vids, selection, env)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        # 영상 구간을 못 정했다(타임스탬프가 가리키는 전투가 없다 · 쇼케이스가 애매하다 …): 사람 확인
        return write_check(d, rev, item, str(exc))
    r = sh([os.path.join(HERE, 'auto_judge.py'), rev], env=env)
    open(os.path.join(d, 'auto_log.txt'), 'w', encoding='utf8').write(r.stdout + r.stderr[-3000:])
    if not os.path.exists(os.path.join(d, 'auto.json')):
        return None
    return json.load(open(os.path.join(d, 'auto.json'), encoding='utf8'))


def send(wh, embed, d, rev):
    if not wh:
        return
    try:
        payload = {'embeds': [embed], 'allowed_mentions': {'parse': []}}
        # 그 사람의 보고 꼴(run_local 과 같다): 임베드 아래에 고른 쇼케이스 시트 + 전투 처음 · 끝 쪽 그림을 묶어 붙인다.
        # 시트가 없는 건(곧바로 CHECK)은 attach_sheets 가 그림 없이 돌려준다
        payload, files = attach_sheets(d, payload)
        post('question_webhook' if wh == 'question' else 'discord_webhook', payload, files=files)
    except Exception as e:
        print('webhook failed:', e)


def run_item(rev, item, d):
    """한 건을 처음부터 끝까지(받기 → 구간 나누기 → 판정). 판정 결과(dict)를 돌려주고 auto.json 에도 쓴다. 판정이 안 되면 None."""
    os.makedirs(d, exist_ok=True)
    one = os.path.join(WORK, f'q_{rev}.json')
    json.dump([item], open(one, 'w', encoding='utf8'), ensure_ascii=False)
    env = dict(ENV, HQ_QUEUE=one)
    for name in ('auto.json', 'auto_cache.json', 'segment_selection.json'):
        Path(d, name).unlink(missing_ok=True)       # 받은 영상은 두고, 지난 판정 · 구간 고르기는 버린다
    return analyze(rev, item, d, env)


def prefetch(rev, item, d):
    """영상만 미리 받는다(prep.py). 분석 자리가 나기 전에 다음 건들의 영상을 받아 두는 용도 — 받은 영상은 분석 때 그대로 쓴다."""
    os.makedirs(d, exist_ok=True)
    one = os.path.join(WORK, f'q_{rev}.json')
    json.dump([item], open(one, 'w', encoding='utf8'), ensure_ascii=False)
    r = sh([os.path.join(HERE, 'prep.py'), rev], env=dict(ENV, HQ_QUEUE=one))
    open(os.path.join(d, 'prefetch.log'), 'w', encoding='utf8').write(r.stdout + r.stderr[-2000:])


def finish(rev, item, d, res, secs, wh):
    """판정이 나온 건을 보고한다(보고 · 기록 · 웹후크는 한 곳에서 차례로 — 병렬이어도 섞이지 않는다)."""
    if res is None:
        print(f'{rev}: no verdict (see auto_log.txt)\n', flush=True)
        return
    video_policy.mark_result(item, res)
    embed = report(rev, res, item)
    print(as_text(embed), f'\n({secs:.0f}s)\n', flush=True)
    with open(os.path.join(WORK, 'results.jsonl'), 'a', encoding='utf8') as f:
        f.write(json.dumps({'rev': rev, 'verdict': res['verdict'], 'confidence': res['confidence'],
                            'problems': res['problems'], 'seconds': round(secs)}, ensure_ascii=False) + '\n')
    send(wh, embed, d, rev)


def source_key(item, rev):
    """같은 영상을 가리키는 건은 같은 열쇠. 같은 영상은 받기 · 구간 나누기 결과(work/video_cache)를 함께 쓰므로 한 번에 하나만 돌린다."""
    pl = item.get('payload') or {}
    return video_key(((pl.get('runs') or [pl])[0]).get('video_url') or '') or rev


def run_parallel(revs, byid, q, legacy, jobs, downloads, claim, wh, qf):
    """여러 건을 한꺼번에: 영상 받기(최대 downloads 개)와 분석(최대 jobs 개)이 겹쳐 돈다.
    분석은 건마다 따로 프로세스(run_queue.py --worker)로 돌려 서로의 전역 상태를 건드리지 않는다.
    같은 영상을 가리키는 건은 앞 건이 끝난 뒤에 시작한다(같은 캐시를 동시에 쓰지 않게)."""
    import subprocess as sp
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    todo = deque()
    for rev in revs:
        item = byid[rev]
        d = os.path.join(RUNS, rev)
        why = gate_reason(rev, item, q, legacy)
        if why:                                   # 곧바로 CHECK 인 건은 분석 없이 바로 보고
            res = write_check(d, rev, item, why)
            embed = report(rev, res, item)
            print(as_text(embed), flush=True)
            send(wh, embed, d, rev)
        else:
            todo.append(rev)
    ex_dl = ThreadPoolExecutor(max(1, downloads))
    ex_run = ThreadPoolExecutor(max(1, jobs))
    procs = {}
    busy = set()                 # 받는 중 · 분석 중인 영상 열쇠
    dl, run = {}, {}             # future → rev
    ready = deque()              # 받기가 끝나 분석을 기다리는 건

    def work(rev):
        t0 = time.time()
        d = os.path.join(RUNS, rev)
        if claim:
            sh([os.path.join(HERE, 'mod_api.py'), 'claim', rev])
        os.makedirs(d, exist_ok=True)
        log = open(os.path.join(d, 'worker.log'), 'w', encoding='utf8')
        p = sp.Popen([PY, '-u', os.path.abspath(__file__), '--worker', rev, '--queue', qf],
                     stdout=log, stderr=sp.STDOUT, env=ENV)
        procs[rev] = p
        p.wait()
        log.close()
        ap = os.path.join(d, 'auto.json')
        res = json.load(open(ap, encoding='utf8')) if p.returncode == 0 and os.path.exists(ap) else None
        return res, time.time() - t0

    try:
        while todo or dl or run or ready:
            # 받기: 자리가 있고 열쇠가 비어 있는 다음 건
            for rev in list(todo):
                k = source_key(byid[rev], rev)
                if k in busy:
                    continue
                if downloads > 0:
                    if len(dl) >= downloads:
                        break
                    todo.remove(rev)
                    busy.add(k)
                    print(f'{rev}: downloading', flush=True)
                    dl[ex_dl.submit(prefetch, rev, byid[rev], os.path.join(RUNS, rev))] = rev
                else:          # 미리 받지 않으면 분석 프로세스가 직접 받는다
                    todo.remove(rev)
                    busy.add(k)
                    ready.append(rev)
            # 분석: 받기가 끝난 건
            while ready and len(run) < jobs:
                rev = ready.popleft()
                print(f'{rev}: analyzing', flush=True)
                run[ex_run.submit(work, rev)] = rev
            pending = set(dl) | set(run)
            if not pending:
                continue
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                if fut in dl:
                    rev = dl.pop(fut)
                    try:
                        fut.result()
                    except Exception as e:
                        print(f'{rev}: download step failed: {e}', flush=True)
                    ready.append(rev)
                else:
                    rev = run.pop(fut)
                    res, secs = fut.result()
                    busy.discard(source_key(byid[rev], rev))
                    finish(rev, byid[rev], os.path.join(RUNS, rev), res, secs, wh)
    finally:
        for p in procs.values():
            if p.poll() is None:
                p.terminate()
        ex_dl.shutdown(wait=False, cancel_futures=True)
        ex_run.shutdown(wait=False, cancel_futures=True)


def main():
    a = sys.argv[1:]
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d
    qf = opt('--queue', os.path.join(WORK, 'queue.json'))
    if '--worker' in a:                          # 병렬 실행이 건마다 띄우는 분석 프로세스: 판정 결과는 runs/<rev>/auto.json
        rev = opt('--worker')
        item = next(x for x in json.load(open(qf, encoding='utf8')) if x['id'] == rev)
        res = run_item(rev, item, os.path.join(RUNS, rev))
        sys.exit(0 if res is not None else 3)
    if '--fetch' in a:
        print(sh([os.path.join(HERE, 'mod_api.py'), 'queue', '--out', qf]).stdout.strip())
    q = json.load(open(qf, encoding='utf8'))
    legacy = bool(config().get('legacy_gates'))
    registry = video_policy.register_items([x for x in q if isinstance(x.get('payload'), dict)])
    skip = {opt('--queue'), opt('--limit'), opt('--webhook'), opt('--jobs'), opt('--downloads')}
    revs = [x for x in a if not x.startswith('--') and x not in skip]
    if not revs:
        revs = [x['id'] for x in q if not x.get('claimed_by_name')][:int(opt('--limit', '1'))]
        # 길이가 20분을 넘어 기다리던 건이 두 번째 기록을 만나 분석할 수 있게 됐으면 앞에 둔다
        ready = [rid for rid, rec in registry['submissions'].items()
                 if video_policy.eligible(rec, registry) and any(x['id'] == rid for x in q) and rid not in revs]
        revs = ready + revs
    byid = {x['id']: x for x in q}
    os.makedirs(WORK, exist_ok=True)
    jobs, downloads = int(opt('--jobs', '1')), int(opt('--downloads', '0'))
    wh = opt('--webhook')
    if jobs > 1 or downloads > 0:
        run_parallel(revs, byid, q, legacy, jobs, downloads, '--claim' in a, wh, qf)
        return
    for rev in revs:
        t0 = time.time()
        item = byid[rev]
        if '--claim' in a:
            sh([os.path.join(HERE, 'mod_api.py'), 'claim', rev])
        d = os.path.join(RUNS, rev)
        why_skip = gate_reason(rev, item, q, legacy)
        if why_skip:
            res = write_check(d, rev, item, why_skip)
            embed = report(rev, res, item)
            print(as_text(embed), flush=True)
            send(wh, embed, d, rev)
            continue
        finish(rev, item, d, run_item(rev, item, d), time.time() - t0, wh)


if __name__ == '__main__':
    main()
