"""Compare sequential vs overlapping boundary/GP scans without Discord delivery."""
import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
MODELS = ('chinese', 'korean', 'latin', 'eslav', 'thai')


def save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')


def gp_worker(args):
    sys.path.insert(0, str(HERE))
    import gp
    import ocr
    ocr.set_gpu(False)
    result = gp.scan(args.run, args.vid, model=args.model, fps=4,
                     start=args.start, end=args.end)
    save(args.output, result)


def boundary_signature(result):
    return {
        'events': [{k: event.get(k) for k in
                    ('kind', 'wave', 'total_waves', 't', 'last_t', 'text', 'score')}
                   for event in result['events']],
        'segments': result['segments'], 'warnings': result['warnings'],
    }


def gp_signature(result):
    return {k: result.get(k) for k in ('seen', 'hits', 'frames', 'ocr_calls')}


def trial(args, mode, label, directory, video, env, psutil):
    output = directory / label
    output.mkdir()
    boundary = [sys.executable, '-u', str(HERE / 'scan_battle_boundaries.py'),
                str(video), '--model', args.model, '--fps', '4',
                '--output', str(output / 'boundaries')]
    gp_command = [sys.executable, '-u', str(Path(__file__).resolve()),
                  args.run, '--worker', '--vid', str(args.vid), '--model', args.model,
                  '--start', str(args.start), '--end', str(args.end),
                  '--output', str(output / 'gp.json')]
    handles, processes, timings = {}, {}, {}
    seen = {}
    samples = []
    started = time.perf_counter()
    psutil.cpu_percent(None)

    def launch(name, command):
        handles[name] = (output / f'{name}.log').open('w', encoding='utf8')
        processes[name] = subprocess.Popen(command, stdout=handles[name],
                                           stderr=subprocess.STDOUT, env=env)
        timings[name] = {'start_seconds': time.perf_counter() - started}
        print(f'{label}: {name} started', flush=True)

    launch('boundary', boundary)
    gp_started = False
    try:
        while True:
            elapsed = time.perf_counter() - started
            if not gp_started and (
                (mode == 'parallel' and elapsed >= args.gp_delay)
                or (mode == 'sequential' and processes['boundary'].poll() is not None)
            ):
                if processes['boundary'].poll() not in (None, 0):
                    raise RuntimeError(f'{label}: boundary scanner failed; see boundary.log')
                launch('gp', gp_command)
                gp_started = True

            live = {}
            for process in processes.values():
                try:
                    parent = psutil.Process(process.pid)
                    for child in [parent] + parent.children(recursive=True):
                        live[(child.pid, child.create_time())] = child
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            cpu, rss = 0.0, 0
            for key, process in live.items():
                try:
                    rss += process.memory_info().rss
                    if key not in seen:
                        process.cpu_percent(None)
                        seen[key] = process
                    else:
                        cpu += seen[key].cpu_percent(None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            samples.append({'elapsed_seconds': round(elapsed, 3),
                            'worker_cpu_percent': round(cpu, 2),
                            'machine_cpu_percent': psutil.cpu_percent(None),
                            'worker_rss_mib': round(rss / 1048576, 2),
                            'processes': len(live)})
            for name, process in processes.items():
                code = process.poll()
                if code is not None and 'end_seconds' not in timings[name]:
                    timings[name].update(end_seconds=elapsed, exit_code=code)
                    print(f'{label}: {name} finished, exit {code}', flush=True)
                    if code:
                        raise RuntimeError(f'{label}: {name} failed; see {name}.log')
            if gp_started and all(process.poll() is not None for process in processes.values()):
                break
            time.sleep(.25)
    finally:
        # Only terminate processes created by this benchmark.
        for process in processes.values():
            if process.poll() is None:
                try:
                    parent = psutil.Process(process.pid)
                    children = parent.children(recursive=True)
                    for child in children:
                        try:
                            child.terminate()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    parent.terminate()
                    _, alive = psutil.wait_procs(children + [parent], timeout=3)
                    for child in alive:
                        try:
                            child.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        for handle in handles.values():
            handle.close()

    elapsed = time.perf_counter() - started
    with (output / 'samples.csv').open('w', newline='', encoding='utf8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(samples[0]))
        writer.writeheader()
        writer.writerows(samples)
    # Weighted sample averages; 100% worker CPU corresponds to one logical core.
    duration = sum(b['elapsed_seconds'] - a['elapsed_seconds'] for a, b in zip(samples, samples[1:]))
    def average(key):
        return sum((b['elapsed_seconds'] - a['elapsed_seconds']) * b[key]
                   for a, b in zip(samples, samples[1:])) / max(duration, .001)
    boundary_data = json.loads((output / 'boundaries' / 'boundaries.json').read_text(encoding='utf8'))
    gp_data = json.loads((output / 'gp.json').read_text(encoding='utf8'))
    result = {'label': label, 'mode': mode, 'elapsed_seconds': round(elapsed, 2),
              'worker_cpu_average_percent': round(average('worker_cpu_percent'), 2),
              'machine_cpu_average_percent': round(average('machine_cpu_percent'), 2),
              'worker_rss_peak_mib': max(s['worker_rss_mib'] for s in samples),
              'timings': timings, 'boundaries': boundary_signature(boundary_data),
              'gp': gp_signature(gp_data)}
    save(output / 'trial.json', result)
    print(f"{label}: {elapsed:.1f}s, peak worker RAM {result['worker_rss_peak_mib']:.0f} MiB", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', help='Existing run folder ID containing the downloaded video')
    parser.add_argument('--vid', type=int, default=0)
    parser.add_argument('--model', choices=MODELS, default='latin')
    parser.add_argument('--start', type=float, required=True, help='GP battle start in original video seconds')
    parser.add_argument('--end', type=float, required=True, help='GP battle end in original video seconds')
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--threads', type=int, default=2, help='OCR thread limit per process, identical in both modes')
    parser.add_argument('--gp-delay', type=float, default=0, help='Parallel-mode delay before GP launches; 0 tests full overlap')
    parser.add_argument('--output')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.start < 0 or args.end <= args.start or args.repeats < 1 or args.threads < 1 or args.gp_delay < 0:
        parser.error('Invalid interval, repeats, threads or GP delay')
    if args.worker:
        gp_worker(args)
        return
    try:
        import psutil
    except ImportError:
        parser.error('Install the measurement dependency: python -m pip install psutil')
    sys.path.insert(0, str(HERE))
    from paths import RUNS, WORK
    import tabs
    run = Path(RUNS) / args.run
    if run.resolve().parent != Path(RUNS).resolve():
        parser.error('Use a run folder ID, not a path')
    entries = json.loads((run / 'videos.json').read_text(encoding='utf8'))
    if not 0 <= args.vid < len(entries):
        parser.error('Video index is outside videos.json')
    video = (run / entries[args.vid]['file']).resolve()
    if not video.is_file():
        parser.error('Downloaded video is missing')
    duration, _, _ = tabs.probe(str(video))
    if args.end > duration:
        parser.error('GP interval exceeds video duration')
    directory = Path(args.output).resolve() if args.output else Path(WORK) / 'benchmarks' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    directory.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, OCR_THREADS=str(args.threads), OCR_GPU='0',
               OMP_NUM_THREADS=str(args.threads), MKL_NUM_THREADS=str(args.threads),
               PYTHONIOENCODING='utf8')
    save(directory / 'settings.json', {'run': args.run, 'video': str(video),
         'model': args.model, 'gp_interval': [args.start, args.end], 'repeats': args.repeats,
         'ocr_threads_per_process': args.threads, 'gp_delay': args.gp_delay,
         'logical_cpus': psutil.cpu_count(),
         'note': 'Fresh CPU-only processes. No analysis caches or Discord calls. Operating-system disk cache is not cleared. CPU and RSS are sampled estimates; shared memory may be counted twice. GP comparison covers the detector\'s returned hits (currently capped at 20).'} )
    results = []
    for repeat in range(1, args.repeats + 1):
        order = ('sequential', 'parallel') if repeat % 2 else ('parallel', 'sequential')
        for mode in order:
            results.append(trial(args, mode, f'{mode}_{repeat}', directory, video, env, psutil))
    sequential = [r for r in results if r['mode'] == 'sequential']
    parallel = [r for r in results if r['mode'] == 'parallel']
    a = statistics.median(r['elapsed_seconds'] for r in sequential)
    b = statistics.median(r['elapsed_seconds'] for r in parallel)
    baseline = results[0]
    summary = {'sequential_median_seconds': a, 'parallel_median_seconds': b,
               'parallel_time_saved_percent': round(100 * (a-b) / max(a,.001), 2),
               'all_boundary_results_identical': all(r['boundaries']==baseline['boundaries'] for r in results),
               'all_gp_results_identical': all(r['gp']==baseline['gp'] for r in results),
               'trials': results}
    save(directory / 'summary.json', summary)
    print(f'Sequential median {a:.1f}s; parallel median {b:.1f}s; time saved {summary["parallel_time_saved_percent"]:.1f}%', flush=True)
    print(f'Boundary results identical: {summary["all_boundary_results_identical"]}; GP results identical: {summary["all_gp_results_identical"]}', flush=True)
    print(f'Send this file: {directory / "summary.json"}', flush=True)


if __name__ == '__main__':
    main()
