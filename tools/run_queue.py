"""대기열의 건을 차례로 AI 없이 판정한다: 받기(prep) → 메뉴 구간(tabs, 파트마다) → 판정(auto_judge).
승인 · 거절 버튼은 누르지 않는다(판정 결과만 낸다).

python run_queue.py [rev_id ...] [--queue work/queue.json] [--fetch] [--limit N] [--claim] [--webhook question|review]
  rev_id 를 주지 않으면 대기열에서 아무도 잡지 않은 건을 오래된 순으로 --limit 개(기본 1)
  --fetch    먼저 mod_api.py queue 로 대기열을 새로 받는다
  --claim    판정 전에 「검토 중」 표시(mod_api.py claim)
  --webhook  결과를 디스코드로(question = config 의 question_webhook, review = discord_webhook)
결과: runs/<rev>/auto.json · auto_log.txt, 요약은 work/results.jsonl 에 한 줄씩"""
import os, sys, re, json, subprocess, time
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import RUNS, WORK, PY   # noqa: E402
from webhook import post   # noqa: E402

ENV = dict(os.environ, PYTHONIOENCODING='utf8')


def sh(args, **kw):
    return subprocess.run([PY] + args, capture_output=True, text=True, encoding='utf8', errors='replace', env=kw.pop('env', ENV), **kw)


def mmss(t):
    return '?' if t is None else f'{int(t) // 60}:{int(t) % 60:02d}'


GP_NAME = {'revive': 'Castorice', 'firewall': 'Silver Wolf LV.999'}


WARN_BELOW = 90   # 이 밑이면 ⚠️(사용자, 2026-10-08)

# 디스코드 봇(discordbot_supabase.py)의 제출 임베드와 같은 색: 대기 = 노랑, 승인 = 초록, 거절 = 빨강
VERDICT_COLOR = {'APPROVE': 0x22c55e, 'REJECT': 0xef4444, 'CHECK': 0xfbbf24}
OK, BAD, UNSURE = '✓', '✗', '?'
ROW_MARK = {OK: '✅', BAD: '❌', UNSURE: '⚠️'}


def worst(levels):
    levels = set(levels)
    return BAD if BAD in levels else UNSURE if UNSURE in levels else OK


def clip(s, n=1024):
    return s if len(s) <= n else s[:n - 1] + '…'


def video_time(url, seconds):
    """Return a Discord markdown link to a video timestamp, or a plain label."""
    if seconds is None:
        return mmss(seconds)
    try:
        seconds = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return '?'
    label = mmss(seconds)
    if not url:
        return label
    video = url.split('&t=')[0].split('?t=')[0]
    sep = '&' if '?' in video else '?'
    return f'[{label}]({video}{sep}t={seconds})'


def link_inline_timestamps(text, url):
    """Link raw `at 297.2` timestamps in deductions and other generated text."""
    import re
    if not url:
        return text
    return re.sub(
        r'(?i)\bat\s+(\d+(?:\.\d+)?)',
        lambda match: f'at {video_time(url, match.group(1))}',
        text,
    )


def bullets(xs, url=''):
    return '\n'.join(f'• {link_inline_timestamps(x, url)}' for x in xs)


def side_name(side):
    """봇의 _review_side_name 꼴: 「MOC | Boss | Subcategory | 10 Cycles | 5L / 2S」."""
    mode = str(side.get('mode') or '').upper()
    metric = side.get('metric_value')
    if isinstance(metric, float) and metric.is_integer():
        metric = int(metric)
    parts = [mode, side.get('boss_name'), side.get('subcategory'),
             None if metric in (None, '') else f"{metric} {'Score' if mode == 'AS' else 'Cycles'}"]
    if side.get('total_limited_5star_count') is not None:
        parts.append(f"{side.get('total_limited_5star_count', 0)}L / {side.get('total_standard_5star_count', 0)}S")
    return ' | '.join(str(x) for x in parts if x) or 'Team'


