"""Live terminal view for the queue coordinator."""
import os
import shutil
import sys
import time
from collections import deque
from pathlib import Path
from urllib.parse import quote


def enable_terminal():
    if not sys.stdout.isatty():
        return False
    if os.name != 'nt':
        return os.environ.get('TERM') != 'dumb'
    import ctypes
    import msvcrt
    from ctypes import wintypes
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(sys.stdout.fileno()))
    mode = wintypes.DWORD()
    kernel = ctypes.windll.kernel32
    return bool(kernel.GetConsoleMode(handle, ctypes.byref(mode))
                and kernel.SetConsoleMode(handle, mode.value | 4))


class QueueGrid:
    def __init__(self, *, links=False):
        self.live = enable_terminal()
        self.links = links and self.live
        self.rows = {}
        self.notices = deque(maxlen=4)
        self.offsets = {}

    def set(self, rev, stage, verdict='Processing', done=False):
        now = time.monotonic()
        old = self.rows.get(rev)
        if old and old[:2] == (stage, verdict):
            return
        started = old[2] if old else now
        stage_started = old[3] if old and old[0] == stage else now
        finished = (old[4] if old and old[4] is not None else now) if done else None
        self.rows[rev] = (stage, verdict, started, stage_started, finished)
        if self.live:
            self.draw()
        else:
            print(f'{rev}: {stage} | {verdict}', flush=True)

    def notice(self, message):
        if not self.live:
            print(message, flush=True)
            return
        self.notices.append(' '.join(message.split()))
        self.draw()

    def poll(self, rev, directory):
        path = Path(directory) / 'worker.log'
        try:
            log = path.open('rb')
        except OSError:
            return
        with log:
            log.seek(self.offsets.get(rev, 0))
            stage = None
            while True:
                offset = log.tell()
                line = log.readline()
                if not line.endswith(b'\n'):
                    self.offsets[rev] = offset
                    break
                marker = b'QUEUE_STAGE: '
                if line.startswith(marker):
                    stage = line[len(marker):].decode('ascii', 'replace').strip()
            if stage:
                self.set(rev, stage)

    def draw(self):
        width, height = shutil.get_terminal_size((100, 30))
        limit = max(2, height - len(self.notices) - 6)
        active = [(rev, row) for rev, row in self.rows.items() if row[4] is None]
        finished = [(rev, row) for rev, row in self.rows.items() if row[4] is not None]
        visible = active[-limit:] + finished[-max(0, limit - len(active)):] if len(active) < limit else active[-limit:]
        now = time.monotonic()
        max_width = max(1, width - 1)
        links = []
        lines = [f"{'REVIEW':<16} | {'PROGRESS':<29} | VERDICT", '-' * min(width - 1, 78)]
        for rev, (stage, verdict, started, stage_started, ended) in visible:
            seconds = int(ended - started if ended is not None else now - stage_started)
            mins, secs = divmod(seconds, 60)
            elapsed = f'{mins}m {secs:02d}s' if mins else f'{secs}s'
            lines.append(f'{rev:<16} | {stage + " / " + elapsed:<29} | {verdict}')
            if self.links:
                links.append((len(lines) - 1, rev))
        hidden = len(self.rows) - len(visible)
        if hidden:
            lines.append(f'{hidden} more review(s); full results are saved in work/')
        lines.extend(self.notices)
        lines = [line[:max_width] for line in lines]
        for index, rev in links:
            line = lines[index]
            label = line[:len(rev)]
            url = 'https://theherta.com/mod?review=' + quote(rev, safe='')
            lines[index] = f'\x1b]8;;{url}\x1b\\{label}\x1b]8;;\x1b\\' + line[len(label):]
        sys.stdout.write('\x1b[2J\x1b[H' + '\n'.join(lines) + '\n')
        sys.stdout.flush()
