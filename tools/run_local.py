"""Analyze local submission JSON and optionally post the report to Discord."""
import time
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import shutil
from urllib.parse import urlsplit

from paths import RUNS, WORK, PY, config
from report import report, as_text, video_key, check_result, attach_sheets
from webhook import post
import video_policy

HERE = Path(__file__).resolve().parent


def normalize(data):
    inputs = data if isinstance(data, list) else [data]
    if not inputs:
        raise ValueError('Input list must not be empty')
    items, seen = [], set()
    for payload in inputs:
        if not isinstance(payload, dict):
            raise ValueError('Each submission must be a JSON object')
        sides = payload.get('runs', [payload])
        if not isinstance(sides, list) or not sides:
            raise ValueError('runs must be a nonempty list')
        for side in sides:
            if not isinstance(side, dict):
                raise ValueError('Each run must be an object')
            if not isinstance(side.get('mode'), str) or not side['mode'].strip():
                raise ValueError('Missing or invalid mode')

            local_keys = ('local_battle_video', 'local_showcase_video')
            is_local = any(bool(side.get(key)) for key in local_keys)

            if is_local:
                for key in local_keys:
                    value = side.get(key, '')
                    if not isinstance(value, str):
                        raise ValueError(f'{key} must be a string')

                    if not value.strip():
                        continue

                    path = Path(value.strip())
                    if (
                        not path.is_absolute()
                        or not path.is_file()
                        or path.stat().st_size == 0
                    ):
                        raise ValueError(f'{key}: file missing or empty')

                    if path.suffix.lower() != '.mp4':
                        raise ValueError(f'{key}: use an MP4 file')

                if len(sides) != 1:
                    raise ValueError('Local video inputs require one run')

                if not isinstance(side.get('video_url', ''), str):
                    raise ValueError('video_url must be a string')
            else:
                value = side.get('video_url')
                if not isinstance(value, str) or not value.strip():
                    raise ValueError('Missing or invalid video_url')

                url = urlsplit(value)
                if url.scheme not in ('http', 'https') or not url.hostname:
                    raise ValueError('video_url must be an HTTP(S) URL')
            character_count = 0

            for i in range(1, 5):
                char = side.get(f'p{i}_char')

                if char is None or (
                    isinstance(char, str) and not char.strip()
                ):
                    continue

                if not isinstance(char, str):
                    raise ValueError(f'p{i}_char must be a string')

                character_count += 1

                lc_key = f'p{i}_lc'
                if not isinstance(side.get(lc_key), str):
                    raise ValueError(f'Missing or invalid {lc_key}')

                for suffix, low, high in (
                    ('eidolon', 0, 6),
                    ('superimp', 1, 5),
                ):
                    key = f'p{i}_{suffix}'
                    value = side.get(key)

                    if type(value) is not int or not low <= value <= high:
                        raise ValueError(
                            f'{key} must be an integer from {low} to {high}'
                        )

            if character_count == 0:
                raise ValueError('Each run must have at least one character')
            
            metric = side.get('metric_value')
            if type(metric) not in (int, float) or not math.isfinite(metric) or metric < 0:
                raise ValueError('metric_value must be a nonnegative finite number')
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        rid = payload.get('submission_id') or f'local_{digest}'
        if not isinstance(rid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', rid):
            raise ValueError('submission_id must contain only letters, digits, underscores or hyphens (max 100)')
        if rid in seen:
            raise ValueError(f'Duplicate submission_id: {rid}')
        seen.add(rid)
        items.append({'id': rid, 'payload': payload, 'run_ids': [rid]})
    return items


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def stage(name, args, env, directory):
    print(f'{directory.name}: {name}', flush=True)
    with (directory / f'{name}.log').open('w', encoding='utf8') as log:
        process = subprocess.Popen(
            [PY, "-u", str(HERE / f'{name}.py'), *args],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf8",
            errors="replace"
        )
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
        process.wait()
    if process.returncode:
        raise RuntimeError(f'{name} failed (exit {process.returncode}); see {name}.log')


class DeferredLongVideo(Exception):
    def __init__(self, decision):
        self.decision = decision
        super().__init__(decision['reason'])


def analyze(item, items):
    rid = item['id']
    directory = Path(RUNS) / rid
    directory.mkdir(parents=True, exist_ok=True)
    previous = directory / 'review.json'
    def evidence_input(value):
        value = json.loads(json.dumps(value))

        def clean(obj):
            if isinstance(obj, dict):
                obj.pop('allow_timestamps', None)
                for key in ('local_battle_video', 'local_showcase_video'):
                    if obj.get(key) == "":
                        obj.pop(key, None)
                for child in obj.values():
                    clean(child)
            elif isinstance(obj, list):
                for child in obj:
                    clean(child)

        clean(value)
        return value

    if previous.exists():
        old_item = json.loads(previous.read_text(encoding='utf8'))
        if evidence_input(old_item) != evidence_input(item):
            raise ValueError(
                f'{rid}: existing evidence belongs to different input; '
                'use a new submission_id'
            )
    save(previous, item)
    # Discard old judgments before retrying, while retaining downloaded videos.
    for name in ('auto.json', 'auto_cache.json', 'report.json', 'webhook_status.json'):
        (directory / name).unlink(missing_ok=True)
    payload = item['payload']
    sides = payload.get('runs') or [payload]
    is_local = any(
        bool(payload.get(key, '').strip())
        for key in ('local_battle_video', 'local_showcase_video')
    )
    reason = None
    if is_local:
        pass
    elif len(sides) > 1:
        reason = 'Combined submissions require manual review; the original pipeline supports one run at a time'
    result = check_result(reason) if reason else None
    if result is None:
        queue = directory / 'input.json'
        save(queue, [item])
        env = dict(os.environ, HQ_QUEUE=str(queue), PYTHONIOENCODING='utf8')
        try:
            if is_local:
                import tabs

                battle_path = payload.get(
                    'local_battle_video', ''
                ).strip()
                showcase_path = payload.get(
                    'local_showcase_video', ''
                ).strip()

                battle_source = Path(
                    battle_path or showcase_path
                ).resolve()
                showcase_source = Path(
                    showcase_path or battle_path
                ).resolve()

                same_video = os.path.samefile(
                    battle_source, showcase_source
                )

                sources = [
                    ('local_battle_video', battle_source, 'battle')
                ]

                if not same_video:
                    sources.append((
                        'local_showcase_video',
                        showcase_source,
                        'showcase',
                    ))

                entries = []

                for index, (key, source, role) in enumerate(sources):
                    destination = directory / f'video{index}.mp4'

                    if source != destination.resolve():
                        shutil.copy2(source, destination)

                    duration, _, _ = tabs.probe(str(destination))
                    if not math.isfinite(duration) or duration <= 0:
                        raise ValueError(
                            f'{key}: could not read video duration'
                        )
                    decision = video_policy.duration_decision(
                        duration, video_policy.local_key(str(source))
                    )
                    if decision:
                        if decision['deferred']:
                            raise DeferredLongVideo(decision)
                        raise ValueError(decision['reason'])

                    entries.append({
                        'file': destination.name,
                        'role': role,
                        'run_part': role == 'battle',
                        'part': 1,
                        'parts': 1,
                        'src': '',
                        'url': '',
                    })

                save(directory / 'videos.json', entries)
                (directory / 'too_long.json').unlink(missing_ok=True)

                if same_video:
                    print(
                        f'{rid}: battle and showcase share one video',
                        flush=True,
                    )
            else:
                stage('prep', [rid], env, directory)
            long_path = directory / 'too_long.json'
            if long_path.exists():
                blocked = json.loads(long_path.read_text(encoding='utf8'))
                result = check_result('; '.join(dict.fromkeys(
                    entry.get('reason', 'Video exceeds duration policy; not analyzed')
                    for entry in blocked
                )))
                if blocked and all(entry.get('deferred') for entry in blocked):
                    result['long_video_waiting'] = [entry['key'] for entry in blocked]
            else:
                videos = json.loads((directory / 'videos.json').read_text(encoding='utf8'))
                if not videos or any(not (directory / v['file']).is_file() or
                                     (directory / v['file']).stat().st_size == 0 for v in videos):
                    result = check_result('Video could not be downloaded; see prep.log and video*.info')
                else:
                    from segment_pipeline import prepare, extract_build
                    selection = prepare(directory, payload, videos)
                    from battle_sheets import generate
                    try:
                        generate(directory, videos, selection)
                    except (OSError, ValueError, RuntimeError) as exc:
                        print(f'{rid}: battle sheets unavailable: {exc}; continuing analysis', flush=True)
                    extract_build(directory, videos, selection, env)
                    stage('auto_judge', [rid], env, directory)
                    result = json.loads((directory / 'auto.json').read_text(encoding='utf8'))
        except DeferredLongVideo as exc:
            result = check_result(exc.decision['reason'])
            result['long_video_waiting'] = [exc.decision['key']]
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            result = check_result(str(exc))
    save(directory / 'auto.json', result)
    embed = report(rid, result, item)
    save(directory / 'report.json', {'embeds': [embed], 'allowed_mentions': {'parse': []}})
    print(as_text(embed), flush=True)
    return directory, result


def main(argv=None):
    
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('submission', type=Path)
    parser.add_argument('--no-webhook', action='store_true')
    parser.add_argument('--validate-only', action='store_true')
    parser.add_argument(
        '--watch',
        action='store_true',
        help='Keep waiting for new submissions'
    )
    parser.add_argument(
        '--poll',
        type=float,
        default=10,
        help='Seconds between idle checks (default: 10)'
    )
    args = parser.parse_args(argv)

    if not math.isfinite(args.poll) or args.poll <= 0:
        parser.error('--poll must be a positive finite number')

    def read_items():
        data = json.loads(
            args.submission.read_text(encoding='utf-8-sig')
        )
        # An empty array is a valid empty queue.
        return [] if data == [] else normalize(data)

    try:
        if args.validate_only:
            items = read_items()
            print(f'Valid: {len(items)} submission(s)')
            return 0

        if not args.no_webhook and not (
            os.environ.get('DISCORD_WEBHOOK_URL')
            or config().get('discord_webhook')
        ):
            raise ValueError(
                'Set DISCORD_WEBHOOK_URL or config.json '
                'discord_webhook, or pass --no-webhook'
            )

        Path(WORK).mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2

    processed = set()
    failed = False
    last_notice = None
    waiting_notified = False
    has_processed = False
    startup_notified = False

    def queue_message(content):
        if args.no_webhook:
            return
        try:
            post('discord_webhook', {
                'content': content,
                'allowed_mentions': {'parse': []}
            })
        except Exception:
            print(
                'Queue notification could not be sent.',
                file=sys.stderr,
                flush=True
            )

    def notice(text):
        nonlocal last_notice
        if text != last_notice:
            print(text, flush=True)
            last_notice = text

    try:
        while True:
            try:
                # Validate the complete file before selecting a run.
                items = read_items()
                references = video_policy.register_items(items)
            except (OSError, ValueError) as exc:
                if not args.watch:
                    print(f'Error: {exc}', file=sys.stderr)
                    return 2

                notice(
                    f'Queue unavailable or invalid: {exc}\n'
                    f'Waiting for a valid file; checking every '
                    f'{args.poll:g} seconds.'
                )
                time.sleep(args.poll)
                continue

            pending = video_policy.pending_items(items, processed, references)
            # Revalidate stored payloads before reconsidering deferred runs.
            validated_pending = []
            for candidate in pending:
                try:
                    validated_pending.append(normalize(candidate['payload'])[0])
                except (OSError, ValueError) as exc:
                    print(f'{candidate["id"]}: saved submission is no longer valid: {exc}',
                          file=sys.stderr, flush=True)
                    video_policy.mark_result(candidate, check_result(str(exc)))
                    processed.add(candidate['id'])
            pending = validated_pending

            if not startup_notified:
                startup_notified = True
                queue_message(
                    f'▶️ Starting reviews with {len(pending)} '
                    f'submission(s) in queue.'
                )

            if not pending:
                if has_processed and not waiting_notified:
                    waiting_notified = True
                    queue_message(
                        '✅ Queue finished. All queued submissions '
                        'have been attempted.'
                        + (
                            ' Waiting for new submissions.'
                            if args.watch else ''
                        )
                    )

                if not args.watch:
                    return 1 if failed else 0

                notice(
                    f'Waiting for new submissions '
                    f'(checking every {args.poll:g} seconds). '
                    f'Press Ctrl+C to stop.'
                )
                time.sleep(args.poll)
                continue

            if waiting_notified:
                waiting_notified = False
                queue_message(
                    f'▶️ Continuing with {len(pending)} new '
                    f'submission(s) in queue.'
                )

            # Process one run, then reload the file immediately.
            item = pending[0]
            last_notice = None

            try:
                directory, result = analyze(item, items)
                video_policy.mark_result(item, result)

                # Reload the queue in case it grew during analysis.
                try:
                    latest_items = read_items()
                    video_policy.register_items(latest_items)
                except (OSError, ValueError):
                    latest_items = items
                    print(
                        'Queue count uses the last valid file.',
                        flush=True
                    )

                # Count attempts this session, including failed runs.
                attempted_ids = processed | {item['id']}
                queued_ids = {entry['id'] for entry in latest_items}

                position = len(attempted_ids)
                total = len(attempted_ids | queued_ids)

                report_path = directory / 'report.json'
                report_payload = json.loads(
                    report_path.read_text(encoding='utf8')
                )

                for embed in report_payload.get('embeds', []):
                    footer = embed.setdefault('footer', {})
                    text = footer.get('text', '')
                    footer['text'] = (
                        f'{text} • Queue: {position}/{total}'
                        if text else f'Queue: {position}/{total}'
                    )

                save(report_path, report_payload)
                print(f'Queue: {position}/{total}', flush=True)

                with (
                    Path(WORK) / 'results.jsonl'
                ).open('a', encoding='utf8') as log:
                    log.write(
                        json.dumps({
                            'id': item['id'],
                            'verdict': result['verdict'],
                            'confidence': result['confidence']
                        }) + '\n'
                    )

                if not args.no_webhook:
                    try:
                        payload = json.loads(
                            (directory / 'report.json')
                            .read_text(encoding='utf8')
                        )
                        payload, files = attach_sheets(
                            directory, payload
                        )

                        status = post(
                            'discord_webhook',
                            payload,
                            files=files,
                        )
                        save(
                            directory / 'webhook_status.json',
                            {
                                'sent': True,
                                'http_status': status
                            }
                        )
                    except Exception:
                        save(
                            directory / 'webhook_status.json',
                            {'sent': False}
                        )
                        print(
                            f'{item["id"]}: Discord delivery failed; '
                            'report.json is saved',
                            file=sys.stderr
                        )
                        failed = True

            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                video_policy.mark_result(item, check_result(str(exc)))
                print(
                    f'{item["id"]}: processing failed: {exc}',
                    file=sys.stderr
                )
                failed = True

            # Deferred runs become eligible again only after another reference arrives.
            processed.add(item['id'])
            has_processed = True

    except KeyboardInterrupt:
        print('\nStopped.', flush=True)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
