"""Persistent submission references and long-video admission policy.

The runner is the sole writer. prep reads the same registry.
"""
import json
import math
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qs, urlsplit

from paths import WORK

REGISTRY = Path(WORK) / 'video_cache' / 'submission_references.json'
NORMAL_SECONDS = 20 * 60
HARD_SECONDS = 60 * 60


def url_key(value):
    # Some copied youtu.be URLs use &t= without a preceding question mark.
    value = re.sub(r'(youtu\.be/[^?&#/]+)&', r'\1?', value.strip(), count=1)
    parsed = urlsplit(value)
    host = (parsed.hostname or '').lower().removeprefix('www.')
    query = parse_qs(parsed.query)
    if host == 'youtu.be' or host in ('youtube.com', 'm.youtube.com', 'music.youtube.com'):
        parts = parsed.path.strip('/').split('/')
        ident = (parts[0] if host == 'youtu.be' else
                 query.get('v', [''])[0] or
                 (parts[1] if len(parts) > 1 and parts[0] in ('shorts', 'embed', 'live') else ''))
        if ident:
            return 'youtube:' + ident
    match = re.search(r'/video/(BV[0-9A-Za-z]+)', parsed.path)
    if (host == 'bilibili.com' or host.endswith('.bilibili.com')) and match:
        part = query.get('p', ['1'])[0]
        return f'bilibili:{match[1]}:p{int(part) if part.isdigit() else 1}'
    return parsed._replace(query='', fragment='').geturl()


def local_key(value):
    return 'local:' + os.path.normcase(str(Path(value.strip()).resolve()))


def payload_keys(payload):
    keys = set()
    for side in payload.get('runs') or [payload]:
        local = [side.get(k, '').strip() for k in ('local_battle_video', 'local_showcase_video')]
        if any(local):
            keys.update(local_key(value) for value in local if value)
        elif side.get('video_url'):
            keys.add(url_key(side['video_url']))
    return sorted(keys)


def load_registry():
    if not REGISTRY.exists():
        return {'version': 1, 'submissions': {}}
    data = json.loads(REGISTRY.read_text(encoding='utf8'))
    if data.get('version') != 1 or not isinstance(data.get('submissions'), dict):
        raise ValueError(f'Invalid submission reference registry: {REGISTRY}')
    return data


def save_registry(data):
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='references-', suffix='.tmp', dir=REGISTRY.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, REGISTRY)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def register_items(items):
    data = load_registry()
    changed = False
    for item in items:
        old = data['submissions'].get(item['id'], {})
        record = dict(old, item=item, keys=payload_keys(item['payload']))
        if record != old:
            data['submissions'][item['id']] = record
            changed = True
    if changed:
        save_registry(data)
    return data


def reference_count(key, data=None):
    data = load_registry() if data is None else data
    ids = set()
    for rid, record in data['submissions'].items():
        if key not in record.get('keys', []):
            continue
        payload = record['item']['payload']
        for index, side in enumerate(payload.get('runs') or [payload]):
            if key in payload_keys(side):
                # A combined payload may have several real submission IDs.
                ident = side.get('submission_id') or (payload.get('run_ids') or [])[index:index+1]
                if isinstance(ident, list):
                    ident = ident[0] if ident else rid
                ids.add(ident or rid)
    return len(ids)


def duration_decision(seconds, key, data=None):
    if not math.isfinite(seconds) or seconds <= 0:
        return {'reason': 'Could not read video duration', 'deferred': False, 'key': key}
    if seconds >= HARD_SECONDS:
        return {'reason': 'Video is 60 minutes or longer; not analyzed', 'deferred': False, 'key': key}
    if seconds > NORMAL_SECONDS and reference_count(key, data) < 2:
        return {'reason': 'Video over 20 minutes; waiting for a second distinct submission referencing this video',
                'deferred': True, 'key': key}
    return None


def mark_result(item, result):
    data = load_registry()
    record = data['submissions'].get(item['id'])
    if record is None:
        return
    waiting = result.get('long_video_waiting', [])
    if waiting:
        record['deferred_keys'] = sorted(set(waiting))
    else:
        record.pop('deferred_keys', None)
    save_registry(data)


def eligible(record, data):
    keys = record.get('deferred_keys', [])
    return bool(keys) and all(reference_count(key, data) >= 2 for key in keys)


def pending_items(items, processed, data):
    candidates = {item['id']: item for item in items}
    for rid, record in data['submissions'].items():
        if eligible(record, data):
            candidates.setdefault(rid, record['item'])
    pending = []
    for rid, item in candidates.items():
        record = data['submissions'].get(rid, {})
        if record.get('deferred_keys'):
            if eligible(record, data):
                pending.append(item)
        elif rid not in processed:
            pending.append(item)
    return pending
