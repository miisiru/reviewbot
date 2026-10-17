"""Find showcase candidates in gaps from an existing boundaries.json."""
import argparse
import json
from pathlib import Path


def search_gaps(segments, start, end):
    complete = sorted((s for s in segments if s.get('start') is not None and s.get('end') is not None), key=lambda s: s['start'])
    if len(complete) != len(segments):
        raise ValueError('Incomplete battle boundaries: resolve CHECK segments before gap scanning')
    previous = start
    gaps = []
    for index, segment in enumerate(complete):
        if not previous <= segment['start'] < segment['end'] <= end:
            raise ValueError('Battle boundaries overlap or fall outside the scanned range')
        if segment['start'] > previous:
            gaps.append({'start': previous, 'end': segment['start'],
                         'after_battle': index if index else None})
        previous = segment['end']
    if previous < end:
        gaps.append({'start': previous, 'end': end, 'after_battle': len(complete) or None})
    return gaps


def group_hits(hits, gap_seconds=1.5):
    groups = []
    for hit in hits:
        if not groups or hit['t'] - groups[-1][-1]['t'] > gap_seconds:
            groups.append([])
        groups[-1].append(hit)
    return groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('boundaries')
    parser.add_argument('--video', help='Override the video path saved in boundaries.json')
    parser.add_argument('--fps', type=float, default=2)
    parser.add_argument('--output')
    parser.add_argument('--check-example', action='store_true')
    args = parser.parse_args()
    if args.fps <= 0:
        parser.error('fps must be positive')
    source = Path(args.boundaries).resolve()
    data = json.loads(source.read_text(encoding='utf-8-sig'))
    video = Path(args.video or data['video']).resolve()
    if not video.is_file():
        parser.error(f'Video not found: {video}; use --video to specify its location')
    import cv2
    import tabs
    duration, width, height = tabs.probe(str(video))
    start, end = data['range']
    if end > duration + 1:
        parser.error('Boundary range exceeds video duration; verify this is the same video')
    end = min(end, duration)
    try:
        gaps = search_gaps(data['segments'], start, end)
    except ValueError as error:
        parser.error(str(error))
    output = Path(args.output).resolve() if args.output else source.parent / 'showcases'
    output.mkdir(parents=True, exist_ok=True)
    scan_width = min(960, width)
    scan_height = max(1, round(height * scan_width / width))
    candidates, scans = [], []
    for index, gap in enumerate(gaps):
        print(f"Gap {index+1}/{len(gaps)}: {gap['start']:.2f}-{gap['end']:.2f}s", flush=True)
        hits = []
        last_layout = None
        gap_dir = output / f'gap{index+1}'
        gap_dir.mkdir(exist_ok=True)
        for frame_index, (t, frame) in enumerate(tabs.frames(str(video), gap['start'], gap['end']-gap['start'], args.fps, scan_width, scan_height)):
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            found = tabs.find_layout_near(gray, last_layout) if last_layout else None
            if found is None:
                found = tabs.find_layout(gray)
            if found is None:
                continue
            score, x, y, spacing = found
            last_layout = (x, y, spacing)
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            tab = tabs.which_tab(tabs.pale_gold(hsv, last_layout), tabs.gold_rows(hsv, last_layout))
            filename = f'{frame_index:04d}_{t:.3f}_{tab or "menu"}.jpg'
            saved = cv2.imwrite(str(gap_dir / filename), frame)
            hits.append({'t': round(t,3), 'tab': tab, 'layout_score': round(float(score),3),
                         'layout': [float(x),float(y),float(spacing)],
                         'evidence': f'gap{index+1}/{filename}' if saved else None})
        scans.append(dict(gap, menu_frames=len(hits), observations=hits))
        for group in group_hits(hits, max(1.5, 2/args.fps)):
            builds = [h for h in group if h['tab'] in ('LightCone','Eidolon')]
            warning = []
            if len(group) < 3:
                warning.append('Fewer than three menu samples')
            if not builds:
                warning.append('No LC or Eidolon tab confirmed')
            candidates.append({'start':group[0]['t'], 'end':group[-1]['t'],
                               'search_window':[gap['start'],gap['end']],
                               'after_battle':gap['after_battle'],
                               'status':'CHECK' if warning else 'candidate',
                               'warnings':warning, 'menu_frames':len(group),
                               'tabs':sorted({h['tab'] for h in group if h['tab']}),
                               'first_evidence':group[0]['evidence'], 'last_evidence':group[-1]['evidence']})
    result = {'video':str(video), 'boundaries':str(source), 'fps':args.fps,
              'showcases':candidates, 'gap_scans':scans,
              'note':'Menu intervals are showcase candidates. after_battle is temporal proximity, not verified build ownership. No reviews or OCR were run.'}
    if args.check_example:
        expected = [(187,205),(508,525),(716,728)]
        comparison = []
        for battle,(a,b) in enumerate(expected,1):
            choices = [c for c in candidates if c['after_battle']==battle]
            comparison.append({'battle':battle,'expected':[a,b],
                               'candidates':[[c['start'],c['end']] for c in choices],
                               'unique_candidate':len(choices)==1})
        result['example_comparison'] = comparison
    path = output / 'showcases.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    for candidate in candidates:
        print(f"  Showcase candidate {candidate['start']:.2f}-{candidate['end']:.2f}s after battle {candidate['after_battle']} ({candidate['status']})",flush=True)
    print(f'Saved {path}',flush=True)


if __name__ == '__main__':
    main()
