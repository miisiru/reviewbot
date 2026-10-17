"""Local Discord report formatting. No dashboard access."""
import os, sys, re, json, subprocess, time
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
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


def timestamp_link(url, seconds, label=None):
    if seconds is None:
        return label or '?'
    try:
        seconds = max(0, int(float(seconds)))
    except (TypeError, ValueError, OverflowError):
        return label or '?'
    label = label or mmss(seconds)
    if not url:
        return label
    url = re.sub(r'(youtu\.be/[^?&#/]+)&', r'\1?', url, count=1)
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query)
             if key not in ('t', 'start', 'time_continue')]
    if (parts.hostname or '').endswith('bilibili.com'):
        query = [(key, value) for key, value in query if key == 'p']
    query.append(('t', str(seconds)))
    target = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
    return f'[{label}]({target})'


def video_time(url, seconds):
    return timestamp_link(url, seconds)


def local_play_url(rev, index=None):
    if re.fullmatch(r'rev_[A-Za-z0-9]+', rev or ''):
        return ''          # 사이트 대기열 건은 로컬 재생 링크를 만들지 않는다(로컬 입력 전용)
    token_file = Path(WORK) / 'folder_opener_token.txt'
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', rev or '') or not token_file.is_file():
        return ''
    token = token_file.read_text(encoding='utf8').strip()
    if not token:
        return ''
    query = {'key': token}
    if type(index) is int and index >= 0:
        query['vid'] = index
    return f'http://127.0.0.1:8765/runs/{rev}/play?' + urlencode(query)


def playback_sources(rev, analysis, side):
    folder = Path(RUNS) / rev
    try:
        videos = json.loads((folder / 'videos.json').read_text(encoding='utf8'))
    except (OSError, ValueError):
        videos = []
    if not isinstance(videos, list):
        videos = []
    selection = analysis.get('segments') or {}
    battle = selection.get('battle_index')
    if type(battle) is not int:
        battle = next((i for i, video in enumerate(videos) if video.get('role') == 'battle'), None)
    if battle is None:
        battle = next((i for i, video in enumerate(videos) if video.get('run_part')), 0)
    build = selection.get('build_index')
    if type(build) is not int:
        build = next((i for i, video in enumerate(videos) if video.get('role') == 'showcase'), battle)

    def online(index, fallback):
        if 0 <= index < len(videos):
            video = videos[index]
            return video.get('url') or video.get('src') or fallback
        return fallback

    fallback = side.get('video_url') or ''
    local_input = bool(side.get('local_battle_video') or side.get('local_showcase_video'))
    return {
        'battle_online': online(battle, '' if local_input else fallback),
        'build_online': online(build, '' if local_input else fallback),
        'battle_local': local_play_url(rev, battle),
        'build_local': local_play_url(rev, build),
    }


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


def build_row(b, video_url='', local_url=''):
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
    elif b.get('lc_uncertain'):
        issues.append((UNSURE, 'LC uncertain'))      # 추가 표본으로도 제목을 못 정했다(auto_judge 가 사람 확인 사유로 올린다)
    elif (b.get('lc_match') or 0) < 0.7:
        issues.append((BAD, f"video LC '{b['lc_seen']}'"))
    # 광추를 안 낀 제출: 영상도 「미장착」이면 맞고, 중첩은 보지 않는다
    if lc and b.get('lc_seen') is not None:
        if b.get('s_uncertain'):
            issues.append((UNSURE, 'S uncertain'))
        elif b.get('s_seen') is None:
            issues.append((UNSURE, 'S unreadable'))
        elif b['s_seen'] != s['s']:
            issues.append((BAD, f'video S{b["s_seen"]}'))
    if b.get('e_t') is None:
        issues.append((BAD, 'Eidolons not shown'))
    elif b.get('e_uncertain'):
        issues.append((UNSURE, 'Eidolons uncertain'))
    elif b.get('e_seen') is None:
        issues.append((UNSURE, 'Eidolons unreadable'))
    elif b['e_seen'] != s['e']:
        if s['e'] == b.get('e_alt'):
            issues.append((UNSURE, f'{uncertain_eidolons(b)} uncertain'))
        else:
            issues.append((BAD, f'video E{b["e_seen"]}'))
    evidence = []
    if b.get('lc_seen') is not None and b.get('lc_t') is not None:
        evidence.append(('LC', b['lc_t']))
    if b.get('e_t') is not None:
        evidence.append(('E', b['e_t']))
    lines = [f'{ROW_MARK[worst(m for m, _ in issues)]} {head}']
    labelled = bool(video_url and local_url)      # 온라인 · 로컬 링크가 둘 다 있을 때만 앞에 이름을 붙인다
    for prefix, target in (('Onl', video_url), ('Loc', local_url)):
        if target and evidence:
            lines.append((prefix if labelled else '') + '└ ' + ' · '.join(
                f'{kind} {video_time(target, timestamp)}'
                for kind, timestamp in evidence
            ))
    if not video_url and not local_url and evidence:
        lines.append('└ ' + ' · '.join(f'{kind} {mmss(timestamp)}' for kind, timestamp in evidence))
    if issues:
        lines.append('└ ' + ' · '.join(f'**{text}**' for _, text in issues))
    return '\n'.join(lines)


