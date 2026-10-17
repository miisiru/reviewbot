"""Isolated showcase/build test; no downloads, GP/HUD scans, or webhooks."""
import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path


def submissions(value):
    rows = value if isinstance(value, list) else value.get('runs', [value])
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise ValueError('Expected a nonempty submission array or runs object')
    indices = [row.get('side_index') for row in rows]
    if any(type(index) is not int or index < 1 for index in indices) or len(set(indices)) != len(indices):
        raise ValueError('Each submission needs a unique positive side_index for this test')
    return sorted(rows, key=lambda row: row['side_index'])


def build_checks(result):
    reasons = []
    for char in result.get('chars', []):
        name = char['char']
        reasons.extend(f'{name}: {problem}' for problem in char.get('problems', []))
        if char.get('lc_t') is None or (char.get('lc_match') or 0) < .9:
            reasons.append(f'{name}: LC identity evidence incomplete')
        if char.get('e_t') is None or char.get('e_seen') is None or char.get('e_uncertain'):
            reasons.append(f'{name}: Eidolon evidence incomplete')
        if char.get('lc_uncertain') or char.get('s_uncertain') or char.get('e_alt') is not None:
            reasons.append(f'{name}: build reading uncertain')
        counts = {candidate.get('count') for candidate in char.get('e_candidates', []) if candidate.get('clear')}
        if len(counts) > 1:
            reasons.append(f'{name}: conflicting Eidolon occurrences')
    if not result.get('chars'):
        reasons.append('No character results')
    if result.get('language_selection', {}).get('uncertain'):
        reasons.append('OCR language selection uncertain')
    return sorted(set(reasons))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('submissions')
    parser.add_argument('showcases')
    parser.add_argument('--video', help='Override the local source video path')
    parser.add_argument('--model', choices=['chinese','korean','latin','eslav','thai'])
    args = parser.parse_args()
    rows = submissions(json.loads(Path(args.submissions).read_text(encoding='utf-8-sig')))
    manifest_path = Path(args.showcases).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    source = Path(args.video or manifest['video']).resolve()
    if not source.is_file():
        parser.error(f'Video not found: {source}')
    import paths
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    output = manifest_path.parent / ('build_test_' + stamp)
    output.mkdir()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'auto'))
    # Point the existing readers at this fresh test directory only.
    paths.RUNS = str(output)
    import tabs
    import judge
    tabs.ROOT = judge.ROOT = str(output)
    results = []
    for row in rows:
        index = row['side_index']
        candidates = [c for c in manifest['showcases'] if c.get('after_battle') == index]
        run_id = row.get('submission_id') or f'side{index}'
        item = {'submission_id':run_id,'side_index':index,'status':'CHECK','reasons':[]}
        results.append(item)
        if len(candidates) != 1 or candidates[0].get('status') != 'candidate':
            item['reasons'] = ['No unique usable showcase interval; manual assignment required']
            continue
        candidate = candidates[0]
        start, end = candidate['start'], candidate['end']
        if not 0 <= start < end:
            raise ValueError('Invalid showcase interval')
        name = f'side{index}_{re.sub(r"[^A-Za-z0-9_-]", "_", run_id)}'
        directory = output / name
        directory.mkdir()
        clip = directory / 'video0.mp4'
        print(f'{run_id}: extracting showcase {start:.2f}-{end:.2f}s',flush=True)
        # A bounded clip keeps nearby-frame retries inside this showcase.
        subprocess.run([paths.FF,'-v','error','-ss',str(start),'-i',str(source),
                        '-t',str(end-start),'-an','-c:v','libx264','-preset','fast',
                        '-crf','18','-y',str(clip)],check=True)
        payload = dict(row)
        if args.model:
            payload['ocr_model'] = args.model
        (directory/'review.json').write_text(json.dumps({'payload':payload,'run_ids':[run_id]},ensure_ascii=False),encoding='utf8')
        (directory/'videos.json').write_text(json.dumps([{'file':'video0.mp4','role':'showcase','run_part':True,
                  'source_file':str(source),'source_offset':start}]),encoding='utf8')
        duration, _, _ = tabs.probe(str(clip))
        saved_argv = sys.argv
        try:
            sys.argv = ['tabs.py',name,'0','0',str(duration)]
            tabs.main()
        finally:
            sys.argv = saved_argv
        result = judge.judge(name,build_indices={0})
        item.update(directory=name,showcase=[start,end],source_offset=start,
                    reasons=build_checks(result),chars=result.get('chars',[]),
                    note='Times in judge.json refer to the showcase clip; add source_offset for original-video times. Temporal pairing is provisional.')
        item['status'] = 'BUILD_CHECK' if item['reasons'] else 'BUILD_MATCH'
        for char in item['chars']:
            for key in ['lc_t','e_t']:
                char['source_'+key] = round(start+char[key],3) if char.get(key) is not None else None
        print(f"{run_id}: {item['status']}",flush=True)
    path = output/'build_results.json'
    path.write_text(json.dumps({'video':str(source),'results':results,
               'note':'Build-only diagnostic, not an approval or verified battle/showcase ownership.'},ensure_ascii=False,indent=2),encoding='utf8')
    print(f'Saved {path}',flush=True)


if __name__ == '__main__':
    main()
