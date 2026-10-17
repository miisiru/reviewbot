"""Shared Bilibili downloads and submission-independent frame extraction."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from paths import WORK

ROOT = Path(WORK) / 'video_cache'

def fingerprint(paths, extra=''):
    digest = hashlib.sha256(extra.encode())
    for path in sorted(map(Path, paths)):
        digest.update(path.name.encode())
        if path.is_file():
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
    return digest.hexdigest()

def part_cache(entry):
    key = entry.get('key')
    if isinstance(key, str):
        from segment_pipeline import canonical
        identity = canonical(entry.get('url') or key)
        if identity.startswith('youtube:'):
            return ROOT / 'online' / hashlib.sha256(identity.encode()).hexdigest()
        return None
    if not isinstance(key, list) or len(key) != 2:
        return None
    bv, part = key
    if not isinstance(bv, str) or not re.fullmatch(r'BV[0-9A-Za-z]+', bv):
        return None
    if type(part) is not int or part < 1:
        return None
    return ROOT / bv / f'p{part}'

def content_hash(path):
    digest = hashlib.sha256()

    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)

    return digest.hexdigest()

def restore(source, destination):
    source, destination = Path(source), Path(destination)
    marker = source / 'complete.json'
    if not marker.is_file():
        return False
    try:
        manifest = json.loads(marker.read_text())
        files = manifest['files']
        if not files or any(not (source / name).is_file() or (source / name).stat().st_size != size for name, size in files.items()):
            return False
        destination.mkdir(parents=True, exist_ok=True)
        for name in files:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, target)
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False

def publish(source, destination):
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.pending-', dir=destination.parent))
    try:
        files = {}
        for path in source.rglob('*'):
            if path.is_file() and path.name != 'complete.json':
                relative = path.relative_to(source)
                target = temporary / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                files[str(relative)] = path.stat().st_size
        if not files:
            return
        (temporary / 'complete.json').write_text(json.dumps({'files': files}))
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