def gp_lines(g, video_url='', rev=None, local_url=None):
    flags = set(g.get('flags') or [])
    seen = set(g.get('seen') or [])
    first = g.get('first') or {}
    out = []

    local_base = local_play_url(rev) if local_url is None else local_url

    for flag in ('revive', 'firewall'):
        if flag in flags and flag in seen:
            line = f'{ROW_MARK[OK]} {GP_NAME[flag]}'
        elif flag in flags:
            line = (
                f'{ROW_MARK[UNSURE]} {GP_NAME[flag]} **not found**'
                if flag == 'revive'
                else f'{ROW_MARK[BAD]} {GP_NAME[flag]} **not triggered**'
            )
        elif flag in seen:
            line = f'{ROW_MARK[BAD]} {GP_NAME[flag]} **not submitted**'
        else:
            continue

        out.append(line)

        timestamp = first.get(flag)
        if timestamp is None:
            continue

        try:
            seconds = max(0, int(float(timestamp)))
        except (TypeError, ValueError, OverflowError):
            continue

        if video_url and not local_base:
            out[-1] += ' ' + video_time(video_url, seconds)      # 로컬 링크가 없으면 같은 줄에
        else:
            if video_url:
                out.append('Onl ' + video_time(video_url, seconds))
            if local_base:
                out.append('Loc ' + video_time(local_base, seconds))

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
    sources = playback_sources(rev, a, side)
    # 사이트 대기열 건(rev_…)이면 검토 페이지로, 로컬 입력이면 payload 의 review_id 또는 영상 주소로
    api = bool(re.fullmatch(r'rev_[A-Za-z0-9]+', rev or ''))
    review_id = rev if api else p.get('review_id')
    review = (
        f'https://theherta.com/mod?review={review_id}'
        if isinstance(review_id, str)
        and re.fullmatch(r'rev_[A-Za-z0-9_-]+', review_id)
        else url
    )
    marks = ('✅ ' if action == 'approve' else '❌ ' if action == 'reject' else '') + ('⚠️ ' if a['confidence'] < WARN_BELOW else '')
    if api:
        status = {'approve': 'Approved on site', 'reject': 'Rejected on site'}.get(action, 'Not decided (human)')
    else:
        status = 'Local analysis; manual review recommended' if a['verdict'] == 'CHECK' else 'Local analysis completed'

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
    timestamp_info = a.get('timestamp_info') or (a.get('segments') or {}).get('timestamp_info')
    if timestamp_info:
        add('Timestamp', timestamp_info.get('message'))
    # 합친 제출(여러 런)은 런마다 칸을 따로 만든다: 한 칸은 1024자까지라 캐릭터 열둘이 한 칸이면 잘린다.
    # 빌드 목록은 런마다 캐릭터 순서(p1~p4)대로 이어져 있다
    builds = list(a.get('build') or [])
    pos = 0
    for si, sd in enumerate(sides):
        n = sum(1 for j in range(1, 5) if sd.get(f'p{j}_char'))
        row_sources = sources if si == 0 else playback_sources(rev, a, sd)
        rows = [build_row(b, row_sources['build_online'], row_sources['build_local'])
                for b in builds[pos:pos + n]]
        if not rows:
            for j in range(1, 5):
                char = sd.get(f'p{j}_char')
                if not char:
                    continue
                e = sd.get(f'p{j}_eidolon', '?')
                s = sd.get(f'p{j}_superimp', '?')
                lc = sd.get(f'p{j}_lc') or 'no Light Cone'
                rows.append(
                    f'⚠️ **{char}** (E{e}S{s}) — *{lc}*\n'
                    '└ **Submitted build · not verified**'
                )
        pos += n
        title = side_name(sd) + (f' ({si + 1}/{len(sides)})' if len(sides) > 1 else '')
        vurl = sd.get('video_url') or ''
        if len(sides) > 1 and vurl:
                    match = re.search(r"[?&]t=(\d+)", vurl)
                    start = int(match.group(1)) if match else 0
                    title += f'  ·  starts {mmss(start)}'
        # Discord limits each field to 1024 characters. Keep character rows intact.
        chunk = []
        field_title = title
        for row in rows or ['—']:
            if chunk and len('\n'.join(chunk + [row])) > 1024:
                add(field_title, chunk)
                field_title = '\u200b'
                chunk = []
            chunk.append(row)
        add(field_title, chunk)
    only1 = ' — run 1 only' if len(sides) > 1 else ''
    # 짧은 값만 나란히(긴 글을 칸에 넣으면 좁은 칸에서 줄이 마구 꺾인다)
    if a.get('gp') is not None:
        add(
            'Global Passive' + only1,
            gp_lines(a['gp'], sources['battle_online'], rev, sources['battle_local']),
            inline=False,
        )
    uid_text = (
        f"`{a['uid']}`" if a.get('uid')
        else f'{ROW_MARK[UNSURE]} **not checked**'
        if a.get('uid_checked') is False
        else f'{ROW_MARK[UNSURE]} **not readable**'
    )
    add('UID', uid_text, inline=False)
    add('Battle (HUD)' + only1, bullets(a['checks'], url), inline=False)
    ded = a.get('deductions', [])
    add(f"Deductions (−{sum(n for n, _ in ded)})", [link_inline_timestamps(f'−{n} {w}', url) for n, w in ded])
    heading = '**Links**'
    if review_id:
        heading += f' · [Open review]({review})'

    from segment_pipeline import timestamp
    local_input = bool(side.get('local_battle_video') or side.get('local_showcase_video'))
    start = side.get('battle_timestamp')
    if start is None:
        start = 0 if local_input else (timestamp(url) or 0)
    lines = [heading]
    for prefix, battle_url, build_url in (
        ('Onl', sources['battle_online'], sources['build_online']),
        ('Loc', sources['battle_local'], sources['build_local']),
    ):
        links = []
        if battle_url:
            links.append(timestamp_link(battle_url, start, 'Video'))
        if build_url and sh_t is not None:
            links.append(timestamp_link(build_url, sh_t, f'Showcase {mmss(sh_t)}'))
        if links:
            lines.append((prefix + ' ' if sources['battle_local'] or sources['build_local'] else '') + ' · '.join(links))
    if sources['battle_local']:
        query = urlsplit(sources['battle_local']).query
        token = dict(parse_qsl(query)).get('key', '')
        folder_link = f'http://127.0.0.1:8765/runs/{rev}?' + urlencode({'key': token})
        lines.extend(['-----', f'[Open run folder]({folder_link})'])

    add('\u200b', '\n'.join(lines))

    run_id = (item.get('run_ids') or [rev])[0]
    return {'title': clip(f"{marks}{a['verdict']} · {a['confidence']}% confidence", 256), **({'url': review} if review else {}),
            'description': clip('\n'.join(desc), 4096), 'color': VERDICT_COLOR.get(a['verdict'], 0x60a5fa),
            'fields': fields, 'footer': {'text': f"ID: {run_id}  •  {'Review' if api else 'Local'} ID: {rev}"},
            'timestamp': datetime.now(timezone.utc).isoformat()}


