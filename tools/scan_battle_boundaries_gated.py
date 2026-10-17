"""Standalone battle prompt scan; does not run reviews or send webhooks."""
import argparse
import difflib
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

PROMPTS = {'TextMapCHS': {'battle_start': '战斗开始', 'your_turn': '我方行动中', 'enemy_turn': '敌方行动中', 'battle_over': '结束战斗'}, 'TextMapCHT': {'battle_start': '戰鬥開始', 'your_turn': '我方行動中', 'enemy_turn': '敵方行動中', 'battle_over': '結束戰鬥'}, 'TextMapDE': {'battle_start': 'Kampf beginnt', 'your_turn': 'Du bist am Zug', 'enemy_turn': 'Gegner ist am Zug', 'battle_over': 'Kampf endet'}, 'TextMapEN': {'battle_start': 'Battle Start', 'your_turn': 'Your Turn', 'enemy_turn': "Enemy's Turn", 'battle_over': 'Battle Over'}, 'TextMapES': {'battle_start': '¡Comienza la batalla!', 'your_turn': 'Tu turno', 'enemy_turn': 'Turno enemigo', 'battle_over': 'Fin de la batalla'}, 'TextMapFR': {'battle_start': 'Début du combat', 'your_turn': 'Votre tour', 'enemy_turn': "Tour de l'ennemi", 'battle_over': 'Combat terminé'}, 'TextMapID': {'battle_start': 'Pertempuran Dimulai', 'your_turn': 'Giliran Timmu', 'enemy_turn': 'Giliran Musuh', 'battle_over': 'Pertempuran Berakhir'}, 'TextMapJP': {'battle_start': '戦闘開始', 'your_turn': '味方のターン', 'enemy_turn': '敵のターン', 'battle_over': '戦闘終了'}, 'TextMapKR_0': {'battle_start': '전투\xa0시작', 'your_turn': '아군\xa0행동\xa0중', 'enemy_turn': '적\xa0행동\xa0중', 'battle_over': '전투\xa0종료'}, 'TextMapPT': {'battle_start': 'Início da Batalha', 'your_turn': 'Sua Vez', 'enemy_turn': 'Vez do Inimigo', 'battle_over': 'Fim da Batalha'}, 'TextMapRU_0': {'battle_start': 'В бой!', 'your_turn': 'Ваш ход', 'enemy_turn': 'Ход противника', 'battle_over': 'Бой окончен'}, 'TextMapTH_0': {'battle_start': 'เริ่มการต่อสู้', 'your_turn': 'แอ็กชันของฝ่ายคุณ', 'enemy_turn': 'แอ็กชันของฝ่ายศัตรู', 'battle_over': 'สิ้นสุดการต่อสู้'}, 'TextMapVI': {'battle_start': 'Bắt Đầu', 'your_turn': 'Phe Ta', 'enemy_turn': 'Phe Địch', 'battle_over': 'Kết Thúc'}}
EXPECTED = [
    ('start', 1, 14), ('wave', 2, 59), ('end', None, 172),
    ('start', 1, 217), ('wave', 2, 277), ('end', None, 494),
    ('start', 1, 535), ('wave', 2, 599), ('end', None, 703),
]


def normalize(text):
    text = unicodedata.normalize('NFKC', text).casefold()
    return ''.join(c for c in text if c.isalnum() or unicodedata.category(c).startswith('M'))


def recognize(text):
    original = unicodedata.normalize('NFKC', text)
    fraction = re.search(r'(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)', original)
    wave = total = None

    if fraction is None and any(c.isdigit() for c in original):
        return None

    if fraction:
        wave, total = map(int, fraction.groups())
        original = original[:fraction.start()] + original[fraction.end():]
        if not 1 <= wave <= total <= 20:
            return None
    target = normalize(original)
    if not target:
        return None
    scores = {}
    for translations in PROMPTS.values():
        for kind in ('battle_start', 'battle_over'):
            label = normalize(translations[kind])
            score = difflib.SequenceMatcher(None, target, label).ratio()
            scores[kind] = max(scores.get(kind, 0), score)
    ranked = sorted(scores, key=scores.get, reverse=True)
    kind = ranked[0]
    if scores[kind] < 0.86 or scores[kind] - scores[ranked[1]] < 0.08:
        return None
    if kind == 'battle_over' and fraction:
        return None
    event = 'end' if kind == 'battle_over' else 'wave' if wave and wave > 1 else 'start'
    return {'kind': event, 'wave': wave, 'total_waves': total,
            'text': text, 'score': round(scores[kind], 4),
            'start_number_missing': event == 'start' and wave is None}


