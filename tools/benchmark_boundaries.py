"""Compare full-video OCR with experimental start/HUD/end scanning. No reviews or webhooks."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time


def load_scanner(path):
    spec = importlib.util.spec_from_file_location('benchmark_scanner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, 'BattleHUD'):
        raise RuntimeError('Use the latest white-icon scan_battle_boundaries.py alongside this script.')
    return module


def frames(ff, video, start, end, fps, width, height):
    import numpy as np
    if end <= start:
        return
    process = subprocess.Popen(
        [ff, '-v', 'error', '-ss', str(start), '-t', str(end-start), '-i', str(video),
         '-vf', f'fps={fps},scale={width}:{height}', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = width*height*3
    try:
        index = 0
        while True:
            chunks = bytearray()
            while len(chunks) < size:
                data = process.stdout.read(size-len(chunks))
                if not data:
                    break
                chunks.extend(data)
            if len(chunks) != size:
                break
            t = start+index/fps
            if t >= end:
                break
            yield t, np.frombuffer(chunks, np.uint8).reshape(height, width, 3)
            index += 1
        if process.poll() is None:
            process.wait()
        if process.returncode:
            raise RuntimeError(f'FFmpeg decoding failed with exit code {process.returncode}')
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def state_scan(args):
    started = time.perf_counter()
    scanner = load_scanner(args.scanner)
    sys.path.insert(0, str(Path(args.scanner).parent))
    sys.path.insert(0, str(Path(args.scanner).parent.parent/'auto'))
    import cv2
    import tabs
    from paths import FF
    from ocr import OCR
    duration, width, height = tabs.probe(str(args.video))
    finish = min(duration, args.end if args.end is not None else duration)
    if finish <= args.start:
        raise ValueError('end must be after start and within video')
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    engine = OCR(args.model)
    hud = scanner.BattleHUD()
    observations, retries, hud_samples = [], [], []
    counts = {'ocr_calls': 0, 'search_ocr_calls': 0, 'transition_ocr_calls': 0,
              'fallback_ocr_calls': 0, 'hud_frames': 0, 'decoded_frames': 0}
    diagnostics = (output/'raw_ocr.jsonl').open('w', encoding='utf8', buffering=1)

    def read(t, frame, source):
        counts['ocr_calls'] += 1
        counts[source+'_ocr_calls'] += 1
        found = scanner.prompt_matches(engine, scanner.boundary_crop(frame), diagnostics,
                                       {'t': round(t, 3), 'crop': source})
        found = [hit for hit in found if hit['kind'] in ('start', 'end')]
        if not found:
            return None
        hit = dict(max(found, key=lambda hit: (hit['score'], hit.get('wave') is not None)))
        hit.update(t=round(t, 3), last_t=round(t, 3), source=source)
        filename = f"{source}_{t:.3f}_{hit['kind']}.jpg"
        hit['evidence'] = filename if cv2.imwrite(str(output/filename), frame) else None
        return hit

    def transition(left, right, battle_start, source):
        info = {'range': [round(left, 3), round(right, 3)], 'fps': 4, 'source': source, 'hits': 0}
        retries.append(info)
        fps = 8 if source == 'transition' else 4
        info['fps'] = fps
        print(f'{source}: {left:.2f}-{right:.2f}s at {fps} fps', flush=True)
        stream = frames(FF, args.video, left, right, fps, width, height)
        try:
            for t, frame in stream:
                counts['decoded_frames'] += 1
                hit = read(t, frame, source)
                if hit and hit['t'] > battle_start+3:
                    info['hits'] += 1
                    # One recognized banner is evidence, matching baseline policy.
                    return hit
        finally:
            stream.close()
        return None

    cursor = args.start
    battle_start = None
    resets = []
    try:
        while cursor < finish:
            last_present = absent = None
            streak = 0
            checked_gap = False
            restart = False
            next_progress = cursor
            stream = frames(FF, args.video, cursor, finish, 2, width, height)
            try:
                for t, frame in stream:
                    counts['decoded_frames'] += 1
                    if t >= next_progress:
                        print(f"{'Searching start' if battle_start is None else 'Tracking HUD'} {t:.1f}/{finish:.1f}s", flush=True)
                        next_progress = t+30
                    if battle_start is None:
                        hit = read(t, frame, 'search')
                        if hit:
                            observations.append(hit)
                            if hit['kind'] == 'start':
                                battle_start = hit['t']
                                print(f"Battle start {battle_start:.2f}s", flush=True)
                        continue
                    sample = dict(t=round(t, 3), **hud.read(frame))
                    hud_samples.append(sample)
                    counts['hud_frames'] += 1
                    if sample['present']:
                        streak += 1
                        if streak >= 2:
                            if absent is not None and t-absent >= 6:
                                hit = transition(
                                    max(battle_start+.5, t-2.5),
                                    min(finish, t+3),
                                    battle_start, 'transition')
                                if hit:
                                    observations.append(hit)
                                    if hit['kind'] == 'end':
                                        print(
                                            f"Battle end {hit['t']:.2f}s "
                                            "(HUD return search)",
                                            flush=True,
                                        )
                                        battle_start = None
                                    else:
                                        print(
                                            f"Restart detected at {hit['t']:.2f}s; "
                                            f"previous attempt starting at "
                                            f"{battle_start:.2f}s marked incomplete",
                                            flush=True,
                                        )
                                        resets.append({
                                            'previous_start': battle_start,
                                            'new_start': hit['t'],
                                        })
                                        battle_start = hit['t']
                                    cursor = hit['t']+.5
                                    restart = True
                                    break
                            last_present = t
                            absent = None
                            checked_gap = False
                        continue
                    streak = 0
                    if last_present is None:
                        continue
                    if absent is None:
                        absent = t
                    if checked_gap or t-absent < 15:
                        continue
                    checked_gap = True
                    hit = transition(max(battle_start+.5, last_present-2),
                                     min(finish, absent+3), battle_start, 'transition')
                    if hit:
                        observations.append(hit)
                        if hit['kind'] == 'end':
                            print(f"Battle end {hit['t']:.2f}s", flush=True)
                            battle_start = None
                        else:
                            resets.append({'previous_start': battle_start, 'new_start': hit['t']})
                            battle_start = hit['t']
                        # Revisit footage after the banner, including time spent confirming absence.
                        cursor = hit['t']+.5
                        restart = True
                        break
            finally:
                stream.close()
            if restart:
                continue
            if battle_start is not None:
                # Full unresolved interval only if visual transition recovery failed.
                hit = transition(battle_start+.5, finish, battle_start, 'fallback')
                if hit:
                    observations.append(hit)
                    if hit['kind'] == 'end':
                        battle_start = None
                    else:
                        resets.append({'previous_start': battle_start, 'new_start': hit['t']})
                        battle_start = hit['t']
                    cursor = hit['t']+.5
                    continue
            break
    finally:
        diagnostics.close()
    events = scanner.consolidate_events(observations, observations)
    segments, warnings = scanner.assemble(events)
    result = {'video': str(args.video), 'model': args.model, 'fps': 2,
              'range': [args.start, finish], 'events': events, 'segments': segments,
              'warnings': warnings, 'observations': observations,
              'adaptive_retries': retries, 'reset_candidates': resets,
              'performance': dict(counts, total_ocr_calls=counts['ocr_calls'],
                                  elapsed_seconds=round(time.perf_counter()-started, 3)),
              'scanner_version': 'experimental-state-hud-1',
              'note': 'Experimental; HUD disappearance never confirms an end without OCR.'}
    (output/'boundaries.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    (output/'hud_samples.json').write_text(json.dumps(hud_samples), encoding='utf8')


def complete_segments(result):
    return [s for s in result.get('segments', []) if s.get('start') is not None
            and s.get('end') is not None and not s.get('warnings')]


def compare(baseline, state, times):
    first, second = complete_segments(baseline), complete_segments(state)
    used = set()
    pairs = []
    for segment in first:
        choices = [(i, other) for i, other in enumerate(second) if i not in used]
        closest = min(choices, key=lambda item: abs(item[1]['start']-segment['start'])) if choices else None
        if closest:
            index, other = closest
            used.add(index)
            ds, de = other['start']-segment['start'], other['end']-segment['end']
            pairs.append({'baseline': [segment['start'], segment['end']],
                          'state_hud': [other['start'], other['end']],
                          'start_delta': round(ds, 3), 'end_delta': round(de, 3),
                          'within_1_second': abs(ds) <= 1 and abs(de) <= 1})
        else:
            pairs.append({'baseline': [segment['start'], segment['end']], 'state_hud': None,
                          'within_1_second': False})
    matched = bool(first) and len(first) == len(second) and all(p['within_1_second'] for p in pairs)
    return {'wall_seconds': times,
            'speed_ratio_baseline_over_state': round(times['baseline']/times['state_hud'], 3),
            'elapsed_reduction_percent': round(100*(1-times['state_hud']/times['baseline']), 2),
            'ocr_calls': {name: value.get('performance', {}).get('total_ocr_calls')
                          for name, value in [('baseline', baseline), ('state_hud', state)]},
            'complete_segments': {'baseline': len(first), 'state_hud': len(second)},
            'complete_segments_match_within_1_second': matched, 'comparison': pairs,
            'state_extra_segments': [s for i, s in enumerate(second) if i not in used],
            'warning': 'Compare boundary accuracy before judging speed. These are experimental detections, not ground truth. Runs are sequential; filesystem caching and CPU load can affect timing.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('--model', default='latin', choices=['latin', 'english', 'chinese', 'korean', 'eslav', 'thai'])
    parser.add_argument('--scanner', type=Path, default=Path(__file__).with_name('scan_battle_boundaries.py'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--start', type=float, default=0)
    parser.add_argument('--end', type=float)
    parser.add_argument('--hud-first', action='store_true', help='Reverse execution order to help check warm-cache effects')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.video, args.scanner = args.video.resolve(), args.scanner.resolve()
    if not args.video.is_file() or not args.scanner.is_file():
        parser.error('Video and scanner paths must exist')
    if args.start < 0 or (args.end is not None and args.end <= args.start):
        parser.error('Invalid start/end range')
    args.output = (args.output or Path('work')/('boundary_benchmark_'+time.strftime('%Y%m%d_%H%M%S'))).resolve()
    if args.worker:
        state_scan(args)
        return
    load_scanner(args.scanner)
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Choose a new empty output directory so old results cannot be mixed in')
    args.output.mkdir(parents=True, exist_ok=True)
    times, results = {}, {}
    order = ['state_hud', 'baseline'] if args.hud_first else ['baseline', 'state_hud']
    for method in order:
        destination = args.output/method
        script = args.scanner if method == 'baseline' else Path(__file__).resolve()
        command = [sys.executable, str(script), str(args.video), '--model', args.model,
                   '--start', str(args.start), '--output', str(destination)]
        if args.end is not None:
            command += ['--end', str(args.end)]
        if method == 'state_hud':
            command += ['--worker', '--scanner', str(args.scanner)]
        print(f'\nRunning {method}...', flush=True)
        started = time.perf_counter()
        with (args.output/(method+'.log')).open('w', encoding='utf8') as log:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf8', errors='replace')
            try:
                for line in process.stdout:
                    print(line, end='', flush=True)
                    log.write(line)
                    log.flush()
                code = process.wait()
            finally:
                process.stdout.close()
                if process.poll() is None:
                    process.terminate()
                    process.wait()
        times[method] = round(time.perf_counter()-started, 3)
        if code:
            raise RuntimeError(f'{method} failed (exit {code}); see {method}.log. No speed comparison made.')
        results[method] = json.loads((destination/'boundaries.json').read_text(encoding='utf8'))
    summary = compare(results['baseline'], results['state_hud'], times)
    summary.update(video=str(args.video), model=args.model, execution_order=order)
    path = args.output/'comparison.json'
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
    print('\n'+json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(f'\nSaved {path}', flush=True)


if __name__ == '__main__':
    main()
