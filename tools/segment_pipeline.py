"""Cached video boundaries and per-submission battle/build intervals."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

VERSION = 'segments-7-adaptive-2fps'
MANIFEST_REVISION = 'partial-battles-1'
HERE = Path(__file__).resolve().parent


def timestamp(url):
    match = re.search(r'[?&#](?:t|start)=([^&#]+)', url or '')
    if not match:
        return None
    value = match[1]
    if value.isdigit():
        return float(value)
    parts = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', value)
    if parts and any(parts.groups()):
        h, m, s = (int(x or 0) for x in parts.groups())
        return float(h * 3600 + m * 60 + s)
    raise ValueError('Unrecognized video timestamp; manual review required')


def canonical(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    query = parse_qs(parsed.query)
    if host in ('youtu.be', 'www.youtu.be'):
        return 'youtube:' + parsed.path.strip('/').split('&')[0]
    if host in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
        video = query.get('v', [None])[0]
        if video:
            return 'youtube:' + video
    bv = re.search(r'/video/(BV[0-9A-Za-z]+)', parsed.path)
    if host.endswith('bilibili.com') and bv:
        return f"bilibili:{bv[1]}:p{query.get('p', ['1'])[0]}"
    return parsed._replace(query='', fragment='').geturl()


def usable_battle(segment):
    return (segment.get('start') is not None and segment.get('end') is not None
            and (segment.get('status') != 'CHECK' or segment.get('warnings') ==
                 ['Start has no readable wave number; verify boundary']))


def select_battle(segments, anchor, unresolved=()):
    if not segments or any(not usable_battle(s) for s in segments):
        raise ValueError('Battle boundaries incomplete or uncertain; manual review required')
    segments = sorted(segments, key=lambda s: s['start'])
    if anchor is None or anchor == 0:
        if any(s['start'] <= segments[0]['start'] for s in unresolved):
            raise ValueError('First battle is incomplete or uncertain; manual review required')
        return 0, segments[0]
    containing = [(i, s) for i, s in enumerate(segments) if s['start'] <= anchor < s['end']]
    if len(containing) == 1:
        return containing[0]
    if containing:
        raise ValueError('Timestamp overlaps multiple battles; manual review required')
    following = [(i, s) for i, s in enumerate(segments) if anchor <= s['start'] <= anchor + 90]
    if len(following) == 1:
        return following[0]
    raise ValueError('Timestamp does not uniquely identify a battle within 90 seconds; manual review required')


def timestamp_details(battle, anchor, unresolved=()):
    if anchor is None:
        return None, []
    delta = anchor - battle['start']
    seconds = f'{abs(delta):.2f}'.rstrip('0').rstrip('.')
    if delta == 0:
        message = 'Submitted timestamp matches the detected battle start.'
    else:
        direction = 'after' if delta > 0 else 'before'
        message = f'Submitted timestamp is {seconds} seconds {direction} the detected battle start.'
    skipped = delta < 0 and any(
        interval['start'] < battle['start'] and interval['end'] > anchor
        for interval in unresolved
    )
    reasons = []
    if abs(delta) > 30:
        reasons.append(message + ' Offset exceeds 30 seconds; manual review required.')
    if skipped:
        reasons.append('Skipped an incomplete attempt to select the next complete battle; manual review required.')
    return {'submitted': anchor, 'detected_start': battle['start'],
            'offset_seconds': delta, 'message': message,
            'snapped_forward': delta < 0, 'skipped_incomplete': skipped}, reasons


def partition_battles(data):
    """Incomplete intervals are exclusion zones, never accepted battles."""
    complete = sorted((s for s in data['segments'] if usable_battle(s)),
                      key=lambda s: s['start'])
    zones = []
    for segment in data['segments']:
        if usable_battle(segment):
            continue
        left = segment.get('start')
        right = segment.get('end')
        if left is None:
            right_hint = right if right is not None else data['range'][1]
            left = max([data['range'][0]] + [s['end'] for s in complete if s['end'] <= right_hint])
        if right is None:
            following = [s['start'] for s in data['segments']
                         if s.get('start') is not None and s['start'] > left]
            right = min(following) if following else data['range'][1]
        if right > left:
            zones.append({'start': left, 'end': right,
                          'warnings': segment.get('warnings', [])})
    merged = []
    for zone in sorted(zones, key=lambda s: s['start']):
        if merged and zone['start'] <= merged[-1]['end']:
            merged[-1]['end'] = max(merged[-1]['end'], zone['end'])
            merged[-1]['warnings'] = sorted(set(merged[-1]['warnings'] + zone['warnings']))
        else:
            merged.append(dict(zone))
    if any(a['start'] < b['end'] and b['start'] < a['end']
           for a in complete for b in merged):
        raise ValueError('Complete and unresolved battle intervals overlap; manual review required')
    return complete, merged


def showcase_scan_input(data, complete, unresolved):
    # Gap scanner accepts closed intervals. These synthetic intervals only mask
    # uncertain footage; they are not returned as valid battles in the manifest.
    barriers = [dict(s, status='exclusion') for s in unresolved]
    timeline = sorted(complete + barriers, key=lambda s: s['start'])
    scoped = dict(data, segments=timeline, warnings=[])
    return scoped, timeline


def associate(segments, showcases, index):
    """Use sequence/proximity, never the submitted build values."""
    grouped = {}
    for fragment in showcases:
        key = (
            fragment.get('after_battle'),
            tuple(fragment['search_window']),
        )
        grouped.setdefault(key, []).append(fragment)

    candidates = []
    for fragments in grouped.values():
        tabs_seen = sorted({
            tab
            for fragment in fragments
            for tab in fragment.get('tabs', [])
        })
        samples = sum(
            fragment.get('menu_frames', 0)
            for fragment in fragments
        )
        other_warnings = {
            warning
            for fragment in fragments
            for warning in fragment.get('warnings', [])
            if warning not in (
                'Fewer than three menu samples',
                'No LC or Eidolon tab confirmed',
            )
        }

        if (
            samples < 3
            or not {'LightCone', 'Eidolon'}.intersection(tabs_seen)
            or other_warnings
        ):
            raise ValueError(
                'Showcase detection uncertain; manual review required'
            )

        region = dict(min(
            fragments, key=lambda fragment: fragment['start']
        ))
        region.update(
            start=min(fragment['start'] for fragment in fragments),
            end=max(fragment['end'] for fragment in fragments),
            status='candidate',
            warnings=[],
            tabs=tabs_seen,
            menu_frames=samples,
            last_evidence=max(
                fragments, key=lambda fragment: fragment['end']
            ).get('last_evidence'),
        )
        candidates.append(region)
    count = len(segments)
    if count == 1 and len(candidates) == 1:
        return candidates[0], False
    # One terminal/prelude showcase with no interspersed showcases.
    if len(candidates) == 1 and candidates[0].get('after_battle') in (None, count):
        return candidates[0], count > 1
    # Require the full alternating pattern, including one per battle.
    if len(candidates) == count and {c.get('after_battle') for c in candidates} == set(range(1, count + 1)):
        return next(c for c in candidates if c['after_battle'] == index + 1), False
    raise ValueError('Mixed or missing showcase sequence; manual review required')


def run_script(name, args):
    try:
        subprocess.run([sys.executable, '-u', str(HERE / name), *map(str, args)], check=True)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f'{name} failed (exit {error.returncode})') from error


def early_language(video, payload, cache_root):
    import cv2
    import judge
    import tabs
    import video_cache

    signature = video_cache.fingerprint(
        [HERE / 'judge.py', HERE / 'tabs.py', HERE / 'menu_icons.png',
         HERE.parent / 'auto' / 'ocr.py'],
        extra='early-language-2:' + video_cache.content_hash(video),
    )
    directory = cache_root / 'language' / signature
    marker = directory / 'selection.json'
    if marker.is_file():
        print('Using cached early OCR language selection', flush=True)
        return json.loads(marker.read_text(encoding='utf8'))

    directory.mkdir(parents=True, exist_ok=True)
    print('Collecting early build-page language samples', flush=True)
    duration, width, height = tabs.probe(str(video))
    samples = {'LightCone': [], 'Eidolon': []}
    decoded = 1.0
    cursor = duration
    span = 90.0

    while cursor > 0 and len(samples['LightCone']) < 4:
        start = max(0.0, cursor - span)
        print(
            f'Early language: searching {start:.1f}-{cursor:.1f}s',
            flush=True,
        )
        windows, ratio = tabs.find_windows(
            str(video), duration, width, height,
            start=start, end=cursor,
        )
        decoded = min(decoded, ratio)

        for a, b, layout in sorted(windows, reverse=True):
            a, b = max(start, a), min(cursor, b)

            for t, frame in tabs.frames(
                str(video), a, max(0, b-a), 4, width, height
            ):
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                tab = tabs.which_tab(
                    tabs.pale_gold(hsv, layout),
                    tabs.gold_rows(hsv, layout),
                )
                if tab not in samples:
                    continue

                pool = samples[tab]
                if len(pool) >= 8 or any(
                    abs(old['t']-t) < 2 for old in pool
                ):
                    continue

                path = directory / f'{t:.3f}_{tab}.jpg'
                if cv2.imwrite(str(path), frame):
                    pool.append({
                        'vid': 0,
                        't': t,
                        'tab': tab,
                        'lay': layout,
                        'path': str(path),
                    })

                if len(samples['LightCone']) >= 4:
                    break

            if len(samples['LightCone']) >= 4:
                break

        cursor = start
        span *= 2

    chars = []
    for side in payload.get('runs') or [payload]:
        for i in range(1, 5):
            if side.get(f'p{i}_char'):
                chars.append({'char': side[f'p{i}_char'], 'lc': side.get(f'p{i}_lc')})
    judge.path_words()
    model, selection = judge.select_language(
        samples['LightCone'] + samples['Eidolon'], chars, rev='early language',
    )
    if decoded < .9:
        selection['uncertain'] = True
        selection['reasons'].append('Early video pass decoded incompletely')
    result = {'model': model, 'selection': selection}
    temporary = directory / 'selection.pending'
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(temporary, marker)
    print(f"Early boundary OCR model {model}; uncertain={selection['uncertain']}", flush=True)
    return result


def manifest(video, preferred, payload=None, language_video=None):
    import video_cache
    video = Path(video)
    signature = video_cache.fingerprint(
        [HERE / 'scan_battle_boundaries.py', HERE / 'scan_showcases.py',
         HERE / 'tabs.py', HERE.parent / 'auto' / 'ocr.py',
         HERE / 'menu_icons.png'], extra=VERSION + preferred + video_cache.content_hash(video))
    directory = video_cache.ROOT / 'segments' / signature
    marker = directory / 'manifest.json'
    if marker.is_file():
        print('Using cached battle/showcase segments', flush=True)
        cached = json.loads(marker.read_text(encoding='utf8'))
        if cached.get('manifest_revision') == MANIFEST_REVISION:
            return cached
    directory.mkdir(parents=True, exist_ok=True)
    language = {'model': preferred, 'selection': {'forced': preferred}}
    if payload is not None and not (payload.get('boundary_ocr_model') or payload.get('ocr_model')):
        try:
            language = early_language(Path(language_video or video), payload, video_cache.ROOT)
            preferred = language['model']
        except (OSError, ValueError, RuntimeError) as error:
            print(f'Early language selection unavailable: {error}; using model fallback', flush=True)
            language = {'model': preferred, 'selection': {'uncertain': True, 'reasons': [str(error)]}}
    chosen = None
    # A wrong recognition model must not turn a prompt-free result into a
    # confident single-run assumption. Try the other installed models.
    # 언어를 확신 있게 골랐거나(빌드 화면 표본으로 uncertain=False) 사람이 모델을 정했으면 그 모델 하나만 쓴다. 완전한 전투가 안 나와도
    # (글이 영상에 없는 경우: 시작 · 종료 배너가 없는 녹화) 다른 네 모델로 같은 영상을 다시 훑는 데 모델마다 9분씩 쓰기 때문이다(사용자, 2026-10-17).
    # 언어를 못 골랐을 때만 다른 모델도 시도한다.
    selection = language.get('selection') or {}
    confident = bool(selection.get('forced')) or selection.get('uncertain') is False
    models = [preferred] if confident else [preferred] + [m for m in ('latin', 'chinese', 'korean', 'eslav', 'thai') if m != preferred]
    for model in models:
        output = directory / model
        boundary_path = output / 'boundaries.json'
        try:
            if boundary_path.is_file():
                print(f'Using cached {model} boundary scan', flush=True)
            else:
                run_script('scan_battle_boundaries.py', [video, '--model', model, '--repair-limit', '60', '--output', output])
            data = json.loads(boundary_path.read_text(encoding='utf8'))
            complete, unresolved = partition_battles(data)
        except (OSError, ValueError, RuntimeError) as error:
            print(str(error), flush=True)
            continue
        if complete:
            chosen = output
            break
    if chosen is None:
        raise ValueError('No complete battle segmentation found; manual review required (see work/video_cache/segments)')
    scoped, timeline = showcase_scan_input(data, complete, unresolved)
    scoped_path = directory / 'showcase_boundaries.json'
    scoped_path.write_text(json.dumps(scoped, ensure_ascii=False, indent=2), encoding='utf8')
    showcase_folder = directory / 'showcases'
    showcase_path = showcase_folder / 'showcases.json'
    completion = showcase_folder / 'completed_scan.json'
    signature = video_cache.fingerprint(
        [scoped_path, HERE / 'scan_showcases.py'],
        extra='showcase-completion-1',
    )

    cached_showcase = None
    if completion.is_file() and showcase_path.is_file():
        try:
            saved = json.loads(completion.read_text(encoding='utf8'))
            candidate = json.loads(showcase_path.read_text(encoding='utf8'))
            if (
                saved.get('signature') == signature
                and isinstance(candidate.get('showcases'), list)
            ):
                cached_showcase = candidate
        except (OSError, ValueError, AttributeError):
            pass

    if cached_showcase is not None:
        print('Using cached completed showcase scan', flush=True)
        showcases = cached_showcase
    else:
        completion.unlink(missing_ok=True)
        run_script(
            'scan_showcases.py',
            [scoped_path, '--video', video, '--output', showcase_folder],
        )
        showcases = json.loads(showcase_path.read_text(encoding='utf8'))
        if not isinstance(showcases.get('showcases'), list):
            raise ValueError('Invalid showcase scan result; manual review required')

        temporary_completion = showcase_folder / 'completed_scan.pending'
        temporary_completion.write_text(
            json.dumps({'signature': signature}), encoding='utf8'
        )
        os.replace(temporary_completion, completion)
    for candidate in showcases['showcases']:
        after = candidate.get('after_battle')
        if after is not None:
            preceding = timeline[:after]
            candidate['after_battle'] = sum(s.get('status') != 'exclusion' for s in preceding) or None
    result = {'segments': complete, 'unresolved_intervals': unresolved,
              'original_segments': data['segments'], 'boundary_warnings': data.get('warnings', []),
              'showcases': showcases['showcases'],
              'range': data['range'], 'model': data['model'], 'cache': str(directory),
              'early_language': language, 'manifest_revision': MANIFEST_REVISION}
    temporary = directory / 'manifest.pending'
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(temporary, marker)
    return result


def prepare(directory, payload, videos):
    import tabs
    selected = next((i for i, v in enumerate(videos) if v.get('run_part')), 0)
    preferred = payload.get('boundary_ocr_model') or payload.get('ocr_model') or 'latin'
    if preferred not in ('latin', 'chinese', 'korean', 'eslav', 'thai'):
        raise ValueError('Unsupported boundary_ocr_model')
    language_index = next((i for i, v in enumerate(videos) if v.get('role') == 'showcase'), selected)
    data = manifest(directory / videos[selected]['file'], preferred, payload,
                    directory / videos[language_index]['file'])
    local = bool(payload.get('local_battle_video') or payload.get('local_showcase_video'))
    anchor = None if local else timestamp(payload.get('video_url'))
    if payload.get('battle_timestamp') is not None:
        anchor = payload['battle_timestamp']
        if type(anchor) not in (int, float) or not math.isfinite(anchor) or anchor < 0:
            raise ValueError('battle_timestamp must be a nonnegative finite number')
    index, battle = select_battle(data['segments'], anchor, data.get('unresolved_intervals', []))
    timing, timing_reasons = timestamp_details(
        battle, anchor, data.get('unresolved_intervals', [])
    )
    reasons = list(battle.get('warnings') or []) + timing_reasons
    if anchor is not None and any(c['start'] <= anchor <= c['end'] for c in data['showcases']):
        raise ValueError('Timestamp points into a showcase; manual review required')
    build_index = next((i for i, v in enumerate(videos) if v.get('role') == 'showcase'), selected)
    if build_index != selected:
        duration, _, _ = tabs.probe(str(directory / videos[build_index]['file']))
        build = [0.0, duration]
    else:
        candidate, shared = associate(data['segments'], data['showcases'], index)
        # Slight padding for transitions, never extending into a battle.
        gap = candidate['search_window']
        build = [max(gap[0], candidate['start'] - .5), min(gap[1], candidate['end'] + .5)]
        if shared:
            reasons.append('Shared showcase: confirm the selected build occurrence belongs to this battle')
    result = {'version': VERSION, 'battle_index': selected,
              'battle': [battle['start'], battle['end']], 'battle_number': index + 1,
              'battle_count': len(data['segments']), 'build_index': build_index,
              'build': build, 'check_reasons': reasons, 'cache': data['cache'],
              'timestamp_info': timing,
              'boundary_language_selection': data.get('early_language'),
              'unresolved_intervals': data.get('unresolved_intervals', [])}
    (directory / 'segment_selection.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print(f"{directory.name}: battle {index+1}/{len(data['segments'])} {result['battle']}; showcase {build}", flush=True)
    return result


@contextmanager
def bounded_frames(tabs, limits):
    """Keep all judge retry decoding inside the selected showcase interval."""
    original = tabs.frames
    normalized = {str(Path(path).resolve()): interval for path, interval in limits.items()}
    def frames(video, start, duration, fps, width, height):
        interval = normalized.get(str(Path(video).resolve()))
        if interval is not None:
            end = min(start + duration, interval[1])
            start = max(start, interval[0])
            duration = end - start
        if duration > 0:
            yield from original(video, start, duration, fps, width, height)
    tabs.frames = frames
    try:
        yield
    finally:
        tabs.frames = original


def extract_build(directory, videos, selection, env):
    import shutil
    import video_cache
    index = selection['build_index']
    a, b = selection['build']
    video = directory / videos[index]['file']
    signature = video_cache.fingerprint(
        [HERE / 'tabs.py', HERE / 'menu_icons.png'],
        extra=f'{VERSION}:{a:.6f}:{b:.6f}:{video_cache.content_hash(video)}')
    cache = video_cache.ROOT / 'segment_tabs' / signature
    destination = directory / f'tabs{index}'
    # Remove old full-video frames, including retries, before restoring a scope.
    if destination.exists():
        shutil.rmtree(destination)
    if video_cache.restore(cache, destination):
        print(f'{directory.name}: cached selected showcase frames', flush=True)
        return
    with (directory / 'tabs.log').open('w', encoding='utf8') as log:
        process = subprocess.Popen([sys.executable, '-u', str(HERE / 'tabs.py'),
                                    directory.name, str(index), str(a), str(b-a)],
                                   env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf8', errors='replace')
        for line in process.stdout:
            print(line, end='', flush=True)
            log.write(line)
        if process.wait():
            raise RuntimeError('Selected showcase extraction failed; see tabs.log')
    summary = json.loads((destination / 'summary.json').read_text())
    if summary.get('decode_error'):
        raise ValueError('Video decodes incompletely; manual review required')
    video_cache.publish(destination, cache)