def consolidate_events(events, gap=3.0):
    """Merge nearby readings of one banner, preferring a readable fraction."""
    merged = []
    for original in sorted(events, key=lambda e: e['t']):
        event = dict(original)
        previous = merged[-1] if merged else None
        nearby = previous and 0 <= event['t'] - previous.get('last_t', previous['t']) <= gap
        same = nearby and all(event.get(k) == previous.get(k)
                              for k in ('kind', 'wave', 'total_waves'))
        unnumbered = nearby and (
            (event['kind'] == 'start' and event.get('wave') is None
             and previous['kind'] in ('start', 'wave'))
            or (previous['kind'] == 'start' and previous.get('wave') is None
                and event['kind'] in ('start', 'wave'))
        )
        if same or unnumbered:
            if previous.get('wave') is None and event.get('wave') is not None:
                first_t = previous['t']
                previous.update(event)
                previous['t'] = first_t
            previous['last_t'] = max(previous.get('last_t', previous['t']),
                                     event.get('last_t', event['t']))
        else:
            merged.append(event)
    return merged


def recovery_ranges(events, end):
    segments, _ = assemble(events)
    ranges = []
    for segment in segments:
        if segment['end'] is not None or segment['start'] is None:
            continue
        left = segment['waves'][-1]['t'] if segment['waves'] else segment['start']
        following = [e['t'] for e in events
                     if e['kind'] == 'start' and e['t'] > left]
        right = min(following) if following else end
        if right > left:
            ranges.append((left, right))
    return ranges


def prompt_matches(engine, crop):
    boxes = sorted(engine(crop, scale=2.0 if crop.shape[1] < 800 else 1.0),
                   key=lambda box: (box[1], box[0]))
    texts = [box[4] for box in boxes]
    for left, right in zip(boxes, boxes[1:]):
        if abs((left[1]+left[3]/2)-(right[1]+right[3]/2)) < .5*max(left[3],right[3]):
            texts.append(left[4] + ' ' + right[4])
    return [match for text in texts if (match := recognize(text)) is not None]


def assemble(events):
    segments, warnings = [], []
    current = None
    for event in events:
        kind = event['kind']
        if kind == 'start':
            if current is not None and event.get('wave') is None:
                last_prompt = (
                    current['waves'][-1]['t']
                    if current['waves']
                    else current['start']
                )
                if (
                    last_prompt is not None
                    and 0 <= event['t'] - last_prompt <= 3.0
                ):
                    continue

            if current is not None:
                current['warnings'].append('New start before an end was detected')
                current['status'] = 'CHECK'
                segments.append(current)
            current = {'start': event['t'], 'end': None, 'waves': [],
                       'status': 'candidate', 'warnings': []}
        elif kind == 'wave':
            if current is None:
                current = {'start': None, 'end': None, 'waves': [],
                           'status': 'CHECK', 'warnings': ['First-wave start not detected']}
            if current['waves'] and event['wave'] <= current['waves'][-1]['wave']:
                current['warnings'].append('Wave sequence is inconsistent')
            current['waves'].append({'t': event['t'], 'wave': event['wave'], 'total': event['total_waves']})
        elif current is not None:
            current['end'] = event['t']
            if current['warnings']:
                current['status'] = 'CHECK'
            segments.append(current)
            current = None
        else:
            warnings.append(f"End at {event['t']} without a detected start")
    if current is not None:
        current['status'] = 'CHECK'
        current['warnings'].append('Battle end not detected')
        segments.append(current)
    return segments, warnings


def aligned_text_row(components, image_height, crop_width):
    """Conservative geometry check; text meaning is still checked by OCR."""
    for x, y, width, height in components:
        row = [box for box in components
               if abs((box[1] + box[3]/2) - (y + height/2))
               <= max(.006*image_height, .45*max(height, box[3]))
               and .5*height <= box[3] <= 2*height]
        if len(row) >= 3:
            span = max(box[0]+box[2] for box in row) - min(box[0] for box in row)
            if span >= .065*crop_width:
                return True
    return False


