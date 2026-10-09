"""빌리빌리 영상 줄기(.m4s) 빨리 받기: 서버(CDN) 고르기 + 여러 갈래로 나눠 받기.

한 줄기로 받으면 서버가 연결마다 속도를 눌러(100KB/s 까지) 한 건에 20분 넘게 걸렸다. 그래서
  1) 후보 서버를 모은다: yt-dlp 가 준 주소의 서버 + 기본 서버 목록(아래), 느린 P2P · PCDN 서버는 뺀다
  2) 후보마다 앞 512KB 를 동시에 받아 보고 빠른 순으로 줄을 세운다(5초 안에 못 받으면 탈락)
  3) 파일을 4MB 조각으로 나눠 8갈래로 받는다. 조각마다 빠른 서버부터 시도하고, 실패하면 다음 서버로

서버 블랙리스트와 기본 서버 목록은 Bili23-Downloader(https://github.com/ScottSloan/Bili23-Downloader, GPL-3.0)의
src/util/network/cdn.py · src/util/common/config.py 에서 가져왔다(사용자 지시, 2026-10-09).

python bili_dl.py <영상 주소(.m4s)> <저장 파일>"""
import os, sys, time, threading, queue, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0'
HEAD = {'Referer': 'https://www.bilibili.com/', 'User-Agent': UA}

# Bili23-Downloader 기본 노드: 중국 안(cn) · 해외(ov). 우리는 해외라 ov 가 먼저 쓰이지만 어디서 막혔는지 모르므로 둘 다 시험한다
OV_HOSTS = ['upos-sz-mirroraliov.bilivideo.com', 'upos-sz-mirrorcosov.bilivideo.com']
CN_HOSTS = ['upos-sz-mirror08c.bilivideo.com', 'upos-sz-mirrorhw.bilivideo.com', 'upos-sz-mirrorhwb.bilivideo.com',
            'upos-sz-mirrorcos.bilivideo.com', 'upos-sz-mirrorali.bilivideo.com', 'upos-sz-mirrorcosb.bilivideo.com']
BLACKLIST = ['mcdn', 'pcdn', 'szbdyd.com', 'mountaintoys.cn', 'upos-sz-mirror14b.bilivideo.com', 'nexusedgeio.com', 'ahdohpiechei.com']

PROBE_BYTES = 512 * 1024
PROBE_TIMEOUT = 6
CHUNK = 4 * 1024 * 1024
THREADS = 8
MAX_SECONDS = 300
MIN_SPEED = 80 * 1024            # 이보다 느린 서버는 후보에서 뺀다(B/s)


def _req(url, rng, timeout):
    h = dict(HEAD)
    h['Range'] = f'bytes={rng[0]}-{rng[1]}'
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout)


def _swap(url, host):
    p = urlparse(url)
    return p._replace(netloc=host).geturl() if p.netloc != host else url


def candidates(url):
    """우선순위 순서 후보 주소(서버 중복 없이). 몰 코스 같은 특수 저장소는 서버를 바꾸지 않는다."""
    hosts, out = [], []
    first = urlparse(url).netloc
    swap_ok = '/mallxcodeboss/' not in url and 'gen=playurlv2_itemsvideo' not in url
    for h in [first] + (OV_HOSTS + CN_HOSTS if swap_ok else []):
        if h in hosts or any(b in h for b in BLACKLIST) and h != first:
            continue
        if any(b in h for b in BLACKLIST):
            continue                       # 원래 주소가 P2P 노드여도 쓰지 않는다(다른 노드가 있을 때)
        hosts.append(h)
    if not hosts:
        hosts = [first]                    # 전부 걸러지면 원래 주소로(없는 것보다 낫다)
    return [_swap(url, h) for h in hosts]


def probe(url):
    """(속도 B/s, 전체 크기) — 앞 512KB 를 받아 본다. 실패하면 (0, 0)"""
    t0 = time.monotonic()
    try:
        with _req(url, (0, PROBE_BYTES - 1), PROBE_TIMEOUT) as r:
            cr = r.headers.get('Content-Range') or ''
            total = int(cr.rsplit('/', 1)[1]) if '/' in cr and cr.rsplit('/', 1)[1].isdigit() else 0
            got = 0
            while got < PROBE_BYTES:
                b = r.read(65536)
                if not b:
                    break
                got += len(b)
                if time.monotonic() - t0 > PROBE_TIMEOUT:
                    break
        dt = max(time.monotonic() - t0, 1e-3)
        return got / dt, total
    except Exception:
        return 0, 0


def download(url, out, log=print):
    """영상 줄기를 out 에 받는다. 성공하면 True."""
    t_start = time.monotonic()
    cands = candidates(url)
    with ThreadPoolExecutor(min(8, len(cands))) as ex:
        res = list(ex.map(probe, cands))
    ranked = sorted(((sp, tot, u) for (sp, tot), u in zip(res, cands) if sp >= MIN_SPEED), reverse=True)
    log('bili_dl probe: ' + ', '.join(f"{urlparse(u).netloc.split('.')[0]}={sp / 1024:.0f}KB/s" for (sp, _), u in zip(res, cands)))
    if not ranked:
        return False
    size = max(t for _, t, _ in ranked)
    if not size:
        return False
    urls = [u for _, _, u in ranked][:4]
    n = (size + CHUNK - 1) // CHUNK
    with open(out, 'wb') as f:
        f.truncate(size)
    todo = queue.Queue()
    for i in range(n):
        todo.put(i)
    failed, stop = [], threading.Event()
    done_bytes = [0]
    lock = threading.Lock()

    def worker(wid):
        with open(out, 'r+b') as f:
            while not stop.is_set():
                try:
                    i = todo.get_nowait()
                except queue.Empty:
                    return
                a, b = i * CHUNK, min(size, (i + 1) * CHUNK) - 1
                ok = False
                for k in range(len(urls) * 2):
                    if stop.is_set():
                        return
                    u = urls[(wid + k) % len(urls)]
                    try:
                        with _req(u, (a, b), 20) as r:
                            data = r.read()
                        if len(data) == b - a + 1:
                            f.seek(a)
                            f.write(data)
                            ok = True
                            break
                    except Exception:
                        continue
                if not ok:
                    failed.append(i)
                    stop.set()
                    return
                with lock:
                    done_bytes[0] += b - a + 1

    ths = [threading.Thread(target=worker, args=(w,), daemon=True) for w in range(THREADS)]
    for t in ths:
        t.start()
    while any(t.is_alive() for t in ths):
        if time.monotonic() - t_start > MAX_SECONDS:
            stop.set()
            log('bili_dl: time limit')
            break
        time.sleep(0.5)
    for t in ths:
        t.join(timeout=25)
    ok = not failed and not stop.is_set() and done_bytes[0] >= size
    log(f'bili_dl: {done_bytes[0] / 1e6:.0f}/{size / 1e6:.0f}MB in {time.monotonic() - t_start:.0f}s -> {"ok" if ok else "FAIL"}')
    if not ok and os.path.exists(out):
        os.remove(out)
    return ok


if __name__ == '__main__':
    sys.exit(0 if download(sys.argv[1], sys.argv[2]) else 1)
