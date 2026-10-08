"""검토 한 건 준비: 영상 받기 + 겹친 프레임 시트.
python prep.py <rev_id> [<rev_id> ...]   (queue.json 에서 payload 를 읽는다)

빌리빌리 영상은 한 영상 안에 여러 파트(P1 실전, P2 配置补录 등)를 올리는 일이 있다. 공유 링크의 p= 는 한 파트만
가리키므로, p= 를 떼고 모든 파트를 각각 video{i}.mp4 로 받는다. 받은 파일 목록은 videos.json 에 적는다
(file, url, part, parts, run_part: 제출 링크가 가리킨 파트인지, src: 제출 링크)."""
import sys, json, os, subprocess, re, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import ROOT, RUNS, WORK, YT, FF   # noqa: E402
q = {x["id"]: x for x in json.load(open(os.environ.get("HQ_QUEUE") or os.path.join(WORK, "queue.json"), encoding="utf8"))}

def tstart(url):
    m = re.search(r"[?&#]t=(\d+)(?:s)?", url) or re.search(r"[?&]start=(\d+)", url)
    return int(m.group(1)) if m else 0

def sheet(video, out, start=0, dur=None, every=3, cols=5, rows=5, width=480):
    os.makedirs(out, exist_ok=True)
    vf = f"fps=1/{every},scale={width}:-1,drawtext=text='%{{pts\\:hms}}':x=5:y=5:fontsize=20:fontcolor=yellow:box=1:boxcolor=black,tile={cols}x{rows}"
    if start: vf = vf.replace("%{pts\\:hms}", f"%{{pts\\:hms\\:{start}}}")
    cmd = [FF, "-loglevel", "error", "-ss", str(start)] + (["-t", str(dur)] if dur else []) + ["-i", video, "-vf", vf, "-q:v", "3", "-y", os.path.join(out, "%02d.jpg")]
    subprocess.run(cmd, stderr=subprocess.DEVNULL)

def resolve(url):
    """b23.tv 같은 짧은 링크는 넘겨주는 주소로 푼다."""
    if re.search(r"//(b23\.tv|bili2233\.cn)/", url):
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
            return urllib.request.urlopen(req, timeout=20).geturl()
        except Exception:
            return url
    return url

def bili_parts(url):
    """빌리빌리 BV 영상이면 (BV, 링크가 가리킨 파트, 파트 수). 아니면 None."""
    m = re.search(r"bilibili\.com/video/(BV[0-9A-Za-z]+)", url)
    if not m:
        return None
    bv = m.group(1)
    pm = re.search(r"[?&]p=(\d+)", url)
    p = subprocess.run([YT, "--flat-playlist", "--print", "%(playlist_index)s", f"https://www.bilibili.com/video/{bv}"],
                       capture_output=True, text=True, encoding="utf8", errors="replace")
    n = len([x for x in p.stdout.split() if x.strip()])
    return bv, int(pm.group(1)) if pm else 1, max(1, n)

FORMATS = ["bv*[vcodec^=avc1][height<=720]/bv*[height<=720][ext=mp4]/bv*[height<=720]/b",
           "bv*[vcodec^=avc1][height<=480]/bv*[height<=480]/b",
           "bv*[vcodec^=avc1][height<=1080]/bv*[height<=1080]/b"]


def decoded_ratio(v, expect=None):
    """끝까지 디코드되는 몫(1fps 로 센 프레임 / 길이). 빌리빌리 720p 파일이 끝부분에서 깨지는 일이 있다.
    길이는 사이트가 알려 준 길이(expect)를 먼저 쓴다 — 깨진 파일은 머리의 길이 정보도 틀릴 수 있다."""
    out = subprocess.run([FF, "-i", v, "-vf", "fps=1", "-f", "null", "-"], capture_output=True, text=True, errors="replace").stderr
    f = re.findall(r"frame=\s*(\d+)", out)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    dur = expect or (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0)
    if not f or not dur:
        return 0.0
    return min(1.0, int(f[-1]) / max(1.0, dur))


def download(u, v):
    """720p 로 받고, 끝까지 디코드되지 않으면(90% 미만) 480p, 1080p 순으로 다시 받는다."""
    log = ""
    for k, fmt in enumerate(FORMATS):
        if os.path.exists(v):
            os.remove(v)
        p = subprocess.run([YT, "-q", "--no-progress", "--js-runtimes", "node", "--retries", "50", "--fragment-retries", "50", "--http-chunk-size", "10M", "-N", "4", "--ffmpeg-location", FF,
                            "--no-playlist", "-f", fmt, "-o", v, "--print", "%(duration)s|%(title)s", "--no-simulate", u],
                           capture_output=True, text=True, encoding="utf8", errors="replace")
        log += p.stdout + p.stderr[-1000:]
        if os.path.exists(v):
            dm = re.match(r"\s*([\d.]+)\|", p.stdout)
            r = decoded_ratio(v, float(dm.group(1)) if dm else None)
            log += f"\nformat try {k + 1}: decoded {r:.0%}\n"
            if r >= 0.9:
                return log
    return log + "\nWARNING: every format decoded incompletely\n"

for rid in sys.argv[1:]:
    rev = q[rid]; d = os.path.join(RUNS, rid); os.makedirs(d, exist_ok=True)
    runs = rev["payload"].get("runs") or [rev["payload"]]
    json.dump(rev, open(os.path.join(d, "review.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    entries, seen = [], set()
    for r in runs:
        src = r["video_url"]
        url = resolve(src)
        bp = bili_parts(url)
        if bp:
            bv, runp, n = bp
            for k in range(1, n + 1):
                key = (bv, k)
                if key in seen:
                    for e in entries:
                        if e["key"] == list(key) and k == runp:
                            e["run_part"] = True
                    continue
                seen.add(key)
                entries.append({"key": [bv, k], "url": f"https://www.bilibili.com/video/{bv}?p={k}" if n > 1 else f"https://www.bilibili.com/video/{bv}",
                                "part": k, "parts": n, "run_part": k == runp, "src": src})
        else:
            base = re.sub(r"[?&](t|start|si|is)=[^&]*", "", url)
            if base in seen:
                continue
            seen.add(base)
            entries.append({"key": base, "url": base, "part": 1, "parts": 1, "run_part": True, "src": src})
    for i, e in enumerate(entries):
        v = os.path.join(d, f"video{i}.mp4")
        e["file"] = f"video{i}.mp4"
        if not os.path.exists(v):
            out = download(e["url"], v)
            open(os.path.join(d, f"video{i}.info"), "w", encoding="utf8").write(
                e["url"] + f"\npart {e['part']}/{e['parts']}" + (" (run part)" if e["run_part"] else "") + "\n" + out)
        if os.path.exists(v): sheet(v, os.path.join(d, f"sheet{i}"))
    json.dump(entries, open(os.path.join(d, "videos.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    ok = all(os.path.exists(os.path.join(d, e["file"])) for e in entries)
    parts = ", ".join(f"{e['file']}=p{e['part']}/{e['parts']}{'*' if e['run_part'] else ''}" for e in entries)
    print(rid, "ok" if ok else "FAIL", parts)