def as_text(e):
    """터미널에 찍을 임베드 글."""
    out = [e['title'], e['description']]
    for f in e['fields']:
        out += [f"[{f['name']}]", f['value']]
    return '\n'.join(out + [e['footer']['text']])


def video_key(url):
    if not isinstance(url, str):
        return None

    bili = re.search(r'(BV[0-9A-Za-z]{10})', url)
    if bili:
        part = re.search(r'[?&]p=(\d+)', url)
        part_number = int(part.group(1)) if part else 1
        return f'{bili.group(1)}:p{part_number}'

    youtube = (
        re.search(r'youtu\.be/([\w-]{11})', url)
        or re.search(r'[?&]v=([\w-]{11})', url)
    )
    return youtube.group(1) if youtube else None


def check_result(reason):
    return {'verdict': 'CHECK', 'confidence': 0, 'problems': [], 'problem_items': [],
            'checks': [], 'build': [], 'check_reasons': [reason], 'deductions': [],
            'uid': None, 'uid_checked': False, 'gp': None,
            'timing': {}, 'stop_loop': False}


def attach_sheets(directory, payload):
    directory = Path(directory)

    def read_json(name, fallback):
        try:
            return json.loads(
                (directory / name).read_text(encoding='utf8')
            )
        except (OSError, ValueError):
            return fallback

    videos = read_json('videos.json', [])
    if not isinstance(videos, list) or not videos:
        videos = [{'file': 'video0.mp4', 'run_part': True}]

    battle = next(
        (
            i for i, video in enumerate(videos)
            if video.get('role') == 'battle'
        ),
        None,
    )

    if battle is None:
        battle = next(
            (
                i for i, video in enumerate(videos)
                if video.get('run_part')
            ),
            0,
        )

    selection = read_json('segment_selection.json', {})
    selected_index = selection.get('battle_index')
    if type(selected_index) is int and 0 <= selected_index < len(videos):
        battle = selected_index

    judged = read_json('judge.json', {})
    builds = judged.get('build_indices', [])

    if not isinstance(builds, list):
        builds = []

    builds = [
        i for i in builds
        if type(i) is int and 0 <= i < len(videos)
    ]

    if not builds:
        builds = [
            i for i, video in enumerate(videos)
            if video.get('role') == 'showcase'
        ] or [battle]

    candidates = []

    build = next(
        (
            directory / f'tabs{i}' / 'sheet.jpg'
            for i in builds
            if (directory / f'tabs{i}' / 'sheet.jpg').is_file()
        ),
        None,
    )

    if build is not None:
        candidates.append(('Build sheet', build))

    sheet_folder = directory / f'sheet{battle}'
    pages = sorted(
        (
            path for path in sheet_folder.glob('*')
            if path.is_file()
            and path.suffix.lower() in ('.jpg', '.jpeg', '.png')
            and path.stem.isdigit()
        ),
        key=lambda path: (int(path.stem), path.name),
    )

    metadata = read_json(f'sheet{battle}/sheets.json', {})
    if metadata.get('battle') != selection.get('battle') or not metadata.get('pages'):
        pages = []

    if pages:
        candidates.append((
            f'Battle start · page {int(pages[0].stem)}',
            pages[0],
        ))

        last = pages[-1]

        if last != pages[0]:
            candidates.append((
                f'Battle end · page {int(last.stem)}',
                last,
            ))

    payload = json.loads(json.dumps(payload))
    embeds = payload.setdefault('embeds', [])
    files = []

    # Different from the main report URL so only the images group.
    main_url = (
        embeds[0].get('url')
        if embeds
        else None
    ) or 'https://theherta.com/mod'

    gallery_url = (
        main_url.split('#', 1)[0]
        + '#reviewbot-sheets'
    )

    payload['attachments'] = []

    for index, (title, path) in enumerate(candidates):
        files.append(str(path))

        payload['attachments'].append({
            'id': index,
            'filename': path.name,
            'description': title,
        })

        image_embed = {
            'url': gallery_url,
            'image': {
                'url': f'attachment://{path.name}',
            },
        }

        if index == 0:
            image_embed['title'] = 'Run sheets'
            image_embed['description'] = (
                ' • '.join(label for label, _ in candidates)
            )
            if embeds:
                image_embed['color'] = embeds[0].get(
                    'color', 0x60a5fa
                )

        embeds.append(image_embed)

    return payload, files