def build_row(b, video_url=''):
    """캐릭터 한 명, 두 줄: 제출 빌드(봇의 fmt_team 꼴) / 영상 시각 링크 + 어긋난 것만 굵게.
    색 표시는 줄 앞 하나만(가장 나쁜 것 ❌ > ⚠️ > ✅), 맞는 항목은 조용히 둔다."""
    from judge import en_key
    from auto_judge import uncertain_eidolons
    s = b['submitted']
    lc = en_key(s['lc']) if s.get('lc') else ''
    head = f"**{b['char']}** (E{s['e']}S{s['s']}) — *{lc}*" if lc else f"**{b['char']}** (E{s['e']}) — *no Light Cone*"
    issues = []
    if b.get('lc_seen') is None:
        issues.append((BAD, 'LC not shown'))
    elif (b.get('lc_match') or 0) < 0.7:
        issues.append((BAD, f"video LC '{b['lc_seen']}'"))
    # 광추를 안 낀 제출: 영상도 「미장착」이면 맞고, 중첩은 보지 않는다
    if lc and b.get('lc_seen') is not None:
        if b.get('s_seen') is None:
            issues.append((UNSURE, 'S unreadable'))
        elif b['s_seen'] != s['s']:
            issues.append((BAD, f'video S{b["s_seen"]}'))
    if b.get('e_t') is None:
        issues.append((BAD, 'Eidolons not shown'))
    elif b.get('e_seen') is None:
        issues.append((UNSURE, 'Eidolons unreadable'))
    elif b['e_seen'] != s['e']:
        if s['e'] == b.get('e_alt'):
            issues.append((UNSURE, f'{uncertain_eidolons(b)} uncertain'))
        else:
            issues.append((BAD, f'video E{b["e_seen"]}'))
    times = []
    if b.get('lc_seen') is not None and b.get('lc_t') is not None:
        times.append(f'LC {video_time(video_url, b["lc_t"])}')
    if b.get('e_t') is not None:
        times.append(f'E {video_time(video_url, b["e_t"])}')
    tail = ' · '.join(times + [f'**{t}**' for _, t in issues])
    return f'{ROW_MARK[worst(m for m, _ in issues)]} {head}\n└ {tail}'


def gp_lines(g, video_url=''):
    flags, seen, first = set(g.get('flags') or []), set(g.get('seen') or []), g.get('first') or {}
    out = []
    for f in ('revive', 'firewall'):
        if f in flags and f in seen:
            out.append(f'{ROW_MARK[OK]} {GP_NAME[f]} {video_time(video_url, first.get(f))}')
        elif f in flags:
            out.append(f'{ROW_MARK[UNSURE]} {GP_NAME[f]} **not found**' if f == 'revive'
                       else f'{ROW_MARK[BAD]} {GP_NAME[f]} **not triggered**')
        elif f in seen:
            out.append(f'{ROW_MARK[BAD]} {GP_NAME[f]} **not submitted** {video_time(video_url, first.get(f))}')
    return out or [f'{ROW_MARK[OK]} None']