def prompt_text_gate(crop, image_height):
    import cv2
    import numpy as np
    if crop.size == 0:
        return False
    scale = min(1.0, 640/crop.shape[1])
    if scale < 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    height = image_height*scale
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 2] >= 130) & (hsv[..., 1] <= 100)).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    components = [tuple(map(int, row[:4])) for row in stats[1:]
                  if .008*height <= row[3] <= .055*height
                  and 1 <= row[2] <= 3*row[3] and row[4] >= 3]
    return aligned_text_row(components, height, crop.shape[1])


def compare_boundaries(baseline, result, tolerance=.75):
    comparisons = []
    used = set()
    for expected in baseline['events']:
        choices = [(i, actual) for i, actual in enumerate(result['events'])
                   if i not in used and all(actual.get(k)==expected.get(k)
                                            for k in ('kind', 'wave', 'total_waves'))]
        nearest = min(choices, key=lambda item: abs(item[1]['t']-expected['t'])) if choices else None
        retained = nearest is not None and abs(nearest[1]['t']-expected['t']) <= tolerance
        if retained:
            used.add(nearest[0])
        comparisons.append({'kind':expected['kind'], 'wave':expected.get('wave'),
                            'baseline_t':expected['t'],
                            'gated_t':nearest[1]['t'] if nearest else None,
                            'retained':retained})
    return {'tolerance_seconds':tolerance,
            'all_baseline_events_retained':all(c['retained'] for c in comparisons),
            'events':comparisons,
            'extra_events':[e for i,e in enumerate(result['events']) if i not in used],
            'baseline_segment_count':len(baseline['segments']),
            'gated_segment_count':len(result['segments'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', help='Existing local video path; no downloading')
    parser.add_argument('--model', default='latin', choices=['chinese', 'korean', 'latin', 'eslav', 'thai', 'english'])
    parser.add_argument('--fps', type=float, default=4)
    parser.add_argument('--start', type=float, default=0)
    parser.add_argument('--end', type=float)
    parser.add_argument('--output', default=None)
    parser.add_argument('--check-example', action='store_true', help='Compare against the provided 12:09 test video')
    parser.add_argument('--text-gate', action='store_true', help='Experimental bright-text geometry gate before OCR')
    parser.add_argument('--baseline', help='Ungated boundaries.json from the same video/model/range')
    parser.add_argument('--no-repair', action='store_true', help='Disable wider ungated retry for missing battle ends')
    args = parser.parse_args()
    if args.fps <= 0 or args.start < 0:
        parser.error('fps must be positive and start nonnegative')
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / 'auto'))
    import cv2
    from ocr import OCR
    import tabs
    video = Path(args.video).expanduser().resolve()
    if not video.is_file():
        parser.error(f'Video not found: {video}')
    duration, width, height = tabs.probe(str(video))
    end = min(duration, args.end if args.end is not None else duration)
    if end <= args.start:
        parser.error('end must be after start and within the video')
    output = Path(args.output) if args.output else video.parent / (video.stem + '_boundaries')
    output.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(Path(args.baseline).read_text(encoding='utf-8-sig')) if args.baseline else None
    if baseline and (baseline.get('model') != args.model or baseline.get('fps') != args.fps
                     or abs(baseline['range'][0]-args.start) > .01
                     or abs(baseline['range'][1]-end) > .1):
        parser.error('Baseline model/fps/range differ from this scan')
    started = time.perf_counter()
    engine = OCR(args.model)
    frame_count = ocr_calls = skipped = 0
    gate_samples = []
    events, observations = [], []
    active, last_hit = None, -100
    next_progress = args.start
    # Upper centre band covering the prompts in the supplied examples.
    for t, frame in tabs.frames(str(video), args.start, end - args.start, args.fps, width, height):
        frame_count += 1
        if t >= next_progress:
            print(f'Scanning {t:.1f}/{end:.1f}s — {len(events)} events', flush=True)
            next_progress = t + 30
        crop = frame[int(.10*height):int(.23*height), int(.375*width):int(.635*width)]
        gate_passed = not args.text_gate or prompt_text_gate(crop, height)
        gate_samples.append({'t':round(t,3), 'passed':gate_passed})
        if not gate_passed:
            skipped += 1
            continue
        ocr_calls += 1
        matches = prompt_matches(engine, crop)
        if not matches:
            continue
        hit = max(matches, key=lambda match: match['score'])
        hit['t'] = round(t, 3)
        observations.append(dict(hit))
        key = (hit['kind'], hit['wave'], hit['total_waves'])
        if active != key or t - last_hit > 2:
            filename = f"{len(events)+1:03d}_{t:.3f}_{hit['kind']}.jpg"
            hit['evidence'] = filename if cv2.imwrite(str(output / filename), frame) else None
            hit['last_t'] = hit['t']
            events.append(hit)
            print(f"  {t:.2f}s {hit['kind']} {hit['text']}", flush=True)
            active = key
        else:
            events[-1]['last_t'] = hit['t']
        last_hit = t
    events = consolidate_events(events)
    retry_frames = retry_calls = 0
    retries = []
    if not args.no_repair:
        for left, right in recovery_ranges(events, end):
            print(f'Wide-crop end retry {left:.2f}-{right:.2f}s (ungated)', flush=True)
            retry_info = {'range': [left, right], 'recovered_end': None}
            retries.append(retry_info)
            for t, frame in tabs.frames(str(video), left, right-left, args.fps, width, height):
                retry_frames += 1
                retry_calls += 1
                crop = frame[int(.08*height):int(.23*height), int(.25*width):int(.75*width)]
                matches = [hit for hit in prompt_matches(engine, crop) if hit['kind'] == 'end']
                if not matches:
                    continue
                hit = max(matches, key=lambda match: match['score'])
                hit.update(t=round(t, 3), last_t=round(t, 3), source='wide_end_retry')
                filename = f"retry_{t:.3f}_end.jpg"
                hit['evidence'] = filename if cv2.imwrite(str(output / filename), frame) else None
                events.append(hit)
                observations.append(dict(hit))
                retry_info['recovered_end'] = hit['t']
                print(f"  recovered end {t:.2f}s {hit['text']}", flush=True)
                break
    events = consolidate_events(events)
    segments, warnings = assemble(events)
    result = {'video': str(video), 'model': args.model, 'fps': args.fps,
              'range': [args.start, end], 'events': events, 'segments': segments,
              'warnings': warnings, 'observations': observations,
              'note': 'Provisional prompt boundaries; does not detect showcases or assign submissions.'}
    result['performance'] = {
        'text_gate':args.text_gate, 'frames':frame_count, 'ocr_calls':ocr_calls,
        'skipped_frames':skipped, 'retry_frames':retry_frames,
        'retry_ocr_calls':retry_calls, 'total_ocr_calls':ocr_calls+retry_calls,
        'elapsed_seconds':round(time.perf_counter()-started,2),
        'ocr_reduction_percent':round(100*skipped/max(1,frame_count),2),
    }
    result['end_retries'] = retries
    if baseline:
        result['baseline_comparison'] = compare_boundaries(baseline, result)
    (output / 'gate_samples.json').write_text(json.dumps(gate_samples), encoding='utf8')
    print(f"Performance: {result['performance']}", flush=True)
    if baseline:
        print(f"All baseline events retained: {result['baseline_comparison']['all_baseline_events_retained']}", flush=True)
    if args.check_example:
        comparison = []
        for kind, wave, expected in EXPECTED:
            eligible = [e for e in events if e['kind']==kind and (wave is None or e['wave']==wave)]
            nearest = min(eligible, key=lambda e:abs(e['t']-expected)) if eligible else None
            delta = round(nearest['t']-expected,3) if nearest else None
            comparison.append({'kind':kind,'wave':wave,'expected':expected,
                               'detected':nearest['t'] if nearest else None,'delta':delta,
                               'within_5_seconds':delta is not None and abs(delta)<=5})
        result['example_comparison'] = comparison
    path = output / 'boundaries.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(f'Saved {path}', flush=True)


if __name__ == '__main__':
    main()
