"""Contact sheets scoped to one detected battle, cached by video and interval."""
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont
from paths import FF
import video_cache

VERSION = 'battle-sheets-1'
EVERY = 3
WIDTH = 480
COLUMNS = ROWS = 5


def _font():
    candidates = [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'consola.ttf',
                  Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), 20)
    return ImageFont.load_default()


def _label(seconds):
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, ms = divmod(remainder, 1000)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}'


def _extract(video, start, end, temporary):
    frames = temporary / 'frames'
    frames.mkdir()
    log_path = temporary / 'ffmpeg.log'
    # Select the first frame and then frames at least EVERY seconds apart.
    # showinfo records the actual selected timestamps before resizing.
    vf = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t,{EVERY})',showinfo,scale={WIDTH}:-2"
    with log_path.open('w', encoding='utf8') as log:
        process = subprocess.run(
            [str(FF), '-hide_banner', '-loglevel', 'info', '-ss', str(start),
             '-t', str(end-start), '-i', str(video), '-an', '-vf', vf,
             '-vsync', '0', '-q:v', '3', '-y', str(frames / '%06d.jpg')],
            stdout=subprocess.DEVNULL, stderr=log,
        )
    if process.returncode:
        raise RuntimeError('Battle sheet frame extraction failed: ' + log_path.read_text(encoding='utf8')[-1500:])
    paths = sorted(frames.glob('*.jpg'))
    times = [start + float(t) for t in re.findall(
        r'\bpts_time:([\d.eE+-]+)', log_path.read_text(encoding='utf8'))]
    if not paths or len(paths) != len(times):
        raise RuntimeError('Battle sheet frame/timestamp count is inconsistent')
    samples = list(zip(paths, times))
    # Include the detected end, or a nearby preceding frame at file EOF.
    end_frame = temporary / 'end.jpg'
    captured_end = None
    for target in dict.fromkeys((end, max(start, end-.1), max(start, end-.5))):
        end_frame.unlink(missing_ok=True)
        result = subprocess.run(
            [str(FF), '-hide_banner', '-loglevel', 'error', '-ss', str(target),
             '-i', str(video), '-an', '-frames:v', '1', '-vf', f'scale={WIDTH}:-2',
             '-q:v', '3', '-y', str(end_frame)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            encoding='utf8', errors='replace',
        )
        if result.returncode == 0 and end_frame.is_file() and end_frame.stat().st_size:
            captured_end = target
            break
    if captured_end is None:
        raise RuntimeError('Could not extract a frame at or near the detected battle end')
    if captured_end > samples[-1][1] + .02:
        samples.append((end_frame, captured_end))
    return samples


def _render(samples, destination):
    font = _font()
    pages = []
    per_page = COLUMNS * ROWS
    with Image.open(samples[0][0]) as first:
        height = first.height
    for page_index, offset in enumerate(range(0, len(samples), per_page), 1):
        group = samples[offset:offset+per_page]
        canvas = Image.new('RGB', (WIDTH*COLUMNS, height*ROWS), 'black')
        for tile, (path, timestamp) in enumerate(group):
            with Image.open(path) as source:
                frame = source.convert('RGB')
            if frame.size != (WIDTH, height):
                frame = frame.resize((WIDTH, height))
            draw = ImageDraw.Draw(frame)
            label = _label(timestamp)
            box = draw.textbbox((5, 5), label, font=font)
            draw.rectangle((0, 0, box[2]+5, box[3]+5), fill='black')
            draw.text((5, 5), label, font=font, fill='yellow')
            canvas.paste(frame, ((tile % COLUMNS)*WIDTH, (tile // COLUMNS)*height))
        name = f'{page_index:02d}.jpg'
        canvas.save(destination / name, quality=88)
        pages.append({'file': name, 'timestamps': [t for _, t in group]})
    return pages


def generate(directory, videos, selection):
    directory = Path(directory)
    index = selection['battle_index']
    start, end = selection['battle']
    if not all(type(v) in (int, float) and math.isfinite(v) for v in (start, end)) or not 0 <= start < end:
        raise ValueError('Invalid battle interval for sheet generation')
    video = directory / videos[index]['file']
    signature = video_cache.fingerprint(
        [__file__], extra=json.dumps({'version': VERSION, 'video': video_cache.content_hash(video),
                                     'battle': [start, end], 'every': EVERY, 'width': WIDTH,
                                     'columns': COLUMNS, 'rows': ROWS}, sort_keys=True),
    )
    cache = video_cache.ROOT / 'battle_sheets' / signature
    destination = directory / f'sheet{index}'
    # Old full-video sheets must not remain mixed with scoped pages.
    if destination.exists():
        shutil.rmtree(destination)
    if video_cache.restore(cache, destination):
        print(f'{directory.name}: cached selected battle sheets [{start:g}, {end:g}]', flush=True)
        return
    print(f'{directory.name}: generating selected battle sheets [{start:g}, {end:g}]', flush=True)
    try:
        with tempfile.TemporaryDirectory() as td:
            temporary = Path(td)
            samples = _extract(video, start, end, temporary)
            destination.mkdir(parents=True, exist_ok=True)
            pages = _render(samples, destination)
            metadata = {'version': VERSION, 'battle': [start, end], 'every': EVERY,
                        'pages': pages, 'first_page': pages[0]['file'], 'last_page': pages[-1]['file']}
            (destination / 'sheets.json').write_text(json.dumps(metadata, indent=2), encoding='utf8')
            video_cache.publish(destination, cache)
    except Exception:
        if destination.exists():
            shutil.rmtree(destination)
        raise
    print(f'{directory.name}: {len(pages)} selected battle sheet(s) finished', flush=True)