def report(rev, a, item, action=None, reason=None):
    """디스코드 보고 임베드(영어). 디스코드 봇의 제출 임베드(_build_review_embed)와 같은 짜임:
    제목 = 맨 앞 표시(✅ 사이트에서 승인함 / ❌ 거절함 / ⚠️ 신뢰도 90% 미만) + 판정 · 신뢰도, 제목 링크 = 검토 페이지, 색 = 판정.
    설명 = 제출자 · 시즌 · 처리 상태 · 거절 사유(넣은 글). 칸 = 사람 확인 · 문제, 편성(캐릭터마다 광추 · 중첩 · 성혼 대조),
    보유 효과, 전투 결과, UID, 신뢰도가 깎인 이유, 링크. 바닥글 = 런 ID · 검토 ID."""
    p = item['payload']
    sides = p.get('runs') or [p]
    side = sides[0]
    url = side.get('video_url') or ''
    sh_t = a.get('showcase')
    vid = url.split('&t=')[0].split('?t=')[0]
    sep = '&' if '?' in vid else '?'
    review = f'https://theherta.com/mod?review={rev}'
    marks = ('✅ ' if action == 'approve' else '❌ ' if action == 'reject' else '') + ('⚠️ ' if a['confidence'] < WARN_BELOW else '')
    status = {'approve': 'Approved on site', 'reject': 'Rejected on site'}.get(action, 'Not decided (human)')

    desc = [f"**Author:** {side.get('author_name') or p.get('author_name') or '—'}",
            f"**Season:** {side.get('season') or p.get('season') or '—'}",
            f'**Status:** {status}']
    if reason:
        desc.append(f"**{'Reason sent' if action else 'Suggested reject reason (not sent)'}:** {reason}")

    fields = []

    def add(name, lines, inline=False):
        if lines:
            fields.append({'name': clip(name, 256), 'value': clip('\n'.join(lines) if isinstance(lines, list) else lines),
                           'inline': inline})

    add('⚠️ Needs human check', bullets(a.get('check_reasons') or [], url))
    add('❌ Problems', bullets(a['problems'], url))
    # 합친 제출(여러 런)은 런마다 칸을 따로 만든다: 한 칸은 1024자까지라 캐릭터 열둘이 한 칸이면 잘린다.
    # 빌드 목록은 런마다 캐릭터 순서(p1~p4)대로 이어져 있다
    builds = list(a.get('build') or [])
    pos = 0
    for si, sd in enumerate(sides):
        n = sum(1 for j in range(1, 5) if sd.get(f'p{j}_char'))
        rows = [build_row(b, sd.get('video_url') or url) for b in builds[pos:pos + n]]
        pos += n
        title = side_name(sd) + (f' ({si + 1}/{len(sides)})' if len(sides) > 1 else '')
        vurl = sd.get('video_url') or ''
        if len(sides) > 1 and vurl:
            title += f'  ·  starts {mmss(int(float(re.search(r"[?&]t=(\d+)", vurl).group(1))) if re.search(r"[?&]t=(\d+)", vurl) else 0)}'
        add(title, rows or ['—'])
    only1 = ' — run 1 only' if len(sides) > 1 else ''
    # 짧은 값만 나란히(긴 글을 칸에 넣으면 좁은 칸에서 줄이 마구 꺾인다)
    if a.get('gp') is not None:
        add('Global Passive' + only1, gp_lines(a['gp'], url), inline=True)
    add('UID', f"`{a['uid']}`" if a.get('uid') else f'{ROW_MARK[UNSURE]} **not readable**', inline=True)
    add('Battle (HUD)' + only1, bullets(a['checks'], url), inline=all(len(x) <= 40 for x in a['checks']))
    ded = a.get('deductions', [])
    add(f"Deductions (−{sum(n for n, _ in ded)})", [link_inline_timestamps(f'−{n} {w}', url) for n, w in ded])
    links = [f'[Video]({url})'] if url else []
    if sh_t is not None:
        links.append(f'[Showcase {mmss(sh_t)}]({vid}{sep}t={int(sh_t)})')
    links.append(f'[Review]({review})')
    add('Links', ' · '.join(links))

    run_id = (item.get('run_ids') or [rev])[0]
    return {'title': clip(f"{marks}{a['verdict']} · {a['confidence']}% confidence", 256), 'url': review,
            'description': clip('\n'.join(desc), 4096), 'color': VERDICT_COLOR.get(a['verdict'], 0x60a5fa),
            'fields': fields, 'footer': {'text': f'ID: {run_id}  •  Review ID: {rev}'},
            'timestamp': datetime.now(timezone.utc).isoformat()}


def as_text(e):
    """터미널에 찍을 임베드 글."""
    out = [e['title'], e['description']]
    for f in e['fields']:
        out += [f"[{f['name']}]", f['value']]
    return '\n'.join(out + [e['footer']['text']])


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
        d = os.path.join(RUNS, rev)
        pl = item.get('payload') or {}
        n_runs = len(pl.get('runs') or [1])
        if item.get('kind') == 'multi' or n_runs > 1:
            # 합친 제출(한 건에 런 여럿)은 검토하지 않고 곧바로 CHECK(사용자, 2026-10-09): 전투 결과 · 보유 효과를 런마다 보지 못한다
            os.makedirs(d, exist_ok=True)
            json.dump(item, open(os.path.join(d, 'review.json'), 'w', encoding='utf8'), ensure_ascii=False, indent=1)
            json.dump({'verdict': 'CHECK', 'confidence': 0, 'problems': [], 'problem_items': [], 'checks': [], 'build': [],
                       'check_reasons': [f'combined submission ({n_runs} runs in one item): not reviewed by the tool'], 'deductions': [],
                       'uid': None, 'gp': None, 'timing': {}, 'stop_loop': False},
                      open(os.path.join(d, 'auto.json'), 'w', encoding='utf8'), ensure_ascii=False, indent=1)
            res = json.load(open(os.path.join(d, 'auto.json'), encoding='utf8'))
            embed = report(rev, res, item)
            print(as_text(embed), flush=True)
            wh = opt('--webhook')
            if wh:
                try:
                    post('question_webhook' if wh == 'question' else 'discord_webhook', {'embeds': [embed], 'allowed_mentions': {'parse': []}})
                except Exception as e:
                    print('webhook failed:', e)
            continue
        one = os.path.join(WORK, f'q_{rev}.json')
        json.dump([item], open(one, 'w', encoding='utf8'), ensure_ascii=False)
        env = dict(ENV, HQ_QUEUE=one)
        print(sh([os.path.join(HERE, 'prep.py'), rev], env=env).stdout.strip())
        tl_p = os.path.join(d, 'too_long.json')
        if os.path.exists(tl_p):
            # 20분 넘는 영상: 받지 않고 곧바로 사람 확인(사용자, 2026-10-09)
            mins = ', '.join(f"{x['seconds'] / 60:.0f} min" for x in json.load(open(tl_p, encoding='utf8')))
            json.dump({'verdict': 'CHECK', 'confidence': 0, 'problems': [], 'problem_items': [], 'checks': [], 'build': [],
                       'check_reasons': [f'video longer than 20 minutes ({mins}), not downloaded'], 'deductions': [],
                       'uid': None, 'gp': None, 'timing': {}, 'stop_loop': False},
                      open(os.path.join(d, 'auto.json'), 'w', encoding='utf8'), ensure_ascii=False, indent=1)
        elif any(not os.path.exists(os.path.join(d, v['file'])) or os.path.getsize(os.path.join(d, v['file'])) == 0
                 for v in json.load(open(os.path.join(d, 'videos.json'), encoding='utf8'))):
            # 영상을 못 받았다(비공개 · 삭제 · 지역 제한 등): 판정하지 않고 사람 확인으로(rev_1e5ddxv)
            why = ''
            for i in range(len(json.load(open(os.path.join(d, 'videos.json'), encoding='utf8')))):
                ip = os.path.join(d, f'video{i}.info')
                if os.path.exists(ip):
                    m = re.findall(r'ERROR: (.*)', open(ip, encoding='utf8', errors='replace').read())
                    why = (m[-1] if m else '')[:160]
            json.dump({'verdict': 'CHECK', 'confidence': 0, 'problems': [], 'problem_items': [], 'checks': [], 'build': [],
                       'check_reasons': ['video could not be downloaded' + (f' ({why})' if why else '')], 'deductions': [],
                       'uid': None, 'gp': None, 'timing': {}, 'stop_loop': False},
                      open(os.path.join(d, 'auto.json'), 'w', encoding='utf8'), ensure_ascii=False, indent=1)
        else:
            vids = json.load(open(os.path.join(d, 'videos.json'), encoding='utf8'))
            for i in range(len(vids)):
                sh([os.path.join(HERE, 'tabs.py'), rev, str(i)])
            r = sh([os.path.join(HERE, 'auto_judge.py'), rev])
            open(os.path.join(d, 'auto_log.txt'), 'w', encoding='utf8').write(r.stdout + r.stderr[-3000:])
        if not os.path.exists(os.path.join(d, 'auto.json')):
            # 영상을 못 받는 등으로 판정이 안 됐다 — 이 건만 건너뛰고 다음 건으로(auto_log.txt 에 까닭)
            print(f'{rev}: no verdict (see auto_log.txt)\n', flush=True)
            continue
        res = json.load(open(os.path.join(d, 'auto.json'), encoding='utf8'))
        embed = report(rev, res, item)
        print(as_text(embed), f'\n({time.time() - t0:.0f}s)\n')
        with open(os.path.join(WORK, 'results.jsonl'), 'a', encoding='utf8') as f:
            f.write(json.dumps({'rev': rev, 'verdict': res['verdict'], 'confidence': res['confidence'],
                                'problems': res['problems'], 'seconds': round(time.time() - t0)}, ensure_ascii=False) + '\n')
        wh = opt('--webhook')
        if wh:
            try:
                post('question_webhook' if wh == 'question' else 'discord_webhook',
                     {'embeds': [embed], 'allowed_mentions': {'parse': []}})
            except Exception as e:
                print('webhook failed:', e)


if __name__ == '__main__':
    main()
